# backend/services/optimization_service.py
# PuLP 기반 스케줄 최적화 로직
#
# - run_optimization(job, sensor_states, tou_prices, env_weights, solar_forecast, outdoor_temp_forecast, now)
#     반환: List[ScheduleBlock] (공장별 블록 리스트)
#
#   [목적함수]
#     Minimize Σ(Grid_Power[t] × TOU_Price[t]) - (Solar_Predicted[t] × w_solar)
#
#   [제약 조건]
#     1. 식품 안전 온도: T_in[t] <= -18°C 항상 유지
#     2. 열 손실 방정식: T_in[t+1] = T_in[t] + (BaseLeakage × w_temp) - Cooling[t]
#     3. Short Cycle 방지: 가동/정지 전환 간격 최소 30분
#     4. 생산량 보장: 남은 시간 내 R 단위 이상 생산
#     5. 수동 정지 공장(manual_stop=True)은 변수에서 제외
#
#   [운영 전략 적용]
#     심야(저렴): 목표 온도를 -25°C ~ -27°C 로 과냉각 (축냉)
#     주간(비쌈): Coasting 모드 — 냉각 장치 최소화, 축적된 냉기로 유지
#
# - estimate_savings(schedule_blocks, baseline_kwh, tou_prices)
#     최적화 전/후 전력 비용 차액 계산 → 일간/월간 절감액 반환

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pulp

_LAST_OPTIMIZATION_DEBUG: dict[str, Any] | None = None


# -----------------------------------------------------------------------------
# [현재 구현 매핑]
# - run_optimization(...)
#   - 공장별 권장 온도(setpoint) 최적화
#   - 목적: 현재 슬롯(30분)의 비용 최소화 + 태양광/외기/입고 열부하 반영
#   - 결과: jobs.py가 바로 사용할 ScheduleBlock list 반환
# - estimate_savings(...)
#   - baseline 대비 단순 절감액 추정
# -----------------------------------------------------------------------------


def _hour_in_slot(hour: int, start: int, end: int) -> bool:
    """시(hour)가 TOU 슬롯(start~end)에 포함되는지 판정한다."""
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def _tou_price_at(now: datetime, tou_prices: list[dict[str, Any]]) -> float:
    """현재 시각 기준 TOU 단가를 찾는다."""
    for slot in tou_prices:
        start = int(slot.get("start_hour", 0))
        end = int(slot.get("end_hour", 0))
        if _hour_in_slot(now.hour, start, end):
            return float(slot.get("price", 0))
    return 0.0


def _first_solar_kwh(solar_forecast: list[dict[str, Any]]) -> float:
    """예측 리스트의 첫 행 태양광 kWh를 가져온다."""
    if not solar_forecast:
        return 0.0
    return float(solar_forecast[0].get("predicted_solar_kwh", 0.0))


def _outdoor_temp_at(now: datetime, outdoor_temp_forecast: list[dict[str, Any]]) -> float | None:
    """현재 시각 기준으로 가장 가까운 시간대의 외기온을 찾는다."""
    if not outdoor_temp_forecast:
        return None

    nearest_future: tuple[datetime, float] | None = None
    nearest_past: tuple[datetime, float] | None = None
    for row in outdoor_temp_forecast:
        ts_raw = row.get("timestamp")
        if not isinstance(ts_raw, str):
            continue
        try:
            ts = datetime.fromisoformat(ts_raw)
        except ValueError:
            continue
        temp_raw = row.get("temp_c")
        try:
            temp_c = float(temp_raw)
        except (TypeError, ValueError):
            continue

        if ts >= now:
            if nearest_future is None or ts < nearest_future[0]:
                nearest_future = (ts, temp_c)
        else:
            if nearest_past is None or ts > nearest_past[0]:
                nearest_past = (ts, temp_c)

    if nearest_future is not None:
        return nearest_future[1]
    if nearest_past is not None:
        return nearest_past[1]
    return None


def _dynamic_temp_weight(
    now: datetime,
    env_weights: dict[str, Any],
    outdoor_temp_forecast: list[dict[str, Any]],
) -> tuple[float, float, float | None]:
    """기본 w_temp를 시간대별 외기온으로 보정해 슬롯용 w_temp(t)를 만든다."""
    base_w_temp = float(env_weights.get("w_temp", 1.0))
    temp_c = _outdoor_temp_at(now, outdoor_temp_forecast)
    if temp_c is None:
        return base_w_temp, base_w_temp, None

    # 기준온도 대비 외기온 편차를 선형 보정해 1차 동적 가중치를 만든다.
    ref_temp_c = float(env_weights.get("max_temp_forecast_c", 18.0))
    delta_c = temp_c - ref_temp_c
    temp_factor = 1.0 + (delta_c * 0.03)
    dynamic_w_temp = max(0.7, min(1.8, base_w_temp * temp_factor))
    return dynamic_w_temp, base_w_temp, temp_c


