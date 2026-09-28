from dataclasses import dataclass
from typing import Protocol

API_KEY_SETTINGS = {"ollama": None, "nvidia": "NVIDIA_API_KEY", "gemini": "GEMINI_API_KEY"}
SUPPORTED_PROVIDERS = tuple(API_KEY_SETTINGS)


def provider_api_key(config, provider):
    setting = API_KEY_SETTINGS.get(provider)
    return config.get(setting, "") if setting else ""


def provider_is_configured(config, profile):
    provider = profile["provider"]
    return (
        provider in API_KEY_SETTINGS
        and bool(profile.get("model"))
        and (API_KEY_SETTINGS[provider] is None or bool(provider_api_key(config, provider)))
    )


@dataclass(frozen=True)
class InferenceImage:
    data: bytes
    mime_type: str = "image/jpeg"


@dataclass
class ProviderResponse:
    output_text: str
    raw_result: dict
    model: str
    model_version: str | None = None
    refused: bool = False
    inference_ms: float | None = None
    error_code: str | None = None
    error_message: str | None = None


class VisionProvider(Protocol):
    def recognize(
        self, *, image: InferenceImage, schema: dict, instruction: str
    ) -> ProviderResponse: ...


def make_provider(profile, *, timeout, max_tokens, api_key="", transport=None):
    from app.errors import AppError

    from .gemini import GeminiVisionProvider
    from .nvidia import NvidiaNimVisionProvider
    from .ollama import OllamaVisionProvider

    registry = {
        "ollama": OllamaVisionProvider,
        "nvidia": NvidiaNimVisionProvider,
        "gemini": GeminiVisionProvider,
    }
    cls = registry.get(profile["provider"])
    if not cls:
        raise AppError("UNKNOWN_PROVIDER", "尚未註冊此模型供應商。")
    return cls(
        profile, timeout=timeout, max_tokens=max_tokens, api_key=api_key, transport=transport
    )
