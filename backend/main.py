import asyncio
import sys
import os

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, os.path.dirname(__file__))

from fastapi import FastAPI
from sqlalchemy import text
from database.connection import engine, create_all_tables
from mqtt.subscriber import MQTTSubscriber

app = FastAPI()
mqtt_subscriber: MQTTSubscriber = None


@app.on_event("startup")
async def startup():
    global mqtt_subscriber

    # DB 테이블 생성
    await create_all_tables()

    # DB 연결 확인
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        print("✅ DB 연결 성공")
    except Exception as e:
        print(f"❌ DB 연결 실패: {e}")
        return

    # MQTT 구독 시작
    loop = asyncio.get_event_loop()
    mqtt_subscriber = MQTTSubscriber(loop)
    mqtt_subscriber.start()


@app.on_event("shutdown")
async def shutdown():
    if mqtt_subscriber:
        mqtt_subscriber.stop()
        print("MQTT 연결 종료")


@app.get("/health")
async def health():
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ok", "db": "connected"}
    except Exception as e:
        return {"status": "error", "db": str(e)}
