"""Opt-in live Ollama check using a synthetic card, isolated from all production data."""

import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import select

from app import create_app
from app.config import ROOT
from app.models import Observation, db, uid
from app.workers import worker


def main():
    output = ROOT / "data" / "verification" / uid()
    output.mkdir(parents=True)
    image = Image.new("RGB", (1200, 920), "#f9faf8")
    draw = ImageDraw.Draw(image)
    font_path = Path("/System/Library/Fonts/Supplemental/Arial.ttf")
    font = (
        ImageFont.truetype(str(font_path), 36)
        if font_path.exists()
        else ImageFont.load_default(size=36)
    )
    lines = [
        "SYNTHETIC SOFTWARE TEST CARD - NOT FIELD DATA",
        "MANUFACTURER: DAIKIN",
        "OUTDOOR MODEL: RHF50RVLT",
        "INDOOR MODEL: FTHF50RVLT",
        "SERIAL NUMBER: E015283",
        "REFRIGERANT: R32",
        "REFRIGERANT CHARGE: 1.00 kg",
        "POWER: 220 V / 60 Hz / 1 phase",
        "COOLING CAPACITY: 5.0 kW",
        "HEATING CAPACITY: 5.6 kW",
        "MANUFACTURE YEAR: 2018",
    ]
    for i, line in enumerate(lines):
        draw.text((35, 30 + i * 76), line, fill="#111111", font=font)
    image.save(output / "synthetic-nameplate.jpg", quality=96)
    with TemporaryDirectory(prefix="nameplate-live-check-") as temp:
        app = create_app(
            {
                "TESTING": True,
                "DATA_DIR": Path(temp) / "data",
                "DATASET_DIR": Path(temp) / "datasets",
                "SECRET_KEY": "isolated-live-check",
                "ACCESS_PASSWORD": "",
                "TRUSTED_HOSTS": ["localhost"],
            }
        )
        client = app.test_client()
        headers = {"X-CSRF-Token": client.get("/api/bootstrap").json["csrf_token"]}
        uploaded = client.post(
            "/api/jobs",
            headers=headers,
            data={
                "scope": "BENCHMARK_SOURCE",
                "profile_id": "ollama",
                "image": (
                    io.BytesIO((output / "synthetic-nameplate.jpg").read_bytes()),
                    "synthetic.jpg",
                ),
            },
        )
        if uploaded.status_code != 202:
            raise RuntimeError(uploaded.json)
        worker(app, once=True)
        result = client.get(f"/api/jobs/{uploaded.json['id']}").json
        result["verification_scope"] = "SYNTHETIC_CONNECTIVITY_TEST_ONLY"
        result["human_ground_truth"] = None
        (output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
        with app.app_context():
            observation = db.session.scalar(select(Observation))
            if observation:
                (output / "raw-response.json").write_text(
                    json.dumps(observation.raw_result, ensure_ascii=False, indent=2)
                )
        attempt = result["attempts"][-1]
        print(
            json.dumps(
                {
                    "status": attempt["status"],
                    "error_code": attempt["error_code"],
                    "model": attempt["model"],
                    "model_version": attempt["model_version"],
                    "latency_ms": attempt["latency_ms"],
                    "output_directory": str(output),
                    "result": attempt["normalized_ai_result"],
                },
                ensure_ascii=False,
            )
        )
        if attempt["status"] != "SUCCEEDED":
            raise SystemExit(1)


if __name__ == "__main__":
    main()
