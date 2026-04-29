from __future__ import annotations

try:
    from .common import recent_records, valid_temperature
except ImportError:
    from common import recent_records, valid_temperature


def _linear_regression(x_values: list[float], y_values: list[float]) -> tuple[float, float] | None:
    n = len(x_values)
    if n < 2:
        return None

    mean_x = sum(x_values) / n
    mean_y = sum(y_values) / n
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(x_values, y_values))
    denominator = sum((x - mean_x) ** 2 for x in x_values)

    if denominator == 0:
        return None

    slope = numerator / denominator
    intercept = mean_y - slope * mean_x
    return slope, intercept


def predict_temperature_1h(
    data,
    window_minutes: float = 30,
    timestamp_col: str = "timestamp",
    temp_col: str = "inside_temp",
):
    """Predict inside temperature 1 hour after the latest sample."""
    recent = [
        row
        for row in recent_records(data, window_minutes, timestamp_col)
        if valid_temperature(row.get(temp_col))
    ]

    if len(recent) < 10:
        return None

    t0 = recent[0][timestamp_col]
    x_values = [(row[timestamp_col] - t0).total_seconds() / 60 for row in recent]
    y_values = [float(row[temp_col]) for row in recent]

    regression = _linear_regression(x_values, y_values)
    if regression is None:
        return None

    slope, intercept = regression
    next_60_min = x_values[-1] + 60
    predicted_temp = slope * next_60_min + intercept

    return {
        "current_temp": y_values[-1],
        "predicted_1h_temp": predicted_temp,
        "trend_c_per_min": slope,
        "window_minutes": window_minutes,
        "sample_count": len(recent),
    }
