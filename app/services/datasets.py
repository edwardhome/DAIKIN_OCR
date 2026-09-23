import json
import re
import shutil
import zipfile
from pathlib import Path

from flask import current_app
from sqlalchemy import or_, select

from app.errors import AppError
from app.image import digest
from app.models import Attempt, Confirmation, DatasetItem, DatasetVersion, Job, db, now, uid
from app.schemas import CORE_FIELDS
from app.services.jobs import audit_payload, confirmation_dict, latest_confirmation

CATEGORIES = {"confirmed", "corrected", "low_confidence", "failed", "benchmark"}


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def eligible_fields(truth):
    return [
        name
        for name, field in (truth or {}).get("fields", {}).items()
        if field["annotation_status"] in {"KNOWN", "NOT_PRESENT"}
    ]


def candidate(job, category):
    confirmed = latest_confirmation(job.id)
    if category in {"confirmed", "corrected", "benchmark"}:
        if not confirmed:
            return None
        attempt = db.session.get(Attempt, confirmed.attempt_id)
    else:
        attempts = db.session.scalars(
            select(Attempt).where(Attempt.job_id == job.id).order_by(Attempt.created_at.desc())
        ).all()
        attempt = next(
            (
                a
                for a in attempts
                if (
                    a.status == "FAILED"
                    if category == "failed"
                    else "LOW_CONFIDENCE" in a.hard_reasons
                )
            ),
            None,
        )
        if not attempt:
            return None
        confirmed = latest_confirmation(job.id, attempt.id)
    confirmation = confirmation_dict(confirmed) if confirmed else None
    corrected = bool(confirmation and any(f["was_corrected"] for f in confirmation["annotations"]))
    truth = confirmed.human_ground_truth if confirmed else None
    fully_reviewed = bool(truth) and len(eligible_fields(truth)) == len(truth["fields"])
    if category == "confirmed" and (
        corrected or attempt.status != "SUCCEEDED" or not fully_reviewed
    ):
        return None
    if category == "corrected" and not corrected:
        return None
    if category == "benchmark" and not set(CORE_FIELDS).intersection(eligible_fields(truth)):
        return None
    categories = []
    if confirmation and corrected:
        categories.append("corrected")
    elif confirmation and fully_reviewed and attempt.status == "SUCCEEDED":
        categories.append("confirmed")
    if "LOW_CONFIDENCE" in attempt.hard_reasons:
        categories.append("low_confidence")
    if attempt.status == "FAILED":
        categories.append("failed")
    if truth and set(CORE_FIELDS).intersection(eligible_fields(truth)):
        categories.append("benchmark")
    history = db.session.scalars(
        select(Confirmation).where(Confirmation.job_id == job.id).order_by(Confirmation.revision_no)
    ).all()
    return {
        "source_job_id": job.id,
        "source_attempt_id": attempt.id,
        "confirmation_id": confirmed.id if confirmed else None,
        "privacy": "PRIVATE",
        "image_difficulty": job.image_difficulty,
        "scenario_tags": job.scenario_tags,
        "group_key": job.group_key,
        "original_sha256": job.original_sha256,
        "processed_sha256": attempt.processed_sha256,
        "source_original_path": job.original_path,
        "source_processed_path": attempt.processed_path,
        "provider": attempt.provider,
        "model": attempt.model,
        "model_version": attempt.model_version,
        "pipeline_config": attempt.snapshot,
        "latency_ms": attempt.latency_ms,
        "normalized_ai_result": attempt.normalized_ai_result,
        "validation_result": attempt.validation_result,
        "decision_result": attempt.decision_result,
        "repair_result": attempt.repair_result,
        "error_code": attempt.error_code,
        "human_ground_truth": truth,
        "difference": confirmation["annotations"] if confirmation else [],
        "confirmation_history": [confirmation_dict(c) for c in history],
        "eligible_supervised_fields": eligible_fields(truth),
        "is_hard_example": bool(attempt.hard_reasons),
        "hard_reasons": attempt.hard_reasons,
        "categories": categories,
        **audit_payload(attempt),
    }