def _economic_precool_signal(
    tou_price: float,
    solar_kwh: float,
    env_weights: dict[str, Any],
) -> float:
    """요금/태양광 신호를 결합해 프리쿨 유도 강도(-1~1)를 계산한다."""
    tou_ref = max(1.0, float(env_weights.get("tou_reference_price", 180.0)))
    solar_ref = max(0.1, float(env_weights.get("solar_reference_kwh", 4.0)))
    tou_gain = max(0.0, float(env_weights.get("tou_precool_gain", 1.0)))
    solar_gain = max(0.0, float(env_weights.get("solar_precool_gain", 0.9)))
    tou_score = (tou_ref - tou_price) / tou_ref
    solar_score = max(0.0, solar_kwh / solar_ref)
    signal = (tou_score * tou_gain) + (solar_score * solar_gain)
    return max(-1.0, min(1.0, signal))


def _desired_temp_from_state(
    factory: dict[str, Any],
    w_temp: float,
    default_min_precool_temp_c: float,
) -> tuple[float, float]:
    """현재 온도 오차와 외기 리스크를 기반으로 공장별 목표 온도를 계산한다."""
    target_temp = float(factory.get("target_temp_c", -18.0))
    current_temp = float(factory.get("temperature_c", target_temp))
    status = str(factory.get("status", ""))
    min_precool_temp_c = float(factory.get("min_precool_temp_c", default_min_precool_temp_c))

    # temp_gap > 0 이면 목표온도보다 따뜻한 상태(냉각 강화 필요)
    temp_gap = current_temp - target_temp
    positive_gap = max(0.0, temp_gap)
    ambient_risk = max(0.0, w_temp - 1.0)

    temp_recovery_gain = float(factory.get("temp_recovery_gain_c", 1.0))
    ambient_precool_gain = float(factory.get("ambient_precool_gain_c", 1.8))
    desired = target_temp - (positive_gap * temp_recovery_gain) - (ambient_risk * ambient_precool_gain)
    if status == "WARNING":
        desired = min(desired, target_temp - 4.0)
    desired = max(min_precool_temp_c, min(target_temp, desired))
    return desired, temp_gap


def _estimated_grid_kwh_from_temp(
    target_temp_c: float,
    recommended_temp_c: float,
    min_precool_temp_c: float,
    ambient_risk: float,
    inbound_units: float,
    env_weights: dict[str, Any],
) -> float:
    """온도 setpoint를 슬롯 예상 grid kWh로 환산한다."""
    span = max(0.1, target_temp_c - min_precool_temp_c)
    bounded_temp = max(min_precool_temp_c, min(target_temp_c, recommended_temp_c))
    temp_drop = max(0.0, target_temp_c - bounded_temp)
    temp_drop_ratio = temp_drop / span
    base_maintenance_kwh = float(env_weights.get("base_maintenance_kwh_per_slot", 0.35))
    cooling_kwh_per_c = float(env_weights.get("cooling_kwh_per_c", 0.20))
    ambient_kwh_gain_per_c = float(env_weights.get("ambient_kwh_gain_per_c", 0.06))
    inbound_kwh_per_unit = float(env_weights.get("inbound_kwh_per_unit", 0.015))
    stability_kwh_per_ratio = float(env_weights.get("stability_kwh_per_ratio", 0.05))
    cooling_kwh = temp_drop * (cooling_kwh_per_c + (ambient_kwh_gain_per_c * ambient_risk))
    load_kwh = inbound_units * inbound_kwh_per_unit
    stability_kwh = temp_drop_ratio * stability_kwh_per_ratio
    return max(0.0, base_maintenance_kwh + cooling_kwh + load_kwh + stability_kwh)


def _parse_planned_inbound_by_factory(job: dict[str, Any]) -> dict[int, float]:
    """job에 포함된 공장별 계획 입고량(마감까지 총량)을 파싱한다."""
    raw = job.get("planned_inbound_by_factory")
    if not isinstance(raw, dict):
        return {}
    parsed: dict[int, float] = {}
    for key, value in raw.items():
        try:
            factory_id = int(key)
            units = float(value or 0.0)
        except (TypeError, ValueError):
            continue
        parsed[factory_id] = max(0.0, units)
    return parsed


def _parse_planned_shipment_by_factory(job: dict[str, Any]) -> dict[int, float]:
    """job에 포함된 공장별 계획 출고량(마감까지 총량)을 파싱한다."""
    raw = job.get("planned_shipment_by_factory")
    if not isinstance(raw, dict):
        return {}
    parsed: dict[int, float] = {}
    for key, value in raw.items():
        try:
            factory_id = int(key)
            units = float(value or 0.0)
        except (TypeError, ValueError):
            continue
        parsed[factory_id] = max(0.0, units)
    return parsed


def _parse_door_open_count_by_factory(job: dict[str, Any]) -> dict[int, int]:
    """job에 포함된 슬롯별 공장 문열림 횟수를 파싱한다."""
    raw = job.get("door_open_count_by_factory")
    if not isinstance(raw, dict):
        return {}
    parsed: dict[int, int] = {}
    for key, value in raw.items():
        try:
            factory_id = int(key)
            count = int(value or 0)
        except (TypeError, ValueError):
            continue
        parsed[factory_id] = max(0, count)
    return parsed


