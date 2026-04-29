from __future__ import annotations

import math
from datetime import timedelta
from typing import Any, Iterable


Record = dict[str, Any]


def to_records(data: Any) -> list[Record]:
    if data is None:
        return []
    if isinstance(data, list):
        return [dict(row) for row in data]
    if isinstance(data, tuple):
        return [dict(row) for row in data]
    if hasattr(data, "to_dict"):
        return data.to_dict("records")
    raise TypeError("data must be a list of dicts or a pandas DataFrame")


def sorted_records(data: Any, timestamp_col: str = "timestamp") -> list[Record]:
    records = [row for row in to_records(data) if row.get(timestamp_col) is not None]
    return sorted(records, key=lambda row: row[timestamp_col])


def recent_records(
    data: Any,
    window_minutes: float,
    timestamp_col: str = "timestamp",
    reference_time: Any | None = None,
) -> list[Record]:
    records = sorted_records(data, timestamp_col)
    if not records:
        return []

    latest = reference_time if reference_time is not None else records[-1][timestamp_col]
    cutoff = latest - timedelta(minutes=window_minutes)
    return [row for row in records if cutoff <= row[timestamp_col] <= latest]


def valid_number(value: Any) -> bool:
    if value is None:
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number)


def valid_temperature(value: Any, minimum: float = -40.0, maximum: float = 100.0) -> bool:
    if not valid_number(value):
        return False
    number = float(value)
    if number in (85.0, -127.0):
        return False
    return minimum <= number <= maximum


def group_records(records: Iterable[Record], key: str) -> dict[Any, list[Record]]:
    groups: dict[Any, list[Record]] = {}
    for row in records:
        groups.setdefault(row.get(key), []).append(row)
    return groups
