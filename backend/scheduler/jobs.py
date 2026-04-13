"""APScheduler background jobs for MIDAS backend.

현재 단계는 데모 중심이며, Job A(30분 주기 최적화) 중심으로 동작한다.
DB/MQTT/실예측이 없는 환경에서도 더미 데이터로 1회 실행 검증이 가능하도록
폴백 로직을 포함한다.
"""

# -----------------------------------------------------------------------------
# [원본 설계 주석 - 보존]
# backend/scheduler/jobs.py
# APScheduler 백그라운드 작업 정의
#
# - get_scheduler() : BackgroundScheduler 인스턴스 반환 (싱글턴)
#
# [Job A] 30분 주기 최적화  (cron: */30 * * * *)
#   1. 현재 활성 job 조회 (없으면 skip)
#   2. 잔여 생산량 R = Q_total - Q_completed 계산
#   3. 현재 TOU 요금 조회
#   4. 공장별 센서 상태 조회 (manual_stop 공장 제외)
#   5. 태양광 예측값 + 환경 가중치(w_solar) 반영
#   6. PuLP 선형 계획법으로 스케줄 최적화 (optimization_service)
#      - 목적함수: Minimize Σ(Grid_Power[t] × TOU_Price[t]) - (Solar_Predicted[t] × w_solar)
#      - 제약: 내부 온도 -18°C 초과 금지, Short Cycle 30분 준수, 생산량 마감 보장
#   7. schedules 테이블 저장
#   8. MQTT 명령 발행 (publisher.publish_schedule)
#   9. schedule_logs 기록
#
# [Job B] 매일 18시 환경 가중치 갱신  (cron: 0 18 * * *)
#   1. 기상청 API 호출 (httpx.AsyncClient) → 다음날 최고기온 / 일사량
#   2. w_temp = f(최고기온) : 폭염이면 1.2, 평년이면 1.0
#   3. w_solar = f(날씨코드) : 맑음 1.0 / 흐림 0.5 / 비 0.2
#   4. environment_weights 테이블 저장
#   5. 야간 축냉 목표 온도 재계산 (폭염 → -27°C, 평년 → -25°C)
#
# [Job C] 1분 주기 알림 감시  (cron: */1 * * * *)
#   1. 최신 sensor_logs에서 온도 이탈 감지 (임계값 ±2°C)
#   2. last_seen_at 기준 통신 timeout 감지 (30초 초과 시 DISCONNECTED)
#   3. 중복 알림 window 확인 (300초 내 동일 factory + type 중복 차단)
#   4. Telegram 발송 (alert_service.send_telegram)
#   5. alerts 테이블 기록
#
# [현재 구현 매핑]
# - Job A 본체: run_job_a_optimization()
#   - 1~5번 입력 조합: _active_job / _available_factories / get_tou_price /
#                      _solar_forecast_for_horizon
#   - 6번 최적화 호출: _run_optimization_with_fallback()
#   - 7~9번 결과 처리: run_job_a_optimization()의 result/log 구간
# - Job B/C: run_job_b_update_environment_weights(), run_job_c_monitor_alerts()
#   (현재 스텁, 후속 구현 대상)
# -----------------------------------------------------------------------------

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import importlib
import json
from pathlib import Path
from typing import Any

try:
    _aps_module = importlib.import_module("apscheduler.schedulers.background")
    BackgroundScheduler = _aps_module.BackgroundScheduler
except Exception:  # pragma: no cover - optional dependency fallback
    BackgroundScheduler = None

DEFAULT_DUMMY_DATA_PATH = (
    Path(__file__).resolve().parents[1] / "database" / "dummy_data.jsonc"
)

_SCHEDULER: Any | None = None
_LAST_JOB_A_RESULT: dict[str, Any] | None = None
_JOB_A_LOGS: list[dict[str, Any]] = []


