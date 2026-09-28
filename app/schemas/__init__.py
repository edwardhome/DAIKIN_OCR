from functools import lru_cache
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, create_model

SCHEMA_VERSION = "nameplate_v001"
IDENTITY_SCHEMA_VERSION = "nameplate_identity_v002"
IDENTITY_FIELDS = ("outdoor_model", "indoor_model", "serial_number")
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


def prompt_field_names(prompt_version):
    return IDENTITY_FIELDS if prompt_version == IDENTITY_SCHEMA_VERSION else tuple(FIELD_SPECS)


def snapshot_field_names(snapshot):
    """Read the scope saved when an attempt was created, never the current setting."""
    names = snapshot.get("field_names")
    if names is None:
        names = (snapshot.get("schema") or {}).get("properties")
    if names is None:
        names = prompt_field_names(snapshot.get("schema_version", SCHEMA_VERSION))
    if not names or not set(names).issubset(FIELD_SPECS):
        raise ValueError("Invalid recognition field scope")
    # Stable, known ordering also handles old schema dictionaries saved with sorted keys.
    return tuple(name for name in FIELD_SPECS if name in names)


def schema_version_for(field_names):
    return IDENTITY_SCHEMA_VERSION if set(field_names) == set(IDENTITY_FIELDS) else SCHEMA_VERSION


@lru_cache(maxsize=8)
def fields_model(field_names):
    if field_names == tuple(FIELD_SPECS):
        return Fields
    return create_model(
        "NameplateIdentityFields",
        __config__=ConfigDict(extra="forbid"),
        **{name: (Field[FIELD_SPECS[name][1]], ...) for name in field_names},
    )


def json_schema(field_names=None):
    return fields_model(
        tuple(FIELD_SPECS if field_names is None else field_names)
    ).model_json_schema()


def field_metadata(field_names=None):
    return [
        {"name": k, "label": label, "type": kind.__name__, "unit": unit, "core": k in CORE_FIELDS}
        for k, (label, kind, unit) in FIELD_SPECS.items()
        if field_names is None or k in field_names
    ]
