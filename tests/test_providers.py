import json

import httpx
import pytest

from app.errors import ProviderError
from app.providers import InferenceImage
from app.providers.nvidia import NvidiaNimVisionProvider
from app.providers.ollama import OllamaVisionProvider
from app.providers.usage import normalize_token_usage
from app.schemas import json_schema


def test_ollama_sends_image_and_schema_and_captures_digest():
    def handler(request):
        if request.url.path == "/api/tags":
            return httpx.Response(
                200, json={"models": [{"name": "vision-example", "digest": "sha-example"}]}
            )
        body = json.loads(request.content)
        assert body["model"] == "vision-example"
        assert body["format"]["type"] == "object"
        assert body["messages"][0]["images"] == ["aW1hZ2U="]
        assert body["stream"] is False
        return httpx.Response(
            200,
            json={
                "model": "vision-example",
                "message": {"content": "{}"},
                "prompt_eval_count": 321,
                "eval_count": 45,
            },
        )

    provider = OllamaVisionProvider(
        {"model": "vision-example", "base_url": "http://ollama"},
        timeout=10,
        max_tokens=100,
        transport=httpx.MockTransport(handler),
    )
    response = provider.recognize(
        image=InferenceImage(b"image"), schema=json_schema(), instruction="extract"
    )
    assert response.model_version == "sha-example"
    assert response.output_text == "{}"
    assert normalize_token_usage("ollama", response.raw_result) == {
        "input_tokens": 321,
        "output_tokens": 45,
        "total_tokens": 366,
    }


@pytest.mark.parametrize("mode", ["prompt", "json_object", "json_schema"])
def test_nvidia_wire_format(mode):
    def handler(request):
        assert request.headers["authorization"] == "Bearer testing-only-key"
        assert request.url.path == "/v1/chat/completions"
        body = json.loads(request.content)
        assert "reasoning_effort" not in body
        assert body["messages"][0]["content"][1]["image_url"]["url"].startswith(
            "data:image/jpeg;base64,"
        )
        assert ("response_format" in body) == (mode != "prompt")
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "{}"}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
            },
        )

    provider = NvidiaNimVisionProvider(
        {"model": "vision-cloud", "base_url": "https://nvidia/v1", "output_mode": mode},
        timeout=10,
        max_tokens=100,
        api_key="testing-only-key",
        transport=httpx.MockTransport(handler),
    )
    response = provider.recognize(image=InferenceImage(b"image"), schema={}, instruction="extract")
    assert response.output_text == "{}"
    assert normalize_token_usage("nvidia", response.raw_result) == {
        "input_tokens": 100,
        "output_tokens": 20,
        "total_tokens": 120,
    }


@pytest.mark.parametrize("effort", ["", "low", "high", "max"])
def test_nvidia_optional_reasoning_effort_is_sent_only_when_configured(effort):
    def handler(request):
        payload = json.loads(request.content)
        if effort:
            assert payload["reasoning_effort"] == effort
        else:
            assert "reasoning_effort" not in payload
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    provider = NvidiaNimVisionProvider(
        {
            "model": "configurable-model",
            "base_url": "https://nvidia/v1",
            "reasoning_effort": effort,
        },
        timeout=1,
        max_tokens=100,
        api_key="testing-only-key",
        transport=httpx.MockTransport(handler),
    )
    result = provider.recognize(image=InferenceImage(b"image"), schema={}, instruction="extract")
    assert result.output_text == "{}"


@pytest.mark.parametrize("effort", [None, True, 1, [], "medium", "LOW"])
def test_nvidia_invalid_reasoning_effort_rejected_before_request(effort):
    def handler(request):
        pytest.fail("Invalid reasoning effort must not make a network request")

    provider = NvidiaNimVisionProvider(
        {
            "model": "configurable-model",
            "base_url": "https://nvidia/v1",
            "reasoning_effort": effort,
        },
        timeout=1,
        max_tokens=100,
        api_key="testing-only-key",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ProviderError) as error:
        provider.recognize(image=InferenceImage(b"image"), schema={}, instruction="extract")
    assert error.value.code == "PROVIDER_CONFIG_INVALID"
    assert error.value.retryable is False


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "PROVIDER_AUTH_FAILED"),
        (402, "PROVIDER_QUOTA_EXHAUSTED"),
        (429, "PROVIDER_RATE_LIMITED"),
        (500, "PROVIDER_API_ERROR"),
        (202, "PROVIDER_ASYNC_UNSUPPORTED"),
    ],
)
def test_provider_errors_are_sanitized(status, code):
    provider = OllamaVisionProvider(
        {"model": "vision", "base_url": "http://ollama"},
        timeout=1,
        max_tokens=1,
        transport=httpx.MockTransport(
            lambda r: httpx.Response(status, text="secret-should-not-leak")
        ),
    )
    with pytest.raises(ProviderError) as err:
        provider.recognize(image=InferenceImage(b"image"), schema={}, instruction="extract")
    assert err.value.code == code
    assert "secret" not in str(err.value)


@pytest.mark.parametrize(
    "body,code",
    [
        ({"error": {"code": "insufficient_quota"}}, "PROVIDER_QUOTA_EXHAUSTED"),
        ({"error": {"type": "insufficient_credits"}}, "PROVIDER_QUOTA_EXHAUSTED"),
        ({"error": {"code": "credits_exhausted"}}, "PROVIDER_QUOTA_EXHAUSTED"),
        ({"error": {"code": "rate_limit_exceeded"}}, "PROVIDER_RATE_LIMITED"),
        ({"error": {"message": "quota exceeded; token rate limit"}}, "PROVIDER_RATE_LIMITED"),
        ({"error": {"code": ["insufficient_quota"]}}, "PROVIDER_RATE_LIMITED"),
        ({"error": "insufficient_quota"}, "PROVIDER_RATE_LIMITED"),
    ],
)
def test_nvidia_distinguishes_quota_from_rate_limits(body, code):
    provider = NvidiaNimVisionProvider(
        {"model": "vision", "base_url": "https://nvidia/v1"},
        timeout=1,
        max_tokens=1,
        api_key="testing-only-key",
        transport=httpx.MockTransport(lambda r: httpx.Response(429, json=body)),
    )
    with pytest.raises(ProviderError) as err:
        provider.recognize(image=InferenceImage(b"image"), schema={}, instruction="extract")
    assert err.value.code == code
    assert err.value.retryable is (code == "PROVIDER_RATE_LIMITED")
    assert "testing-only-key" not in str(err.value)
    assert "insufficient_quota" not in str(err.value)


@pytest.mark.parametrize(
    "exc,code", [(httpx.ReadTimeout, "AI_TIMEOUT"), (httpx.ConnectError, "PROVIDER_UNAVAILABLE")]
)
def test_timeout_and_unavailable(exc, code):
    def handler(request):
        raise exc("private transport detail")

    provider = OllamaVisionProvider(
        {"model": "vision", "base_url": "http://ollama"},
        timeout=1,
        max_tokens=1,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ProviderError) as err:
        provider.recognize(image=InferenceImage(b"image"), schema={}, instruction="extract")
    assert err.value.code == code