@dataclass
class JobAContext:
    """Job A 최적화 1회 실행에 필요한 입력 스냅샷을 묶는다."""

    now: datetime
    active_job: dict[str, Any]
    factories: list[dict[str, Any]]
    tou_price: float
    tou_slots: list[dict[str, Any]]
    env_weights: dict[str, Any]
    solar_forecast: list[dict[str, Any]]
    outdoor_temp_forecast: list[dict[str, Any]]


class _FallbackScheduler:
    """APScheduler 미설치 환경용 최소 대체 스케줄러."""

    def __init__(self) -> None:
        self._jobs: list[dict[str, Any]] = []
        self._running = False

    def add_job(
        self,
        func: Any,
        trigger: str,
        minute: str,
        id: str,
        replace_existing: bool = True,
    ) -> None:
        """크론 트리거 Job 메타데이터를 내부 목록에 등록한다."""
        if replace_existing:
            self._jobs = [job for job in self._jobs if job["id"] != id]
        self._jobs.append(
            {
                "id": id,
                "func": func,
                "trigger": trigger,
                "minute": minute,
            }
        )

    def get_jobs(self) -> list[dict[str, Any]]:
        """등록된 Job 메타데이터 목록을 반환한다."""
        return list(self._jobs)

    def start(self) -> None:
        """폴백 스케줄러를 '실행 중' 상태로 표시한다."""
        self._running = True

    def shutdown(self, wait: bool = False) -> None:  # noqa: ARG002
        """폴백 스케줄러를 중지 상태로 표시한다."""
        self._running = False


def _strip_jsonc_comments(text: str) -> str:
    """JSONC에서 // 주석만 제거한다 (문자열 내부는 유지)."""
    out: list[str] = []
    in_string = False
    escaped = False
    i = 0
    n = len(text)

    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""

        if in_string:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            i += 1
            continue

        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue

        if ch == "/" and nxt == "/":
            while i < n and text[i] not in "\r\n":
                i += 1
            continue

        out.append(ch)
        i += 1

    return "".join(out)


def load_dummy_data(path: Path = DEFAULT_DUMMY_DATA_PATH) -> dict[str, Any]:
    """JSONC 형식 더미 데이터를 로드해 dict로 반환한다."""
    raw = path.read_text(encoding="utf-8")
    clean = _strip_jsonc_comments(raw)
    return json.loads(clean)


def _parse_iso(dt_str: str | None) -> datetime | None:
    """ISO 8601 문자열을 datetime으로 파싱한다 (없으면 None)."""
    if not dt_str:
        return None
    return datetime.fromisoformat(dt_str)


def _resolve_now(data: dict[str, Any], now: datetime | None = None) -> datetime:
    """주어진 now 또는 더미의 dashboard_summary.current_time 기준으로 기준 시각을 정한다."""
    if now is not None:
        return now
    summary_now = (
        data.get("dashboard_summary", {}).get("current_time")
        if isinstance(data.get("dashboard_summary"), dict)
        else None
    )
    parsed = _parse_iso(summary_now)
    return parsed or datetime.now()


def _hour_in_slot(hour: int, start: int, end: int) -> bool:
    """시(hour)가 TOU 슬롯(start_hour~end_hour)에 속하는지 판정한다."""
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def get_tou_price(now: datetime, pricing_tou: dict[str, Any]) -> float:
    """현재 시각에 해당하는 TOU 단가(원/kWh)를 계산한다."""
    hour = now.hour
    for slot in pricing_tou.get("slots", []):
        start = int(slot.get("start_hour", 0))
        end = int(slot.get("end_hour", 0))
        if _hour_in_slot(hour, start, end):
            return float(slot.get("price", 0))
    return float(pricing_tou.get("current_price_krw_per_kwh", 0))


def _active_job(data: dict[str, Any]) -> dict[str, Any] | None:
    """더미 데이터에서 활성화된 동적 스케줄링 Job 1건을 찾는다."""
    for job in data.get("jobs", []):
        if job.get("is_active") and job.get("dynamic_scheduling_enabled", True):
            return job
    return None


