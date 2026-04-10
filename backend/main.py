import asyncio
import sys
import os

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, os.path.dirname(__file__))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from database.connection import engine, create_all_tables
from mqtt.subscriber import MQTTSubscriber
from routers.readonly import router as readonly_router
from routers.control import router as control_router
from routers.weather import router as weather_router

app = FastAPI()
mqtt_subscriber: MQTTSubscriber = None

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")
app.include_router(readonly_router)
app.include_router(control_router)
app.include_router(weather_router)

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse(os.path.join(os.path.dirname(__file__), "static", "favicon.ico"))

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