def _dynamic_inbound_scores(sensor_states: list[dict[str, Any]]) -> dict[int, float]:
    """공장 상태(여유용량/온도마진/상태)를 점수화해 동적 분배 비율의 기반을 만든다."""
    scores: dict[int, float] = {}
    for factory in sensor_states:
        factory_id = int(factory["factory_id"])
        capacity = float(factory.get("capacity_units", 0.0) or 0.0)
        stock = float(factory.get("current_stock_units", 0.0) or 0.0)
        available_capacity = max(0.0, capacity - stock)
        capacity_ratio = available_capacity / max(1.0, capacity)

        target_temp = float(factory.get("target_temp_c", -18.0))
        current_temp = float(factory.get("temperature_c", target_temp))
        temp_margin = max(0.0, target_temp - current_temp)
        temp_margin_norm = min(1.0, temp_margin / 6.0)

        status = str(factory.get("status", "NORMAL"))
        status_factor_map = {
            "NORMAL": 1.0,
            "SAVING": 0.95,
            "WARNING": 0.8,
            "EMERGENCY": 0.7,
            "STOPPED": 0.7,
            "MANUAL_STOP": 0.0,
        }
        status_factor = status_factor_map.get(status, 1.0)

        # 여유용량과 온도마진을 우선 반영하고, 상태계수로 보정한다.
        score = (0.6 * capacity_ratio + 0.4 * temp_margin_norm) * status_factor
        scores[factory_id] = max(0.01, score)
    return scores


def _allocate_inbound_units_by_factory(
    total_inbound_units_this_slot: float,
    sensor_states: list[dict[str, Any]],
    planned_inbound_by_factory: dict[int, float],
) -> tuple[dict[int, float], str]:
    """슬롯 입고량을 공장별로 분배한다. 계획값이 있으면 계획+상태 하이브리드로 배분한다."""
    if total_inbound_units_this_slot <= 0:
        return {int(f["factory_id"]): 0.0 for f in sensor_states}, "NONE"

    scores = _dynamic_inbound_scores(sensor_states)
    planned_total = sum(planned_inbound_by_factory.values())

    weights: dict[int, float] = {}
    if planned_total > 0:
        # 계획 분배(70%) + 상태 점수(30%) 하이브리드
        score_total = sum(scores.values()) or 1.0
        for factory in sensor_states:
            factory_id = int(factory["factory_id"])
            plan_ratio = planned_inbound_by_factory.get(factory_id, 0.0) / planned_total
            score_ratio = scores.get(factory_id, 0.0) / score_total
            weights[factory_id] = (0.7 * plan_ratio) + (0.3 * score_ratio)
        source = "PLANNED_PLUS_DYNAMIC"
    else:
        score_total = sum(scores.values()) or 1.0
        for factory_id, score in scores.items():
            weights[factory_id] = score / score_total
        source = "DYNAMIC_ONLY"

    allocations = {
        factory_id: max(0.0, total_inbound_units_this_slot * weight)
        for factory_id, weight in weights.items()
    }
    return allocations, source


