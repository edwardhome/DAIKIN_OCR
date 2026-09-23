from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, create_model

SCHEMA_VERSION = "nameplate_v001"
CONFIDENCES = ("HIGH", "MEDIUM", "LOW", "UNKNOWN")
CORRECTION_TYPES = (
    "OCR_ERROR",
    "VLM_EXTRACTION_ERROR",
    "FIELD_MAPPING_ERROR",
    "UNIT_ERROR",
    "FORMAT_ERROR",
    "HALLUCINATION",
    "MISSING_VALUE",
    "WRONG_CANDIDATE",
    "IMAGE_UNREADABLE",
    "UNKNOWN",
)
ANNOTATION_STATUSES = ("KNOWN", "NOT_PRESENT", "UNREADABLE", "UNREVIEWED")
CORE_FIELDS = (
    "outdoor_model",
    "indoor_model",
    "serial_number",
    "refrigerant",
    "refrigerant_charge",
    "manufacture_year",
)
FIELD_SPECS = {
    "manufacturer": ("製造商", str, None),
    "outdoor_model": ("室外機型號", str, None),
    "indoor_model": ("室內機型號", str, None),
    "serial_number": ("序號", str, None),
    "refrigerant": ("冷媒", str, None),
    "refrigerant_charge": ("冷媒量", float, "kg"),
    "power_voltage": ("電壓", float, "V"),
    "power_frequency": ("頻率", float, "Hz"),
    "phase": ("相數", int, None),
    "cooling_capacity": ("冷氣能力", float, "kW"),
    "heating_capacity": ("暖氣能力", float, "kW"),
    "cooling_power_consumption": ("冷氣消耗功率", float, "kW"),
    "heating_power_consumption": ("暖氣消耗功率", float, "kW"),
    "cooling_current": ("冷氣電流", float, "A"),
    "heating_current": ("暖氣電流", float, "A"),
    "max_current": ("最大電流", float, "A"),
    "net_weight": ("淨重", float, "kg"),
    "manufacture_year": ("製造年份", int, None),
    "manufacture_month": ("製造月份", int, None),
}
T = TypeVar("T")


class Field(BaseModel, Generic[T]):
    model_config = ConfigDict(extra="forbid", strict=True)
    value: T | None
    confidence: Literal["HIGH", "MEDIUM", "LOW", "UNKNOWN"]
    raw_text: str | None
    unit: str | None


Fields = create_model(
    "NameplateFields",
    __config__=ConfigDict(extra="forbid"),
    **{name: (Field[spec[1]], ...) for name, spec in FIELD_SPECS.items()},
)


def json_schema():
    return Fields.model_json_schema()


def field_metadata():
    return [
        {"name": k, "label": label, "type": kind.__name__, "unit": unit, "core": k in CORE_FIELDS}
        for k, (label, kind, unit) in FIELD_SPECS.items()
    ]
