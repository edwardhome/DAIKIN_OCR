from dataclasses import dataclass
from typing import Protocol


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


class VisionProvider(Protocol):
    def recognize(
        self, *, image: InferenceImage, schema: dict, instruction: str
    ) -> ProviderResponse: ...


def make_provider(profile, *, timeout, max_tokens, api_key="", transport=None):
    from app.errors import AppError

    from .nvidia import NvidiaNimVisionProvider
    from .ollama import OllamaVisionProvider

    registry = {"ollama": OllamaVisionProvider, "nvidia": NvidiaNimVisionProvider}
    cls = registry.get(profile["provider"])
    if not cls:
        raise AppError("UNKNOWN_PROVIDER", "尚未註冊此模型供應商。")
    return cls(
        profile, timeout=timeout, max_tokens=max_tokens, api_key=api_key, transport=transport
    )
