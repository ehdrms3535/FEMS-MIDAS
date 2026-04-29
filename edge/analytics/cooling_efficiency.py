from __future__ import annotations

try:
    from .common import group_records, recent_records, sorted_records, valid_temperature
except ImportError:
    from common import group_records, recent_records, sorted_records, valid_temperature


def calculate_cooling_efficiency(
    data,
    window_minutes: float = 10,
    timestamp_col: str = "timestamp",
    temp_col: str = "inside_temp",
):
    """Calculate cooling speed from the real timestamp window.

    Returns minutes needed to drop 1 degree Celsius based on the recent
    temperature trend.
    """
    recent = [
        row
        for row in recent_records(data, window_minutes, timestamp_col)
        if valid_temperature(row.get(temp_col))
    ]

    if len(recent) < 2:
        return None

    start_temp = float(recent[0][temp_col])
    end_temp = float(recent[-1][temp_col])
    start_time = recent[0][timestamp_col]
    end_time = recent[-1][timestamp_col]

    elapsed_min = (end_time - start_time).total_seconds() / 60
    if elapsed_min <= 0:
        return None

    temp_delta = end_temp - start_temp
    cooling_rate = temp_delta / elapsed_min

    if cooling_rate >= 0:
        return {
            "status": "not_cooling",
            "cooling_rate": cooling_rate,
            "minutes_per_1c": None,
            "window_minutes": window_minutes,
            "sample_count": len(recent),
            "temp_delta": temp_delta,
        }

    return {
        "status": "cooling",
        "cooling_rate": cooling_rate,
        "minutes_per_1c": 1 / abs(cooling_rate),
        "window_minutes": window_minutes,
        "sample_count": len(recent),
        "temp_delta": temp_delta,
    }


def compare_cooling_efficiency_by_factory(
    data,
    window_minutes: float = 10,
    factory_col: str = "factory_id",
    timestamp_col: str = "timestamp",
    temp_col: str = "inside_temp",
):
    records = sorted_records(data, timestamp_col)
    results = []

    for factory_id, factory_records in group_records(records, factory_col).items():
        if factory_id is None:
            continue

        efficiency = calculate_cooling_efficiency(
            factory_records,
            window_minutes=window_minutes,
            timestamp_col=timestamp_col,
            temp_col=temp_col,
        )
        if efficiency is None:
            continue

        results.append({"factory_id": factory_id, **efficiency})

    return sorted(
        results,
        key=lambda row: (
            row["minutes_per_1c"] is None,
            row["minutes_per_1c"] if row["minutes_per_1c"] is not None else float("inf"),
        ),
    )
