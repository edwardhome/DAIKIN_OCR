import json

import httpx
import pytest

from app.errors import ProviderError
from app.providers import InferenceImage
from app.providers.nvidia import NvidiaNimVisionProvider
from app.providers.ollama import OllamaVisionProvider
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
        return httpx.Response(200, json={"model": "vision-example", "message": {"content": "{}"}})

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


@pytest.mark.parametrize("mode", ["prompt", "json_object", "json_schema"])
def test_nvidia_wire_format(mode):
    def handler(request):
        assert request.headers["authorization"] == "Bearer testing-only-key"
        assert request.url.path == "/v1/chat/completions"
        body = json.loads(request.content)
        assert body["messages"][0]["content"][1]["image_url"]["url"].startswith(
            "data:image/jpeg;base64,"
        )
        assert ("response_format" in body) == (mode != "prompt")
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    provider = NvidiaNimVisionProvider(
        {"model": "vision-cloud", "base_url": "https://nvidia/v1", "output_mode": mode},
        timeout=10,
        max_tokens=100,
        api_key="testing-only-key",
        transport=httpx.MockTransport(handler),
    )
    assert (
        provider.recognize(
            image=InferenceImage(b"image"), schema={}, instruction="extract"
        ).output_text
        == "{}"
    )


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "PROVIDER_AUTH_FAILED"),
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
