import re
from datetime import datetime

from app.services.normalize import issue

VALIDATOR_VERSION = "rules_v001"


def validate(result):
    warnings = []
    fields = result["fields"]
    for name, field in fields.items():
        value = field["value"]
        if value is None:
            continue
        if name == "refrigerant" and value not in {"R22", "R32", "R410A", "R407C"}:
            warnings.append(issue(name, "UNKNOWN_REFRIGERANT", "冷媒不在第一版已知清單，請核對。"))
        if name == "power_voltage" and not 50 <= value <= 1000:
            warnings.append(issue(name, "VOLTAGE_RANGE", "電壓超出常用檢查範圍。"))
        if name == "power_frequency" and value not in {50, 60}:
            warnings.append(issue(name, "FREQUENCY_RANGE", "頻率不是常見的 50／60 Hz。"))
        if name == "phase" and value not in {1, 3}:
            warnings.append(issue(name, "PHASE_RANGE", "相數不是 1 或 3。"))
        if name == "manufacture_year" and not 1900 <= value <= datetime.now().year + 1:
            warnings.append(issue(name, "YEAR_RANGE", "製造年份需人工核對。"))
        if name == "manufacture_month" and not 1 <= value <= 12:
            warnings.append(issue(name, "MONTH_RANGE", "月份應介於 1 至 12。"))
        if isinstance(value, (int, float)) and value <= 0:
            warnings.append(issue(name, "NON_POSITIVE", "數值不是正數，請核對。"))
        if name == "serial_number" and re.search(r"[0O1I5S8B]", value, re.I):
            warnings.append(
                issue(
                    name, "AMBIGUOUS_SERIAL_CHARACTER", "含易混淆字元，請對照原圖；系統未替換字元。"
                )
            )
    return warnings
