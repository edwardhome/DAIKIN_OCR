from sqlalchemy import update

from app.errors import AppError
from app.models import Attempt, Confirmation, FieldAnnotation, Job, db
from app.schemas import (
    ANNOTATION_STATUSES,
    CORRECTION_TYPES,
    FIELD_SPECS,
    schema_version_for,
    snapshot_field_names,
)
from app.services.jobs import latest_confirmation, require
from app.services.normalize import normalize_value
from app.validators import validate


def confirm(job, payload):
    attempt = require(Attempt, payload.get("attempt_id"))
    if attempt.job_id != job.id:
        raise AppError("ATTEMPT_MISMATCH", "辨識結果不屬於這張照片。", 422)
    source = payload.get("fields")
    names = snapshot_field_names(attempt.snapshot)
    if not isinstance(source, dict) or set(source) != set(names):
        raise AppError(
            "INCOMPLETE_CONFIRMATION", f"請提交本次辨識的完整 {len(names)} 個欄位。", 422
        )
    expected = payload.get("expected_revision")
    if isinstance(expected, bool) or not isinstance(expected, int) or expected != job.revision:
        raise AppError("REVISION_CONFLICT", "此資料已有新版本，請重新整理後確認。", 409)
    if attempt.status not in {"SUCCEEDED", "FAILED"}:
        raise AppError("NOT_READY", "辨識尚未完成。", 409)
    elapsed = payload.get("review_active_ms", 0)
    if isinstance(elapsed, bool) or not isinstance(elapsed, int) or not 0 <= elapsed <= 86400000:
        raise AppError("INVALID_REVIEW_TIME", "人工確認時間格式無效。", 422)
    previous = latest_confirmation(job.id)
    fields, annotations = {}, []
    ai = (attempt.normalized_ai_result or {}).get("fields", {})
    for name in names:
        field = source[name]
        if not isinstance(field, dict):
            raise AppError("INVALID_FIELD", "確認欄位格式無效。", 422)
        raw_value = field.get("value")
        if isinstance(raw_value, str) and len(raw_value) > 200:
            raise AppError("FIELD_TOO_LONG", "欄位內容過長。", 422)
        value, unit, warnings = normalize_value(name, raw_value, field.get("unit"))
        if warnings:
            raise AppError(
                "INVALID_FIELD", f"{FIELD_SPECS[name][0]}：{warnings[0]['message']}", 422
            )
        status = field.get("annotation_status", "KNOWN" if value is not None else "UNREVIEWED")
        if status not in ANNOTATION_STATUSES or ((value is not None) != (status == "KNOWN")):
            raise AppError("INVALID_ANNOTATION", "有值欄位請標記已核實；空值請選擇空白原因。", 422)
        reason = field.get("correction_type", "UNKNOWN")
        note = field.get("note", "")
        if reason not in CORRECTION_TYPES or not isinstance(note, str) or len(note) > 2000:
            raise AppError("INVALID_CORRECTION", "修正原因格式無效。", 422)
        predicted = ai.get(name, {})
        changed = predicted.get("value") != value or predicted.get("unit") != unit
        before = (
            previous.human_ground_truth["fields"][name]["value"]
            if previous and name in previous.human_ground_truth["fields"]
            else predicted.get("value")
        )
        fields[name] = {"value": value, "unit": unit, "annotation_status": status}
        annotations.append(
            FieldAnnotation(
                field_name=name,
                ai_value=predicted.get("value"),
                human_value=value,
                human_input=dict(field),
                before_value=before,
                ai_confidence=predicted.get("confidence", "UNKNOWN"),
                validation_warning=[w for w in attempt.validation_result if w.get("field") == name],
                was_corrected=changed,
                correction_type=reason,
                correction_type_source="HUMAN" if reason != "UNKNOWN" else "UNSPECIFIED",
                annotation_status=status,
                note=note,
            )
        )
    result = {"schema_version": schema_version_for(names), "fields": fields}
    problems = validate(result)
    changed_rows = db.session.execute(
        update(Job).where(Job.id == job.id, Job.revision == expected).values(revision=expected + 1)
    ).rowcount
    if changed_rows != 1:
        db.session.rollback()
        raise AppError("REVISION_CONFLICT", "此資料已有新版本，請重新整理。", 409)
    revision = Confirmation(
        job_id=job.id,
        attempt_id=attempt.id,
        revision_no=expected + 1,
        previous_revision_id=previous.id if previous else None,
        human_ground_truth=result,
        validation_result=problems,
        review_active_ms=elapsed,
    )
    db.session.add(revision)
    db.session.flush()
    for annotation in annotations:
        annotation.confirmation_id = revision.id
        db.session.add(annotation)
    if any(a.was_corrected for a in annotations):
        attempt.hard_reasons = sorted(set(attempt.hard_reasons) | {"HUMAN_CORRECTION"})
    db.session.commit()
    return revision


def share_text(confirmation):
    fields = confirmation.human_ground_truth["fields"]

    def display(name):
        value = fields.get(name, {}).get("value")
        if value is None:
            return ""
        # Keep exactly two lines even when an older confirmation contains line breaks.
        return "".join(str(value).splitlines()).strip()

    return f"{display('outdoor_model')}\n{display('serial_number')}"
