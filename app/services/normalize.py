import json
import math
import re

from app.errors import AppError
from app.schemas import CONFIDENCES, FIELD_SPECS, SCHEMA_VERSION, Fields

NORMALIZER_VERSION = "normalize_v001"


def issue(field, code, message):
    return {"field": field, "code": code, "severity": "WARNING", "message": message}


def parse_output(text):
    if not isinstance(text, str) or not text.strip():
        raise AppError("AI_PARSE_FAILED", "模型未回傳可解析的 JSON。", 502, True)

    def parse(value):
        return json.loads(
            value, parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token))
        )

    try:
        payload = parse(text)
        repaired = {"attempted": False, "succeeded": False}
    except (ValueError, TypeError):
        # One bounded syntax-only pass. No completion of truncated strings or invented values.
        fixed = text.strip()
        if fixed.startswith("```") and fixed.endswith("```"):
            fixed = re.sub(r"^```(?:json)?\s*", "", fixed, flags=re.I)[:-3].strip()
        # Remove trailing commas outside quoted strings only.
        parts = re.split(r'("(?:\\.|[^"\\])*")', fixed)
        fixed = "".join(
            p if i % 2 else re.sub(r",\s*([}\]])", r"\1", p) for i, p in enumerate(parts)
        )
        try:
            payload = parse(fixed)
        except (ValueError, TypeError):
            raise AppError("AI_PARSE_FAILED", "JSON 修復一次後仍無法解析，請重新辨識。", 502, True)
        repaired = {"attempted": True, "succeeded": True, "repaired_text": fixed}
    if not isinstance(payload, dict):
        raise AppError("AI_PARSE_FAILED", "模型回覆不是 JSON 物件。", 502, True)
    return payload, repaired


def normalize_value(name, value, supplied_unit=None):
    _, kind, expected_unit = FIELD_SPECS[name]
    warnings = []
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, None, warnings
    if kind is str:
        if not isinstance(value, str):
            return None, None, [issue(name, "WRONG_TYPE", "欄位型別不符，請人工確認。")]
        value = value.strip()
        if name in {"outdoor_model", "indoor_model"}:
            value = re.sub(r"\s+", "", value).upper()
        elif name == "refrigerant":
            value = re.sub(r"[\s-]+", "", value).upper()
        return value, None, warnings
    unit = supplied_unit.strip() if isinstance(supplied_unit, str) else None
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None, None, [issue(name, "WRONG_TYPE", "數值型別不符。")]
    if isinstance(value, str):
        match = re.fullmatch(r"\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*([A-Za-z]+)?\s*", value)
        if not match:
            return None, None, [issue(name, "AMBIGUOUS_NUMBER", "無法確定單一數值，已保留原文。")]
        value = float(match[1])
        if match[2]:
            if unit and unit.lower() != match[2].lower():
                return None, None, [issue(name, "UNIT_CONFLICT", "數字與單位欄互相衝突。")]
            unit = match[2]
    if not math.isfinite(value):
        return None, None, [issue(name, "INVALID_NUMBER", "數值無效。")]
    if kind is int:
        if float(value).is_integer() and not unit:
            return int(value), None, warnings
        return None, None, [issue(name, "WRONG_TYPE", "需要不含單位的整數。")]
    aliases = {
        "v": ("V", 1),
        "hz": ("Hz", 1),
        "a": ("A", 1),
        "kw": ("kW", 1),
        "w": ("kW", 0.001),
        "kg": ("kg", 1),
        "g": ("kg", 0.001),
    }
    if not unit:
        return None, None, [issue(name, "MISSING_UNIT", "未能確認單位，請依原圖填寫。")]
    conversion = aliases.get(unit.lower())
    if not conversion or conversion[0] != expected_unit:
        return None, None, [issue(name, "UNKNOWN_UNIT", "無法安全換算單位。")]
    return round(float(value) * conversion[1], 9), expected_unit, warnings


def normalize(payload):
    source = payload.get("fields", payload)
    if not isinstance(source, dict) or not set(source).intersection(FIELD_SPECS):
        raise AppError("AI_PARSE_FAILED", "回覆未包含銘牌欄位，請重新辨識。", 502, True)
    fields, warnings = {}, []
    for name in FIELD_SPECS:
        raw = source.get(name)
        if name not in source:
            warnings.append(issue(name, "MISSING_FIELD", "模型未回傳此欄位。"))
        if not isinstance(raw, dict):
            raw = {"value": raw}
        raw_value = raw.get("value")
        value, unit, problems = normalize_value(name, raw_value, raw.get("unit"))
        warnings.extend(problems)
        confidence = raw.get("confidence", "UNKNOWN")
        confidence = confidence.upper() if isinstance(confidence, str) else "UNKNOWN"
        if confidence not in CONFIDENCES:
            confidence = "UNKNOWN"
        evidence = raw.get("raw_text")
        if not isinstance(evidence, str):
            evidence = None
        fields[name] = {
            "value": value,
            "unit": unit,
            "confidence": confidence,
            "raw_text": evidence,
        }
    Fields.model_validate(fields)
    return {"schema_version": SCHEMA_VERSION, "fields": fields}, warnings
