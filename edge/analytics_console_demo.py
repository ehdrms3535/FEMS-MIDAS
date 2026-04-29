from __future__ import annotations

import argparse
from datetime import datetime, timedelta

from analytics.anomaly_detection import detect_anomalies
from analytics.cooling_efficiency import compare_cooling_efficiency_by_factory
from analytics.cooling_load import calculate_today_cooling_load
from analytics.temperature_forecast import predict_temperature_1h


def build_sample_records(minutes: int = 40, interval_seconds: int = 5):
    started_at = datetime.now() - timedelta(minutes=minutes)
    sample_count = int(minutes * 60 / interval_seconds)
    records = []

    factory_profiles = {
        1: {"start": -12.0, "slope_per_min": -0.12, "hot": 42.0},
        2: {"start": -10.0, "slope_per_min": -0.06, "hot": 48.0},
        3: {"start": -8.0, "slope_per_min": 0.03, "hot": 57.0},
        4: {"start": -9.0, "slope_per_min": -0.02, "hot": 67.0},
    }

    for factory_id, profile in factory_profiles.items():
        for index in range(sample_count):
            timestamp = started_at + timedelta(seconds=index * interval_seconds)
            minutes_from_start = index * interval_seconds / 60
            temp = profile["start"] + profile["slope_per_min"] * minutes_from_start

            if factory_id == 3 and sample_count - 30 <= index <= sample_count - 25:
                temp += 6.0
            if factory_id == 2 and index >= sample_count - 5:
                temp = 85.0

            records.append(
                {
                    "factory_id": factory_id,
                    "timestamp": timestamp,
                    "inside_temp": temp,
                    "hot_side_temp": profile["hot"],
                    "peltier_pwm": 30,
                }
            )

    return records


def format_float(value, digits: int = 2):
    if value is None:
        return "-"
    return f"{value:.{digits}f}"


def show_efficiency(records):
    print("\n[Cooling efficiency: recent 10 minutes]")
    for row in compare_cooling_efficiency_by_factory(records, window_minutes=10):
        minutes_per_1c = format_float(row["minutes_per_1c"])
        rate = format_float(row["cooling_rate"], 3)
        print(
            f"factory={row['factory_id']} status={row['status']} "
            f"rate={rate}C/min minutes_per_1C={minutes_per_1c} "
            f"samples={row['sample_count']}"
        )


def show_forecast(records, factory_id: int):
    factory_records = [row for row in records if row["factory_id"] == factory_id]
    forecast = predict_temperature_1h(factory_records, window_minutes=30)

    print(f"\n[Temperature forecast: factory {factory_id}, recent 30 minutes]")
    if forecast is None:
        print("not enough data")
        return

    print(
        f"current={format_float(forecast['current_temp'])}C "
        f"predicted_1h={format_float(forecast['predicted_1h_temp'])}C "
        f"trend={format_float(forecast['trend_c_per_min'], 3)}C/min "
        f"samples={forecast['sample_count']}"
    )


def show_anomalies(records):
    print("\n[Anomaly detection]")
    for factory_id in sorted({row["factory_id"] for row in records}):
        factory_records = [row for row in records if row["factory_id"] == factory_id]
        anomalies = detect_anomalies(factory_records)
        print(
            f"factory={factory_id} "
            f"spike={anomalies['temp_spike']} "
            f"sensor={anomalies['sensor_failure']} "
            f"hot_side={anomalies['hot_side']}"
        )


def show_load():
    print("\n[Cooling load: today estimate]")
    kma_like_forecast = [22, 24, 27, 30, 32, 31, 28, 25]
    load = calculate_today_cooling_load(kma_like_forecast, target_temp=-18, factory_factor=1.0)
    print(load)


def parse_args():
    parser = argparse.ArgumentParser(description="Console demo for edge analytics")
    parser.add_argument("--factory-id", type=int, default=1, help="Factory to use for 1h forecast demo")
    parser.add_argument("--minutes", type=int, default=40, help="Sample history length")
    return parser.parse_args()


def main():
    args = parse_args()
    records = build_sample_records(minutes=args.minutes)
    show_efficiency(records)
    show_forecast(records, args.factory_id)
    show_anomalies(records)
    show_load()


if __name__ == "__main__":
    main()
