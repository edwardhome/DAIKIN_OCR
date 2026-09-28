import io
import json
import zipfile

from conftest import confirmation_payload, prediction, upload_job
from sqlalchemy import select

from app.models import Attempt, Observation, db
from app.schemas import FIELD_SPECS, IDENTITY_FIELDS, IDENTITY_SCHEMA_VERSION
from app.services.jobs import config_snapshot
from app.workers import worker


def ready(app, client, headers):
    job = upload_job(client, headers)
    worker(app, once=True)
    return client.get(f"/api/jobs/{job['id']}").json


def confirm(client, headers, job, **overrides):
    response = client.post(
        f"/api/jobs/{job['id']}/confirmations",
        headers=headers,
        json=confirmation_payload(job, **overrides),
    )
    assert response.status_code == 201, response.json
    return response.json


def test_identity_scope_end_to_end_keeps_raw_observation_and_only_three_fields(
    app, client, headers
):
    app.config["PROMPT_VERSION"] = IDENTITY_SCHEMA_VERSION
    with app.app_context():
        snapshot = config_snapshot()
    assert snapshot["field_names"] == list(IDENTITY_FIELDS)
    assert snapshot["schema_version"] == IDENTITY_SCHEMA_VERSION
    assert set(snapshot["schema"]["properties"]) == set(IDENTITY_FIELDS)
    assert set(snapshot["schema"]["required"]) == set(IDENTITY_FIELDS)
    bootstrap = client.get("/api/bootstrap").json
    assert [f["name"] for f in bootstrap["recognition_fields"]] == list(IDENTITY_FIELDS)
    assert len(bootstrap["fields"]) == 19  # Legacy field catalog remains available.
    job = ready(app, client, headers)
    attempt = job["attempts"][-1]
    assert attempt["status"] == "SUCCEEDED"
    assert [f["name"] for f in attempt["field_metadata"]] == list(IDENTITY_FIELDS)
    assert set(attempt["normalized_ai_result"]["fields"]) == set(IDENTITY_FIELDS)
    assert "NULL_VALUE" not in attempt["hard_reasons"]
    assert all(w["field"] in IDENTITY_FIELDS for w in attempt["validation_result"])
    with app.app_context():
        # Fake provider deliberately emits all19. We retain its observation without
        # allowing surplus fields to become predictions/annotations in the new scope.
        raw = db.session.scalar(select(Observation)).output_text
        assert "refrigerant" in json.loads(raw)
    revision = confirm(client, headers, job, outdoor_model="RHF50RVLT")
    assert len(revision["annotations"]) == 3
    assert set(revision["human_ground_truth"]["fields"]) == set(IDENTITY_FIELDS)
    assert revision["human_ground_truth"]["schema_version"] == IDENTITY_SCHEMA_VERSION
    assert revision["share_text"] == "RHF50RVLT\nE015283"


def test_identity_failure_can_be_confirmed_but_wrong_field_scope_is_rejected(app, client, headers):
    app.config.update(PROMPT_VERSION=IDENTITY_SCHEMA_VERSION, FAKE_OUTPUT="bad JSON")
    job = ready(app, client, headers)
    assert job["attempts"][-1]["error_code"] == "AI_PARSE_FAILED"
    payload = confirmation_payload(job, outdoor_model="RHF50RVLT")
    payload["fields"]["manufacturer"] = {"value": "DAIKIN", "annotation_status": "KNOWN"}
    response = client.post(f"/api/jobs/{job['id']}/confirmations", headers=headers, json=payload)
    assert response.status_code == 422
    assert response.json["error"]["code"] == "INCOMPLETE_CONFIRMATION"
    revision = confirm(client, headers, job, outdoor_model="RHF50RVLT")
    assert len(revision["annotations"]) == 3


