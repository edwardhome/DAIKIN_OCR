"""Supervisor tests use fake children in a temporary release, never the real app."""

import fcntl
import importlib.util
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "service.py"


def eventually(predicate, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if result := predicate():
            return result
        time.sleep(0.05)
    raise AssertionError("Condition did not become true")


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


@pytest.fixture
def service(tmp_path):
    release = tmp_path / "release"
    (release / "scripts").mkdir(parents=True)
    shutil.copyfile(SCRIPT, release / "scripts" / "service.py")
    (release / "app").mkdir()
    (release / "app" / "__init__.py").touch()
    (release / "app" / "cli.py").write_text(
        "import os, sys, time\n"
        "from pathlib import Path\n"
        "role = sys.argv[1]\n"
        "print('fake ' + role, flush=True)\n"
        "while True:\n"
        "    if role == 'worker' and Path('crash-worker').exists():\n"
        "        Path('crash-worker').unlink()\n"
        "        sys.exit(23)\n"
        "    time.sleep(.05)\n"
    )
    runtime = tmp_path / "runtime"

    def run(command):
        result = subprocess.run(
            [
                sys.executable,
                str(release / "scripts" / "service.py"),
                command,
                "--runtime-dir",
                str(runtime),
            ],
            capture_output=True,
            text=True,
            timeout=35,
        )
        return result, json.loads(result.stdout.splitlines()[-1]) if result.stdout else None

    yield release, runtime, run
    run("stop")


def test_start_is_idempotent_and_stop_reaps_both_children(service):
    _, runtime, run = service
    result, status = run("start")
    assert result.returncode == 0, result.stderr
    assert status["state"] == "RUNNING"
    assert set(status["children"]) == {"worker", "serve"}
    assert "token" not in status
    assert all(alive(pid) for pid in status["children"].values())
    assert (runtime / "service.json").stat().st_mode & 0o777 == 0o600
    _, duplicate = run("start")
    assert duplicate["pid"] == status["pid"]
    _, stopped = run("stop")
    assert stopped["state"] == "STOPPED"
    assert all(not alive(pid) for pid in status["children"].values())
    assert not (runtime / "service.json").exists()


def test_child_failure_restarts_the_pair_with_same_supervisor(service):
    release, runtime, run = service
    _, before = run("start")
    (release / "crash-worker").touch()

    def restarted():
        _, after = run("status")
        return (
            after
            if (
                after["state"] == "RUNNING"
                and len(after["children"]) == 2
                and all(after["children"][role] != pid for role, pid in before["children"].items())
            )
            else None
        )

    after = eventually(restarted)
    assert after["pid"] == before["pid"]
    assert all(not alive(pid) for pid in before["children"].values())
    assert "Restart backoff 1.0 seconds" in (runtime / "service.log").read_text()


def test_supervisor_sigterm_stops_children(service):
    _, _, run = service
    _, status = run("start")
    os.kill(status["pid"], signal.SIGTERM)
    eventually(lambda: run("status")[1]["state"] == "STOPPED")
    assert all(not alive(pid) for pid in status["children"].values())


def test_restart_replaces_supervisor_and_children(service):
    _, _, run = service
    _, before = run("start")
    result, after = run("restart")
    assert result.returncode == 0, result.stderr
    assert after["pid"] != before["pid"]
    assert all(not alive(pid) for pid in before["children"].values())


def test_control_requires_token_and_held_unknown_lock_is_not_stopped(service):
    _, runtime, run = service
    _, before = run("start")
    metadata = json.loads((runtime / "service.json").read_text())
    with socket.create_connection(("127.0.0.1", metadata["port"]), timeout=2) as conn:
        conn.sendall(b'{"action":"stop","token":"wrong"}\n')
        assert conn.recv(100) == b""
    _, after = run("status")
    assert after["pid"] == before["pid"]
    run("stop")
    with (runtime / "service.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result, status = run("status")
        assert result.returncode == 1
        assert status["state"] == "UNVERIFIED"
        result, status = run("stop")
        assert result.returncode == 1
        assert status is None
        assert "nothing killed" in result.stderr


def test_stale_pid_is_never_killed(service):
    _, runtime, run = service
    runtime.mkdir()
    unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        (runtime / "service.json").write_text(
            json.dumps(
                {
                    "pid": unrelated.pid,
                    "port": 1,
                    "token": "stale",
                    "identity": "unrelated",
                }
            )
        )
        result, stopped = run("stop")
        assert result.returncode == 0
        assert stopped["state"] == "STOPPED"
        assert unrelated.poll() is None
    finally:
        unrelated.terminate()
        unrelated.wait(timeout=5)


def test_log_rotation_is_bounded(tmp_path):
    spec = importlib.util.spec_from_file_location("service_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    logger = module.make_logger(tmp_path, max_bytes=200)
    try:
        for index in range(100):
            logger.info("%s %s", index, "x" * 50)
    finally:
        for handler in logger.handlers:
            handler.close()
    logs = list(tmp_path.glob("service.log*"))
    assert len(logs) == 4
    assert all(path.stat().st_size < 200 for path in logs)
