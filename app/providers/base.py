import json
import time

import httpx

from app.errors import ProviderError


class HttpProvider:
    def __init__(self, profile, *, timeout, max_tokens, api_key="", transport=None):
        self.profile, self.timeout, self.max_tokens = profile, timeout, max_tokens
        self.api_key, self.transport = api_key, transport

    def post(self, path, payload, headers=None):
        if not self.profile.get("model"):
            raise ProviderError("MODEL_NOT_CONFIGURED", "尚未設定視覺模型名稱。", False)
        try:
            started = time.monotonic()
            with httpx.Client(
                timeout=self.timeout, transport=self.transport, trust_env=False
            ) as client:
                response = client.post(
                    self.profile["base_url"].rstrip("/") + path, json=payload, headers=headers or {}
                )
            self.inference_ms = (time.monotonic() - started) * 1000
            if response.status_code in {401, 403}:
                raise ProviderError(
                    "PROVIDER_AUTH_FAILED", "模型服務驗證失敗，請檢查伺服器設定。", False
                )
            if response.status_code == 429:
                raise ProviderError("PROVIDER_RATE_LIMITED", "模型服務忙碌，請稍後重新辨識。")
            if response.status_code == 202:
                raise ProviderError(
                    "PROVIDER_ASYNC_UNSUPPORTED",
                    "此端點回傳非同步工作；請設定同步 Chat Completions 端點。",
                    False,
                )
            if response.status_code != 200:
                raise ProviderError(
                    "PROVIDER_API_ERROR", f"模型服務回傳 HTTP {response.status_code}。"
                )
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError("Invalid response envelope")
            return result
        except httpx.TimeoutException:
            raise ProviderError("AI_TIMEOUT", "模型辨識逾時，請重新辨識。")
        except httpx.ConnectError:
            raise ProviderError("PROVIDER_UNAVAILABLE", "無法連線至模型服務，請檢查服務是否啟動。")
        except httpx.HTTPError:
            raise ProviderError("NETWORK_FAILURE", "模型服務連線中斷，請稍後重試。")
        except (ValueError, json.JSONDecodeError):
            raise ProviderError("PROVIDER_INVALID_RESPONSE", "模型服務的回覆格式無效。")
