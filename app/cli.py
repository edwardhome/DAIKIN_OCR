import argparse
import fcntl
import ipaddress

from alembic import command
from alembic.config import Config
from waitress import serve

from app import create_app
from app.config import ROOT
from app.models import db


def migrate(app):
    with app.app_context(), db.engine.connect() as connection:
        cfg = Config(str(ROOT / "alembic.ini"))
        cfg.set_main_option("script_location", str(ROOT / "migrations"))
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "head")


def main():
    parser = argparse.ArgumentParser(description="大金空調銘牌辨識")
    parser.add_argument("command", choices=["init-db", "serve", "worker"])
    parser.add_argument("--once", action="store_true", help="Drain queued work and exit")
    args = parser.parse_args()
    app = create_app()
    if args.command == "init-db":
        migrate(app)
        print("資料庫版本已更新。")
        return
    if args.command == "serve":
        host = app.config["APP_HOST"]
        try:
            ip = ipaddress.ip_address(host)
            internal = (
                ip.is_loopback
                or ip in ipaddress.ip_network("100.64.0.0/10")
                or ip in ipaddress.ip_network("fd7a:115c:a1e0::/48")
            )
        except ValueError:
            internal = False
        if not internal and len(app.config["ACCESS_PASSWORD"]) < 12:
            parser.error("外部綁定位址需設定至少 12 字元的 ACCESS_PASSWORD。")
        serve(
            app,
            host=host,
            port=app.config["APP_PORT"],
            threads=8,
            max_request_body_size=app.config["MAX_CONTENT_LENGTH"],
        )
    else:
        from app.workers import worker

        with (app.config["DATA_DIR"] / ".worker.lock").open("w") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                parser.error("此資料目錄已有 Worker 在執行。")
            worker(app, once=args.once)


if __name__ == "__main__":
    main()
