import json
import threading
import time

import httpx
import pytest
from conftest import confirmation_payload, prediction, upload_job
from sqlalchemy import select

from app import config
from app.models import Attempt, Observation, db
from app.providers import ProviderResponse, make_provider
from app.schemas import IDENTITY_SCHEMA_VERSION
from app.services.jobs import config_snapshot
from app.workers import worker

NVIDIA_KEY = "test-nvidia-credential-only"
GEMINI_KEY = "test-gemini-credential-only"


@pytest.fixture(autouse=True)
def isolated_credentials(monkeypatch):
    monkeypatch.setattr(config, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setenv("NVIDIA_API_KEY", NVIDIA_KEY)
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)


@pytest.fixture
def cloud_app(app):
    app.config.update(
        NVIDIA_API_KEY=NVIDIA_KEY,
        GEMINI_API_KEY=GEMINI_KEY,
        DEFAULT_PROFILE="nvidia",
        PROMPT_VERSION=IDENTITY_SCHEMA_VERSION,
    )
    for provider, model in (("nvidia", "nim-test-vision"), ("gemini", "gemini-test-vision")):
        app.config["PROFILES"][provider] = {
            "id": provider,
            "provider": provider,
            "model": model,
            "base_url": f"https://{provider}.example.invalid/v1beta",
            "output_mode": "json_schema",
        }
    return app


def test_settings_add_gemini_profiles_without_changing_default_or_embedding_credentials(
    monkeypatch, tmp_path
):
    monkeypatch.delenv("VISION_PROVIDER", raising=False)
    monkeypatch.setenv("GEMINI_MODEL", "gemini-flash-latest")
    monkeypatch.setenv("GEMINI_MODEL_VERSION", "gemini-test-version")
    profiles = tmp_path / "profiles.toml"
    profiles.write_text(
        '[[profiles]]\nid = "gemini-comparison"\nprovider = "gemini"\n'
        'model = "gemini-test-other"\napi_key = "must-not-enter-profile"\n'
    )
    monkeypatch.setenv("PROFILES_FILE", str(profiles))
    configured = config.settings(
        {
            "DATA_DIR": tmp_path / "data",
            "DATASET_DIR": tmp_path / "datasets",
            "SECRET_KEY": "settings-test-secret",
        }
    )
    assert configured["DEFAULT_PROFILE"] == "nvidia"
    assert configured["GEMINI_API_KEY"] == GEMINI_KEY
    assert configured["NVIDIA_API_KEY"] == NVIDIA_KEY
    assert configured["PROFILES"]["gemini"]["model"] == "gemini-flash-latest"
    assert configured["PROFILES"]["gemini"]["model_version"] == "gemini-test-version"
    custom = configured["PROFILES"]["gemini-comparison"]
    assert custom["provider"] == "gemini"
    assert custom["model"] == "gemini-test-other"
    serialized = json.dumps(configured["PROFILES"])
    for secret in (GEMINI_KEY, NVIDIA_KEY, "must-not-enter-profile"):
        assert secret not in serialized
    assert "api_key" not in custom


@pytest.mark.parametrize(
    ("nvidia_key", "gemini_key", "gemini_model", "nim_ready", "gemini_ready"),
    [
        (NVIDIA_KEY, "", "gemini-test-vision", True, False),
        ("", GEMINI_KEY, "gemini-test-vision", False, True),
        (NVIDIA_KEY, GEMINI_KEY, "gemini-test-vision", True, True),
        ("", "", "gemini-test-vision", False, False),
        (NVIDIA_KEY, GEMINI_KEY, "", True, False),
    ],
)
def test_bootstrap_requires_each_cloud_providers_own_key_and_hides_credentials(
    cloud_app, client, nvidia_key, gemini_key, gemini_model, nim_ready, gemini_ready
):
    cloud_app.config.update(NVIDIA_API_KEY=nvidia_key, GEMINI_API_KEY=gemini_key)
    cloud_app.config["PROFILES"]["gemini"]["model"] = gemini_model
    response = client.get("/api/bootstrap")
    assert response.status_code == 200
    data = response.json
    profiles = {profile["id"]: profile for profile in data["profiles"]}
    assert data["default_profile"] == "nvidia"
    assert profiles["nvidia"]["configured"] is nim_ready
    assert profiles["gemini"]["configured"] is gemini_ready
    with cloud_app.app_context():
        snapshots = [config_snapshot(provider) for provider in ("nvidia", "gemini")]
    public_data = response.text + json.dumps(snapshots)
    for secret in (GEMINI_KEY, NVIDIA_KEY):
        assert secret not in public_data
    assert "api_key" not in public_data.lower()


