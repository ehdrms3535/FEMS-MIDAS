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
# - calculate_required_factories(remaining_units, remaining_time_hours)
#     L1 로직: Q 비율에 따라 필요 공장 수(1~4) 반환
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
#   - 1.5단계 모델: 공장별 ON/COASTING(binary+continuous) 최적화
#   - 목적: 현재 슬롯(30분)의 비용 최소화 + 태양광 가중치 반영
#   - 결과: jobs.py가 바로 사용할 ScheduleBlock list 반환
# - calculate_required_factories(...)
#   - L1 규칙을 단순화하여 최소 가동 공장 수(1~4) 계산
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


def _desired_pwm_from_temp(factory: dict[str, Any], w_temp: float) -> tuple[float, float]:
    """현재 온도 오차와 외기 리스크를 기반으로 공장별 목표 PWM을 계산한다."""
    target_temp = float(factory.get("target_temp_c", -18.0))
    current_temp = float(factory.get("temperature_c", target_temp))
    status = str(factory.get("status", ""))

    # temp_gap > 0 이면 목표온도보다 따뜻한 상태(냉각 강화 필요)
    temp_gap = current_temp - target_temp
    positive_gap = max(0.0, temp_gap)
    ambient_risk = max(0.0, w_temp - 1.0)

    base_pwm = 20.0
    temp_gap_pwm_gain = float(factory.get("temp_gap_pwm_gain", 12.0))
    ambient_pwm_gain = float(factory.get("ambient_pwm_gain", 10.0))
    desired = base_pwm + (positive_gap * temp_gap_pwm_gain) + (ambient_risk * ambient_pwm_gain)
    if status == "WARNING":
        desired = max(desired, 70.0)
    desired = max(20.0, min(100.0, desired))
    return desired, temp_gap


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


def calculate_required_factories(
    remaining_units: float,
    remaining_time_hours: float,
    available_factories: int,
) -> int:
    """남은 입고량/시간 기준으로 최소 필요 공장 수를 계산한다."""
    if remaining_units <= 0:
        return 1
    safe_hours = max(0.5, remaining_time_hours)
    required_rate = remaining_units / safe_hours
    # 1단계 가정: 공장 1개가 시간당 약 40 unit의 입고 열부하를 안정적으로 처리 가능
    per_factory_capacity_per_hour = 40.0
    required = int((required_rate / per_factory_capacity_per_hour) + 0.9999)
    if required_rate >= 120:
        required = max(required, 4)
    elif required_rate >= 60:
        required = max(required, 2)
    else:
        required = max(required, 1)
    return max(1, min(available_factories, required))


