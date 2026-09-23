import io
import json

import pytest
from PIL import Image

from app import create_app
from app.models import db
from app.providers import ProviderResponse
from app.schemas import FIELD_SPECS


def prediction(**overrides):
    result = {
        n: {"value": None, "confidence": "UNKNOWN", "raw_text": None, "unit": None}
        for n in FIELD_SPECS
    }
    defaults = {
        "manufacturer": "DAIKIN",
        "outdoor_model": "RHF5ORVLT",
        "indoor_model": "FTHF50RVLT",
        "serial_number": "E015283",
        "refrigerant": "R32",
        "refrigerant_charge": 1.0,
        "power_voltage": 220,
        "power_frequency": 60,
        "manufacture_year": 2018,
    }
    defaults.update(overrides)
    for name, value in defaults.items():
        result[name] = {
            "value": value,
            "confidence": "HIGH" if value is not None else "UNKNOWN",
            "raw_text": f"{name}: {value}" if value is not None else None,
            "unit": FIELD_SPECS[name][2] if value is not None else None,
        }
    return result


@pytest.fixture
def app(tmp_path):
    output = prediction()

    class FakeProvider:
        def recognize(self, **kwargs):
            content = application.config.get("FAKE_OUTPUT", json.dumps(output))
            application.config["FAKE_CALLS"] = application.config.get("FAKE_CALLS", 0) + 1
            return ProviderResponse(
                content, {"message": {"content": content}}, "test-vision", "digest-test"
            )

    application = create_app(
        {
            "TESTING": True,
            "DATA_DIR": tmp_path / "data",
            "DATASET_DIR": tmp_path / "datasets",
            "SECRET_KEY": "test-secret",
            "ACCESS_PASSWORD": "",
            "TRUSTED_HOSTS": ["localhost"],
            "PROVIDER_FACTORY": lambda *a, **kw: FakeProvider(),
            "DEBUG_DATA": False,
            "PROFILES": {
                "ollama": {
                    "id": "ollama",
                    "provider": "ollama",
                    "model": "test-vision",
                    "base_url": "http://127.0.0.1:11434",
                    "output_mode": "json_schema",
                },
                "alternative": {
                    "id": "alternative",
                    "provider": "ollama",
                    "model": "other-vision",
                    "base_url": "http://127.0.0.1:11434",
                    "output_mode": "json_schema",
                },
            },
            "REGRESSION_MIN_KNOWN_SAMPLES": 1,
        }
    )
    yield application
    with application.app_context():
        db.session.remove()
        db.engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def headers(client):
    return {"X-CSRF-Token": client.get("/api/bootstrap").json["csrf_token"]}


def image_bytes():
    out = io.BytesIO()
    Image.new("RGB", (640, 420), (225, 229, 222)).save(out, "JPEG")
    return out.getvalue()


def upload_job(client, headers, **metadata):
    data = {"image": (io.BytesIO(image_bytes()), "plate.jpg"), **metadata}
    response = client.post("/api/jobs", data=data, headers=headers)
    assert response.status_code == 202, response.json
    return response.json


def confirmation_payload(job, **values):
    attempt = job["attempts"][-1]
    fields = {}
    for name, spec in FIELD_SPECS.items():
        field = (attempt.get("normalized_ai_result") or {"fields": {}})["fields"].get(name, {})
        value = values.get(name, field.get("value"))
        fields[name] = {
            "value": value,
            "unit": spec[2] if value is not None else None,
            "annotation_status": "KNOWN" if value is not None else "NOT_PRESENT",
            "correction_type": "UNKNOWN",
        }
    return {
        "attempt_id": attempt["id"],
        "expected_revision": job["revision"],
        "fields": fields,
        "review_active_ms": 5000,
    }