def _available_factories(data: dict[str, Any]) -> list[dict[str, Any]]:
    """manual_stop이 아닌 공장들만 골라 가동 후보 공장 목록을 만든다."""
    result: list[dict[str, Any]] = []
    for factory in data.get("factories", []):
        if factory.get("manual_stop"):
            continue
        result.append(factory)
    return result


def _solar_forecast_for_horizon(
    data: dict[str, Any],
    now: datetime,
    deadline: datetime | None,
) -> list[dict[str, Any]]:
    """현재 시각부터 deadline까지 구간에 해당하는 태양광 예측 행들을 필터링한다."""
    if deadline is None:
        deadline = now + timedelta(hours=24)
    rows: list[dict[str, Any]] = []
    for row in data.get("predict_solar", []):
        ts = _parse_iso(row.get("timestamp"))
        if ts is None:
            continue
        if now <= ts <= deadline:
            rows.append(row)
    return rows


def _outdoor_temp_forecast_for_horizon(
    data: dict[str, Any],
    now: datetime,
    deadline: datetime | None,
) -> list[dict[str, Any]]:
    """현재 시각부터 deadline까지 구간의 시간대별 외기온 예측 행을 필터링한다."""
    if deadline is None:
        deadline = now + timedelta(hours=24)
    rows: list[dict[str, Any]] = []
    for row in data.get("predict_outdoor_temp_hourly", []):
        ts = _parse_iso(row.get("timestamp"))
        if ts is None:
            continue
        if now <= ts <= deadline:
            rows.append(row)
    return rows


def _planned_inbound_by_factory(
    data: dict[str, Any],
    job_id: str | None,
    available_factory_ids: set[int],
) -> dict[int, float]:
    """더미의 production_allocations에서 공장별 입고 총량 계획을 읽어온다."""
    if not job_id:
        return {}
    result: dict[int, float] = {}
    for row in data.get("production_allocations", []):
        if not isinstance(row, dict):
            continue
        if str(row.get("job_id")) != str(job_id):
            continue
        try:
            factory_id = int(row.get("factory_id"))
        except (TypeError, ValueError):
            continue
        if factory_id not in available_factory_ids:
            continue
        planned_units = float(row.get("planned_inbound_units_until_deadline", 0.0) or 0.0)
        result[factory_id] = max(0.0, planned_units)
    return result


def _planned_shipment_by_factory(
    data: dict[str, Any],
    job_id: str | None,
    available_factory_ids: set[int],
) -> dict[int, float]:
    """더미의 shipment_allocations에서 공장별 출고 총량 계획을 읽어온다."""
    if not job_id:
        return {}
    result: dict[int, float] = {}
    for row in data.get("shipment_allocations", []):
        if not isinstance(row, dict):
            continue
        if str(row.get("job_id")) != str(job_id):
            continue
        try:
            factory_id = int(row.get("factory_id"))
        except (TypeError, ValueError):
            continue
        if factory_id not in available_factory_ids:
            continue
        planned_units = float(row.get("planned_shipment_units_until_deadline", 0.0) or 0.0)
        result[factory_id] = max(0.0, planned_units)
    return result


def _door_open_count_by_factory(
    data: dict[str, Any],
    now: datetime,
    horizon_end: datetime,
    available_factory_ids: set[int],
) -> dict[int, int]:
    """현재 슬롯(now~horizon_end)의 공장별 문열림 횟수를 집계한다."""
    counts = {factory_id: 0 for factory_id in available_factory_ids}
    for row in data.get("door_open_events", []):
        if not isinstance(row, dict):
            continue
        ts = _parse_iso(row.get("timestamp"))
        if ts is None or not (now <= ts < horizon_end):
            continue
        try:
            factory_id = int(row.get("factory_id"))
        except (TypeError, ValueError):
            continue
        if factory_id not in counts:
            continue
        counts[factory_id] += 1
    return counts


