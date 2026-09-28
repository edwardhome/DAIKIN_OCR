from types import SimpleNamespace

import pytest

from app.services.confirmations import share_text


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        (
            {
                "outdoor_model": {"value": "RHF30RVLT"},
                "serial_number": {"value": "E045859"},
                "indoor_model": {"value": "FTHF30RVLT"},
                "manufacturer": {"value": "DAIKIN"},
                "refrigerant_charge": {"value": 1.0, "unit": "kg"},
            },
            "RHF30RVLT\nE045859",
        ),
        (
            {"outdoor_model": {"value": None}, "serial_number": {"value": "E045859"}},
            "\nE045859",
        ),
        ({"outdoor_model": {"value": "RHF30RVLT"}}, "RHF30RVLT\n"),
        ({}, "\n"),
        (
            {
                "outdoor_model": {"value": " RHF30\r\nRVLT "},
                "serial_number": {"value": "E04\n5859"},
            },
            "RHF30RVLT\nE045859",
        ),
    ],
)
def test_share_text_preserves_two_line_positions_without_extra_content(fields, expected):
    confirmation = SimpleNamespace(human_ground_truth={"fields": fields})
    assert share_text(confirmation) == expected
