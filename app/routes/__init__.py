import hashlib
import hmac
import secrets
import threading
import time
from collections import OrderedDict
from pathlib import Path

from flask import (
    Blueprint,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
)
from sqlalchemy import select

from app.errors import AppError
from app.models import Attempt, Benchmark, BenchmarkItem, Confirmation, DatasetVersion, Job, db, now
from app.schemas import CORRECTION_TYPES, FIELD_SPECS, field_metadata
from app.services import benchmark, datasets
from app.services.confirmations import confirm, share_text
from app.services.dashboard import dashboard
from app.services.jobs import (
    attempt_dict,
    config_snapshot,
    confirmation_dict,
    job_dict,
    new_attempt,
    require,
    upload,
)

pages = Blueprint("pages", __name__)
api = Blueprint("api", __name__, url_prefix="/api")
_login_attempts = OrderedDict()
_login_lock = threading.Lock()


def body():
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        raise AppError("INVALID_JSON", "請求必須是 JSON 物件。", 422)
    return value


@pages.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        ip = request.remote_addr or "unknown"
        with _login_lock:
            cutoff = time.monotonic() - 900
            attempts = [t for t in _login_attempts.get(ip, []) if t > cutoff]
            if len(attempts) >= 8:
                raise AppError("LOGIN_RATE_LIMIT", "嘗試次數過多，請 15 分鐘後再試。", 429)
            supplied = request.form.get("password", "")
            expected = current_app.config["ACCESS_PASSWORD"]
            valid = (
                bool(expected)
                and len(supplied) <= 200
                and hmac.compare_digest(supplied.encode(), expected.encode())
            )
            if valid:
                _login_attempts.pop(ip, None)
            else:
                _login_attempts[ip] = attempts + [time.monotonic()]
                while len(_login_attempts) > 1024:
                    _login_attempts.popitem(last=False)
        if valid:
            session.clear()
            session["access"] = hashlib.sha256(expected.encode()).hexdigest()
            session["csrf"] = secrets.token_urlsafe(32)
            session.permanent = True
            return redirect("/")
        error = "存取碼不正確。"
    return render_template("login.html", error=error)


@pages.post("/logout")
def logout():
    session.clear()
    return redirect("/login")


@pages.get("/healthz")
def health():
    return {"status": "ok"}


@pages.get("/")
@pages.get("/history")
@pages.get("/dashboard")
@pages.get("/benchmark")
@pages.get("/datasets")
@pages.get("/jobs/<identifier>")
def index(identifier=None):
    return render_template(
        "index.html", csrf=session["csrf"], auth_enabled=bool(current_app.config["ACCESS_PASSWORD"])
    )


@api.get("/bootstrap")
def bootstrap():
    cfg = current_app.config
    return {
        "csrf_token": session["csrf"],
        "fields": field_metadata(),
        "correction_types": CORRECTION_TYPES,
        "default_profile": cfg["DEFAULT_PROFILE"],
        "debug_data": cfg["DEBUG_DATA"],
        "max_upload_bytes": cfg["MAX_UPLOAD_BYTES"],
        "profiles": [
            {
                "id": p["id"],
                "provider": p["provider"],
                "model": p["model"],
                "configured": bool(p["model"])
                and (p["provider"] != "nvidia" or bool(cfg["NVIDIA_API_KEY"])),
            }
            for p in cfg["PROFILES"].values()
        ],
    }


@api.route("/jobs", methods=["GET", "POST"])
def jobs():
    if request.method == "POST":
        job = upload(request.files.get("image"), request.form)
        return jsonify(job_dict(job)), 202
    try:
        page = max(1, int(request.args.get("page", "1")))
    except ValueError:
        raise AppError("INVALID_PAGE", "頁碼無效。", 422)
    query = select(Job).where(Job.scope != "BENCHMARK").order_by(Job.created_at.desc())
    records = db.session.scalars(query.offset((page - 1) * 30).limit(31)).all()
    return {
        "items": [job_dict(j, False) for j in records[:30]],
        "page": page,
        "has_next": len(records) > 30,
    }


@api.route("/jobs/<identifier>", methods=["GET", "PATCH"])
def job(identifier):
    record = require(Job, identifier)
    if request.method == "PATCH":
        payload = body()
        difficulty = payload.get("image_difficulty", record.image_difficulty)
        tags = payload.get("scenario_tags", record.scenario_tags)
        if (
            not isinstance(difficulty, str)
            or difficulty not in {"EASY", "MEDIUM", "HARD", "UNLABELED"}
            or not isinstance(tags, list)
            or len(tags) > 20
            or not all(isinstance(t, str) and len(t) <= 50 for t in tags)
        ):
            raise AppError("INVALID_METADATA", "難度或情境標記無效。", 422)
        record.image_difficulty, record.scenario_tags = difficulty, tags
        db.session.commit()
    return job_dict(record)


