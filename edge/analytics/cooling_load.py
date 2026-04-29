from __future__ import annotations


def calculate_cooling_load(
    outside_temp: float,
    target_temp: float,
    factory_factor: float = 1.0,
    insulation_factor: float = 1.0,
):
    temp_gap = max(0.0, float(outside_temp) - float(target_temp))
    load_index = temp_gap * factory_factor * insulation_factor

    if load_index < 10:
        level = "low"
    elif load_index < 20:
        level = "normal"
    elif load_index < 30:
        level = "high"
    else:
        level = "very_high"

    return {
        "outside_temp": float(outside_temp),
        "target_temp": float(target_temp),
        "temp_gap": temp_gap,
        "load_index": load_index,
        "level": level,
    }


def calculate_today_cooling_load(
    outside_temperatures,
    target_temp: float,
    factory_factor: float = 1.0,
    insulation_factor: float = 1.0,
):
    """Estimate today's load from weather forecast temperatures.

    Pass KMA forecast temperatures or manually entered outside temperatures.
    The peak index is useful for capacity planning; the average index is useful
    for today's expected cooling burden.
    """
    temps = [float(temp) for temp in outside_temperatures]
    if not temps:
        return None

    average_temp = sum(temps) / len(temps)
    peak_temp = max(temps)

    average_load = calculate_cooling_load(
        average_temp,
        target_temp,
        factory_factor=factory_factor,
        insulation_factor=insulation_factor,
    )
    peak_load = calculate_cooling_load(
        peak_temp,
        target_temp,
        factory_factor=factory_factor,
        insulation_factor=insulation_factor,
    )

    return {
        "target_temp": float(target_temp),
        "average_outside_temp": average_temp,
        "peak_outside_temp": peak_temp,
        "average_load_index": average_load["load_index"],
        "peak_load_index": peak_load["load_index"],
        "average_level": average_load["level"],
        "peak_level": peak_load["level"],
        "sample_count": len(temps),
    }
