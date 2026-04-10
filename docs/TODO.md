# FEMS-MIDAS 개발 현황 및 남은 작업

## 완료된 것
- Supabase DB 연결
- sensor_logs 테이블
- MQTT 브로커 (Mosquitto)
- 백엔드 MQTT 구독자
- DHT22 센서 → MQTT → Supabase 저장
- Edge MQTT 클라이언트
- .gitignore, README
- QR 조회 API

---

## 백엔드

### 필수

- [ ] **DB 모델 추가**
  - `factories` : 공장별 현재 상태 (factory_id, name, status, last_seen_at, current_temp, current_humidity)
  - `alerts` : 알림 이력 (factory_id, level, message, triggered_at, ack_at)
  - `schedules` : 스케줄 블록 (factory_id, start_at, end_at, mode, target_temp)
  - `jobs` : 작업 등록 (factory_id, target_units, deadline_at, strategy, status)

- [ ] **factories 최신 상태 업데이트**
  - MQTT 수신 시 `sensor_logs` INSERT + `factories` 현재 온도/습도/last_seen_at UPDATE
  - `backend/mqtt/subscriber.py`에서 처리

- [ ] **센서 조회 API**
  - `GET /api/v1/sensors/live` : 공장별 최신 데이터 1건
  - `GET /api/v1/sensors/history` : 기간/공장/interval 기반 시계열 조회
  - `backend/routers/sensors.py` 구현

- [ ] **대시보드 API**
  - `GET /api/v1/dashboard` : 전체 공장 요약 (상태, 현재 온도, 알림 수, 통신 상태)
  - `backend/routers/dashboard.py` 구현

- [ ] **알림 서비스**
  - 온도/습도 임계값 초과 감지 (MQTT 수신 시마다 체크)
  - Telegram Bot API로 메시지 발송
  - `alerts` 테이블에 이력 저장
  - `backend/services/alert_service.py` 구현

- [ ] **통신 상태 API**
  - `GET /api/v1/system/status` : 공장별 last_seen_at 기준
    - 10초 이내: OK
    - 10~30초: DELAYED
    - 30초 초과: DISCONNECTED
  - `backend/routers/system.py` 구현

- [ ] **CORS 설정**
  - `backend/main.py`에 CORSMiddleware 추가
  - Streamlit 프론트 연결 시 필요

- [ ] **백엔드 → RPi 제어 명령 (MQTT publisher)**
  - `POST /api/v1/control/manual` : 수동 제어 명령 발행
  - 토픽: `factory/{node_id}/{factory_id}/command`
  - payload: `{action: SET_PWM, value: 80}` 등
  - `backend/mqtt/publisher.py` 구현
  - `backend/routers/control.py` 구현

---

### 추가하면 좋은 것

- [ ] **WebSocket**
  - `WS /ws/live-data` : 실시간 센서 데이터 push
  - 프론트에서 polling 없이 실시간 갱신 가능

- [ ] **시간별 집계 테이블**
  - raw 5초 데이터를 1분/1시간 평균으로 미리 집계
  - 차트 조회 속도 향상

- [ ] **이상 감지**
  - 5분 내 온도 급변 (예: 5°C 이상) 자동 감지
  - 센서 연속 실패 3회 이상 시 점검 알림

- [ ] **데이터 정리 스케줄러**
  - 90일 이상 된 `sensor_logs` 자동 삭제
  - APScheduler로 매일 새벽 실행

- [ ] **CSV 내보내기 API**
  - `GET /api/v1/sensors/export` : 기간별 데이터 CSV 다운로드

- [ ] **에너지 리포트 자동 생성**
  - 주간/월간 평균 온도, 알림 횟수, 추정 전기요금 집계
  - 매주 월요일 Telegram으로 자동 발송

- [ ] **최적화 전후 비교**
  - 스케줄 적용 전후 전기요금 절감액 계산
  - "이 시스템으로 X% 절감" 수치 제시

- [ ] **API 요청 로깅**
  - 누가 언제 어떤 API 호출했는지 기록

---

### 외부 API 연동

- [x] **기상청 API**
  - 외부 온도/날씨 데이터 수집
  - `GET /api/v1/weather/today`, `GET /api/v1/weather/tomorrow`
  - `.env`에 `KMA_API_KEY`, `KMA_NX`, `KMA_NY` 설정

- [ ] **한전 전기요금 API**
  - 시간대별 전기요금 조회
  - 요금 싼 시간대 → PRECOOL, 비싼 시간대 → COASTING 자동 결정

- [ ] **탄소중립 포인트 API**
  - 에너지 절감량 → 탄소 저감량 계산
  - 발표 시 환경적 가치 수치로 제시 가능

---

## 하드웨어

### 바로 가능

- [ ] **공장 2번 DHT22 센서 (GPIO5)**
  - RPi4 GPIO5 (핀 29번)에 DHT22 + 10kΩ 풀업 저항 연결
  - `.env`에서 `FACTORY_IDS=1,2` 확인
  - `edge/sensors/dht22.py` GPIO_PIN_MAP에 2번 핀 추가

- [ ] **LED 상태 표시**
  - 초록 LED: GPIO17, 빨강 LED: GPIO27 (예시)
  - 330Ω 저항 직렬 연결
  - 정상: 초록, 임계값 초과: 빨강
  - `edge/controllers/led_controller.py` 구현

- [ ] **부저 알림** // 보류
  - GPIO 출력으로 제어
  - 임계값 초과 시 경보음
  - `edge/controllers/buzzer_controller.py` 구현

### 부품 오면

- [ ] **PWM 제어 장치 연결**
  - 냉각 팬/모터 RPi4에 연결
  - `edge/controllers/pwm_controller.py` 구현
  - 백엔드 명령 수신 시 듀티 사이클 조절

### 연동

- [ ] **백엔드 → RPi MQTT 명령 수신 처리**
  - `edge/communication/mqtt_client.py`의 `_on_message()`에서 action 분기 처리
  - SET_PWM, SET_TARGET_TEMP, START, STOP 등

- [ ] **임계값 초과 시 자동 LED/부저 제어**
  - 백엔드 알림 서비스 → MQTT 명령 발행 → RPi에서 LED/부저 동작
  - 정상 복귀 시 자동 해제

---

## 프론트엔드

- [ ] **메인 대시보드**
  - 공장별 현재 온도/습도/상태 카드
  - 통신 상태 표시
  - 대시보드 API 연결

- [ ] **센서 데이터 차트**
  - 시간대별 온도/습도 라인 차트
  - 공장별 필터링
  - history API 연결

- [ ] **알림 이력**
  - 알림 목록 + 확인 처리
  - alerts API 연결

- [ ] **수동 제어 화면**
  - 공장별 PWM 설정, 모드 변경
  - 제어 API 연결

- [x] **QR 조회** (완료)

---

## 발표 시연 시나리오 (5월 7일)

```
1. RPi → 실시간 센서 데이터 → Supabase 저장 (실시간으로 쌓이는 것 보여주기)
2. 임계값 낮춰서 초과 유도
   → Telegram 알림 전송
   → LED 빨강 켜짐 + 부저 경보
3. Swagger(/docs)에서 수동 제어 API 호출
   → RPi 즉시 반응 (LED, PWM)
4. 한전 요금 API 기반 전기요금 절감 수치 제시
```