def export_dataset(payload):
    category = payload.get("category", "benchmark")
    split = payload.get("split", "DEVELOPMENT")
    if (
        not isinstance(category, str)
        or not isinstance(split, str)
        or category not in CATEGORIES
        or split not in {"DEVELOPMENT", "HOLDOUT"}
    ):
        raise AppError("INVALID_DATASET", "資料集類別或分組無效。", 422)
    version = payload.get("version") or (
        "dataset_" + now()[:19].replace(":", "").replace("-", "") + "_" + uid()[:8]
    )
    if not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", version):
        raise AppError("INVALID_VERSION", "版本名稱僅能使用英數字、底線及連字號。", 422)
    if db.session.scalar(select(DatasetVersion.id).where(DatasetVersion.version == version)):
        raise AppError("VERSION_EXISTS", "此資料集版本已存在，請使用新版本名稱。", 409)
    query = select(Job).where(Job.scope.in_(["PRODUCTION", "BENCHMARK_SOURCE"]))
    ids = payload.get("job_ids")
    if ids is not None:
        if (
            not isinstance(ids, list)
            or not ids
            or len(ids) > 100
            or not all(isinstance(x, str) for x in ids)
        ):
            raise AppError("INVALID_SELECTION", "請選擇 1 至 100 筆照片。", 422)
        query = query.where(Job.id.in_(ids))
    jobs = db.session.scalars(query.order_by(Job.created_at.desc()).limit(100)).all()
    samples, seen = [], set()
    for job in jobs:
        sample = candidate(job, category)
        if not sample or job.original_sha256 in seen:
            continue
        conflict = db.session.scalar(
            select(DatasetItem.id)
            .where(
                or_(
                    DatasetItem.group_key == job.group_key,
                    DatasetItem.image_sha256 == job.original_sha256,
                ),
                DatasetItem.split != split,
            )
            .limit(1)
        )
        if conflict:
            raise AppError(
                "DATASET_SPLIT_LEAKAGE",
                "選取的照片或設備群組已屬於另一分組，不能跨入調整集／保留集。",
                409,
            )
        samples.append(sample)
        seen.add(job.original_sha256)
    if not samples:
        raise AppError(
            "EMPTY_DATASET", "目前沒有符合條件的樣本；Benchmark 需先人工確認核心欄位。", 422
        )
    # Keep hard examples first without changing their manually assigned image difficulty.
    samples.sort(key=lambda s: not s["is_hard_example"])
    root = current_app.config["DATASET_DIR"] / category
    directory = root / version
    staging = root / (".pending-" + uid())
    staging.mkdir(parents=True)
    (staging / "images").mkdir()
    try:
        for sample in samples:
            original = Path(sample.pop("source_original_path"))
            if digest(original.read_bytes()) != sample["original_sha256"]:
                raise AppError("IMAGE_INTEGRITY_FAILED", "原圖內容與紀錄不符，停止匯出。", 409)
            relative = f"images/{sample['original_sha256']}{original.suffix}"
            shutil.copyfile(original, staging / relative)
            sample["original_image"] = relative
            processed = sample.pop("source_processed_path")
            sample["processed_image"] = None
            if processed:
                relative = f"images/{sample['processed_sha256']}.jpg"
                if digest(Path(processed).read_bytes()) != sample["processed_sha256"]:
                    raise AppError("IMAGE_INTEGRITY_FAILED", "處理圖內容與紀錄不符。", 409)
                shutil.copyfile(processed, staging / relative)
                sample["processed_image"] = relative
            sample["split"] = split
        records = b"\n".join(json_bytes(s) for s in samples) + b"\n"
        (staging / "samples.jsonl").write_bytes(records)
        training = []
        for sample in samples:
            truth = sample["human_ground_truth"]
            if (
                split == "DEVELOPMENT"
                and truth
                and len(sample["eligible_supervised_fields"]) == len(truth["fields"])
            ):
                training.append(
                    {
                        "image": sample["original_image"],
                        "instruction": "Extract structured equipment nameplate information. Use null for absent fields.",
                        "ground_truth_json": {
                            name: {"value": field["value"], "unit": field["unit"]}
                            for name, field in truth["fields"].items()
                        },
                        "confirmation_id": sample["confirmation_id"],
                    }
                )
        (staging / "training_ready.jsonl").write_bytes(b"\n".join(json_bytes(s) for s in training))
        manifest = {
            "version": version,
            "category": category,
            "split": split,
            "privacy": "PRIVATE",
            "created_at": now(),
            "sample_count": len(samples),
            "training_ready_count": len(training),
            "samples_sha256": digest(records),
            "export_version": "export_v001",
            "notice": "Private local export. No external sharing or training permission is granted.",
        }
        manifest_data = json_bytes(manifest)
        (staging / "manifest.json").write_bytes(manifest_data)
        with zipfile.ZipFile(staging / "export.zip", "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(staging.rglob("*")):
                if path.is_file() and path.name != "export.zip":
                    archive.write(path, path.relative_to(staging))
        if directory.exists():
            raise AppError("VERSION_EXISTS", "匯出目錄已存在。", 409)
        staging.rename(directory)
        record = DatasetVersion(
            version=version,
            category=category,
            split=split,
            directory=str(directory),
            manifest_sha256=digest(manifest_data),
            sample_count=len(samples),
        )
        db.session.add(record)
        db.session.flush()
        for sample in samples:
            db.session.add(
                DatasetItem(
                    dataset_id=record.id,
                    source_job_id=sample["source_job_id"],
                    group_key=sample["group_key"],
                    image_sha256=sample["original_sha256"],
                    split=split,
                    snapshot=sample,
                )
            )
        db.session.commit()
        return record
    except Exception:
        db.session.rollback()
        shutil.rmtree(staging, ignore_errors=True)
        raise


def verify_dataset(dataset):
    path = Path(dataset.directory)
    if digest((path / "manifest.json").read_bytes()) != dataset.manifest_sha256:
        raise AppError("DATASET_INTEGRITY_FAILED", "資料集 manifest 已變更。", 409)
    manifest = json.loads((path / "manifest.json").read_text())
    if digest((path / "samples.jsonl").read_bytes()) != manifest["samples_sha256"]:
        raise AppError("DATASET_INTEGRITY_FAILED", "資料集標註檔已變更。", 409)
    return manifest
