from collections import defaultdict
from pathlib import Path
from statistics import mean

from flask import current_app
from sqlalchemy import select

from app.errors import AppError
from app.image import digest
from app.models import Attempt, Benchmark, BenchmarkItem, DatasetItem, DatasetVersion, Job, db
from app.schemas import CORE_FIELDS, FIELD_SPECS
from app.services.datasets import verify_dataset
from app.services.jobs import config_snapshot, new_attempt, require


def fraction(correct, total):
    return {"numerator": correct, "denominator": total, "rate": correct / total if total else None}


def create_benchmark(payload):
    dataset = require(DatasetVersion, payload.get("dataset_id"))
    if dataset.category != "benchmark":
        raise AppError("NOT_BENCHMARK_DATASET", "請先建立人工確認的 Benchmark 資料集。", 422)
    verify_dataset(dataset)
    targets = payload.get("profiles", [])
    if (
        not isinstance(targets, list)
        or not 1 <= len(targets) <= 8
        or not all(isinstance(target, str) for target in targets)
        or len(set(targets)) != len(targets)
    ):
        raise AppError("INVALID_TARGETS", "請選擇 1 至 8 組不同的模型設定。", 422)
    configs = {target: config_snapshot(target) for target in targets}
    items = db.session.scalars(
        select(DatasetItem).where(DatasetItem.dataset_id == dataset.id)
    ).all()
    for item in items:
        image = Path(dataset.directory) / item.snapshot["original_image"]
        if digest(image.read_bytes()) != item.image_sha256:
            raise AppError("DATASET_INTEGRITY_FAILED", "Benchmark 原圖已變更。", 409)
    experiment = Benchmark(
        dataset_id=dataset.id,
        targets=configs,
        regression_policy={
            "max_drop": current_app.config["REGRESSION_MAX_DROP"],
            "min_known_samples": current_app.config["REGRESSION_MIN_KNOWN_SAMPLES"],
        },
    )
    db.session.add(experiment)
    db.session.flush()
    for item in items:
        image = Path(dataset.directory) / item.snapshot["original_image"]
        original_job = require(Job, item.source_job_id)
        job = Job(
            scope="BENCHMARK",
            original_path=str(image),
            original_sha256=item.image_sha256,
            mime_type=original_job.mime_type,
            file_size=image.stat().st_size,
            group_key=item.group_key,
            image_difficulty=item.snapshot["image_difficulty"],
            scenario_tags=item.snapshot["scenario_tags"],
        )
        db.session.add(job)
        db.session.flush()
        for target, snapshot in configs.items():
            attempt = new_attempt(job, snapshot)
            db.session.add(
                BenchmarkItem(
                    benchmark_id=experiment.id,
                    dataset_item_id=item.id,
                    attempt_id=attempt.id,
                    target_id=target,
                    ground_truth_snapshot=item.snapshot["human_ground_truth"],
                )
            )
    db.session.commit()
    return experiment


def metrics(rows):
    per_field = {
        name: {
            "known": 0,
            "correct": 0,
            "absent": 0,
            "correct_absent": 0,
            "reviewed": 0,
            "different": 0,
        }
        for name in FIELD_SPECS
    }
    exact_n = exact_d = nulls = slots = failures = unsupported = audited = unsupported_absent = 0
    latencies, times = [], []
    for item, attempt, sample in rows:
        success = attempt.status == "SUCCEEDED"
        failures += attempt.status == "FAILED"
        prediction = (attempt.normalized_ai_result or {}).get("fields", {})
        truth = item.ground_truth_snapshot["fields"]
        if attempt.latency_ms is not None:
            latencies.append(attempt.latency_ms)
        if attempt.processing_ms is not None:
            times.append(attempt.processing_ms)
        all_core_scorable = all(
            truth[n]["annotation_status"] in {"KNOWN", "NOT_PRESENT"} for n in CORE_FIELDS
        )
        all_core_match = success
        for name in FIELD_SPECS:
            expected = truth[name]
            predicted = prediction.get(name, {"value": None, "unit": None})
            match = (
                success
                and predicted.get("value") == expected["value"]
                and predicted.get("unit") == expected["unit"]
            )
            stats = per_field[name]
            state = expected["annotation_status"]
            if state == "KNOWN":
                stats["known"] += 1
                stats["correct"] += bool(match)
            elif state == "NOT_PRESENT":
                stats["absent"] += 1
                stats["correct_absent"] += bool(match)
                unsupported_absent += predicted.get("value") is not None
            if state in {"KNOWN", "NOT_PRESENT"}:
                stats["reviewed"] += 1
                stats["different"] += not match
            if name in CORE_FIELDS:
                all_core_match = all_core_match and match
                if success:
                    slots += 1
                    nulls += predicted.get("value") is None
            assessment = item.field_assessments.get(name)
            if predicted.get("value") is not None and assessment in {"SUPPORTED", "UNSUPPORTED"}:
                audited += 1
                unsupported += assessment == "UNSUPPORTED"
        if all_core_scorable:
            exact_d += 1
            exact_n += bool(all_core_match)
    fields = {
        name: {
            "accuracy": fraction(s["correct"], s["known"]),
            "absence_accuracy": fraction(s["correct_absent"], s["absent"]),
            "correction_rate": fraction(s["different"], s["reviewed"]),
        }
        for name, s in per_field.items()
    }
    return {
        "sample_count": len(rows),
        "failure_count": failures,
        "completed_count": sum(a.status in {"SUCCEEDED", "FAILED"} for _, a, _ in rows),
        "core_field_accuracy": fraction(
            sum(per_field[n]["correct"] for n in CORE_FIELDS),
            sum(per_field[n]["known"] for n in CORE_FIELDS),
        ),
        "exact_match_accuracy": fraction(exact_n, exact_d),
        "per_field": fields,
        "correction_rate": fraction(
            sum(s["different"] for s in per_field.values()),
            sum(s["reviewed"] for s in per_field.values()),
        ),
        "null_rate": fraction(nulls, slots),
        "hallucination_rate": fraction(unsupported, audited),
        "unsupported_absent_predictions": unsupported_absent,
        "average_latency_ms": mean(latencies) if latencies else None,
        "average_processing_ms": mean(times) if times else None,
    }


