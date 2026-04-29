# backend/services/anomaly_service.py
# 이상 감지 판단 로직 

# - check_temperature_range(factory_id, current_temp)
#   온도 범위 이탈 감지
#   정상 범위: -22°C ~ -16°C (추후 변경 가능)
#   범위를 벗어나면 TEMP_RANGE_OUT 이상으로 판단 
#
# - check_temperature_spike(current_sensor_log, old_sensor_log)
#   온도 급변 감지
#   현재 로그와 최근 5분 구간 내 이전 로그의 온도 변화량이 5°C 이상이면 TEMP_SPIKE 이상으로 판단 
#
# - check_communication_timeout(factory_id)
#   센서/통신 이상 감지
#   factories.Last_seen_at 기준 일정 시간 이상 데이터 미수신 시 COMMUNICATION_TIMEOUT 판단
#
# - build_anomaly_result(factory_id, Level, anomaly_type, message)
#   alert_service.create_alert에서 사용할 수 있는 형태로 이상 감지 결과 생성
#

TEMP_MIN_C = -22.0
TEMP_MAX_C = -16.0
SPIKE_THRESHOLD_C = 5.0

def build_anomaly_result(factory_id, level, anomaly_type, message):
    return{
        "factory_id": factory_id,
        "level": level,
        "alert_type": anomaly_type,
        "message": message
    }

def check_temperature_range(sensor_log):
    factory_id = sensor_log["factory_id"]
    current_temp = sensor_log["temperature_c"]

    if current_temp < TEMP_MIN_C:
        return build_anomaly_result(
            factory_id,
            "WARNING",
            "TEMP_RANGE_OUT",
            f"{factory_id}번 공장 온도가 너무 낮습니다. 현재 온도: {current_temp}°C"
        )
    if current_temp > TEMP_MAX_C:
        return build_anomaly_result(
            factory_id,
            "WARNING",
            "TEMP_RANGE_OUT",
            f"{factory_id}번 공장 온도가 너무 높습니다. 현재 온도: {current_temp}°C"
        )

    return None

def check_temperature_spike(current_sensor_log, old_sensor_log):
    if old_sensor_log is None:
        return None
    
    factory_id = current_sensor_log["factory_id"]
    current_temp = current_sensor_log["temperature_c"]
    old_temp = old_sensor_log["temperature_c"]

    diff = abs(current_temp - old_temp)

    if diff >= SPIKE_THRESHOLD_C:
        return build_anomaly_result(
            factory_id,
            "WARNING",
            "TEMP_SPIKE",
            f"{factory_id}번 공장 온도가 최근 5분 구간 내 급변했습니다. "
            f"현재 온도: {current_temp}°C, "
            f"이전 온도: {old_temp}°C, "
            f"변화량: {diff:.2f}°C"
        )
    return None

# 임시 테스트용
if __name__ == "__main__":
    print("=== 온도 범위 테스트 ===")
    dummy_sensor_logs = [
        {"factory_id": 1, "temperature_c": -21.40},
        {"factory_id": 3, "temperature_c": -16.20},
        {"factory_id": 4, "temperature_c": -14.50},
    ]

    for sensor_log in dummy_sensor_logs:
        result = check_temperature_range(sensor_log)

        if result:
            print("이상 감지됨:", result)
        else:
            print("정상:", sensor_log)
    
    print("\n=== 온도 급변 테스트 ===")
    current_sensor_log = {
        "factory_id": 1,
        "temperature_c": -14.5,
        "measured_at": "2026-04-29T13:00:00",
    }

    old_sensor_log = {
        "factory_id": 1,
        "temperature_c": -20.0,
        "measured_at": "2026-04-29T12:56:00",
    }

    result = check_temperature_spike(current_sensor_log, old_sensor_log)

    if result:
        print("급변 감지됨:", result)
    else:
        print("급변 없음")