def _heuristic_blocks(ctx: JobAContext) -> list[dict[str, Any]]:
    """PuLP 미구현 시 데모용으로 간단한 휴리스틱 스케줄 블록을 생성한다."""
    blocks: list[dict[str, Any]] = []
    active_deadline = _parse_iso(ctx.active_job.get("deadline_at"))
    end = active_deadline if active_deadline and active_deadline > ctx.now else ctx.now + timedelta(hours=1)
    for factory in ctx.factories:
        mode = "ON"
        reason = "BASE_LOAD"
        status = str(factory.get("status", ""))
        if status == "WARNING":
            mode = "ON"
            reason = "TEMP_RECOVERY"
        elif ctx.tou_price >= 180:
            mode = "COASTING"
            reason = "PEAK_AVOID"
        solar_bonus = 0.0
        if ctx.solar_forecast:
            solar_bonus = float(ctx.solar_forecast[0].get("predicted_solar_kwh", 0.0))
        blocks.append(
            {
                "factory_id": factory.get("factory_id"),
                "start_at": ctx.now.isoformat(),
                "end_at": end.isoformat(),
                "mode": mode,
                "target_temp_c": float(factory.get("target_temp_c", -18.0)),
                "expected_grid_kwh": 1.0 if mode == "COASTING" else 3.0,
                "expected_solar_kwh": max(0.0, solar_bonus * float(ctx.env_weights.get("w_solar", 1.0))),
                "reason": reason,
            }
        )
    return blocks


def _run_optimization_with_fallback(ctx: JobAContext) -> list[dict[str, Any]]:
    """optimization_service.run_optimization이 있으면 호출하고, 없으면 휴리스틱으로 대체한다."""
    try:
        from backend.services import optimization_service  # type: ignore
    except Exception:
        optimization_service = None  # type: ignore

    if optimization_service and hasattr(optimization_service, "run_optimization"):
        return optimization_service.run_optimization(  # type: ignore[no-any-return]
            job=ctx.active_job,
            sensor_states=ctx.factories,
            tou_prices=ctx.tou_slots,
            env_weights=ctx.env_weights,
            solar_forecast=ctx.solar_forecast,
            outdoor_temp_forecast=ctx.outdoor_temp_forecast,
            now=ctx.now,
        )
    return _heuristic_blocks(ctx)


