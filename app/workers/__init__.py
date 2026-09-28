import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from sqlalchemy import select, update

from app.errors import AppError, ProviderError
from app.image import ImagePreprocessor
from app.models import Attempt, Job, Observation, db, now, uid
from app.providers import SUPPORTED_PROVIDERS, InferenceImage, make_provider, provider_api_key
from app.schemas import snapshot_field_names
from app.services.normalize import normalize, parse_output
from app.validators import validate

log = logging.getLogger("nameplate.jobs")
ACTIVE = ("PREPROCESSING", "RUNNING")


def recover_expired():
    db.session.execute(
        update(Attempt)
        .where(Attempt.status.in_(ACTIVE), Attempt.lease_until < time.time())
        .values(
            status="FAILED",
            error_code="WORKER_INTERRUPTED",
            error_message="辨識程序曾中斷，請重新辨識。",
            finished_at=now(),
            hard_reasons=["FAILED"],
        )
    )
    db.session.commit()


def claim(provider=None):
    query = select(Attempt.id).where(Attempt.status == "QUEUED").order_by(Attempt.created_at)
    if provider:
        query = query.where(
            Attempt.provider.in_(provider)
            if isinstance(provider, (tuple, list))
            else Attempt.provider == provider
        )
    for identifier in db.session.scalars(query.limit(20)).all():
        worker_id = uid()
        count = db.session.execute(
            update(Attempt)
            .where(Attempt.id == identifier, Attempt.status == "QUEUED")
            .values(
                status="PREPROCESSING",
                worker_id=worker_id,
                lease_until=time.time() + 30,
                started_at=now(),
            )
        ).rowcount
        db.session.commit()
        if count:
            return identifier, worker_id
    return None


