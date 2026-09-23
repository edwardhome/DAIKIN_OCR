import hashlib
import hmac
import ipaddress
import logging
import secrets
from datetime import timedelta

from flask import Flask, jsonify, redirect, request, session, url_for
from werkzeug.exceptions import HTTPException

from app.config import ROOT, settings
from app.errors import AppError
from app.models import db


def create_app(overrides=None):
    app = Flask(
        __name__, static_folder=str(ROOT / "static"), template_folder=str(ROOT / "app/templates")
    )
    app.config.update(settings(overrides))
    app.permanent_session_lifetime = timedelta(hours=8)
    db.init_app(app)
    from app.routes import api, pages

    app.register_blueprint(pages)
    app.register_blueprint(api)

    @app.before_request
    def access_control():
        if request.endpoint in {"static", "pages.health"}:
            return None
        password = app.config["ACCESS_PASSWORD"]
        if password:
            expected = hashlib.sha256(password.encode()).hexdigest()
            authenticated = hmac.compare_digest(session.get("access", ""), expected)
            if not authenticated and request.endpoint != "pages.login":
                if request.path.startswith("/api/"):
                    raise AppError("AUTH_REQUIRED", "請先輸入存取碼。", 401)
                return redirect(url_for("pages.login"))
        else:
            try:
                address = ipaddress.ip_address(request.remote_addr or "")
                internal = (
                    address.is_loopback
                    or address in ipaddress.ip_network("100.64.0.0/10")
                    or address in ipaddress.ip_network("fd7a:115c:a1e0::/48")
                )
            except ValueError:
                internal = False
            if not internal:
                raise AppError("ACCESS_NOT_CONFIGURED", "外部存取尚未設定存取碼。", 403)
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(32)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            supplied = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
            if not hmac.compare_digest(supplied.encode(), session["csrf"].encode()):
                raise AppError("CSRF_FAILED", "頁面驗證已失效，請重新整理後操作。", 403)

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' blob:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        if request.endpoint != "static":
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(AppError)
    def application_error(error):
        db.session.rollback()
        return jsonify(
            error={"code": error.code, "message": error.message, "retryable": error.retryable}
        ), error.status

    @app.errorhandler(HTTPException)
    def http_error(error):
        messages = {
            413: "圖片超過上傳大小限制。",
            404: "找不到這個頁面或資料。",
            400: "請求格式或存取網址不正確。",
        }
        return jsonify(
            error={
                "code": f"HTTP_{error.code}",
                "message": messages.get(error.code, "請求無法處理。"),
                "retryable": False,
            }
        ), error.code

    @app.errorhandler(Exception)
    def unexpected_error(error):
        db.session.rollback()
        app.logger.error("Unhandled error type=%s", type(error).__name__)
        return jsonify(
            error={
                "code": "INTERNAL_ERROR",
                "message": "服務暫時無法完成操作，請稍後重試。",
                "retryable": True,
            }
        ), 500

    if app.config.get("TESTING"):
        with app.app_context():
            db.create_all()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return app