def run_job_a_optimization(
    *,
    now: datetime | None = None,
    data_path: Path = DEFAULT_DUMMY_DATA_PATH,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Job A: 30분 주기 최적화 1회 실행 (더미 또는 실제 데이터를 기반으로 스케줄 계산)."""
    global _LAST_JOB_A_RESULT

    data = load_dummy_data(data_path)
    resolved_now = _resolve_now(data, now=now)
    active_job = _active_job(data)
    if active_job is None:
        result = {
            "success": True,
            "skipped": True,
            "reason": "NO_ACTIVE_JOB",
            "computed_at": resolved_now.isoformat(),
            "schedule_blocks": [],
        }
        _LAST_JOB_A_RESULT = result
        _JOB_A_LOGS.append(result)
        return result

    factories = _available_factories(data)
    pricing_tou = data.get("pricing_tou", {})
    tou_price = get_tou_price(resolved_now, pricing_tou)
    deadline = _parse_iso(active_job.get("deadline_at"))
    env_weights = data.get("environment_weights", {})
    solar_forecast = _solar_forecast_for_horizon(data, resolved_now, deadline)
    outdoor_temp_forecast = _outdoor_temp_forecast_for_horizon(data, resolved_now, deadline)

    available_factory_ids = {int(factory.get("factory_id")) for factory in factories if "factory_id" in factory}
    planned_inbound_by_factory = _planned_inbound_by_factory(
        data,
        active_job.get("job_id"),
        available_factory_ids,
    )
    planned_shipment_by_factory = _planned_shipment_by_factory(
        data,
        active_job.get("job_id"),
        available_factory_ids,
    )
    slot_end = resolved_now + timedelta(minutes=30)
    door_open_count_by_factory = _door_open_count_by_factory(
        data=data,
        now=resolved_now,
        horizon_end=slot_end,
        available_factory_ids=available_factory_ids,
    )
    optimization_job = dict(active_job)
    if planned_inbound_by_factory:
        optimization_job["planned_inbound_by_factory"] = {
            str(factory_id): units for factory_id, units in planned_inbound_by_factory.items()
        }
    if planned_shipment_by_factory:
        optimization_job["planned_shipment_by_factory"] = {
            str(factory_id): units for factory_id, units in planned_shipment_by_factory.items()
        }
    if door_open_count_by_factory:
        optimization_job["door_open_count_by_factory"] = {
            str(factory_id): count for factory_id, count in door_open_count_by_factory.items()
        }

    ctx = JobAContext(
        now=resolved_now,
        active_job=optimization_job,
        factories=factories,
        tou_price=tou_price,
        tou_slots=pricing_tou.get("slots", []),
        env_weights=env_weights,
        solar_forecast=solar_forecast,
        outdoor_temp_forecast=outdoor_temp_forecast,
    )
    blocks = _run_optimization_with_fallback(ctx)
    optimization_debug: dict[str, Any] | None = None
    try:
        from backend.services import optimization_service  # type: ignore

        if hasattr(optimization_service, "get_last_optimization_debug"):
            optimization_debug = optimization_service.get_last_optimization_debug()  # type: ignore[assignment]
    except Exception:
        optimization_debug = None

    target_units = int(active_job.get("target_units", 0))
    produced_units = int(active_job.get("produced_units", 0))
    remaining_units = max(0, target_units - produced_units)
    result = {
        "success": True,
        "skipped": False,
        "computed_at": resolved_now.isoformat(),
        "job_id": active_job.get("job_id"),
        "tou_price_krw_per_kwh": tou_price,
        "remaining_units": remaining_units,
        "factory_count": len(factories),
        "schedule_blocks": blocks,
        "applied": not dry_run,
    }
    if optimization_debug:
        result["optimization_debug"] = optimization_debug

    # 데모 단계: dry_run=False일 때만 추후 MQTT 발행 지점으로 사용
    if not dry_run:
        result["publish_status"] = "PENDING_MQTT_INTEGRATION"

    _LAST_JOB_A_RESULT = result
    _JOB_A_LOGS.append(result)
    return result


def run_job_b_update_environment_weights() -> dict[str, Any]:
    """Job B 스텁: 환경 가중치 갱신 작업 자리(현재는 미구현)."""
    return {"success": True, "skipped": True, "reason": "NOT_IMPLEMENTED"}


def run_job_c_monitor_alerts() -> dict[str, Any]:
    """Job C 스텁: 온도 이탈·알림 감시 작업 자리(현재는 미구현)."""
    return {"success": True, "skipped": True, "reason": "NOT_IMPLEMENTED"}


def get_scheduler() -> Any:
    """BackgroundScheduler(또는 폴백 스케줄러) 인스턴스를 싱글턴으로 반환한다."""
    global _SCHEDULER
    if _SCHEDULER is None:
        if BackgroundScheduler is None:
            _SCHEDULER = _FallbackScheduler()
        else:
            _SCHEDULER = BackgroundScheduler(timezone="Asia/Seoul")
    return _SCHEDULER


def configure_scheduler_jobs() -> Any:
    """현재 단계에서는 Job A(30분 주기)만 스케줄러에 등록한다."""
    scheduler = get_scheduler()
    scheduler.add_job(
        run_job_a_optimization,
        trigger="cron",
        minute="*/30",
        id="job_a_optimization",
        replace_existing=True,
    )
    return scheduler


def get_last_job_a_result() -> dict[str, Any] | None:
    """마지막 Job A 실행 결과를 메모리에서 반환한다."""
    return _LAST_JOB_A_RESULT


def get_job_a_logs(limit: int = 20) -> list[dict[str, Any]]:
    """최근 Job A 실행 로그를 최대 limit개까지 반환한다."""
    if limit <= 0:
        return []
    return _JOB_A_LOGS[-limit:]
