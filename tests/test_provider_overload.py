import httpx
import pytest
from conftest import confirmation_payload, upload_job

from app.errors import ProviderError
from app.providers import InferenceImage, make_provider
from app.providers.gemini import GeminiVisionProvider
from app.schemas import IDENTITY_SCHEMA_VERSION
from app.workers import worker

OVERLOAD_MESSAGE = (
    "This model is currently experiencing high demand. "
    "Spikes in demand are usually temporary. Please try again later."
)
SAFE_MESSAGE = "模型需求量過高，請更換模型後重新辨識。"
PRIVATE_DETAIL = "private-provider-detail-must-not-leak"


def provider_for(response):
    return GeminiVisionProvider(
        {"model": "test-vision", "base_url": "https://gemini.example.invalid/v1beta"},
        timeout=1,
        max_tokens=100,
        api_key="test-only-key",
        transport=httpx.MockTransport(lambda _: response),
    )


@pytest.mark.parametrize(
    "message",
    [
        OVERLOAD_MESSAGE,
        "The model is overloaded. Try again later.",
        "Model is currently at capacity.",
        "Model capacity exhausted.",
        "The model is experiencing HIGH\n DEMAND.",
    ],
)
def test_explicit_http_503_overload_has_sanitized_retryable_error(message):
    provider = provider_for(
        httpx.Response(
            503,
            json={
                "error": {
                    "code": 503,
                    "status": "UNAVAILABLE",
                    "message": f"{message} {PRIVATE_DETAIL}",
                }
            },
        )
    )
    with pytest.raises(ProviderError) as caught:
        provider.recognize(image=InferenceImage(b"image"), schema={}, instruction="extract")
    assert caught.value.code == "PROVIDER_OVERLOADED"
    assert caught.value.message == SAFE_MESSAGE
    assert caught.value.retryable is True
    assert PRIVATE_DETAIL not in str(caught.value)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(503, json={"error": {"status": "UNAVAILABLE"}}),
        httpx.Response(503, json={"error": {"message": "Service unavailable for maintenance."}}),
        httpx.Response(503, json={"error": {"message": "Invalid capacity configuration."}}),
        httpx.Response(503, json={"error": {"message": ["high demand"]}}),
        httpx.Response(503, json={"error": "high demand"}),
        httpx.Response(503, json=[{"message": "high demand"}]),
        httpx.Response(503, json=None),
        httpx.Response(503, text="<html>high demand</html>"),
        httpx.Response(503, text='{"error":{"message":"high demand"'),
    ],
)
def test_ordinary_or_unstructured_503_keeps_generic_service_error(response):
    with pytest.raises(ProviderError) as caught:
        provider_for(response).recognize(
            image=InferenceImage(b"image"), schema={}, instruction="extract"
        )
    assert caught.value.code == "PROVIDER_API_ERROR"
    assert caught.value.message == "模型服務回傳 HTTP 503。"


@pytest.mark.parametrize(
    ("status", "error", "expected"),
    [
        (429, {"message": OVERLOAD_MESSAGE}, "PROVIDER_RATE_LIMITED"),
        (
            429,
            {"code": "insufficient_quota", "message": OVERLOAD_MESSAGE},
            "PROVIDER_QUOTA_EXHAUSTED",
        ),
        (500, {"message": OVERLOAD_MESSAGE}, "PROVIDER_API_ERROR"),
    ],
)
def test_overload_classification_does_not_change_other_statuses(status, error, expected):
    with pytest.raises(ProviderError) as caught:
        provider_for(httpx.Response(status, json={"error": error})).recognize(
            image=InferenceImage(b"image"), schema={}, instruction="extract"
        )
    assert caught.value.code == expected


def test_overload_reaches_job_api_without_retry_or_usage_and_allows_manual_confirmation(
    app, client, headers, caplog
):
    caplog.set_level("INFO")
    key = "overload-test-gemini-key"
    app.config.update(
        DEFAULT_PROFILE="gemini",
        PROMPT_VERSION=IDENTITY_SCHEMA_VERSION,
        GEMINI_API_KEY=key,
        PROFILES={
            "gemini": {
                "id": "gemini",
                "provider": "gemini",
                "model": "test-vision",
                "base_url": "https://gemini.example.invalid/v1beta",
                "output_mode": "json_schema",
            }
        },
    )
    calls = []

    def respond(request):
        calls.append(request)
        assert request.headers["X-goog-api-key"] == key
        return httpx.Response(
            503,
            json={
                "error": {
                    "code": 503,
                    "status": "UNAVAILABLE",
                    "message": f"{OVERLOAD_MESSAGE} {PRIVATE_DETAIL} {key}",
                }
            },
        )

    app.config["PROVIDER_FACTORY"] = lambda profile, **kwargs: make_provider(
        profile, **kwargs, transport=httpx.MockTransport(respond)
    )
    job = upload_job(client, headers)
    worker(app, once=True)
    worker(app, once=True)  # FAILED jobs are not automatically retried.
    response = client.get(f"/api/jobs/{job['id']}")
    assert response.status_code == 200
    result = response.json
    attempt = result["attempts"][-1]
    assert len(calls) == 1
    assert attempt["status"] == "FAILED"
    assert attempt["error_code"] == "PROVIDER_OVERLOADED"
    assert attempt["error_message"] == SAFE_MESSAGE
    assert attempt["normalized_ai_result"] is None
    assert attempt["token_usage"] == {
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
    }
    assert attempt["latency_ms"] >= 0
    assert attempt["processing_ms"] >= attempt["latency_ms"]
    assert key not in response.text + caplog.text
    assert PRIVATE_DETAIL not in response.text + caplog.text
    confirmation = client.post(
        f"/api/jobs/{job['id']}/confirmations",
        headers=headers,
        json=confirmation_payload(result, outdoor_model="RHF30RVLT", serial_number="E045859"),
    )
    assert confirmation.status_code == 201
    assert confirmation.json["share_text"] == "RHF30RVLT\nE045859"
