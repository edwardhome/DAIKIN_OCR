import base64
import json

from app.errors import ProviderError

from . import ProviderResponse
from .base import HttpProvider


class NvidiaNimVisionProvider(HttpProvider):
    def recognize(self, *, image, schema, instruction):
        if not self.api_key:
            raise ProviderError("PROVIDER_NOT_CONFIGURED", "尚未設定 NVIDIA API Key。", False)
        if len(image.data) > self.profile.get("max_image_bytes", 5000000):
            raise ProviderError(
                "PROVIDER_IMAGE_TOO_LARGE",
                "推論圖片超過此模型設定的限制，請調整前處理尺寸。",
                False,
            )
        payload = {
            "model": self.profile["model"],
            "stream": False,
            "temperature": 0,
            "max_tokens": self.max_tokens,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": instruction + "\nJSON Schema:\n" + json.dumps(schema),
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{image.mime_type};base64,"
                                + base64.b64encode(image.data).decode()
                            },
                        },
                    ],
                }
            ],
        }
        mode = self.profile.get("output_mode", "prompt")
        if mode == "json_schema":
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "nameplate", "strict": True, "schema": schema},
            }
        elif mode == "json_object":
            payload["response_format"] = {"type": "json_object"}
        elif mode != "prompt":
            raise ProviderError("PROVIDER_CONFIG_INVALID", "NVIDIA 輸出模式設定無效。", False)
        result = self.post(
            "/chat/completions", payload, {"Authorization": f"Bearer {self.api_key}"}
        )
        choices = result.get("choices") or []
        message = choices[0].get("message", {}) if choices and isinstance(choices[0], dict) else {}
        content = message.get("content", "")
        if isinstance(content, list):
            content = "".join(
                p.get("text", "")
                for p in content
                if isinstance(p, dict) and p.get("type") == "text"
            )
        return ProviderResponse(
            content if isinstance(content, str) else "",
            result,
            result.get("model") or self.profile["model"],
            self.profile.get("model_version"),
            bool(message.get("refusal")),
            self.inference_ms,
        )
