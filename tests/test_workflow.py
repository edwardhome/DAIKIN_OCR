import io
import json
import time
import zipfile
from pathlib import Path

import pytest
from conftest import confirmation_payload, image_bytes, prediction, upload_job
from PIL import Image
from sqlalchemy import select

from app.image import ImagePreprocessor, digest
from app.models import Attempt, FieldAnnotation, Job, Observation, db
from app.workers import claim, recover_expired, worker


def recognized(app, client, headers):
    job = upload_job(client, headers)
    worker(app, once=True)
    result = client.get(f"/api/jobs/{job['id']}").json
    assert result["attempts"][-1]["status"] == "SUCCEEDED", result
    return result


def confirm_job(client, headers, job, **changes):
    response = client.post(
        f"/api/jobs/{job['id']}/confirmations",
        headers=headers,
        json=confirmation_payload(job, **changes),
    )
    assert response.status_code == 201, response.json
    return response.json


def export(client, headers, **payload):
    response = client.post("/api/datasets", headers=headers, json=payload)
    assert response.status_code == 201, response.json
    return response.json


def test_complete_workflow_and_immutable_revisions(app, client, headers):
    job = recognized(app, client, headers)
    aid = job["attempts"][-1]["id"]
    assert client.get(f"/api/confirmations/{aid}/share-text").status_code == 404
    first = confirm_job(client, headers, job, outdoor_model="RHF50RVLT")
    assert first["share_text"] == "RHF50RVLT\nE015283"
    assert len(first["annotations"]) == 19
    field = next(a for a in first["annotations"] if a["field_name"] == "outdoor_model")
    assert field["ai_value"] == "RHF5ORVLT" and field["human_value"] == "RHF50RVLT"
    assert field["was_corrected"] and field["correction_type"] == "UNKNOWN"
    assert (
        client.post(
            f"/api/jobs/{job['id']}/confirmations", headers=headers, json=confirmation_payload(job)
        ).status_code
        == 409
    )
    current = client.get(f"/api/jobs/{job['id']}").json
    second = confirm_job(client, headers, current, outdoor_model="RHF51RVLT")
    assert second["revision_no"] == 2
    assert second["share_text"] == "RHF51RVLT\nE015283"
    changed = next(a for a in second["annotations"] if a["field_name"] == "outdoor_model")
    assert changed["before_value"] == "RHF50RVLT"
    assert changed["ai_value"] == "RHF5ORVLT"
    assert (
        client.get(f"/api/confirmations/{first['id']}/share-text").json["text"]
        == first["share_text"]
    )
    with app.app_context():
        attempt = db.session.get(Attempt, aid)
        original = db.session.get(Job, job["id"])
        assert attempt.normalized_ai_result["fields"]["outdoor_model"]["value"] == "RHF5ORVLT"
        assert digest(Path(original.original_path).read_bytes()) == digest(image_bytes())
        assert Path(attempt.processed_path) != Path(original.original_path)
        assert len(db.session.scalars(select(FieldAnnotation)).all()) == 38
    assert len(client.get("/api/jobs").json["items"]) == 1
    assert client.get("/api/dashboard").json["corrected_samples"] == 1
    assert client.get(f"/api/attempts/{aid}/debug").status_code == 404


def test_parse_failure_preserves_observation_and_allows_manual_truth(app, client, headers):
    app.config["FAKE_OUTPUT"] = "not JSON"
    job = upload_job(client, headers)
    worker(app, once=True)
    result = client.get(f"/api/jobs/{job['id']}").json
    attempt = result["attempts"][-1]
    assert attempt["error_code"] == "AI_PARSE_FAILED"
    assert app.config["FAKE_CALLS"] == 1
    with app.app_context():
        observation = db.session.scalar(select(Observation))
        assert observation.output_text == "not JSON"
        assert db.session.get(Attempt, attempt["id"]).repair_result["succeeded"] is False
    revision = confirm_job(client, headers, result, outdoor_model="RHF50RVLT")
    assert revision["human_ground_truth"]["fields"]["outdoor_model"]["value"] == "RHF50RVLT"


def test_retry_creates_new_attempt_and_retains_old_result(app, client, headers):
    job = recognized(app, client, headers)
    first_id = job["attempts"][-1]["id"]
    app.config["FAKE_OUTPUT"] = json.dumps(prediction(outdoor_model="RHF50RVLT"))
    response = client.post(
        f"/api/jobs/{job['id']}/attempts", json={"profile_id": "alternative"}, headers=headers
    )
    assert response.status_code == 202
    assert (
        client.post(f"/api/jobs/{job['id']}/attempts", json={}, headers=headers).status_code == 409
    )
    worker(app, once=True)
    result = client.get(f"/api/jobs/{job['id']}").json
    assert len(result["attempts"]) == 2
    assert result["attempts"][0]["id"] == first_id
    assert all("MODEL_DISAGREEMENT" in a["hard_reasons"] for a in result["attempts"])
    assert result["attempts"][1]["decision_result"]["provider_disagreement"] is True