def run_optimization(
    job: dict[str, Any],
    sensor_states: list[dict[str, Any]],
    tou_prices: list[dict[str, Any]],
    env_weights: dict[str, Any],
    solar_forecast: list[dict[str, Any]],
    outdoor_temp_forecast: list[dict[str, Any]] | None,
    now: datetime,
) -> list[dict[str, Any]]:
    """현재 슬롯(30분) 기준 권장 온도(setpoint) 최적화 결과 블록을 만든다."""
    global _LAST_OPTIMIZATION_DEBUG
    if not sensor_states:
        _LAST_OPTIMIZATION_DEBUG = {
            "solver_status": "NO_SENSOR_STATES",
            "objective_expression": "",
            "constraint_expressions": [],
            "variable_values": {},
        }
        return []

    horizon_end = now + timedelta(minutes=30)
    slot_hours = max(0.1, (horizon_end - now).total_seconds() / 3600.0)
    deadline = job.get("deadline_at")
    if isinstance(deadline, str):
        try:
            parsed_deadline = datetime.fromisoformat(deadline)
            if parsed_deadline > now:
                horizon_end = min(horizon_end, parsed_deadline)
                slot_hours = max(0.1, (horizon_end - now).total_seconds() / 3600.0)
        except ValueError:
            pass

    tou_price = _tou_price_at(now, tou_prices)
    w_solar = float(env_weights.get("w_solar", 1.0))
    forecast_rows = outdoor_temp_forecast or []
    w_temp, w_temp_base, outdoor_temp_c = _dynamic_temp_weight(now, env_weights, forecast_rows)
    solar_kwh = _first_solar_kwh(solar_forecast)

    target_units = float(job.get("target_units", 0))
    produced_units = float(job.get("produced_units", 0))
    remaining_units = max(0.0, target_units - produced_units)
    if isinstance(deadline, str):
        try:
            deadline_dt = datetime.fromisoformat(deadline)
            remaining_time_hours = max(0.0, (deadline_dt - now).total_seconds() / 3600.0)
        except ValueError:
            remaining_time_hours = 24.0
    else:
        remaining_time_hours = 24.0
    # 냉각은 단일 30분 슬롯에서 완결되지 않으므로, deadline 압박을 완화한 계획 지평을 사용한다.
    thermal_planning_hours = float(job.get("thermal_planning_hours", 24.0))
    effective_planning_hours = max(6.0, thermal_planning_hours, remaining_time_hours)
    planned_inbound_by_factory = _parse_planned_inbound_by_factory(job)
    inbound_units_this_slot = remaining_units * (slot_hours / effective_planning_hours)
    inbound_units_by_factory, inbound_allocation_source = _allocate_inbound_units_by_factory(
        total_inbound_units_this_slot=inbound_units_this_slot,
        sensor_states=sensor_states,
        planned_inbound_by_factory=planned_inbound_by_factory,
    )
    planned_shipment_by_factory = _parse_planned_shipment_by_factory(job)
    daily_shipment_hour = int(job.get("daily_shipment_hour", 6))
    daily_shipment_max_ratio = max(0.0, min(1.0, float(job.get("daily_shipment_max_ratio", 0.25))))
    planned_total_shipment = float(job.get("planned_total_shipment_until_deadline", 0.0) or 0.0)
    shipment_units_by_factory = {int(factory["factory_id"]): 0.0 for factory in sensor_states}
    if now.hour == daily_shipment_hour and planned_total_shipment > 0 and planned_shipment_by_factory:
        slot_shipment_total = min(
            planned_total_shipment * daily_shipment_max_ratio,
            sum(planned_shipment_by_factory.values()),
        )
        shipment_weight_total = sum(planned_shipment_by_factory.values()) or 1.0
        for factory_id, total_units in planned_shipment_by_factory.items():
            ratio = total_units / shipment_weight_total
            shipment_units_by_factory[factory_id] = max(0.0, slot_shipment_total * ratio)
    door_open_count_by_factory = _parse_door_open_count_by_factory(job)
    inbound_cooling_c_per_unit = max(0.0, float(env_weights.get("inbound_cooling_c_per_unit", 0.09)))

    problem = pulp.LpProblem("midas_job_a_slot_optimization", pulp.LpMinimize)
    recommended_temp: dict[int, pulp.LpVariable] = {}
    temp_dev: dict[int, pulp.LpVariable] = {}
    inbound_shortfall: dict[int, pulp.LpVariable] = {}
    economic_dev: dict[int, pulp.LpVariable] = {}
    desired_temp_by_factory: dict[int, float] = {}
    economic_target_temp_by_factory: dict[int, float] = {}
    temp_gap_by_factory: dict[int, float] = {}
    target_temp_by_factory: dict[int, float] = {}
    min_precool_temp_by_factory: dict[int, float] = {}
    inbound_required_cap_temp_by_factory: dict[int, float] = {}
    estimated_grid_kwh_expr_by_factory: dict[int, Any] = {}
    required_extra_cooling_c_by_factory: dict[int, float] = {}
    ambient_risk = max(0.0, w_temp - 1.0)
    warning_recovery_c = max(0.0, float(env_weights.get("warning_recovery_c", 4.0)))
    cooling_strength_per_c = float(env_weights.get("cooling_kwh_per_c", 0.20)) + (
        float(env_weights.get("ambient_kwh_gain_per_c", 0.06)) * ambient_risk
    )
    base_maintenance_kwh = float(env_weights.get("base_maintenance_kwh_per_slot", 0.35))
    inbound_kwh_per_unit = float(env_weights.get("inbound_kwh_per_unit", 0.015))
    stability_kwh_per_ratio = float(env_weights.get("stability_kwh_per_ratio", 0.05))
    solar_util_reference_kwh = max(0.1, float(env_weights.get("solar_util_reference_kwh", 4.0)))
    solar_util_ratio = max(0.0, min(1.0, solar_kwh / solar_util_reference_kwh))
    ambient_temp_penalty_weight = float(env_weights.get("ambient_temp_penalty_weight", 0.03))
    inbound_cooling_penalty_weight = float(env_weights.get("inbound_cooling_penalty_weight", 45.0))
    releasable_margin_ref_c = max(0.1, float(env_weights.get("releasable_margin_ref_c", 4.0)))
    shipment_cooling_relief_c_per_unit = max(
        0.0,
        float(env_weights.get("shipment_cooling_relief_c_per_unit", 0.06)),
    )
    door_open_loss_c_per_event = max(0.0, float(env_weights.get("door_open_loss_c_per_event", 0.22)))
    economic_signal = _economic_precool_signal(
        tou_price=tou_price,
        solar_kwh=solar_kwh,
        env_weights=env_weights,
    )
    economic_precool_max_c = max(0.0, float(env_weights.get("economic_precool_max_c", 1.8)))
    economic_tracking_penalty_weight = float(env_weights.get("economic_tracking_penalty_weight", 35.0))

    for factory in sensor_states:
        factory_id = int(factory["factory_id"])
        target_temp = float(factory.get("target_temp_c", -18.0))
        min_precool_temp = float(factory.get("min_precool_temp_c", env_weights.get("min_precool_temp_c", -27.0)))
        temp_span = max(0.1, target_temp - min_precool_temp)
        inbound_units_factory = inbound_units_by_factory.get(factory_id, 0.0)
        shipment_units_factory = shipment_units_by_factory.get(factory_id, 0.0)
        current_temp = float(factory.get("temperature_c", target_temp))
        temp_margin = max(0.0, target_temp - current_temp)
        releasable_factor = min(1.0, temp_margin / releasable_margin_ref_c)
        shipment_relief_c = shipment_units_factory * shipment_cooling_relief_c_per_unit * releasable_factor
        door_open_loss_c = float(door_open_count_by_factory.get(factory_id, 0)) * door_open_loss_c_per_event
        required_extra_cooling_c = min(
            temp_span,
            max(0.0, (inbound_units_factory * inbound_cooling_c_per_unit) - shipment_relief_c + door_open_loss_c),
        )
        required_extra_cooling_c_by_factory[factory_id] = required_extra_cooling_c
        target_temp_by_factory[factory_id] = target_temp
        min_precool_temp_by_factory[factory_id] = min_precool_temp
        inbound_required_cap_temp = target_temp - required_extra_cooling_c
        inbound_required_cap_temp_by_factory[factory_id] = inbound_required_cap_temp

        recommended_temp[factory_id] = pulp.LpVariable(
            f"recommended_temp_{factory_id}",
            lowBound=min_precool_temp,
            upBound=target_temp,
            cat="Continuous",
        )
        # 온도 하강량과 입고 열부하를 사용해 슬롯 전력사용량을 추정한다.
        temp_drop_expr = target_temp - recommended_temp[factory_id]
        estimated_grid_kwh_expr = (
            base_maintenance_kwh
            + (temp_drop_expr * cooling_strength_per_c)
            + (inbound_units_factory * inbound_kwh_per_unit)
            + ((temp_drop_expr / temp_span) * stability_kwh_per_ratio)
        )
        estimated_grid_kwh_expr_by_factory[factory_id] = estimated_grid_kwh_expr

        # 입고 냉각 요구는 hard cap이 아닌 soft penalty로 반영해 요금/태양광 민감도를 확보한다.
        inbound_shortfall[factory_id] = pulp.LpVariable(
            f"inbound_temp_shortfall_{factory_id}",
            lowBound=0,
            upBound=20,
            cat="Continuous",
        )
        problem += (
            inbound_shortfall[factory_id] >= recommended_temp[factory_id] - inbound_required_cap_temp,
            f"inbound_shortfall_pos_{factory_id}",
        )

        status = str(factory.get("status", ""))
        if status == "WARNING":
            # WARNING 공장은 회복 우선: 권장 온도를 더 낮게 강제
            warning_cap = max(min_precool_temp, target_temp - warning_recovery_c)
            problem += recommended_temp[factory_id] <= warning_cap, f"warning_temp_cap_{factory_id}"

        # 온도 오차 추종 연속 패널티용 목표온도
        desired_temp, temp_gap = _desired_temp_from_state(
            factory,
            w_temp,
            default_min_precool_temp_c=min_precool_temp,
        )
        desired_temp_by_factory[factory_id] = desired_temp
        economic_target_temp = max(
            min_precool_temp,
            min(target_temp, target_temp - (economic_signal * economic_precool_max_c)),
        )
        economic_target_temp_by_factory[factory_id] = economic_target_temp
        temp_gap_by_factory[factory_id] = temp_gap
        temp_dev[factory_id] = pulp.LpVariable(
            f"temp_setpoint_dev_{factory_id}",
            lowBound=0,
            upBound=20,
            cat="Continuous",
        )
        # temp_dev >= |recommended_temp - desired_temp| (L1 절댓값 선형화)
        problem += (
            temp_dev[factory_id] >= recommended_temp[factory_id] - desired_temp,
            f"temp_dev_pos_{factory_id}",
        )
        problem += (
            temp_dev[factory_id] >= desired_temp - recommended_temp[factory_id],
            f"temp_dev_neg_{factory_id}",
        )
        economic_dev[factory_id] = pulp.LpVariable(
            f"economic_temp_dev_{factory_id}",
            lowBound=0,
            upBound=20,
            cat="Continuous",
        )
        problem += (
            economic_dev[factory_id] >= recommended_temp[factory_id] - economic_target_temp,
            f"economic_dev_pos_{factory_id}",
        )
        problem += (
            economic_dev[factory_id] >= economic_target_temp - recommended_temp[factory_id],
            f"economic_dev_neg_{factory_id}",
        )

    # 비용 최소화 + 태양광 기여 반영 + 고온 리스크 시 충분 냉각 유도
    cost_term = pulp.lpSum(
        estimated_grid_kwh_expr_by_factory[fid] * tou_price
        for fid in estimated_grid_kwh_expr_by_factory
    )
    solar_credit_term = pulp.lpSum(
        estimated_grid_kwh_expr_by_factory[fid] * tou_price * (solar_util_ratio * w_solar)
        for fid in estimated_grid_kwh_expr_by_factory
    )
    ambient_penalty_term = pulp.lpSum(
        (recommended_temp[fid] - min_precool_temp_by_factory[fid]) * ambient_risk * ambient_temp_penalty_weight
        for fid in recommended_temp
    )
    temp_tracking_penalty_weight = float(env_weights.get("temp_tracking_penalty_weight", 1.2))
    temp_tracking_penalty_term = pulp.lpSum(
        temp_dev[fid] * temp_tracking_penalty_weight for fid in temp_dev
    )
    inbound_cooling_penalty_term = pulp.lpSum(
        inbound_shortfall[fid] * inbound_cooling_penalty_weight for fid in inbound_shortfall
    )
    economic_tracking_penalty_term = pulp.lpSum(
        economic_dev[fid] * economic_tracking_penalty_weight for fid in economic_dev
    )
    problem += (
        cost_term
        - solar_credit_term
        + ambient_penalty_term
        + temp_tracking_penalty_term
        + inbound_cooling_penalty_term
        + economic_tracking_penalty_term
    )

    objective_expression = (
        "Minimize [sum(estimated_grid_kwh(temp_i) * tou_price)] "
        "- [sum(estimated_grid_kwh(temp_i) * tou_price * (solar_util_ratio * w_solar))] "
        "+ [sum((temp_i - min_precool_i) * ambient_risk * ambient_temp_penalty_weight)] "
        "+ [sum(abs(temp_i - desired_temp_i) * temp_tracking_penalty_weight)] "
        "+ [sum(max(0, temp_i - inbound_required_temp_i) * inbound_cooling_penalty_weight)] "
        "+ [sum(abs(temp_i - economic_target_temp_i) * economic_tracking_penalty_weight)]"
    )
    constraint_expressions = [
        "forall i: min_precool_temp_i <= temp_i <= target_temp_i",
        "forall i: temp_setpoint_dev_i >= |temp_i - desired_temp_i|",
        "forall i: inbound_temp_shortfall_i >= max(0, temp_i - inbound_required_temp_i)",
        "forall i: economic_temp_dev_i >= |temp_i - economic_target_temp_i|",
    ]
    for factory in sensor_states:
        factory_id = int(factory["factory_id"])
        required_extra_cooling_c = required_extra_cooling_c_by_factory.get(factory_id, 0.0)
        if required_extra_cooling_c > 0:
            constraint_expressions.append(
                f"factory {factory_id}: inbound_required_temp_i <= "
                f"{inbound_required_cap_temp_by_factory[factory_id]:.3f} (soft target)"
            )
    for factory in sensor_states:
        if str(factory.get("status", "")) == "WARNING":
            factory_id = int(factory["factory_id"])
            warning_cap = max(
                min_precool_temp_by_factory[factory_id],
                target_temp_by_factory[factory_id] - warning_recovery_c,
            )
            constraint_expressions.append(f"factory {factory_id}: temp_i <= {warning_cap:.3f} (warning recovery)")

    solver = pulp.PULP_CBC_CMD(msg=False)
    status_code = problem.solve(solver)
    solver_status = str(pulp.LpStatus.get(status_code))
    if pulp.LpStatus.get(status_code) != "Optimal":
        # 해가 불능/비최적일 경우 보수적으로 기존 ON 성향을 유지
        blocks: list[dict[str, Any]] = []
        for factory in sensor_states:
            status = str(factory.get("status", ""))
            mode = "RECOVERY" if status == "WARNING" else "HOLD"
            target_temp = float(factory.get("target_temp_c", -18.0))
            min_precool_temp = float(factory.get("min_precool_temp_c", env_weights.get("min_precool_temp_c", -27.0)))
            factory_id = int(factory["factory_id"])
            estimated_grid_kwh = _estimated_grid_kwh_from_temp(
                target_temp_c=target_temp,
                recommended_temp_c=target_temp,
                min_precool_temp_c=min_precool_temp,
                ambient_risk=ambient_risk,
                inbound_units=inbound_units_by_factory.get(factory_id, 0.0),
                env_weights=env_weights,
            )
            blocks.append(
                {
                    "factory_id": factory["factory_id"],
                    "start_at": now.isoformat(),
                    "end_at": horizon_end.isoformat(),
                    "mode": mode,
                "target_temp_c": round(target_temp, 2),
                "recommended_temp_c": round(target_temp, 2),
                    "expected_grid_kwh": round(max(0.0, estimated_grid_kwh), 3),
                    "expected_solar_kwh": max(0.0, solar_kwh * w_solar),
                    "reason": "LP_FALLBACK",
                }
            )
        _LAST_OPTIMIZATION_DEBUG = {
            "solver_status": solver_status,
            "objective_expression": objective_expression,
            "constraint_expressions": constraint_expressions,
            "variable_values": {},
            "parameters": {
                "tou_price": tou_price,
                "w_solar": w_solar,
                "w_temp": w_temp,
                "w_temp_base": w_temp_base,
                "outdoor_temp_c": outdoor_temp_c,
                "outdoor_temp_rows": len(forecast_rows),
                "solar_kwh": solar_kwh,
                "solar_util_ratio": round(solar_util_ratio, 4),
                "solar_util_reference_kwh": round(solar_util_reference_kwh, 4),
                "thermal_planning_hours": round(thermal_planning_hours, 3),
                "effective_planning_hours": round(effective_planning_hours, 3),
                "remaining_time_hours": round(remaining_time_hours, 3),
                "temp_tracking_penalty_weight": round(temp_tracking_penalty_weight, 4),
                "inbound_cooling_c_per_unit": round(inbound_cooling_c_per_unit, 4),
                "shipment_cooling_relief_c_per_unit": round(shipment_cooling_relief_c_per_unit, 4),
                "door_open_loss_c_per_event": round(door_open_loss_c_per_event, 4),
                "inbound_allocation_source": inbound_allocation_source,
            },
            "inbound_allocation": {
                str(fid): {
                    "slot_inbound_units": round(inbound_units_by_factory.get(fid, 0.0), 4),
                    "slot_shipment_units": round(shipment_units_by_factory.get(fid, 0.0), 4),
                    "door_open_count": int(door_open_count_by_factory.get(fid, 0)),
                    "required_extra_cooling_c": round(required_extra_cooling_c_by_factory.get(fid, 0.0), 4),
                }
                for fid in sorted(inbound_units_by_factory.keys())
            },
        }
        return blocks

    blocks: list[dict[str, Any]] = []
    variable_values: dict[str, dict[str, float]] = {}
    total_cost_term = 0.0
    total_solar_credit_term = 0.0
    total_ambient_penalty_term = 0.0
    total_temp_tracking_penalty_term = 0.0
    total_inbound_cooling_penalty_term = 0.0
    total_economic_tracking_penalty_term = 0.0
    mode_temp_drop_threshold_c = float(env_weights.get("mode_temp_drop_threshold_c", 1.5))
    for factory in sensor_states:
        factory_id = int(factory["factory_id"])
        recommended_temp_val = float(
            pulp.value(recommended_temp[factory_id]) or target_temp_by_factory[factory_id]
        )
        estimated_grid_kwh_val = _estimated_grid_kwh_from_temp(
            target_temp_c=target_temp_by_factory[factory_id],
            recommended_temp_c=recommended_temp_val,
            min_precool_temp_c=min_precool_temp_by_factory[factory_id],
            ambient_risk=ambient_risk,
            inbound_units=inbound_units_by_factory.get(factory_id, 0.0),
            env_weights=env_weights,
        )
        temp_drop_val = max(0.0, target_temp_by_factory[factory_id] - recommended_temp_val)
        variable_values[str(factory_id)] = {
            "recommended_temp_c": round(recommended_temp_val, 4),
            "estimated_grid_kwh": round(estimated_grid_kwh_val, 4),
            "inbound_shortfall_c": round(
                max(0.0, recommended_temp_val - inbound_required_cap_temp_by_factory[factory_id]), 4
            ),
        }
        total_cost_term += estimated_grid_kwh_val * tou_price
        total_solar_credit_term += estimated_grid_kwh_val * tou_price * (solar_util_ratio * w_solar)
        total_ambient_penalty_term += (
            (recommended_temp_val - min_precool_temp_by_factory[factory_id])
            * ambient_risk
            * ambient_temp_penalty_weight
        )
        desired_temp = desired_temp_by_factory.get(factory_id, target_temp_by_factory[factory_id])
        total_temp_tracking_penalty_term += abs(recommended_temp_val - desired_temp) * temp_tracking_penalty_weight
        total_inbound_cooling_penalty_term += (
            max(0.0, recommended_temp_val - inbound_required_cap_temp_by_factory[factory_id])
            * inbound_cooling_penalty_weight
        )
        total_economic_tracking_penalty_term += (
            abs(recommended_temp_val - economic_target_temp_by_factory[factory_id])
            * economic_tracking_penalty_weight
        )
        if str(factory.get("status", "")) == "WARNING":
            mode = "RECOVERY"
            reason = "TEMP_RECOVERY"
        elif temp_drop_val >= mode_temp_drop_threshold_c:
            mode = "PRECOOL"
            reason = "BASE_LOAD"
        else:
            mode = "HOLD"
            reason = "PEAK_AVOID" if tou_price >= 180 else "BASE_LOAD"

        blocks.append(
            {
                "factory_id": factory_id,
                "start_at": now.isoformat(),
                "end_at": horizon_end.isoformat(),
                "mode": mode,
                "target_temp_c": round(target_temp_by_factory[factory_id], 2),
                "recommended_temp_c": round(recommended_temp_val, 2),
                "expected_grid_kwh": round(max(0.0, estimated_grid_kwh_val), 3),
                "expected_solar_kwh": round(max(0.0, solar_kwh * w_solar), 3),
                "reason": reason,
            }
        )

    _LAST_OPTIMIZATION_DEBUG = {
        "solver_status": solver_status,
        "objective_expression": objective_expression,
        "constraint_expressions": constraint_expressions,
        "variable_values": variable_values,
        "objective_breakdown": {
            "cost_term": round(total_cost_term, 6),
            "solar_credit_term": round(total_solar_credit_term, 6),
            "ambient_penalty_term": round(total_ambient_penalty_term, 6),
            "temp_tracking_penalty_term": round(total_temp_tracking_penalty_term, 6),
            "inbound_cooling_penalty_term": round(total_inbound_cooling_penalty_term, 6),
            "economic_tracking_penalty_term": round(total_economic_tracking_penalty_term, 6),
            "objective_value": round(
                total_cost_term
                - total_solar_credit_term
                + total_ambient_penalty_term,
                # 온도 추종 연속 패널티를 포함한 최종 목적함수 값
                6,
            ),
            "objective_value_with_temp_tracking": round(
                total_cost_term
                - total_solar_credit_term
                + total_ambient_penalty_term
                + total_temp_tracking_penalty_term,
                # 입고냉각/경제신호 추종 패널티까지 포함한 최종 목적함수 값
                6,
            ),
            "objective_value_full": round(
                total_cost_term
                - total_solar_credit_term
                + total_ambient_penalty_term
                + total_temp_tracking_penalty_term
                + total_inbound_cooling_penalty_term
                + total_economic_tracking_penalty_term,
                6,
            ),
        },
        "temperature_tracking": {
            str(fid): {
                "desired_temp_c": round(desired_temp_by_factory.get(fid, target_temp_by_factory[fid]), 3),
                "economic_target_temp_c": round(
                    economic_target_temp_by_factory.get(fid, target_temp_by_factory[fid]),
                    3,
                ),
                "temp_gap_c": round(temp_gap_by_factory.get(fid, 0.0), 3),
            }
            for fid in sorted(desired_temp_by_factory.keys())
        },
        "inbound_allocation": {
            str(fid): {
                "slot_inbound_units": round(inbound_units_by_factory.get(fid, 0.0), 4),
                "slot_shipment_units": round(shipment_units_by_factory.get(fid, 0.0), 4),
                "door_open_count": int(door_open_count_by_factory.get(fid, 0)),
                "required_extra_cooling_c": round(required_extra_cooling_c_by_factory.get(fid, 0.0), 4),
            }
            for fid in sorted(inbound_units_by_factory.keys())
        },
        "parameters": {
            "tou_price": tou_price,
            "w_solar": w_solar,
            "w_temp": w_temp,
            "w_temp_base": w_temp_base,
            "outdoor_temp_c": outdoor_temp_c,
            "outdoor_temp_rows": len(forecast_rows),
            "solar_kwh": solar_kwh,
            "solar_util_ratio": round(solar_util_ratio, 4),
            "solar_util_reference_kwh": round(solar_util_reference_kwh, 4),
            "thermal_planning_hours": round(thermal_planning_hours, 3),
            "effective_planning_hours": round(effective_planning_hours, 3),
            "remaining_time_hours": round(remaining_time_hours, 3),
            "inbound_units_this_slot": round(inbound_units_this_slot, 3),
            "temp_tracking_penalty_weight": round(temp_tracking_penalty_weight, 4),
            "inbound_cooling_penalty_weight": round(inbound_cooling_penalty_weight, 4),
            "economic_tracking_penalty_weight": round(economic_tracking_penalty_weight, 4),
            "economic_signal": round(economic_signal, 4),
            "economic_precool_max_c": round(economic_precool_max_c, 4),
            "inbound_cooling_c_per_unit": round(inbound_cooling_c_per_unit, 4),
            "shipment_cooling_relief_c_per_unit": round(shipment_cooling_relief_c_per_unit, 4),
            "door_open_loss_c_per_event": round(door_open_loss_c_per_event, 4),
            "cooling_strength_per_c": round(cooling_strength_per_c, 4),
            "base_maintenance_kwh_per_slot": round(base_maintenance_kwh, 4),
            "inbound_kwh_per_unit": round(inbound_kwh_per_unit, 4),
            "stability_kwh_per_ratio": round(stability_kwh_per_ratio, 4),
            "daily_shipment_hour": daily_shipment_hour,
            "daily_shipment_max_ratio": round(daily_shipment_max_ratio, 4),
            "inbound_allocation_source": inbound_allocation_source,
        },
    }
    return blocks


def get_last_optimization_debug() -> dict[str, Any] | None:
    """직전 run_optimization의 식/변수/목적함수 분해 정보를 반환한다."""
    return _LAST_OPTIMIZATION_DEBUG


def estimate_savings(
    schedule_blocks: list[dict[str, Any]],
    baseline_kwh: float,
    tou_prices: list[dict[str, Any]],
) -> dict[str, float]:
    """baseline 대비 간단 절감액(일/월) 추정값을 계산한다."""
    avg_price = 0.0
    if tou_prices:
        avg_price = sum(float(slot.get("price", 0.0)) for slot in tou_prices) / len(tou_prices)
    optimized_kwh = sum(float(block.get("expected_grid_kwh", 0.0)) for block in schedule_blocks)
    baseline_cost = baseline_kwh * avg_price
    optimized_cost = optimized_kwh * avg_price
    daily = max(0.0, baseline_cost - optimized_cost)
    return {
        "estimated_daily_saving_krw": round(daily, 1),
        "estimated_monthly_saving_krw": round(daily * 30, 1),
    }
