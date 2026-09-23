from collections import Counter, defaultdict
from statistics import mean

from sqlalchemy import select

from app.models import Attempt, FieldAnnotation, Job, db
from app.schemas import FIELD_SPECS
from app.services.benchmark import fraction
from app.services.jobs import latest_confirmation


def dashboard():
    jobs = db.session.scalars(select(Job).where(Job.scope == "PRODUCTION")).all()
    attempts = db.session.scalars(select(Attempt).join(Job).where(Job.scope == "PRODUCTION")).all()
    annotations, confirmed, corrected, times = [], 0, 0, []
    fully_correct = 0
    models, difficulty = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
    for job in jobs:
        confirmation = latest_confirmation(job.id)
        if not confirmation:
            continue
        confirmed += 1
        fields = db.session.scalars(
            select(FieldAnnotation).where(FieldAnnotation.confirmation_id == confirmation.id)
        ).all()
        annotations.extend(fields)
        changed = any(f.was_corrected for f in fields)
        corrected += changed
        times.append(confirmation.review_active_ms)
        attempt = db.session.get(Attempt, confirmation.attempt_id)
        fully_correct += (
            not changed
            and attempt.status == "SUCCEEDED"
            and all(f.annotation_status in {"KNOWN", "NOT_PRESENT"} for f in fields)
        )
        key = f"{attempt.provider} / {attempt.model} / {attempt.model_version or 'version unknown'}"
        models[key][0] += changed
        models[key][1] += 1
        difficulty[job.image_difficulty][0] += changed
        difficulty[job.image_difficulty][1] += 1
    ranking = []
    for name, (label, _, _) in FIELD_SPECS.items():
        fields = [
            a for a in annotations if a.field_name == name and a.annotation_status != "UNREVIEWED"
        ]
        ranking.append(
            {
                "field": name,
                "label": label,
                **fraction(sum(a.was_corrected for a in fields), len(fields)),
            }
        )
    ranking.sort(key=lambda row: row["rate"] if row["rate"] is not None else -1, reverse=True)
    return {
        "total_jobs": len(jobs),
        "confirmed_samples": confirmed,
        "fully_correct_samples": fully_correct,
        "corrected_samples": corrected,
        "hard_examples": len({a.job_id for a in attempts if a.hard_reasons}),
        "correction_rate": fraction(corrected, confirmed),
        "average_processing_ms": mean(
            [a.processing_ms for a in attempts if a.processing_ms is not None]
        )
        if any(a.processing_ms is not None for a in attempts)
        else None,
        "average_human_review_ms": mean(times) if times else None,
        "provider_usage": dict(Counter(a.provider for a in attempts)),
        "correction_by_model": {k: fraction(*v) for k, v in models.items()},
        "correction_by_difficulty": {k: fraction(*v) for k, v in difficulty.items()},
        "field_error_ranking": ranking,
        "correction_types": dict(
            Counter(a.correction_type for a in annotations if a.was_corrected)
        ),
        "counting_policy": "每張現場照片只計最新人工確認版本；Benchmark 執行排除。",
    }
