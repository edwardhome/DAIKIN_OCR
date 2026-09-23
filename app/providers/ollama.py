import base64
import json

import httpx

from . import ProviderResponse
from .base import HttpProvider


class OllamaVisionProvider(HttpProvider):
    def recognize(self, *, image, schema, instruction):
        result = self.post(
            "/api/chat",
            {
                "model": self.profile["model"],
                "stream": False,
                "format": schema,
                "messages": [
                    {
                        "role": "user",
                        "content": instruction + "\nJSON Schema:\n" + json.dumps(schema),
                        "images": [base64.b64encode(image.data).decode()],
                    }
                ],
                "options": {
                    "temperature": 0,
                    "num_predict": self.max_tokens,
                    "num_ctx": self.profile.get("num_ctx", 8192),
                },
            },
        )
        version = self.profile.get("model_version")
        if not version:
            try:
                with httpx.Client(
                    timeout=min(self.timeout, 5), transport=self.transport, trust_env=False
                ) as client:
                    tags = client.get(self.profile["base_url"].rstrip("/") + "/api/tags").json()
                version = next(
                    (
                        m.get("digest")
                        for m in tags.get("models", [])
                        if m.get("name") == self.profile["model"]
                    ),
                    None,
                )
            except Exception:
                version = None
        message = result.get("message", {})
        content = message.get("content", "") if isinstance(message, dict) else ""
        return ProviderResponse(
            content if isinstance(content, str) else "",
            result,
            result.get("model") or self.profile["model"],
            version,
            bool(message.get("refusal")) if isinstance(message, dict) else False,
            self.inference_ms,
        )
