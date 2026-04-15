"""TOU(Time-of-Use) 요금 계산 서비스.

electricity_rate_simulator.py의 시간대별 전기요금 함수를 Job A 스케줄러에서 재사용할 수 있도록
백엔드 서비스 계층으로 정리한 모듈.
"""

from __future__ import annotations

from datetime import datetime


def is_holiday(dt: datetime) -> bool:
    """주말(토/일)을 공휴일로 간주한다.

    TODO: 향후 공휴일 API/캘린더 연동 시 치환.
    """
    return dt.weekday() >= 5


def get_rate_weekday(hour: float) -> float:
    """평일 TOU 단가(원/kWh)."""
    if hour < 8 or hour >= 22:
        return 117.0
    if (8 <= hour < 11) or (18 <= hour < 21):
        return 135.0
    if 11 <= hour < 18:
        return 155.0
    return 117.0


def get_rate_holiday(hour: float) -> float:
    """주말/공휴일 TOU 단가(원/kWh)."""
    if 11 <= hour < 14:
        return 60.0
    return 117.0


def get_tou_price_krw_per_kwh(now: datetime) -> float:
    """현재 시각의 TOU 단가(원/kWh)를 반환한다."""
    hour = now.hour + (now.minute / 60.0)
    if is_holiday(now):
        return get_rate_holiday(hour)
    return get_rate_weekday(hour)