def benchmark_report(experiment):
    dataset = require(DatasetVersion, experiment.dataset_id)
    rows = db.session.execute(
        select(BenchmarkItem, Attempt, DatasetItem)
        .join(Attempt, BenchmarkItem.attempt_id == Attempt.id)
        .join(DatasetItem, BenchmarkItem.dataset_item_id == DatasetItem.id)
        .where(BenchmarkItem.benchmark_id == experiment.id)
    ).all()
    grouped = defaultdict(list)
    for row in rows:
        grouped[row[0].target_id].append(row)
    reports = {}
    for target, group in grouped.items():
        reports[target] = metrics(group)
        reports[target]["by_difficulty"] = {
            difficulty: metrics(
                [row for row in group if row[2].snapshot["image_difficulty"] == difficulty]
            )
            for difficulty in ("EASY", "MEDIUM", "HARD", "UNLABELED")
        }
    return {
        "id": experiment.id,
        "dataset_id": dataset.id,
        "dataset_version": dataset.version,
        "dataset_hash": dataset.manifest_sha256,
        "created_at": experiment.created_at,
        "targets": experiment.targets,
        "evaluation_version": experiment.evaluation_version,
        "regression_policy": experiment.regression_policy,
        "reports": reports,
        "complete": all(a.status in {"SUCCEEDED", "FAILED"} for _, a, _ in rows),
        "items": [
            {
                "id": i.id,
                "target_id": i.target_id,
                "attempt_id": a.id,
                "job_id": a.job_id,
                "status": a.status,
                "latency_ms": a.latency_ms,
                "ai_result": a.normalized_ai_result,
                "ground_truth": i.ground_truth_snapshot,
                "field_assessments": i.field_assessments,
                "image_difficulty": s.snapshot["image_difficulty"],
            }
            for i, a, s in rows
        ],
    }


def compare(experiment, baseline, target, baseline_target):
    if (
        experiment.dataset_id != baseline.dataset_id
        or experiment.evaluation_version != baseline.evaluation_version
    ):
        raise AppError("INCOMPARABLE_BENCHMARK", "前後比較必須使用相同固定資料集與評分版本。", 422)
    after, before = benchmark_report(experiment), benchmark_report(baseline)
    if target not in after["reports"] or baseline_target not in before["reports"]:
        raise AppError("UNKNOWN_TARGET", "比較的模型組合不存在。", 422)
    if not after["complete"] or not before["complete"]:
        raise AppError("BENCHMARK_INCOMPLETE", "請等待兩次 Benchmark 都完成。", 409)
    changes, regressed, insufficient = {}, [], []
    policy = experiment.regression_policy
    for name in CORE_FIELDS:
        old = before["reports"][baseline_target]["per_field"][name]["accuracy"]
        new = after["reports"][target]["per_field"][name]["accuracy"]
        delta = (
            new["rate"] - old["rate"]
            if new["rate"] is not None and old["rate"] is not None
            else None
        )
        changes[name] = {"before": old, "after": new, "delta": delta}
        if delta is not None and delta < -policy["max_drop"] - 1e-12:
            regressed.append(name)
        if min(old["denominator"], new["denominator"]) < policy["min_known_samples"]:
            insufficient.append(name)
    failure_increase = (
        after["reports"][target]["failure_count"]
        > before["reports"][baseline_target]["failure_count"]
    )
    return {
        "status": "REGRESSION"
        if regressed or failure_increase
        else "INSUFFICIENT_DATA"
        if insufficient
        else "PASS",
        "fields": changes,
        "regressed_fields": regressed,
        "insufficient_fields": insufficient,
        "failure_increase": failure_increase,
        "policy": policy,
        "note": "此報告不會自動更換部署模型。",
    }
