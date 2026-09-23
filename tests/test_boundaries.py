import io
import json
import zipfile

from conftest import confirmation_payload, prediction, upload_job

from app.workers import worker


def confirmed_dataset(app, client, headers):
    job = upload_job(client, headers)
    worker(app, once=True)
    job = client.get(f"/api/jobs/{job['id']}").json
    payload = confirmation_payload(job, outdoor_model="RHF50RVLT")
    assert (
        client.post(
            f"/api/jobs/{job['id']}/confirmations", headers=headers, json=payload
        ).status_code
        == 201
    )
    return client.post("/api/datasets", headers=headers, json={"category": "benchmark"}).json


def test_failed_runs_remain_in_accuracy_denominator(app, client, headers):
    dataset = confirmed_dataset(app, client, headers)
    app.config["FAKE_OUTPUT"] = "invalid JSON"
    experiment = client.post(
        "/api/benchmarks",
        headers=headers,
        json={"dataset_id": dataset["id"], "profiles": ["ollama"]},
    ).json
    worker(app, once=True)
    report = client.get(f"/api/benchmarks/{experiment['id']}").json["reports"]["ollama"]
    assert report["failure_count"] == 1
    assert report["core_field_accuracy"] == {"numerator": 0, "denominator": 6, "rate": 0}
    assert report["hallucination_rate"]["rate"] is None
    assert report["null_rate"]["rate"] is None


def test_low_confidence_unconfirmed_is_not_truth(app, client, headers):
    payload = prediction()
    payload["outdoor_model"]["confidence"] = "LOW"
    app.config["FAKE_OUTPUT"] = json.dumps(payload)
    upload_job(client, headers)
    worker(app, once=True)
    dataset = client.post(
        "/api/datasets", headers=headers, json={"category": "low_confidence"}
    ).json
    with zipfile.ZipFile(
        io.BytesIO(client.get(f"/api/datasets/{dataset['id']}/download").data)
    ) as archive:
        sample = json.loads(archive.read("samples.jsonl"))
        assert sample["human_ground_truth"] is None
        assert "LOW_CONFIDENCE" in sample["hard_reasons"]
        assert archive.read("training_ready.jsonl") == b""


def test_dataset_labels_cannot_be_silently_changed(app, client, headers):
    dataset = confirmed_dataset(app, client, headers)
    path = app.config["DATASET_DIR"] / "benchmark" / dataset["version"] / "samples.jsonl"
    path.write_text("changed")
    response = client.post(
        "/api/benchmarks",
        headers=headers,
        json={"dataset_id": dataset["id"], "profiles": ["ollama"]},
    )
    assert response.status_code == 409
    assert response.json["error"]["code"] == "DATASET_INTEGRITY_FAILED"


def test_bad_api_types_return_errors_not_internal_failures(app, client, headers):
    assert client.post("/api/datasets", headers=headers, json={"category": {}}).status_code == 422
    job = upload_job(client, headers)
    assert (
        client.patch(
            f"/api/jobs/{job['id']}", headers=headers, json={"image_difficulty": {}}
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/api/jobs/{job['id']}/confirmations", headers=headers, json={"attempt_id": {}}
        ).status_code
        == 422
    )
    dataset = confirmed_dataset(app, client, headers)
    assert (
        client.post(
            "/api/benchmarks", headers=headers, json={"dataset_id": dataset["id"], "profiles": [{}]}
        ).status_code
        == 422
    )
