# FEMS-MIDAS

공장 에너지 관리 시스템 (Factory Energy Management System)

---

## 구조

```
RPi5 (Edge)          로컬 PC (Backend)         Supabase
────────────         ─────────────────         ────────
센서 읽기        →   MQTT 구독 + API 서버   →   PostgreSQL DB
MQTT 발행            FastAPI + SQLAlchemy
```

---

## 사전 준비

### 공통
- Python 3.9 이상
- `.env.example`을 `.env`로 복사 후 값 채우기
- Supabase DB 비밀번호는 팀장에게 문의

### 백엔드 PC 추가 설치
- [Mosquitto MQTT 브로커](https://mosquitto.org/download/) 설치 후 서비스 시작
  ```bash
  net start mosquitto   # Windows (관리자 권한)
  ```

---

## 실행 방법

### 백엔드 (로컬 PC)

```bash
# 프로젝트 루트에서 실행
cd backend
python -m venv venv
venv\Scripts\activate      # Windows
# source venv/bin/activate  # Linux/Mac
pip install -r requirements.txt
cd ..
python -m uvicorn backend.main:app --reload
```

### Edge (RPi5)

```bash
# RPi5에서 실행
git clone https://github.com/ehdrms3535/FEMS-MIDAS.git
cd FEMS-MIDAS
pip install -r edge/requirements.txt

# .env 설정 (MQTT_HOST = 백엔드 PC의 로컬 IP)
cp .env.example .env
nano .env

python edge/main.py
```

---

## .env 설정 항목

| 항목 | 백엔드 PC | RPi5 |
|---|---|---|
| `DATABASE_URL` | Supabase 연결 문자열 | 불필요 |
| `MQTT_HOST` | `localhost` | 백엔드 PC의 로컬 IP (예: `192.168.0.10`) |
| `MQTT_PORT` | `1883` | `1883` |
| `NODE_ID` | 불필요 | `node_A` 또는 `node_B` |
| `FACTORY_IDS` | 불필요 | `1,2` 또는 `3,4` |

---

## 로컬 PC IP 확인 방법 (Windows)

```bash
ipconfig
# IPv4 Address 항목 확인
```
