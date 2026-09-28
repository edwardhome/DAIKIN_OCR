import json

import httpx
import pytest
from conftest import confirmation_payload, prediction, upload_job

from app.providers import ProviderResponse
from app.providers.nvidia import NvidiaNimVisionProvider
from app.providers.usage import aggregate_token_usage, normalize_token_usage
from app.workers import worker

UNKNOWN = {"input_tokens": None, "output_tokens": None, "total_tokens": None}


@pytest.mark.parametrize("raw", [None, [], "private response", {}, {"usage": []}])
def test_missing_or_invalid_usage_is_unknown(raw):
    assert normalize_token_usage("nvidia", raw) == UNKNOWN
    assert normalize_token_usage("ollama", raw) == UNKNOWN


@pytest.mark.parametrize("value", [True, False, -1, 1.5, 2.0, "7", [], {}])
def test_only_nonnegative_integer_counts_are_accepted(value):
    assert (
        normalize_token_usage(
            "nvidia",
            {"usage": {"prompt_tokens": value, "completion_tokens": value, "total_tokens": value}},
        )
        == UNKNOWN
    )
    assert (
        normalize_token_usage("ollama", {"prompt_eval_count": value, "eval_count": value})
        == UNKNOWN
    )


def test_zero_is_known_and_complete_components_can_supply_total():
    assert normalize_token_usage(
        "nvidia", {"usage": {"prompt_tokens": 17, "completion_tokens": 0}}
    ) == {"input_tokens": 17, "output_tokens": 0, "total_tokens": 17}
    assert normalize_token_usage("ollama", {"prompt_eval_count": 0, "eval_count": 0}) == {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
    }


def test_incomplete_components_do_not_invent_total_or_missing_component():
    assert normalize_token_usage("nvidia", {"usage": {"prompt_tokens": 17}}) == {
        "input_tokens": 17,
        "output_tokens": None,
        "total_tokens": None,
    }
    assert normalize_token_usage("ollama", {"eval_count": 8}) == {
        "input_tokens": None,
        "output_tokens": 8,
        "total_tokens": None,
    }
    assert normalize_token_usage(
        "nvidia", {"usage": {"prompt_tokens": True, "total_tokens": 29}}
    ) == {"input_tokens": None, "output_tokens": None, "total_tokens": 29}
    assert normalize_token_usage("unregistered", {"usage": {"total_tokens": 29}}) == UNKNOWN


def test_multi_call_aggregation_keeps_partial_totals_unknown():
    complete = {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12}
    partial = {"input_tokens": None, "output_tokens": 3, "total_tokens": None}
    assert aggregate_token_usage([]) == UNKNOWN
    assert aggregate_token_usage([complete, complete]) == {
        "input_tokens": 20,
        "output_tokens": 4,
        "total_tokens": 24,
    }
    assert aggregate_token_usage([complete, partial]) == {
        "input_tokens": None,
        "output_tokens": 5,
        "total_tokens": None,
    }


@pytest.mark.parametrize("provider_name", ["nvidia", "ollama"])
@pytest.mark.parametrize("output_valid", [True, False])
def test_api_reports_usage_for_success_and_parse_failure_without_raw_response(
    app, client, headers, provider_name, output_valid
):
    content = json.dumps(prediction()) if output_valid else "private invalid model output"
    raw = {"private_response": "private response sentinel", "output": content}
    if provider_name == "nvidia":
        raw["usage"] = {"prompt_tokens": 30, "completion_tokens": 20, "total_tokens": 50}
    else:
        raw.update(prompt_eval_count=30, eval_count=20)

    class RecordedProvider:
        def recognize(self, **kwargs):
            return ProviderResponse(content, raw, "test-vision")

    app.config["PROFILES"][provider_name] = {
        "id": provider_name,
        "provider": provider_name,
        "model": "test-vision",
        "base_url": "https://example.invalid",
    }
    app.config["PROVIDER_FACTORY"] = lambda *args, **kwargs: RecordedProvider()
    job = upload_job(client, headers, profile_id=provider_name)
    assert job["attempts"][-1]["token_usage"] == UNKNOWN
    worker(app, once=True)
    response = client.get(f"/api/jobs/{job['id']}")
    attempt = response.json["attempts"][-1]
    assert attempt["status"] == ("SUCCEEDED" if output_valid else "FAILED")
    assert attempt["token_usage"] == {"input_tokens": 30, "output_tokens": 20, "total_tokens": 50}
    assert "private response sentinel" not in response.text
    assert "private invalid model output" not in response.text
    assert "raw_result" not in attempt and "observations" not in attempt
    assert client.get(f"/api/attempts/{attempt['id']}/debug").status_code == 404


def test_nvidia_quota_failure_reaches_api_and_still_allows_human_confirmation(app, client, headers):
    app.config["PROFILES"]["nvidia"] = {
        "id": "nvidia",
        "provider": "nvidia",
        "model": "vision-cloud",
        "base_url": "https://nvidia/v1",
    }
    app.config["PROVIDER_FACTORY"] = lambda profile, **kwargs: NvidiaNimVisionProvider(
        profile,
        timeout=1,
        max_tokens=1,
        api_key="testing-only-key",
        transport=httpx.MockTransport(
            lambda r: httpx.Response(402, text="private billing details testing-only-key")
        ),
    )
    job = upload_job(client, headers, profile_id="nvidia")
    worker(app, once=True)
    response = client.get(f"/api/jobs/{job['id']}")
    result = response.json
    attempt = result["attempts"][-1]
    assert attempt["status"] == "FAILED"
    assert attempt["error_code"] == "PROVIDER_QUOTA_EXHAUSTED"
    assert "額度不足" in attempt["error_message"]
    assert attempt["token_usage"] == UNKNOWN
    assert "private billing" not in response.text
    assert "testing-only-key" not in response.text
    confirmation = client.post(
        f"/api/jobs/{job['id']}/confirmations",
        headers=headers,
        json=confirmation_payload(result, outdoor_model="RHF50RVLT"),
    )
    assert confirmation.status_code == 201
