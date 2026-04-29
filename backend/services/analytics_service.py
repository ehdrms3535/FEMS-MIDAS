import math
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from database.models import SensorLog, Factory, Schedule
from services.weather_service import fetch_today_forecast

ANOMALY_TEMP_THRESHOLD = 3.0  # 이상 감지 온도 변화 임계값 (°C)


async def cooling_efficiency(db: AsyncSession, factory_id: int, hours: int = 24) -> dict:
    """온도 1도 내리는데 걸리는 평균 시간 (분)"""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    result = await db.execute(
        select(SensorLog.temperature_c, SensorLog.measured_at)
        .where(SensorLog.factory_id == factory_id)
        .where(SensorLog.measured_at >= since)
        .order_by(SensorLog.measured_at)
    )
    rows = result.all()

    if len(rows) < 10:
        return {"factory_id": factory_id, "minutes_per_degree": None, "message": "데이터 부족"}

    segments = []
    seg_start = None

    for i in range(1, len(rows)):
        prev = float(rows[i - 1].temperature_c)
        curr = float(rows[i].temperature_c)

        if curr < prev:
            if seg_start is None:
                seg_start = i - 1
        else:
            if seg_start is not None and (i - seg_start) >= 3:
                t0 = rows[seg_start].temperature_c
                t1 = rows[i - 1].temperature_c
                dt0 = rows[seg_start].measured_at
                dt1 = rows[i - 1].measured_at
                if hasattr(dt0, "tzinfo") and dt0.tzinfo is None:
                    dt0 = dt0.replace(tzinfo=timezone.utc)
                if hasattr(dt1, "tzinfo") and dt1.tzinfo is None:
                    dt1 = dt1.replace(tzinfo=timezone.utc)
                drop = float(t0) - float(t1)
                mins = (dt1 - dt0).total_seconds() / 60
                if drop > 0.5 and mins > 0:
                    segments.append(round(mins / drop, 2))
            seg_start = None

    if not segments:
        return {"factory_id": factory_id, "minutes_per_degree": None, "message": "냉각 구간 없음"}

    avg_rate = round(sum(segments) / len(segments), 2)
    return {
        "factory_id": factory_id,
        "minutes_per_degree": avg_rate,
        "cooling_segments_count": len(segments),
        "period_hours": hours,
    }


async def predict_temperature(db: AsyncSession, factory_id: int, horizon_minutes: int = 60) -> dict:
    """최근 60분 선형 회귀 기반 온도 예측"""
    since = datetime.now(timezone.utc) - timedelta(minutes=60)
    result = await db.execute(
        select(SensorLog.temperature_c, SensorLog.measured_at)
        .where(SensorLog.factory_id == factory_id)
        .where(SensorLog.measured_at >= since)
        .order_by(SensorLog.measured_at)
    )
    rows = result.all()

    if len(rows) < 10:
        return {"factory_id": factory_id, "predicted_temp": None, "message": "데이터 부족"}

    base = rows[0].measured_at
    if hasattr(base, "tzinfo") and base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)

    xs, ys = [], []
    for row in rows:
        t = row.measured_at
        if hasattr(t, "tzinfo") and t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        xs.append((t - base).total_seconds() / 60)
        ys.append(float(row.temperature_c))

    n = len(xs)
    sx, sy = sum(xs), sum(ys)
    sxy = sum(x * y for x, y in zip(xs, ys))
    sx2 = sum(x * x for x in xs)
    denom = n * sx2 - sx ** 2

    if denom == 0:
        return {"factory_id": factory_id, "current_temp": round(ys[-1], 2),
                "predicted_temp": round(ys[-1], 2), "trend": "안정", "horizon_minutes": horizon_minutes}

    a = (n * sxy - sx * sy) / denom
    b = (sy - a * sx) / n
    predicted = round(a * (xs[-1] + horizon_minutes) + b, 2)

    return {
        "factory_id": factory_id,
        "current_temp": round(ys[-1], 2),
        "predicted_temp": predicted,
        "horizon_minutes": horizon_minutes,
        "trend": "상승" if a > 0.01 else "하강" if a < -0.01 else "안정",
    }


async def detect_anomalies(db: AsyncSession, factory_id: int, minutes: int = 5) -> dict:
    """최근 N분 내 온도 급변 및 센서 지연 감지"""
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    result = await db.execute(
        select(SensorLog.temperature_c, SensorLog.measured_at)
        .where(SensorLog.factory_id == factory_id)
        .where(SensorLog.measured_at >= since)
        .order_by(SensorLog.measured_at)
    )
    rows = result.all()

    anomalies = []

    if len(rows) < 2:
        anomalies.append({"type": "SENSOR_FAILURE", "message": f"최근 {minutes}분 데이터 없음"})
        return {"factory_id": factory_id, "anomalies": anomalies, "is_normal": False}

    temps = [float(r.temperature_c) for r in rows]
    temp_range = max(temps) - min(temps)

    if temp_range >= ANOMALY_TEMP_THRESHOLD:
        anomalies.append({
            "type": "RAPID_TEMP_CHANGE",
            "message": f"{minutes}분 내 {temp_range:.1f}°C 변동",
            "max": round(max(temps), 2),
            "min": round(min(temps), 2),
        })

    last_t = rows[-1].measured_at
    if hasattr(last_t, "tzinfo") and last_t.tzinfo is None:
        last_t = last_t.replace(tzinfo=timezone.utc)
    gap = (datetime.now(timezone.utc) - last_t).total_seconds()
    if gap > 30:
        anomalies.append({"type": "SENSOR_DELAY", "message": f"마지막 수신 {int(gap)}초 전"})

    return {
        "factory_id": factory_id,
        "anomalies": anomalies,
        "is_normal": len(anomalies) == 0,
        "data_points": len(rows),
        "checked_minutes": minutes,
    }


async def cooling_load(db: AsyncSession, factory_id: int) -> dict:
    """기상청 외부 온도 vs 목표 온도 기반 냉각 부하 계산"""
    factory = await db.get(Factory, factory_id)
    if not factory:
        return {"factory_id": factory_id, "cooling_load": None, "message": "공장 없음"}

    now = datetime.now(timezone.utc)
    sched_result = await db.execute(
        select(Schedule)
        .where(Schedule.factory_id == factory_id)
        .where(Schedule.start_at <= now)
        .where(Schedule.end_at >= now)
        .limit(1)
    )
    schedule = sched_result.scalar_one_or_none()
    target_temp = schedule.target_temp if schedule else None

    try:
        forecasts = await fetch_today_forecast()
        current_hour = f"{datetime.now().hour:02d}"
        fc = next((f for f in forecasts if f["hour"] == current_hour), None)
        external_temp = fc["temperature_c"] if fc else None
    except Exception:
        external_temp = None

    if external_temp is None or target_temp is None:
        return {
            "factory_id": factory_id,
            "external_temp": external_temp,
            "target_temp": target_temp,
            "cooling_load": None,
            "message": "외부 온도 또는 목표 온도 없음",
        }

    load = round(external_temp - target_temp, 2)
    return {
        "factory_id": factory_id,
        "external_temp": external_temp,
        "target_temp": target_temp,
        "cooling_load": load,
        "load_level": "HIGH" if load > 30 else "MEDIUM" if load > 20 else "LOW",
    }
