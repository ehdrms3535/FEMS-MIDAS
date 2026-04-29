from __future__ import annotations

try:
    from .common import recent_records, sorted_records, valid_number, valid_temperature
except ImportError:
    from common import recent_records, sorted_records, valid_number, valid_temperature


def detect_temp_spike(
    data,
    window_minutes: float = 5,
    threshold_c: float = 5.0,
    timestamp_col: str = "timestamp",
    temp_col: str = "inside_temp",
):
    """Detect sudden temperature changes inside the real recent time window."""
    recent = [
        row
        for row in recent_records(data, window_minutes, timestamp_col)
        if valid_temperature(row.get(temp_col))
    ]

    if len(recent) < 2:
        return False, "data_not_enough"

    temps = [float(row[temp_col]) for row in recent]
    first_last_delta = temps[-1] - temps[0]
    range_delta = max(temps) - min(temps)
    max_step_delta = max(abs(curr - prev) for prev, curr in zip(temps, temps[1:]))

    if abs(first_last_delta) >= threshold_c:
        return True, f"{window_minutes}min endpoint change {first_last_delta:.1f}C"

    if range_delta >= threshold_c:
        return True, f"{window_minutes}min range change {range_delta:.1f}C"

    if max_step_delta >= threshold_c:
        return True, f"sample-to-sample change {max_step_delta:.1f}C"

    return False, "normal"


def is_invalid_temp(value):
    return not valid_temperature(value)


def detect_sensor_failure(data, consecutive_limit: int = 5, temp_col: str = "inside_temp"):
    records = sorted_records(data)
    recent_values = [row.get(temp_col) for row in records[-consecutive_limit:]]

    if len(recent_values) < consecutive_limit:
        return False, "data_not_enough"

    failed_count = sum(is_invalid_temp(value) for value in recent_values)

    if failed_count >= consecutive_limit:
        return True, f"sensor_failed_{consecutive_limit}_times"

    return False, "normal"


def detect_hot_side_overheat(
    data,
    warning_temp: float = 55,
    stop_temp: float = 65,
    hot_temp_col: str = "hot_side_temp",
):
    records = sorted_records(data)
    if not records:
        return "unknown", "data_not_enough"

    hot_temp = records[-1].get(hot_temp_col)
    if not valid_number(hot_temp):
        return "unknown", "hot_side_temp_missing"

    hot_temp = float(hot_temp)

    if hot_temp >= stop_temp:
        return "critical", f"hot_side_{hot_temp:.1f}C_stop_peltier"

    if hot_temp >= warning_temp:
        return "warning", f"hot_side_{hot_temp:.1f}C_check_cooling"

    return "normal", "normal"


def detect_anomalies(data):
    temp_spike = detect_temp_spike(data)
    sensor_failure = detect_sensor_failure(data)
    hot_side = detect_hot_side_overheat(data)

    return {
        "temp_spike": {"detected": temp_spike[0], "message": temp_spike[1]},
        "sensor_failure": {"detected": sensor_failure[0], "message": sensor_failure[1]},
        "hot_side": {"level": hot_side[0], "message": hot_side[1]},
    }
