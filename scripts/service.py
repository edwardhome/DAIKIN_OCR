#!/usr/bin/env python3
"""Manage this release's web/worker pair; does not install a boot-time service.

Run with the release's .venv/bin/python. The runtime directory must be shared
across releases. Database migrations remain an explicit deployment step.
"""

import argparse
import fcntl
import hmac
import json
import logging
import os
import secrets
import signal
import socket
import socketserver
import subprocess
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IDENTITY = "nameplate-supervisor-v1"


def lock_file(runtime):
    fd = os.open(runtime / "service.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    return os.fdopen(fd, "a+")


def is_locked(runtime):
    with lock_file(runtime) as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        return False


def request(runtime, action="status"):
    """Authenticate a local control request instead of trusting/killing a stale PID."""
    try:
        metadata = json.loads((runtime / "service.json").read_text())
        with socket.create_connection(("127.0.0.1", metadata["port"]), timeout=2) as conn:
            conn.settimeout(2)
            payload = {"token": metadata["token"], "action": action}
            conn.sendall(json.dumps(payload).encode() + b"\n")
            with conn.makefile("rb") as stream:
                result = json.loads(stream.readline(16384))
        if (
            result.get("identity") == IDENTITY
            and result.get("pid") == metadata["pid"]
            and hmac.compare_digest(str(result.get("token", "")), metadata["token"])
        ):
            return {key: value for key, value in result.items() if key != "token"}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    return None


def make_logger(runtime, max_bytes=5 * 1024 * 1024):
    logger = logging.Logger("nameplate-service")
    handler = RotatingFileHandler(runtime / "service.log", maxBytes=max_bytes, backupCount=3)
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger


def pipe_logs(process, role, logger):
    with process.stdout:
        while chunk := process.stdout.readline(16384):
            logger.info("[%s] %s", role, chunk.decode("utf-8", errors="replace").rstrip())


def stop_children(children, logger, grace=10):
    for role, process in children.items():
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        logger.info("Stopping %s pid=%s", role, process.pid)
    deadline = time.monotonic() + grace
    for process in children.values():
        try:
            process.wait(timeout=max(0.01, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            pass
        # Also reap descendants if a child exited before its process group did.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
    children.clear()


def supervise(runtime):
    with lock_file(runtime) as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        logger = make_logger(runtime)
        children = {}
        stopping = False
        token = secrets.token_hex(32)
        state = "STARTING"

        def on_signal(_signum, _frame):
            nonlocal stopping
            stopping = True

        signal.signal(signal.SIGTERM, on_signal)
        signal.signal(signal.SIGINT, on_signal)

        class Control(socketserver.StreamRequestHandler):
            def handle(self):
                nonlocal stopping
                self.connection.settimeout(0.5)
                try:
                    payload = json.loads(self.rfile.readline(4096))
                    if not hmac.compare_digest(str(payload.get("token", "")), token):
                        return
                    if payload.get("action") == "stop":
                        stopping = True
                    result = {
                        "identity": IDENTITY,
                        "token": token,
                        "pid": os.getpid(),
                        "release": str(ROOT),
                        "state": "STOPPING" if stopping else state,
                        "children": {role: proc.pid for role, proc in children.items()},
                    }
                    self.wfile.write(json.dumps(result).encode() + b"\n")
                except (OSError, ValueError, AttributeError):
                    return

        metadata_path = runtime / "service.json"
        try:
            with socketserver.TCPServer(("127.0.0.1", 0), Control) as server:
                server.timeout = 0.2
                metadata = {
                    "identity": IDENTITY,
                    "pid": os.getpid(),
                    "token": token,
                    "port": server.server_address[1],
                }
                temporary = runtime / f"service.{os.getpid()}.tmp"
                with temporary.open("w", encoding="utf-8") as stream:
                    os.chmod(temporary, 0o600)
                    json.dump(metadata, stream)
                temporary.replace(metadata_path)
                retry_at, delay, started_at = 0.0, 1.0, 0.0
                logger.info("Supervisor started pid=%s release=%s", os.getpid(), ROOT)
                while not stopping:
                    now = time.monotonic()
                    if children and any(proc.poll() is not None for proc in children.values()):
                        logger.warning("A child exited; restarting the web/worker pair")
                        state = "RESTARTING"
                        stop_children(children, logger)
                        if now - started_at >= 60:
                            delay = 1.0
                        retry_at = time.monotonic() + delay
                        logger.info("Restart backoff %.1f seconds", delay)
                        delay = min(delay * 2, 30.0)
                    if not children and time.monotonic() >= retry_at and not stopping:
                        try:
                            for role in ("worker", "serve"):
                                process = subprocess.Popen(
                                    [sys.executable, "-u", "-m", "app.cli", role],
                                    cwd=ROOT,
                                    stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT,
                                    start_new_session=True,
                                )
                                children[role] = process
                                threading.Thread(
                                    target=pipe_logs, args=(process, role, logger), daemon=True
                                ).start()
                            started_at = time.monotonic()
                            state = "RUNNING"
                        except OSError as exc:
                            logger.error("Unable to launch children: %s", exc)
                            stop_children(children, logger)
                            state = "RESTARTING"
                            retry_at = time.monotonic() + delay
                            delay = min(delay * 2, 30.0)
                    server.handle_request()
        finally:
            stop_children(children, logger)
            metadata_path.unlink(missing_ok=True)
            logger.info("Supervisor stopped")
            for handler in logger.handlers:
                handler.close()
    return 0


def start(runtime):
    existing = request(runtime)
    if existing:
        print(json.dumps(existing, ensure_ascii=False))
        return 0
    process = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "supervise", "--runtime-dir", str(runtime)],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        result = request(runtime)
        if result:
            print(json.dumps(result, ensure_ascii=False))
            return 0
        if process.poll() is not None and not is_locked(runtime):
            break
        time.sleep(0.1)
    print("Supervisor did not become available; inspect the runtime service.log.", file=sys.stderr)
    return 1


def stop(runtime):
    result = request(runtime, "stop")
    if not result and is_locked(runtime):
        print(
            "Service lock is held but identity could not be verified; nothing killed.",
            file=sys.stderr,
        )
        return 1
    deadline = time.monotonic() + 30
    while is_locked(runtime):
        if time.monotonic() >= deadline:
            print("Supervisor has not stopped; inspect service.log.", file=sys.stderr)
            return 1
        time.sleep(0.1)
    print(json.dumps({"state": "STOPPED"}))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["start", "status", "stop", "restart", "supervise"])
    parser.add_argument("--runtime-dir", type=Path, default=ROOT / "data" / "runtime")
    args = parser.parse_args()
    os.umask(0o077)
    runtime = args.runtime_dir.resolve()
    runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
    if runtime.stat().st_uid != os.getuid():
        parser.error("Runtime directory must belong to the current user.")
    if args.command == "supervise":
        return supervise(runtime)
    if args.command == "status":
        result = request(runtime)
        print(json.dumps(result or {"state": "UNVERIFIED" if is_locked(runtime) else "STOPPED"}))
        return 0 if result else 1
    if args.command in {"stop", "restart"}:
        result = stop(runtime)
        if result or args.command == "stop":
            return result
    return start(runtime)


if __name__ == "__main__":
    raise SystemExit(main())
