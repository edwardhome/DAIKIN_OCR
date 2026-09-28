import re

from flask import current_app
from sqlalchemy import select

from app.config import ROOT
from app.errors import AppError
from app.image import digest, inspect_image
from app.models import Attempt, Confirmation, FieldAnnotation, Job, Observation, db, uid
from app.providers.usage import aggregate_token_usage, normalize_token_usage
from app.schemas import (
    field_metadata,
    json_schema,
    prompt_field_names,
    schema_version_for,
    snapshot_field_names,
)
from app.services.normalize import NORMALIZER_VERSION
from app.validators import VALIDATOR_VERSION


def require(model, identifier):
    if not isinstance(identifier, str) or len(identifier) > 100:
        raise AppError("INVALID_ID", "資料識別碼格式無效。", 422)
    value = db.session.get(model, identifier)
    if not value:
        raise AppError("NOT_FOUND", "找不到這筆資料。", 404)
    return value


def config_snapshot(profile_id=None):
    cfg = current_app.config
    profile_id = profile_id or cfg["DEFAULT_PROFILE"]
    if not isinstance(profile_id, str):
        raise AppError("UNKNOWN_PROFILE", "模型設定識別碼格式無效。", 422)
    profile = cfg["PROFILES"].get(profile_id)
    if not profile:
        raise AppError("UNKNOWN_PROFILE", "找不到模型設定。", 422)
    version = cfg["PROMPT_VERSION"]
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", version):
        raise AppError("INVALID_PROMPT", "Prompt 版本名稱無效。", 422)
    path = ROOT / "prompts" / version / "instruction.txt"
    if not path.is_file():
        raise AppError("PROMPT_NOT_FOUND", "找不到指定 Prompt 版本。", 422)
    instruction = path.read_text()
    names = prompt_field_names(version)
    return {
        "profile": dict(profile),
        "prompt_version": version,
        "instruction": instruction,
        "prompt_sha256": digest(instruction.encode()),
        "schema_version": schema_version_for(names),
        "field_names": list(names),
        "schema": json_schema(names),
        "preprocessor": dict(cfg["PREPROCESSOR"]),
        "normalizer_version": NORMALIZER_VERSION,
        "validator_version": VALIDATOR_VERSION,
        "decision_version": "single_provider_v001",
        "timeout_seconds": cfg["PROVIDER_TIMEOUT"],
        "max_tokens": cfg["MAX_TOKENS"],
        "temperature": 0,
        "confidence_kind": "SELF_REPORTED_ENUM",
        "calibration_version": None,
        "thresholds_active": False,
        "configured_thresholds": {
            "high": cfg["HIGH_CONFIDENCE_THRESHOLD"],
            "low": cfg["LOW_CONFIDENCE_THRESHOLD"],
        },
        "code_sha256": digest(
            b"".join(
                path.relative_to(ROOT).as_posix().encode() + path.read_bytes()
                for path in sorted((ROOT / "app").rglob("*.py"))
            )
        ),
    }


def new_attempt(job, snapshot=None):
    snapshot = snapshot or config_snapshot()
    profile = snapshot["profile"]
    attempt = Attempt(
        job_id=job.id,
        profile_id=profile["id"],
        provider=profile["provider"],
        model=profile["model"],
        model_version=profile.get("model_version"),
        snapshot=snapshot,
    )
    db.session.add(attempt)
    db.session.flush()
    return attempt


def upload(file, metadata):
    if not file:
        raise AppError("IMAGE_REQUIRED", "請選擇銘牌照片。", 422)
    cfg = current_app.config
    data = file.stream.read(cfg["MAX_UPLOAD_BYTES"] + 1)
    if not data or len(data) > cfg["MAX_UPLOAD_BYTES"]:
        raise AppError("UPLOAD_SIZE_INVALID", "照片是空檔或超過上傳大小限制。", 413)
    extension, mime = inspect_image(data, cfg["MAX_IMAGE_PIXELS"])
    scope = metadata.get("scope", "PRODUCTION")
    if scope not in {"PRODUCTION", "BENCHMARK_SOURCE"}:
        raise AppError("INVALID_SCOPE", "上傳類別無效。", 422)
    difficulty = metadata.get("image_difficulty", "UNLABELED")
    if difficulty not in {"EASY", "MEDIUM", "HARD", "UNLABELED"}:
        raise AppError("INVALID_DIFFICULTY", "照片難度標記無效。", 422)
    group = str(metadata.get("group_key", "")).strip()
    if len(group) > 200:
        raise AppError("INVALID_GROUP", "設備群組名稱過長。", 422)
    snapshot = config_snapshot(metadata.get("profile_id"))
    job_id = uid()
    folder = (
        cfg["DATA_DIR"] / ("benchmark/images" if scope == "BENCHMARK_SOURCE" else "images") / job_id
    )
    folder.mkdir(parents=True)
    path = folder / f"original.{extension}"
    with path.open("xb") as stream:
        stream.write(data)
    job = Job(
        id=job_id,
        scope=scope,
        original_path=str(path),
        original_sha256=digest(data),
        mime_type=mime,
        file_size=len(data),
        image_difficulty=difficulty,
        group_key=group or digest(data),
        scenario_tags=[],
        privacy="PRIVATE",
    )
    db.session.add(job)
    db.session.flush()
    new_attempt(job, snapshot)
    db.session.commit()
    return job


