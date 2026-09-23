import pytest
from conftest import prediction

from app.errors import AppError
from app.schemas import FIELD_SPECS
from app.services.normalize import normalize, parse_output
from app.validators import validate


def test_schema_missing_wrong_type_null_and_confidence():
    result, warnings = normalize(
        {
            "outdoor_model": {"value": "rhf 50\nrvlt", "confidence": 0.97},
            "serial_number": {"value": ["invalid"]},
            "manufacturer": None,
        }
    )
    assert len(result["fields"]) == 19
    assert result["fields"]["outdoor_model"]["value"] == "RHF50RVLT"
    assert result["fields"]["outdoor_model"]["confidence"] == "UNKNOWN"
    assert result["fields"]["serial_number"]["value"] is None
    assert result["fields"]["manufacturer"]["value"] is None
    assert {w["code"] for w in warnings} >= {"MISSING_FIELD", "WRONG_TYPE"}


def test_normalization_never_replaces_serial_characters():
    payload = prediction(serial_number="  0O1I5S8B  ")
    payload["power_voltage"] = {"value": "220 V"}
    payload["refrigerant_charge"] = {"value": "1000 g"}
    payload["cooling_capacity"] = {"value": "5000 W"}
    result, _ = normalize(payload)
    assert result["fields"]["serial_number"]["value"] == "0O1I5S8B"
    assert result["fields"]["power_voltage"]["value"] == 220
    assert result["fields"]["refrigerant_charge"]["value"] == 1
    assert result["fields"]["cooling_capacity"]["value"] == 5


@pytest.mark.parametrize(
    "value,unit",
    [("220/380 V", None), (220, None), (True, "V"), ("220V", "Hz"), (float("inf"), "V")],
)
def test_ambiguous_measurements_become_null(value, unit):
    result, warnings = normalize({"power_voltage": {"value": value, "unit": unit}})
    assert result["fields"]["power_voltage"]["value"] is None
    assert warnings


def test_rules_warn_without_mutating():
    result, _ = normalize(prediction(power_voltage=4000, power_frequency=55, refrigerant="R999"))
    codes = {w["code"] for w in validate(result)}
    assert {
        "VOLTAGE_RANGE",
        "FREQUENCY_RANGE",
        "UNKNOWN_REFRIGERANT",
        "AMBIGUOUS_SERIAL_CHARACTER",
    } <= codes
    assert result["fields"]["power_voltage"]["value"] == 4000


def test_one_syntax_repair_preserves_quoted_content():
    payload, repair = parse_output('```json\n{"outdoor_model":{"value":"a,}",},}\n```')
    assert payload["outdoor_model"]["value"] == "a,}"
    assert repair["attempted"] and repair["succeeded"]


@pytest.mark.parametrize("text", ['{"outdoor_model": "RHF', "這是一台冷氣", "[]", '{"value": NaN}'])
def test_unrecoverable_json_fails(text):
    with pytest.raises(AppError) as err:
        parse_output(text)
    assert err.value.code == "AI_PARSE_FAILED"


def test_all_null_is_a_valid_prediction():
    data = {n: {"value": None} for n in FIELD_SPECS}
    result, _ = normalize(data)
    assert all(f["value"] is None for f in result["fields"].values())