def test_legacy_identity_legacy_retry_preserves_truth_and_missing_prior_fields(
    app, client, headers
):
    job = ready(app, client, headers)
    old_attempt = job["attempts"][-1]["id"]
    old = confirm(client, headers, job)
    assert len(old["annotations"]) == 19
    # Simulate a genuine pre-upgrade snapshot without the newly introduced field_names.
    with app.app_context():
        attempt = db.session.get(Attempt, old_attempt)
        attempt.snapshot = {k: v for k, v in attempt.snapshot.items() if k != "field_names"}
        db.session.commit()
    app.config["PROMPT_VERSION"] = IDENTITY_SCHEMA_VERSION
    assert (
        client.post(f"/api/jobs/{job['id']}/attempts", json={}, headers=headers).status_code == 202
    )
    worker(app, once=True)
    job = client.get(f"/api/jobs/{job['id']}").json
    assert [len(a["field_metadata"]) for a in job["attempts"]] == [19, 3]
    reduced = confirm(client, headers, job, outdoor_model="RHF50RVLT")
    assert len(reduced["annotations"]) == 3
    app.config["PROMPT_VERSION"] = "nameplate_v001"
    assert (
        client.post(f"/api/jobs/{job['id']}/attempts", json={}, headers=headers).status_code == 202
    )
    worker(app, once=True)
    job = client.get(f"/api/jobs/{job['id']}").json
    full = confirm(client, headers, job)
    assert len(full["annotations"]) == 19
    assert full["revision_no"] == 3
    assert (
        client.get(f"/api/confirmations/{old['id']}/share-text").json["text"] == old["share_text"]
    )
    revisions = client.get(f"/api/jobs/{job['id']}/confirmations").json["items"]
    assert [len(r["human_ground_truth"]["fields"]) for r in revisions] == [19, 3, 19]


def test_identity_dataset_exports_explicit_scope_and_no_unreviewed_extra_labels(
    app, client, headers
):
    app.config["PROMPT_VERSION"] = IDENTITY_SCHEMA_VERSION
    job = ready(app, client, headers)
    confirm(client, headers, job)
    response = client.post("/api/datasets", headers=headers, json={"category": "benchmark"})
    assert response.status_code == 201, response.json
    dataset = response.json
    with zipfile.ZipFile(
        io.BytesIO(client.get(f"/api/datasets/{dataset['id']}/download").data)
    ) as archive:
        sample = json.loads(archive.read("samples.jsonl"))
        training = json.loads(archive.read("training_ready.jsonl"))
        manifest = json.loads(archive.read("manifest.json"))
    assert sample["eligible_supervised_fields"] == list(IDENTITY_FIELDS)
    assert set(training["ground_truth_json"]) == set(IDENTITY_FIELDS)
    assert training["schema_version"] == IDENTITY_SCHEMA_VERSION
    assert "serial_number" in training["instruction"]
    assert manifest["field_scopes"] == [list(IDENTITY_FIELDS)]
    experiment = client.post(
        "/api/benchmarks",
        headers=headers,
        json={"dataset_id": dataset["id"], "profiles": ["ollama"]},
    ).json
    app.config["FAKE_OUTPUT"] = "broken"
    worker(app, once=True)
    report = client.get(f"/api/benchmarks/{experiment['id']}").json["reports"]["ollama"]
    assert report["core_fields"] == list(IDENTITY_FIELDS)
    assert report["core_field_accuracy"] == {"numerator": 0, "denominator": 3, "rate": 0}
    assert report["exact_match_accuracy"]["denominator"] == 1
    assert set(report["per_field"]) == set(IDENTITY_FIELDS)


def test_benchmark_compares_legacy_to_identity_on_explicit_common_scope(app, client, headers):
    job = ready(app, client, headers)
    confirm(client, headers, job)
    dataset = client.post("/api/datasets", headers=headers, json={"category": "benchmark"}).json

    def benchmark(profile):
        experiment = client.post(
            "/api/benchmarks",
            headers=headers,
            json={"dataset_id": dataset["id"], "profiles": [profile]},
        ).json
        worker(app, once=True)
        return experiment["id"]

    baseline = benchmark("ollama")
    app.config["PROMPT_VERSION"] = IDENTITY_SCHEMA_VERSION
    app.config["FAKE_OUTPUT"] = json.dumps(prediction(serial_number="E01528B"))
    candidate = benchmark("alternative")
    report = client.get(f"/api/benchmarks/{candidate}").json["reports"]["alternative"]
    assert report["core_field_accuracy"]["denominator"] == 3
    assert report["core_field_accuracy"]["numerator"] == 2
    assert set(report["excluded_fields"]) == set(FIELD_SPECS) - set(IDENTITY_FIELDS)
    comparison = client.get(
        f"/api/benchmarks/{candidate}/compare",
        query_string={"baseline": baseline, "target": "alternative", "baseline_target": "ollama"},
    )
    assert comparison.status_code == 200, comparison.json
    result = comparison.json
    assert result["status"] == "REGRESSION"
    assert result["regressed_fields"] == ["serial_number"]
    assert result["scope_changed"] is True
    assert result["core_fields"] == list(IDENTITY_FIELDS)
    assert result["before_metrics"]["core_field_accuracy"] == {
        "numerator": 3,
        "denominator": 3,
        "rate": 1,
    }
    assert result["after_metrics"]["core_field_accuracy"]["denominator"] == 3