def latest_confirmation(job_id, attempt_id=None):
    query = select(Confirmation).where(Confirmation.job_id == job_id)
    if attempt_id:
        query = query.where(Confirmation.attempt_id == attempt_id)
    return db.session.scalars(query.order_by(Confirmation.revision_no.desc())).first()


def confirmation_dict(c):
    annotations = db.session.scalars(
        select(FieldAnnotation).where(FieldAnnotation.confirmation_id == c.id)
    ).all()
    return {
        "id": c.id,
        "attempt_id": c.attempt_id,
        "revision_no": c.revision_no,
        "confirmed_at": c.confirmed_at,
        "human_ground_truth": c.human_ground_truth,
        "review_active_ms": c.review_active_ms,
        "validation_result": c.validation_result,
        "annotations": [
            {
                key: getattr(a, key)
                for key in (
                    "field_name",
                    "ai_value",
                    "human_value",
                    "human_input",
                    "before_value",
                    "ai_confidence",
                    "validation_warning",
                    "was_corrected",
                    "correction_type",
                    "correction_type_source",
                    "annotation_status",
                    "note",
                )
            }
            for a in annotations
        ],
    }


def attempt_dict(a, debug=False):
    observations = db.session.scalars(
        select(Observation).where(Observation.attempt_id == a.id).order_by(Observation.created_at)
    ).all()
    result = {
        key: getattr(a, key)
        for key in (
            "id",
            "job_id",
            "profile_id",
            "provider",
            "model",
            "model_version",
            "status",
            "normalized_ai_result",
            "validation_result",
            "decision_result",
            "error_code",
            "error_message",
            "latency_ms",
            "processing_ms",
            "queue_ms",
            "hard_reasons",
            "created_at",
            "started_at",
            "finished_at",
        )
    }
    result["token_usage"] = aggregate_token_usage(
        [normalize_token_usage(o.provider, o.raw_result) for o in observations]
    )
    result["prompt_version"] = a.snapshot["prompt_version"]
    names = snapshot_field_names(a.snapshot)
    result["field_names"] = list(names)
    result["schema_version"] = schema_version_for(names)
    result["field_metadata"] = field_metadata(names)
    result["processed_image_url"] = f"/api/attempts/{a.id}/image" if a.processed_path else None
    if debug:
        result["snapshot"] = a.snapshot
        result["repair_result"] = a.repair_result
        result["observations"] = [
            {
                "stage": o.stage,
                "provider": o.provider,
                "model": o.model,
                "raw_result": o.raw_result,
                "output_text": o.output_text,
            }
            for o in observations
        ]
    return result


def job_dict(job, detail=True):
    attempts = db.session.scalars(
        select(Attempt).where(Attempt.job_id == job.id).order_by(Attempt.created_at)
    ).all()
    confirmed = latest_confirmation(job.id)
    result = {
        key: getattr(job, key)
        for key in (
            "id",
            "scope",
            "image_difficulty",
            "scenario_tags",
            "group_key",
            "privacy",
            "revision",
            "created_at",
        )
    }
    result["original_image_url"] = f"/api/jobs/{job.id}/image"
    result["status"] = attempts[-1].status if attempts else "UPLOADED"
    result["confirmed"] = confirmed is not None
    result["is_hard_example"] = any(a.hard_reasons for a in attempts)
    result["display_model"] = None
    if confirmed:
        result["display_model"] = confirmed.human_ground_truth["fields"]["outdoor_model"]["value"]
    elif attempts and attempts[-1].normalized_ai_result:
        result["display_model"] = attempts[-1].normalized_ai_result["fields"]["outdoor_model"][
            "value"
        ]
    if detail:
        result["attempts"] = [attempt_dict(a) for a in attempts]
        result["confirmation"] = confirmation_dict(confirmed) if confirmed else None
    return result


def audit_payload(attempt):
    observations = db.session.scalars(
        select(Observation).where(Observation.attempt_id == attempt.id)
    ).all()
    return {
        "ocr_raw_result": [o.raw_result for o in observations if o.stage == "OCR"] or None,
        "vlm_raw_result": [o.raw_result for o in observations if o.stage == "VLM"] or None,
        "observations": [
            {
                "id": o.id,
                "stage": o.stage,
                "provider": o.provider,
                "model": o.model,
                "model_version": o.model_version,
                "raw_result": o.raw_result,
                "output_text": o.output_text,
                "confidence_kind": o.confidence_kind,
            }
            for o in observations
        ],
    }
