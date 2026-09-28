import base64
import json

import httpx
import pytest

from app.errors import ProviderError
from app.providers import InferenceImage
from app.providers.gemini import GeminiVisionProvider
from app.providers.usage import aggregate_token_usage, normalize_token_usage
from app.schemas import IDENTITY_FIELDS, json_schema


def provider_for(handler, **profile):
    return GeminiVisionProvider(
        {"model": "test-vision-model", "base_url": "https://gemini.example/v1beta", **profile},
        timeout=1,
        max_tokens=4096,
        api_key="test-only-key",
        transport=httpx.MockTransport(handler),
    )


def recognize(provider, schema=None):
    return provider.recognize(
        image=InferenceImage(b"image"), schema=schema or {}, instruction="Extract the nameplate."
    )


def envelope(text="{}", finish="STOP", **extras):
    return {
        "candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": finish}],
        **extras,
    }


@pytest.mark.parametrize("fields", [None, IDENTITY_FIELDS])
@pytest.mark.parametrize("model", ["test-vision-model", "models/test-vision-model"])
def test_gemini_native_wire_schema_and_resolved_version(fields, model):
    schema = json_schema(fields)
    raw = envelope(modelVersion="test-vision-2026-09-28")

    def handler(request):
        assert request.url.path == "/v1beta/models/test-vision-model:generateContent"
        assert request.url.query == b""
        assert request.headers["x-goog-api-key"] == "test-only-key"
        assert "authorization" not in request.headers
        payload = json.loads(request.content)
        assert payload["contents"] == [
            {
                "role": "user",
                "parts": [
                    {"text": "Extract the nameplate."},
                    {
                        "inlineData": {
                            "mimeType": "image/jpeg",
                            "data": base64.b64encode(b"image").decode(),
                        }
                    },
                ],
            }
        ]
        assert payload["generationConfig"] == {
            "temperature": 0,
            "candidateCount": 1,
            "maxOutputTokens": 4096,
            "responseMimeType": "application/json",
            "responseJsonSchema": schema,
        }
        assert "test-only-key" not in request.content.decode()
        return httpx.Response(200, json=raw)

    response = recognize(provider_for(handler, model=model), schema)
    assert response.output_text == "{}"
    assert response.model == model
    assert response.model_version == "test-vision-2026-09-28"
    assert response.raw_result == raw
    assert response.refused is False
    assert response.error_code is None
    assert response.inference_ms >= 0


def test_gemini_joins_only_final_text_parts_and_keeps_raw_observation():
    raw = envelope()
    raw["candidates"][0]["content"]["parts"] = [
        {"thought": True, "text": "internal model reasoning"},
        {"text": '{"outdoor_model":'},
        {"thought": True, "thoughtSignature": "opaque-value"},
        {"text": "null}", "thought": False},
    ]
    response = recognize(provider_for(lambda _: httpx.Response(200, json=raw)))
    assert response.output_text == '{"outdoor_model":null}'
    assert response.raw_result == raw
    assert response.model_version is None


@pytest.mark.parametrize("reason", ["SAFETY", "OTHER", "BLOCKLIST", "PROHIBITED_CONTENT"])
def test_prompt_refusal_retains_raw_and_usage(reason):
    raw = {"promptFeedback": {"blockReason": reason}, "usageMetadata": {"promptTokenCount": 70}}
    response = recognize(provider_for(lambda _: httpx.Response(200, json=raw)))
    assert response.refused is True
    assert response.output_text == ""
    assert response.raw_result == raw


@pytest.mark.parametrize("reason", ["SAFETY", "RECITATION", "LANGUAGE", "SPII", "BLOCKLIST"])
def test_candidate_refusal_ignores_its_content(reason):
    raw = {"candidates": [{"finishReason": reason}]}
    response = recognize(provider_for(lambda _: httpx.Response(200, json=raw)))
    assert response.refused is True
    assert response.output_text == ""
    assert response.raw_result == raw


@pytest.mark.parametrize("text", ['{"outdoor_model":', "{}", ""])
def test_truncated_output_is_never_treated_as_success(text):
    raw = envelope(text, finish="MAX_TOKENS", usageMetadata={"totalTokenCount": 4200})
    response = recognize(provider_for(lambda _: httpx.Response(200, json=raw)))
    assert response.error_code == "PROVIDER_OUTPUT_TRUNCATED"
    assert response.output_text == text
    assert response.raw_result == raw
    assert response.refused is False