@api.post("/jobs/<identifier>/attempts")
def retry(identifier):
    record = require(Job, identifier)
    payload = body()
    pending = db.session.scalar(
        select(Attempt.id).where(
            Attempt.job_id == record.id, Attempt.status.in_(["QUEUED", "PREPROCESSING", "RUNNING"])
        )
    )
    if pending:
        raise AppError("ALREADY_RUNNING", "此照片仍在辨識，請等待完成。", 409)
    attempt = new_attempt(record, config_snapshot(payload.get("profile_id")))
    db.session.commit()
    return jsonify(attempt_dict(attempt)), 202


@api.route("/jobs/<identifier>/confirmations", methods=["GET", "POST"])
def confirmations(identifier):
    record = require(Job, identifier)
    if request.method == "POST":
        revision = confirm(record, body())
        return jsonify({**confirmation_dict(revision), "share_text": share_text(revision)}), 201
    records = db.session.scalars(
        select(Confirmation)
        .where(Confirmation.job_id == record.id)
        .order_by(Confirmation.revision_no.desc())
    ).all()
    return {"items": [confirmation_dict(c) for c in records]}


@api.get("/confirmations/<identifier>/share-text")
def get_share(identifier):
    revision = require(Confirmation, identifier)
    return {"confirmation_id": revision.id, "text": share_text(revision)}


@api.get("/jobs/<identifier>/image")
def original_image(identifier):
    record = require(Job, identifier)
    return send_file(record.original_path, mimetype=record.mime_type, conditional=True)


@api.get("/attempts/<identifier>/image")
def processed_image(identifier):
    record = require(Attempt, identifier)
    if not record.processed_path:
        raise AppError("NOT_FOUND", "尚無處理圖。", 404)
    return send_file(record.processed_path, mimetype="image/jpeg", conditional=True)


@api.get("/attempts/<identifier>/debug")
def debug_attempt(identifier):
    if not current_app.config["DEBUG_DATA"]:
        raise AppError("NOT_FOUND", "此功能未開放。", 404)
    return attempt_dict(require(Attempt, identifier), True)


@api.get("/dashboard")
def get_dashboard():
    return dashboard()


def dataset_dict(record):
    return {
        key: getattr(record, key)
        for key in (
            "id",
            "version",
            "category",
            "split",
            "privacy",
            "sample_count",
            "created_at",
            "manifest_sha256",
        )
    }


@api.route("/datasets", methods=["GET", "POST"])
def dataset_list():
    if request.method == "POST":
        return jsonify(dataset_dict(datasets.export_dataset(body()))), 201
    return {
        "items": [
            dataset_dict(d)
            for d in db.session.scalars(
                select(DatasetVersion).order_by(DatasetVersion.created_at.desc())
            )
        ]
    }


@api.get("/datasets/<identifier>/download")
def dataset_download(identifier):
    record = require(DatasetVersion, identifier)
    datasets.verify_dataset(record)
    return send_file(
        Path(record.directory) / "export.zip",
        as_attachment=True,
        download_name=f"{record.version}.zip",
    )


@api.route("/benchmarks", methods=["GET", "POST"])
def benchmark_list():
    if request.method == "POST":
        record = benchmark.create_benchmark(body())
        return jsonify({"id": record.id}), 202
    return {
        "items": [
            {
                "id": b.id,
                "dataset_id": b.dataset_id,
                "created_at": b.created_at,
                "targets": list(b.targets),
            }
            for b in db.session.scalars(select(Benchmark).order_by(Benchmark.created_at.desc()))
        ]
    }


@api.get("/benchmarks/<identifier>")
def benchmark_detail(identifier):
    return benchmark.benchmark_report(require(Benchmark, identifier))


@api.get("/benchmarks/<identifier>/compare")
def benchmark_compare(identifier):
    return benchmark.compare(
        require(Benchmark, identifier),
        require(Benchmark, request.args.get("baseline")),
        request.args.get("target"),
        request.args.get("baseline_target"),
    )


@api.post("/benchmark-items/<identifier>/assessments")
def assess(identifier):
    record = require(BenchmarkItem, identifier)
    assessments = body().get("fields")
    attempt = require(Attempt, record.attempt_id)
    if (
        attempt.status != "SUCCEEDED"
        or not isinstance(assessments, dict)
        or not assessments
        or not set(assessments).issubset(FIELD_SPECS)
        or any(
            not isinstance(v, str) or v not in {"SUPPORTED", "UNSUPPORTED", "UNREVIEWED"}
            for v in assessments.values()
        )
    ):
        raise AppError("INVALID_ASSESSMENT", "人工依據審查格式無效。", 422)
    record.assessment_history = record.assessment_history + [{"at": now(), "fields": assessments}]
    record.field_assessments = {**record.field_assessments, **assessments}
    if "UNSUPPORTED" in assessments.values():
        attempt.hard_reasons = sorted(set(attempt.hard_reasons) | {"HUMAN_UNSUPPORTED_PREDICTION"})
    db.session.commit()
    return {"field_assessments": record.field_assessments}