def test_failed_export_has_no_ground_truth_or_training_labels(app, client, headers):
    app.config["FAKE_OUTPUT"] = "broken"
    upload_job(client, headers)
    worker(app, once=True)
    dataset = export(client, headers, category="failed", version="dataset_failed_v001")
    download = client.get(f"/api/datasets/{dataset['id']}/download")
    with zipfile.ZipFile(io.BytesIO(download.data)) as archive:
        sample = json.loads(archive.read("samples.jsonl"))
        assert sample["human_ground_truth"] is None
        assert sample["ocr_raw_result"] is None
        assert sample["vlm_raw_result"]
        assert sample["eligible_supervised_fields"] == []
        assert archive.read("training_ready.jsonl") == b""
        assert json.loads(archive.read("manifest.json"))["privacy"] == "PRIVATE"
    assert (
        client.post("/api/datasets", headers=headers, json={"category": "benchmark"}).status_code
        == 422
    )


def test_dataset_versioning_integrity_and_split_leakage(app, client, headers):
    job = recognized(app, client, headers)
    confirm_job(client, headers, job, outdoor_model="RHF50RVLT")
    dataset = export(client, headers, category="benchmark", version="dataset_v001", split="HOLDOUT")
    assert (
        client.post(
            "/api/datasets",
            headers=headers,
            json={"category": "benchmark", "version": "dataset_v001"},
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/datasets", headers=headers, json={"category": "corrected", "split": "DEVELOPMENT"}
        ).json["error"]["code"]
        == "DATASET_SPLIT_LEAKAGE"
    )
    current = client.get(f"/api/jobs/{job['id']}").json
    confirm_job(client, headers, current, outdoor_model="NEW-HUMAN-VALUE")
    with zipfile.ZipFile(
        io.BytesIO(client.get(f"/api/datasets/{dataset['id']}/download").data)
    ) as archive:
        sample = json.loads(archive.read("samples.jsonl"))
        assert sample["human_ground_truth"]["fields"]["outdoor_model"]["value"] == "RHF50RVLT"
        assert archive.read("training_ready.jsonl") == b""


def test_unreviewed_fields_do_not_enter_supervised_export(app, client, headers):
    job = recognized(app, client, headers)
    payload = confirmation_payload(job)
    payload["fields"]["net_weight"]["annotation_status"] = "UNREVIEWED"
    assert (
        client.post(
            f"/api/jobs/{job['id']}/confirmations", headers=headers, json=payload
        ).status_code
        == 201
    )
    assert (
        client.post("/api/datasets", headers=headers, json={"category": "confirmed"}).status_code
        == 422
    )
    dataset = export(client, headers, category="benchmark")
    with zipfile.ZipFile(
        io.BytesIO(client.get(f"/api/datasets/{dataset['id']}/download").data)
    ) as archive:
        sample = json.loads(archive.read("samples.jsonl"))
        assert "net_weight" not in sample["eligible_supervised_fields"]
        assert archive.read("training_ready.jsonl") == b""