@pytest.mark.parametrize(
    "raw",
    [
        {},
        {"candidates": None},
        {"candidates": {}},
        {"candidates": []},
        {"candidates": [None]},
        {"candidates": [{"finishReason": []}]},
        {"candidates": [{"finishReason": "STOP", "content": []}]},
        {"candidates": [{"finishReason": "STOP", "content": {"parts": {}}}]},
        {"candidates": [{"finishReason": "STOP", "content": {"parts": [None]}}]},
        {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": None}]}}]},
        {
            "candidates": [
                {"finishReason": "STOP", "content": {"parts": [{"text": "{}", "thought": "false"}]}}
            ]
        },
        envelope(" "),
        envelope(finish="UNEXPECTED_TOOL_CALL"),
        envelope(modelVersion={}),
        envelope(promptFeedback=[]),
        envelope(promptFeedback={"blockReason": []}),
    ],
)
def test_malformed_or_empty_envelope_is_a_recordable_failure(raw):
    response = recognize(provider_for(lambda _: httpx.Response(200, json=raw)))
    assert response.error_code == "PROVIDER_INVALID_RESPONSE"
    assert response.raw_result == raw
    assert response.refused is False


@pytest.mark.parametrize(
    "model", ["", "../other", "models/../other", "foo/bar", "a?key=x", "a#b", 1]
)
def test_model_path_is_validated_before_http(model):
    provider = provider_for(lambda _: pytest.fail("Must not send invalid model"), model=model)
    with pytest.raises(ProviderError) as error:
        recognize(provider)
    assert error.value.code in {"PROVIDER_CONFIG_INVALID", "MODEL_NOT_CONFIGURED"}


def test_key_image_and_inline_request_limits_are_checked_before_http(monkeypatch):
    provider = provider_for(lambda _: pytest.fail("Must not send invalid request"))
    provider.api_key = ""
    with pytest.raises(ProviderError, match="Gemini API Key"):
        recognize(provider)
    provider.api_key = "test-only-key"
    provider.profile["max_image_bytes"] = 4
    with pytest.raises(ProviderError) as error:
        recognize(provider)
    assert error.value.code == "PROVIDER_IMAGE_TOO_LARGE"
    provider.profile["max_image_bytes"] = 100
    monkeypatch.setattr("app.providers.gemini.MAX_REQUEST_BYTES", 30)
    with pytest.raises(ProviderError) as error:
        recognize(provider)
    assert error.value.code == "PROVIDER_REQUEST_TOO_LARGE"


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "PROVIDER_AUTH_FAILED"),
        (403, "PROVIDER_AUTH_FAILED"),
        (429, "PROVIDER_RATE_LIMITED"),
        (503, "PROVIDER_API_ERROR"),
    ],
)
def test_gemini_uses_sanitized_common_http_errors(status, code):
    provider = provider_for(lambda _: httpx.Response(status, text="private detail test-only-key"))
    with pytest.raises(ProviderError) as error:
        recognize(provider)
    assert error.value.code == code
    assert "private detail" not in str(error.value)
    assert "test-only-key" not in str(error.value)


def test_gemini_timeout_uses_common_timeout_error():
    def handler(request):
        raise httpx.ReadTimeout("private detail")

    with pytest.raises(ProviderError) as error:
        recognize(provider_for(handler))
    assert error.value.code == "AI_TIMEOUT"


@pytest.mark.parametrize(
    "usage,expected",
    [
        (
            {
                "promptTokenCount": 100,
                "candidatesTokenCount": 20,
                "thoughtsTokenCount": 50,
                "totalTokenCount": 170,
            },
            (100, 70, 170),
        ),
        (
            {"promptTokenCount": 100, "candidatesTokenCount": 20, "totalTokenCount": 170},
            (100, 70, 170),
        ),
        ({"promptTokenCount": 100, "candidatesTokenCount": 20}, (100, None, None)),
        (
            {"promptTokenCount": 100, "candidatesTokenCount": 20, "thoughtsTokenCount": 0},
            (100, 20, 120),
        ),
        ({"totalTokenCount": 170}, (None, None, 170)),
        ({"promptTokenCount": 100, "totalTokenCount": 170}, (100, 70, 170)),
        ({"promptTokenCount": 100, "totalTokenCount": 70}, (100, None, 70)),
        (
            {"promptTokenCount": 100, "candidatesTokenCount": 20, "totalTokenCount": 110},
            (100, None, 110),
        ),
        (
            {"promptTokenCount": 100, "totalTokenCount": 170, "toolUsePromptTokenCount": 5},
            (100, None, 170),
        ),
        (
            {
                "promptTokenCount": True,
                "candidatesTokenCount": "20",
                "thoughtsTokenCount": -1,
                "totalTokenCount": 170.0,
            },
            (None, None, None),
        ),
        (
            {
                "promptTokenCount": 100,
                "candidatesTokenCount": 20,
                "thoughtsTokenCount": 50,
                "totalTokenCount": 999,
            },
            (100, 70, 999),
        ),
    ],
)
def test_gemini_usage_includes_thoughts_without_inventing_missing_counts(usage, expected):
    assert normalize_token_usage("gemini", {"usageMetadata": usage}) == dict(
        zip(("input_tokens", "output_tokens", "total_tokens"), expected, strict=True)
    )


def test_unknown_gemini_usage_stays_unknown_when_aggregated():
    known = normalize_token_usage(
        "gemini",
        {
            "usageMetadata": {
                "promptTokenCount": 100,
                "totalTokenCount": 170,
            }
        },
    )
    unknown = normalize_token_usage("gemini", {})
    assert aggregate_token_usage([known, unknown]) == {
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
    }
