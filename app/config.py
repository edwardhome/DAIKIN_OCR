import os
import secrets
import tomllib
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


def settings(overrides=None):
    load_dotenv(ROOT / ".env")
    env = os.environ
    host = env.get("APP_HOST", "127.0.0.1")
    result = {
        "DATA_DIR": ROOT / env.get("DATA_DIR", "data"),
        "DATASET_DIR": ROOT / env.get("DATASET_DIR", "datasets"),
        "SECRET_KEY": env.get("SECRET_KEY") or None,
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "MAX_UPLOAD_BYTES": int(env.get("MAX_UPLOAD_MB", "20")) * 1024 * 1024,
        "MAX_IMAGE_PIXELS": int(env.get("MAX_IMAGE_PIXELS", "60000000")),
        "MAX_FORM_MEMORY_SIZE": 524288,
        "MAX_FORM_PARTS": 20,
        "APP_HOST": host,
        "APP_PORT": int(env.get("APP_PORT", "50003")),
        "ACCESS_PASSWORD": env.get("ACCESS_PASSWORD", ""),
        "TRUSTED_HOSTS": env.get("TRUSTED_HOSTS", f"localhost,127.0.0.1,{host}").split(","),
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_NAME": "nameplate_session",
        "SESSION_COOKIE_SAMESITE": "Lax",
        "SESSION_COOKIE_SECURE": False,
        "DEBUG_DATA": env.get("DEBUG_DATA", "false").lower() == "true",
        "DEFAULT_PROFILE": env.get("VISION_PROVIDER", "ollama"),
        "PROMPT_VERSION": env.get("PROMPT_VERSION", "nameplate_v001"),
        "PREPROCESSOR": {
            "version": "image_v001",
            "max_edge": int(env.get("IMAGE_MAX_EDGE", "2560")),
            "contrast": float(env.get("IMAGE_CONTRAST", "1")),
            "sharpness": float(env.get("IMAGE_SHARPNESS", "1")),
        },
        "PROVIDER_TIMEOUT": float(env.get("PROVIDER_TIMEOUT_SECONDS", "180")),
        "MAX_TOKENS": int(env.get("MODEL_MAX_TOKENS", "4096")),
        "NVIDIA_API_KEY": env.get("NVIDIA_API_KEY", ""),
        "HIGH_CONFIDENCE_THRESHOLD": float(env.get("HIGH_CONFIDENCE_THRESHOLD", ".95")),
        "LOW_CONFIDENCE_THRESHOLD": float(env.get("LOW_CONFIDENCE_THRESHOLD", ".80")),
        "REGRESSION_MAX_DROP": float(env.get("REGRESSION_MAX_DROP", "0")),
        "REGRESSION_MIN_KNOWN_SAMPLES": int(env.get("REGRESSION_MIN_KNOWN_SAMPLES", "5")),
        "LEASE_SECONDS": 30,
    }
    profiles = {
        "ollama": {
            "id": "ollama",
            "provider": "ollama",
            "model": env.get("OLLAMA_MODEL", ""),
            "model_version": env.get("OLLAMA_MODEL_VERSION") or None,
            "base_url": env.get("OLLAMA_HOST", "http://127.0.0.1:11434"),
            "output_mode": "json_schema",
            "num_ctx": int(env.get("MODEL_CONTEXT_LENGTH", "8192")),
        },
        "nvidia": {
            "id": "nvidia",
            "provider": "nvidia",
            "model": env.get("NVIDIA_MODEL", ""),
            "model_version": env.get("NVIDIA_MODEL_VERSION") or None,
            "base_url": env.get("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"),
            "output_mode": env.get("NVIDIA_OUTPUT_MODE", "prompt"),
            "max_image_bytes": int(env.get("NVIDIA_MAX_IMAGE_BYTES", "5000000")),
        },
    }
    path = ROOT / env.get("PROFILES_FILE", "config/profiles.toml")
    if path.exists():
        for item in tomllib.loads(path.read_text()).get("profiles", []):
            if item.get("provider") not in {"ollama", "nvidia"} or not item.get("id"):
                raise ValueError("Invalid provider profile")
            base = dict(profiles[item["provider"]])
            base.update(
                {
                    k: v
                    for k, v in item.items()
                    if k in {"id", "provider", "model", "model_version", "output_mode"}
                }
            )
            profiles[item["id"]] = base
    result["PROFILES"] = profiles
    result.update(overrides or {})
    for key in ("DATA_DIR", "DATASET_DIR"):
        result[key] = Path(result[key]).resolve()
        result[key].mkdir(parents=True, exist_ok=True)
    result.setdefault(
        "SQLALCHEMY_DATABASE_URI", f"sqlite:///{result['DATA_DIR'] / 'database.sqlite3'}"
    )
    result["MAX_CONTENT_LENGTH"] = result["MAX_UPLOAD_BYTES"] + 1048576
    if not result["SECRET_KEY"]:
        keyfile = result["DATA_DIR"] / ".session-secret"
        if not keyfile.exists():
            try:
                fd = os.open(keyfile, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(fd, "w") as stream:
                    stream.write(secrets.token_hex(32))
            except FileExistsError:
                pass
        result["SECRET_KEY"] = keyfile.read_text().strip()
    if not 0 <= result["LOW_CONFIDENCE_THRESHOLD"] < result["HIGH_CONFIDENCE_THRESHOLD"] <= 1:
        raise ValueError("Invalid future confidence thresholds")
    return result
