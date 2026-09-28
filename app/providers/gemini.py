"""Google AI Studio's native Gemini generateContent API."""

import base64
import json
import re

from app.errors import ProviderError

from . import ProviderResponse
from .base import HttpProvider

# A local guard for inline requests, independent of changes to Google's quotas.
MAX_REQUEST_BYTES = 20_000_000
REFUSAL_REASONS = {
    "SAFETY",
    "RECITATION",
    "LANGUAGE",
    "BLOCKLIST",
    "PROHIBITED_CONTENT",
    "SPII",
    "IMAGE_SAFETY",
    "IMAGE_PROHIBITED_CONTENT",
    "IMAGE_RECITATION",
    "ESCALATION",
    "PUP_LIMITED_DISABLED",
}


class GeminiVisionProvider(HttpProvider):
    def recognize(self, *, image, schema, instruction):
        model = self.profile.get("model")
        if not model:
            raise ProviderError("MODEL_NOT_CONFIGURED", "尚未設定視覺模型名稱。", False)
        model_id = model.removeprefix("models/") if isinstance(model, str) else ""
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", model_id):
            raise ProviderError("PROVIDER_CONFIG_INVALID", "Gemini 模型名稱設定無效。", False)
        if not self.api_key:
            raise ProviderError("PROVIDER_NOT_CONFIGURED", "尚未設定 Gemini API Key。", False)
        image_limit = self.profile.get("max_image_bytes", 5_000_000)
        if type(image_limit) is not int or image_limit <= 0:
            raise ProviderError("PROVIDER_CONFIG_INVALID", "Gemini 圖片大小設定無效。", False)
        if len(image.data) > image_limit:
            raise ProviderError(
                "PROVIDER_IMAGE_TOO_LARGE",
                "推論圖片超過此模型設定的限制，請調整前處理尺寸。",
                False,
            )
        if not image.data or image.mime_type not in {
            "image/jpeg",
            "image/png",
            "image/webp",
            "image/heic",
            "image/heif",
        }:
            raise ProviderError("PROVIDER_IMAGE_INVALID", "Gemini 推論圖片格式無效。", False)
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": instruction},
                        {
                            "inlineData": {
                                "mimeType": image.mime_type,
                                "data": base64.b64encode(image.data).decode("ascii"),
                            }
                        },
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0,
                "candidateCount": 1,
                "maxOutputTokens": self.max_tokens,
                "responseMimeType": "application/json",
                "responseJsonSchema": schema,
            },
        }
        if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > MAX_REQUEST_BYTES:
            raise ProviderError(
                "PROVIDER_REQUEST_TOO_LARGE",
                "Gemini 推論請求超過本系統的大小限制，請調整前處理尺寸。",
                False,
            )
        result = self.post(
            f"/models/{model_id}:generateContent", payload, {"X-goog-api-key": self.api_key}
        )
        version = result.get("modelVersion")
        response = ProviderResponse(
            output_text="",
            raw_result=result,
            model=model,
            model_version=version if isinstance(version, str) and version else None,
            inference_ms=self.inference_ms,
        )

        def invalid():
            response.error_code = "PROVIDER_INVALID_RESPONSE"
            response.error_message = "Gemini 未回傳完整可用的辨識內容。"
            return response

        if version is not None and not isinstance(version, str):
            return invalid()
        feedback = result.get("promptFeedback", {})
        if not isinstance(feedback, dict):
            return invalid()
        block_reason = feedback.get("blockReason")
        if block_reason is not None and not isinstance(block_reason, str):
            return invalid()
        if block_reason and block_reason != "BLOCK_REASON_UNSPECIFIED":
            response.refused = True
            return response
        candidates = result.get("candidates")
        if not isinstance(candidates, list) or len(candidates) != 1:
            return invalid()
        candidate = candidates[0]
        if not isinstance(candidate, dict):
            return invalid()
        finish_reason = candidate.get("finishReason")
        if not isinstance(finish_reason, str):
            return invalid()
        if finish_reason in REFUSAL_REASONS:
            response.refused = True
            return response
        content = candidate.get("content", {})
        if not isinstance(content, dict):
            return invalid()
        parts = content.get("parts", [])
        if not isinstance(parts, list):
            return invalid()
        texts = []
        for part in parts:
            if not isinstance(part, dict):
                return invalid()
            thought = part.get("thought", False)
            if type(thought) is not bool:
                return invalid()
            if thought:
                continue
            text = part.get("text")
            if not isinstance(text, str):
                return invalid()
            texts.append(text)
        response.output_text = "".join(texts)
        if finish_reason == "MAX_TOKENS":
            # Never normalize a truncated candidate, even if its prefix parses as JSON.
            response.error_code = "PROVIDER_OUTPUT_TRUNCATED"
            response.error_message = "Gemini 回覆達到輸出上限，請調整模型輸出設定後重新辨識。"
            return response
        if finish_reason != "STOP" or not response.output_text.strip():
            return invalid()
        return response