def run_optimization(
    job: dict[str, Any],
    sensor_states: list[dict[str, Any]],
    tou_prices: list[dict[str, Any]],
    env_weights: dict[str, Any],
    solar_forecast: list[dict[str, Any]],
    outdoor_temp_forecast: list[dict[str, Any]] | None,
    now: datetime,
) -> list[dict[str, Any]]:
    """현재 슬롯(30분) 기준 ON/COASTING + PWM 최적화 결과 블록을 만든다."""
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
    min_active = calculate_required_factories(
        remaining_units=remaining_units,
        remaining_time_hours=effective_planning_hours,
        available_factories=len(sensor_states),
    )
    planned_inbound_by_factory = _parse_planned_inbound_by_factory(job)
    inbound_units_this_slot = remaining_units * (slot_hours / effective_planning_hours)
    inbound_units_by_factory, inbound_allocation_source = _allocate_inbound_units_by_factory(
        total_inbound_units_this_slot=inbound_units_this_slot,
        sensor_states=sensor_states,
        planned_inbound_by_factory=planned_inbound_by_factory,
    )
    inbound_pwm_per_unit = float(env_weights.get("inbound_pwm_per_unit", 0.8))
    required_extra_pwm_by_factory = {
        factory_id: min(80.0, units * inbound_pwm_per_unit)
        for factory_id, units in inbound_units_by_factory.items()
    }
    required_pwm_total = min(
        100.0 * len(sensor_states),
        sum((20.0 + required_extra_pwm_by_factory.get(int(factory["factory_id"]), 0.0)) for factory in sensor_states),
    )

    problem = pulp.LpProblem("midas_job_a_slot_optimization", pulp.LpMinimize)
    on: dict[int, pulp.LpVariable] = {}
    pwm: dict[int, pulp.LpVariable] = {}
    pwm_dev: dict[int, pulp.LpVariable] = {}
    desired_pwm_by_factory: dict[int, float] = {}
    temp_gap_by_factory: dict[int, float] = {}

    for factory in sensor_states:
        factory_id = int(factory["factory_id"])
        on[factory_id] = pulp.LpVariable(f"on_{factory_id}", lowBound=0, upBound=1, cat="Binary")
        pwm[factory_id] = pulp.LpVariable(f"pwm_{factory_id}", lowBound=0, upBound=100, cat="Continuous")
        # 동적 스케줄링에서는 자동 OFF를 허용하지 않고 ON/COASTING만 운용한다.
        problem += on[factory_id] == 1, f"dynamic_force_on_{factory_id}"
        problem += pwm[factory_id] <= 100 * on[factory_id], f"pwm_on_link_{factory_id}"
        # on=1인데 pwm=0이 되는 해를 방지하여 가동 의미를 보장한다.
        problem += pwm[factory_id] >= 20 * on[factory_id], f"min_pwm_when_on_{factory_id}"
        required_extra_pwm = required_extra_pwm_by_factory.get(factory_id, 0.0)
        if required_extra_pwm > 0:
            # 입고량을 냉각 필요량으로 변환해 공장별 PWM 하한에 반영한다.
            problem += (
                pwm[factory_id] >= (20.0 + required_extra_pwm) * on[factory_id],
                f"inbound_cooling_min_pwm_{factory_id}",
            )

        status = str(factory.get("status", ""))
        # WARNING 공장은 회복 우선: 강제 ON + 최소 PWM
        if status == "WARNING":
            problem += on[factory_id] == 1, f"warning_force_on_{factory_id}"
            problem += pwm[factory_id] >= 70, f"warning_min_pwm_{factory_id}"

        # 연속 패널티용 목표 PWM(온도 오차 + 외기 리스크 반영)
        desired_pwm, temp_gap = _desired_pwm_from_temp(factory, w_temp)
        desired_pwm_by_factory[factory_id] = desired_pwm
        temp_gap_by_factory[factory_id] = temp_gap
        pwm_dev[factory_id] = pulp.LpVariable(
            f"pwm_temp_dev_{factory_id}",
            lowBound=0,
            upBound=100,
            cat="Continuous",
        )
        # pwm_dev >= |pwm - desired_pwm| (L1 절댓값 선형화)
        problem += pwm_dev[factory_id] >= pwm[factory_id] - desired_pwm, f"pwm_dev_pos_{factory_id}"
        problem += pwm_dev[factory_id] >= desired_pwm - pwm[factory_id], f"pwm_dev_neg_{factory_id}"

    # L1 기반 최소 가동 공장 수
    problem += pulp.lpSum(on.values()) >= min_active, "min_active_factories"
    # 공장별 입고량 기반 PWM 하한을 합산한 전체 안전 하한
    problem += pulp.lpSum(pwm.values()) >= required_pwm_total, "inbound_heat_buffer_pwm"

    # 비용 최소화 + 태양광 기여 반영 + 폭염 시 냉각 부족 페널티
    # (0.5h 슬롯 기준: kWh ~= PWM% * 0.02로 단순화)
    slot_kwh_per_pwm = 0.02
    cost_term = pulp.lpSum(pwm[fid] * slot_kwh_per_pwm * tou_price for fid in pwm)
    solar_credit_term = pulp.lpSum(
        pwm[fid] * slot_kwh_per_pwm * (solar_kwh * w_solar * 0.1) for fid in pwm
    )
    thermal_penalty_term = pulp.lpSum((100 - pwm[fid]) * max(0.0, w_temp - 1.0) * 0.02 for fid in pwm)
    inbound_penalty_weight = max(0.0, inbound_units_this_slot) * 0.03
    inbound_penalty_term = pulp.lpSum((100 - pwm[fid]) * inbound_penalty_weight * 0.01 for fid in pwm)
    temp_tracking_penalty_weight = float(env_weights.get("temp_tracking_penalty_weight", 1.2))
    temp_tracking_penalty_term = pulp.lpSum(
        pwm_dev[fid] * temp_tracking_penalty_weight for fid in pwm_dev
    )
    problem += (
        cost_term
        - solar_credit_term
        + thermal_penalty_term
        + inbound_penalty_term
        + temp_tracking_penalty_term
    )

    objective_expression = (
        "Minimize [sum(pwm_i * 0.02 * tou_price)] "
        "- [sum(pwm_i * 0.02 * (solar_kwh * w_solar * 0.1))] "
        "+ [sum((100 - pwm_i) * max(0, w_temp-1.0) * 0.02)] "
        "+ [sum((100 - pwm_i) * inbound_penalty_weight * 0.01)] "
        "+ [sum(abs(pwm_i - desired_pwm_i) * temp_tracking_penalty_weight)]"
    )
    constraint_expressions = [
        "forall i: on_i = 1 (dynamic scheduling does not auto-OFF)",
        "forall i: pwm_i <= 100 * on_i",
        "forall i: pwm_i >= 20 * on_i",
        f"sum(on_i) >= {min_active}",
        f"sum(pwm_i) >= {required_pwm_total:.3f}",
        "forall i: pwm_temp_dev_i >= |pwm_i - desired_pwm_i|",
    ]
    for factory in sensor_states:
        factory_id = int(factory["factory_id"])
        required_extra_pwm = required_extra_pwm_by_factory.get(factory_id, 0.0)
        if required_extra_pwm > 0:
            constraint_expressions.append(
                f"factory {factory_id}: pwm_i >= {(20.0 + required_extra_pwm):.3f} * on_i (inbound cooling)"
            )
    for factory in sensor_states:
        if str(factory.get("status", "")) == "WARNING":
            factory_id = int(factory["factory_id"])
            constraint_expressions.append(f"factory {factory_id}: on_i = 1, pwm_i >= 70")

    solver = pulp.PULP_CBC_CMD(msg=False)
    status_code = problem.solve(solver)
    solver_status = str(pulp.LpStatus.get(status_code))
    if pulp.LpStatus.get(status_code) != "Optimal":
        # 해가 불능/비최적일 경우 보수적으로 기존 ON 성향을 유지
        blocks: list[dict[str, Any]] = []
        for factory in sensor_states:
            mode = "ON" if str(factory.get("status", "")) == "WARNING" else "COASTING"
            blocks.append(
                {
                    "factory_id": factory["factory_id"],
                    "start_at": now.isoformat(),
                    "end_at": horizon_end.isoformat(),
                    "mode": mode,
                    "target_temp_c": float(factory.get("target_temp_c", -18.0)),
                    "expected_grid_kwh": 3.0 if mode == "ON" else 1.0,
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
                "slot_kwh_per_pwm": slot_kwh_per_pwm,
                "min_active": min_active,
                "thermal_planning_hours": round(thermal_planning_hours, 3),
                "effective_planning_hours": round(effective_planning_hours, 3),
                "remaining_time_hours": round(remaining_time_hours, 3),
                "temp_tracking_penalty_weight": round(temp_tracking_penalty_weight, 4),
                "inbound_pwm_per_unit": round(inbound_pwm_per_unit, 4),
                "inbound_allocation_source": inbound_allocation_source,
            },
            "inbound_allocation": {
                str(fid): {
                    "slot_inbound_units": round(inbound_units_by_factory.get(fid, 0.0), 4),
                    "required_extra_pwm": round(required_extra_pwm_by_factory.get(fid, 0.0), 4),
                }
                for fid in sorted(inbound_units_by_factory.keys())
            },
        }
        return blocks

    blocks: list[dict[str, Any]] = []
    variable_values: dict[str, dict[str, float]] = {}
    total_cost_term = 0.0
    total_solar_credit_term = 0.0
    total_thermal_penalty_term = 0.0
    total_inbound_penalty_term = 0.0
    total_temp_tracking_penalty_term = 0.0
    for factory in sensor_states:
        factory_id = int(factory["factory_id"])
        on_val = float(pulp.value(on[factory_id]) or 0.0)
        pwm_val = float(pulp.value(pwm[factory_id]) or 0.0)
        variable_values[str(factory_id)] = {
            "on": round(on_val, 4),
            "pwm": round(pwm_val, 4),
        }
        total_cost_term += pwm_val * slot_kwh_per_pwm * tou_price
        total_solar_credit_term += pwm_val * slot_kwh_per_pwm * (solar_kwh * w_solar * 0.1)
        total_thermal_penalty_term += (100 - pwm_val) * max(0.0, w_temp - 1.0) * 0.02
        total_inbound_penalty_term += (100 - pwm_val) * inbound_penalty_weight * 0.01
        desired_pwm = desired_pwm_by_factory.get(factory_id, 20.0)
        total_temp_tracking_penalty_term += abs(pwm_val - desired_pwm) * temp_tracking_penalty_weight
        if pwm_val < 35:
            mode = "COASTING"
            grid_kwh = pwm_val * slot_kwh_per_pwm
            reason = "PEAK_AVOID"
        else:
            mode = "ON"
            grid_kwh = pwm_val * slot_kwh_per_pwm
            reason = "TEMP_RECOVERY" if str(factory.get("status", "")) == "WARNING" else "BASE_LOAD"

        blocks.append(
            {
                "factory_id": factory_id,
                "start_at": now.isoformat(),
                "end_at": horizon_end.isoformat(),
                "mode": mode,
                "target_temp_c": float(factory.get("target_temp_c", -18.0)),
                "expected_grid_kwh": round(max(0.0, grid_kwh), 3),
                "expected_solar_kwh": round(max(0.0, solar_kwh * w_solar), 3),
                "reason": reason,
                "pwm_pct": round(max(0.0, min(100.0, pwm_val)), 1),
                "on_value": round(on_val, 3),
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
            "thermal_penalty_term": round(total_thermal_penalty_term, 6),
            "inbound_penalty_term": round(total_inbound_penalty_term, 6),
            "temp_tracking_penalty_term": round(total_temp_tracking_penalty_term, 6),
            "objective_value": round(
                total_cost_term
                - total_solar_credit_term
                + total_thermal_penalty_term
                + total_inbound_penalty_term,
                # 온도 추종 연속 패널티를 포함한 최종 목적함수 값
                6,
            ),
            "objective_value_with_temp_tracking": round(
                total_cost_term
                - total_solar_credit_term
                + total_thermal_penalty_term
                + total_inbound_penalty_term
                + total_temp_tracking_penalty_term,
                6,
            ),
        },
        "temperature_tracking": {
            str(fid): {
                "desired_pwm": round(desired_pwm_by_factory.get(fid, 20.0), 3),
                "temp_gap_c": round(temp_gap_by_factory.get(fid, 0.0), 3),
            }
            for fid in sorted(desired_pwm_by_factory.keys())
        },
        "inbound_allocation": {
            str(fid): {
                "slot_inbound_units": round(inbound_units_by_factory.get(fid, 0.0), 4),
                "required_extra_pwm": round(required_extra_pwm_by_factory.get(fid, 0.0), 4),
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
            "slot_kwh_per_pwm": slot_kwh_per_pwm,
            "min_active": min_active,
            "thermal_planning_hours": round(thermal_planning_hours, 3),
            "effective_planning_hours": round(effective_planning_hours, 3),
            "remaining_time_hours": round(remaining_time_hours, 3),
            "inbound_units_this_slot": round(inbound_units_this_slot, 3),
            "required_pwm_total": round(required_pwm_total, 3),
            "temp_tracking_penalty_weight": round(temp_tracking_penalty_weight, 4),
            "inbound_pwm_per_unit": round(inbound_pwm_per_unit, 4),
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