def run_attempt(app, identifier, worker_id):
    with app.app_context():
        started = time.monotonic()
        a = db.session.get(Attempt, identifier)
        job = db.session.get(Job, a.job_id)
        provider_started = None
        try:
            a.queue_ms = (
                datetime.fromisoformat(a.started_at) - datetime.fromisoformat(a.created_at)
            ).total_seconds() * 1000
            output = app.config["DATA_DIR"] / "processed" / a.id / "inference.jpg"
            a.processed_sha256 = ImagePreprocessor().process(
                job.original_path,
                output,
                a.snapshot["preprocessor"],
                app.config["MAX_IMAGE_PIXELS"],
            )
            a.processed_path = str(output)
            a.status = "RUNNING"
            snapshot = a.snapshot
            db.session.commit()
            factory = app.config.get("PROVIDER_FACTORY", make_provider)
            provider = factory(
                snapshot["profile"],
                timeout=snapshot["timeout_seconds"],
                max_tokens=snapshot["max_tokens"],
                api_key=provider_api_key(app.config, snapshot["profile"]["provider"]),
            )
            provider_started = time.monotonic()
            response = provider.recognize(
                image=InferenceImage(output.read_bytes()),
                schema=snapshot["schema"],
                instruction=snapshot["instruction"],
            )
            elapsed = (time.monotonic() - provider_started) * 1000
            # End any old read transaction after the network call; verify the lease owner again.
            db.session.expire_all()
            a = db.session.get(Attempt, identifier)
            if a.worker_id != worker_id or a.status != "RUNNING":
                return
            a.latency_ms = response.inference_ms if response.inference_ms is not None else elapsed
            a.model_version = response.model_version
            observation = Observation(
                attempt_id=a.id,
                stage="VLM",
                provider=a.provider,
                model=response.model,
                model_version=response.model_version,
                raw_result=response.raw_result,
                output_text=response.output_text,
            )
            db.session.add(observation)
            db.session.commit()  # Preserve observation even if parsing fails next.
            if response.error_code:
                raise ProviderError(
                    response.error_code,
                    response.error_message or "模型服務的回覆格式無效。",
                    False,
                )
            if response.refused:
                raise AppError(
                    "MODEL_REFUSAL", "模型未接受這次辨識，請重新拍攝或改用其他模型。", 502, True
                )
            payload, repaired = parse_output(response.output_text)
            normalized, warnings = normalize(payload, snapshot_field_names(snapshot))
            warnings.extend(validate(normalized))
            a.normalized_ai_result, a.validation_result, a.repair_result = (
                normalized,
                warnings,
                repaired,
            )
            a.decision_result = {
                "policy": "single_provider_v001",
                "selected_observation_id": observation.id,
                "requires_human_confirmation": True,
                "thresholds_applied": False,
                "confidence_kind": "SELF_REPORTED_ENUM",
                "routing": [a.provider],
                "provider_disagreement": False,
                "ocr_vlm_conflict": None,
            }
            reasons = []
            if any(f["value"] is None for f in normalized["fields"].values()):
                reasons.append("NULL_VALUE")
            if any(f["confidence"] == "LOW" for f in normalized["fields"].values()):
                reasons.append("LOW_CONFIDENCE")
            if warnings:
                reasons.append("VALIDATION_WARNING")
            comparisons = db.session.scalars(
                select(Attempt)
                .join(Job)
                .where(
                    Job.original_sha256 == job.original_sha256,
                    Attempt.id != a.id,
                    Attempt.status == "SUCCEEDED",
                )
            ).all()
            disagreed = []
            for previous in comparisons:
                old = previous.normalized_ai_result
                if (
                    not old
                    or previous.snapshot["normalizer_version"] != snapshot["normalizer_version"]
                ):
                    continue
                if any(
                    (field["value"], field["unit"])
                    != (old["fields"][name]["value"], old["fields"][name]["unit"])
                    for name, field in normalized["fields"].items()
                    if name in old["fields"]
                ):
                    disagreed.append(previous.id)
                    previous.hard_reasons = sorted(
                        set(previous.hard_reasons) | {"MODEL_DISAGREEMENT"}
                    )
            if disagreed:
                reasons.append("MODEL_DISAGREEMENT")
                a.decision_result = {
                    **a.decision_result,
                    "provider_disagreement": True,
                    "compared_attempt_ids": disagreed,
                }
            a.hard_reasons, a.status = reasons, "SUCCEEDED"
        except AppError as error:
            a.status, a.error_code, a.error_message = "FAILED", error.code, error.message
            a.hard_reasons = ["FAILED"]
            if error.code == "AI_PARSE_FAILED":
                a.repair_result = {"attempted": True, "succeeded": False}
        except Exception:
            db.session.rollback()
            a = db.session.get(Attempt, identifier)
            a.status, a.error_code = "FAILED", "PROCESSING_FAILED"
            a.error_message, a.hard_reasons = "辨識程序發生錯誤，請重新辨識。", ["FAILED"]
        finally:
            if a.worker_id == worker_id and a.status in {"SUCCEEDED", "FAILED"}:
                a.finished_at = now()
                a.processing_ms = (time.monotonic() - started) * 1000
                if a.latency_ms is None and provider_started:
                    a.latency_ms = (time.monotonic() - provider_started) * 1000
                a.lease_until = None
                db.session.commit()
                log.info(
                    json.dumps(
                        {
                            "timestamp": now(),
                            "job_id": a.job_id,
                            "attempt_id": a.id,
                            "provider": a.provider,
                            "model": a.model,
                            "latency_ms": a.latency_ms,
                            "success": a.status == "SUCCEEDED",
                            "error_code": a.error_code,
                        }
                    )
                )


def worker(app, once=False):
    # Keep one local and one shared cloud slot even when more providers are configured.
    slots = {
        "local": ("ollama",),
        "cloud": tuple(p for p in SUPPORTED_PROVIDERS if p != "ollama"),
    }
    with ThreadPoolExecutor(max_workers=2) as executor:
        active = {}
        while True:
            with app.app_context():
                recover_expired()
                for key, (future, identifier, owner) in list(active.items()):
                    if future.done():
                        future.result()
                        del active[key]
                    else:
                        db.session.execute(
                            update(Attempt)
                            .where(
                                Attempt.id == identifier,
                                Attempt.worker_id == owner,
                                Attempt.status.in_(ACTIVE),
                            )
                            .values(lease_until=time.time() + app.config["LEASE_SECONDS"])
                        )
                db.session.commit()
                for slot, providers in slots.items():
                    if slot not in active:
                        claimed = claim(providers)
                        if claimed:
                            identifier, owner = claimed
                            active[slot] = (
                                executor.submit(run_attempt, app, identifier, owner),
                                identifier,
                                owner,
                            )
                if once and not active:
                    return
            time.sleep(0.2 if once else 1)