def test_benchmark_exact_match_and_per_field_regression(app, client, headers):
    job = recognized(app, client, headers)
    confirm_job(client, headers, job, outdoor_model="RHF50RVLT")
    dataset = export(client, headers, category="benchmark")
    app.config["FAKE_OUTPUT"] = json.dumps(prediction(outdoor_model="RHF50RVLT"))
    baseline = client.post(
        "/api/benchmarks",
        json={"dataset_id": dataset["id"], "profiles": ["ollama"]},
        headers=headers,
    ).json
    worker(app, once=True)
    report = client.get(f"/api/benchmarks/{baseline['id']}").json
    assert report["reports"]["ollama"]["core_field_accuracy"]["rate"] == 1
    assert report["reports"]["ollama"]["exact_match_accuracy"]["rate"] == 1
    app.config["FAKE_OUTPUT"] = json.dumps(
        prediction(outdoor_model="RHF50RVLT", serial_number="E01528B")
    )
    candidate = client.post(
        "/api/benchmarks",
        json={"dataset_id": dataset["id"], "profiles": ["alternative"]},
        headers=headers,
    ).json
    worker(app, once=True)
    report = client.get(f"/api/benchmarks/{candidate['id']}").json
    metric = report["reports"]["alternative"]
    assert metric["core_field_accuracy"]["rate"] == pytest.approx(5 / 6)
    assert metric["exact_match_accuracy"]["rate"] == 0
    assert metric["hallucination_rate"]["rate"] is None
    compare = client.get(
        f"/api/benchmarks/{candidate['id']}/compare",
        query_string={
            "baseline": baseline["id"],
            "target": "alternative",
            "baseline_target": "ollama",
        },
    ).json
    assert compare["status"] == "REGRESSION"
    assert compare["regressed_fields"] == ["serial_number"]
    item_id = report["items"][0]["id"]
    assert (
        client.post(
            f"/api/benchmark-items/{item_id}/assessments",
            json={"fields": {"serial_number": "UNSUPPORTED"}},
            headers=headers,
        ).status_code
        == 200
    )
    audited = client.get(f"/api/benchmarks/{candidate['id']}").json
    assert audited["reports"]["alternative"]["hallucination_rate"]["rate"] == 1
    assert client.get("/api/dashboard").json["total_jobs"] == 1
    assert len(client.get("/api/jobs").json["items"]) == 1


def test_worker_interruption_recovery_is_not_an_automatic_retry(app, client, headers):
    upload_job(client, headers)
    with app.app_context():
        identifier, owner = claim("ollama")
        attempt = db.session.get(Attempt, identifier)
        attempt.lease_until = time.time() - 1
        db.session.commit()
        recover_expired()
        assert db.session.get(Attempt, identifier).error_code == "WORKER_INTERRUPTED"
    worker(app, once=True)
    assert app.config.get("FAKE_CALLS", 0) == 0


def test_upload_rejections_and_csrf(app, client, headers):
    assert (
        client.post("/api/jobs", data={"image": (io.BytesIO(image_bytes()), "a.jpg")}).status_code
        == 403
    )
    assert (
        client.post(
            "/api/jobs", data={"image": (io.BytesIO(b"not an image"), "a.jpg")}, headers=headers
        ).status_code
        == 415
    )
    out = io.BytesIO()
    Image.new("RGB", (20, 20)).save(out, "GIF")
    assert (
        client.post(
            "/api/jobs", data={"image": (io.BytesIO(out.getvalue()), "a.gif")}, headers=headers
        ).status_code
        == 415
    )
    app.config["MAX_UPLOAD_BYTES"] = 100
    assert (
        client.post(
            "/api/jobs", data={"image": (io.BytesIO(image_bytes()), "a.jpg")}, headers=headers
        ).status_code
        == 413
    )


def test_external_access_requires_password_and_protects_all_resources(app, client, headers):
    job = recognized(app, client, headers)
    assert (
        client.get("/api/jobs", environ_overrides={"REMOTE_ADDR": "203.0.113.10"}).status_code
        == 403
    )
    app.config["ACCESS_PASSWORD"] = "example-long-password"
    for path in ["/api/jobs", f"/api/jobs/{job['id']}/image", "/api/datasets", "/api/dashboard"]:
        assert client.get(path).status_code == 401
    login = client.get("/login")
    assert login.status_code == 200
    with client.session_transaction() as session:
        csrf = session["csrf"]
    assert client.post("/login", data={"password": "wrong", "csrf_token": csrf}).status_code == 200
    assert (
        client.post(
            "/login", data={"password": "example-long-password", "csrf_token": csrf}
        ).status_code
        == 302
    )
    assert client.get("/api/jobs").status_code == 200
    assert b"example-long-password" not in client.get("/api/bootstrap").data


def test_heic_and_orientation_preserve_original(tmp_path):
    import pillow_heif

    pillow_heif.register_heif_opener()
    heic = tmp_path / "original.heic"
    Image.new("RGB", (120, 80), "white").save(heic, "HEIF")
    original = heic.read_bytes()
    processor = ImagePreprocessor()
    processed = tmp_path / "processed.jpg"
    processor.process(heic, processed, {"max_edge": 256, "contrast": 1, "sharpness": 1}, 100000)
    assert heic.read_bytes() == original
    assert Image.open(processed).format == "JPEG"
    source = tmp_path / "rotated.jpg"
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (100, 50), "white").save(source, exif=exif)
    processor.process(
        source, tmp_path / "upright.jpg", {"max_edge": 256, "contrast": 1, "sharpness": 1}, 100000
    )
    assert Image.open(tmp_path / "upright.jpg").size == (50, 100)
    assert Image.open(source).getexif()[274] == 6