def test_worker_once_drains_both_cloud_providers_serially_with_separate_credentials(
    cloud_app, client, headers
):
    lock = threading.Lock()
    active_calls = 0
    maximum_calls = 0
    calls = []
    content = json.dumps(prediction(outdoor_model="RHF30RVLT", serial_number="E045859"))

    class CloudProvider:
        def __init__(self, profile):
            self.profile = profile

        def recognize(self, **kwargs):
            nonlocal active_calls, maximum_calls
            with lock:
                active_calls += 1
                maximum_calls = max(maximum_calls, active_calls)
            try:
                time.sleep(0.25)  # Overlap would expose independent cloud slots.
                return ProviderResponse(content, {"output": content}, self.profile["model"])
            finally:
                with lock:
                    active_calls -= 1

    def factory(profile, **kwargs):
        calls.append((profile["provider"], kwargs["api_key"]))
        return CloudProvider(profile)

    cloud_app.config["PROVIDER_FACTORY"] = factory
    jobs = [upload_job(client, headers, profile_id=p) for p in ("gemini", "nvidia")]
    worker(cloud_app, once=True)
    assert maximum_calls == 1
    assert active_calls == 0
    assert set(calls) == {("gemini", GEMINI_KEY), ("nvidia", NVIDIA_KEY)}
    assert len(calls) == 2
    for job in jobs:
        result = client.get(f"/api/jobs/{job['id']}").json
        attempt = result["attempts"][-1]
        assert attempt["status"] == "SUCCEEDED"
        assert attempt["normalized_ai_result"]["fields"]["outdoor_model"]["value"] == "RHF30RVLT"
    with cloud_app.app_context():
        assert db.session.scalars(select(Attempt).where(Attempt.status == "QUEUED")).all() == []
        for attempt in db.session.scalars(select(Attempt)).all():
            assert GEMINI_KEY not in json.dumps(attempt.snapshot)
            assert NVIDIA_KEY not in json.dumps(attempt.snapshot)


def test_gemini_http_success_with_truncation_preserves_usage_before_failed_and_manual_confirmation(
    cloud_app, client, headers
):
    # A syntactically valid prefix must still fail when Gemini reports MAX_TOKENS.
    content = json.dumps(prediction(outdoor_model="RHF5ORVLT"))
    raw = {
        "modelVersion": "gemini-test-resolved-version",
        "candidates": [
            {"content": {"parts": [{"text": content}]}, "finishReason": "MAX_TOKENS"}
        ],
        "usageMetadata": {
            "promptTokenCount": 100,
            "candidatesTokenCount": 20,
            "thoughtsTokenCount": 30,
            "totalTokenCount": 150,
        },
    }
    requests = []

    def respond(request):
        requests.append(request)
        assert request.headers["X-goog-api-key"] == GEMINI_KEY
        assert NVIDIA_KEY not in str(request.headers)
        return httpx.Response(200, json=raw)

    def factory(profile, **kwargs):
        return make_provider(profile, **kwargs, transport=httpx.MockTransport(respond))

    cloud_app.config["PROVIDER_FACTORY"] = factory
    job = upload_job(client, headers, profile_id="gemini")
    worker(cloud_app, once=True)
    response = client.get(f"/api/jobs/{job['id']}")
    result = response.json
    attempt = result["attempts"][-1]
    assert len(requests) == 1
    assert attempt["status"] == "FAILED"
    assert attempt["error_code"] == "PROVIDER_OUTPUT_TRUNCATED"
    assert attempt["normalized_ai_result"] is None
    assert attempt["token_usage"] == {
        "input_tokens": 100,
        "output_tokens": 50,
        "total_tokens": 150,
    }
    assert attempt["model_version"] == raw["modelVersion"]
    assert attempt["latency_ms"] >= 0
    assert attempt["processing_ms"] >= attempt["latency_ms"]
    assert "usageMetadata" not in response.text
    assert GEMINI_KEY not in response.text and NVIDIA_KEY not in response.text
    with cloud_app.app_context():
        observation = db.session.scalar(
            select(Observation).where(Observation.attempt_id == attempt["id"])
        )
        assert observation.raw_result == raw
        assert observation.output_text == content
        assert observation.provider == "gemini"
        assert observation.model_version == raw["modelVersion"]
    confirmation = client.post(
        f"/api/jobs/{job['id']}/confirmations",
        headers=headers,
        json=confirmation_payload(result, outdoor_model="RHF30RVLT", serial_number="E045859"),
    )
    assert confirmation.status_code == 201
    assert confirmation.json["share_text"] == "RHF30RVLT\nE045859"
    assert confirmation.json["human_ground_truth"]["fields"]["outdoor_model"]["value"] == "RHF30RVLT"
