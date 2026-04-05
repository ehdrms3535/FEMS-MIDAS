import json
import asyncio
import os
import paho.mqtt.client as mqtt
from database.connection import AsyncSessionLocal
from database.models import SensorLog


class MQTTSubscriber:
    def __init__(self, loop: asyncio.AbstractEventLoop):
        self.loop = loop
        self.client = mqtt.Client()
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    def start(self):
        host = os.getenv("MQTT_HOST", "localhost")
        port = int(os.getenv("MQTT_PORT", 1883))
        self.client.connect(host, port)
        self.client.loop_start()
        print(f"MQTT 구독 시작: {host}:{port}")

    def stop(self):
        self.client.loop_stop()
        self.client.disconnect()

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            print("MQTT 브로커 연결 성공")
            client.subscribe("factory/+/+/telemetry")
        else:
            print(f"MQTT 연결 실패: {rc}")

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
            asyncio.run_coroutine_threadsafe(self._save(payload), self.loop)
        except Exception as e:
            print(f"MQTT 메시지 처리 오류: {e}")

    async def _save(self, payload):
        try:
            async with AsyncSessionLocal() as session:
                log = SensorLog(
                    factory_id=payload["factory_id"],
                    node_id=payload.get("node_id"),
                    temperature_c=payload.get("temperature_c"),
                    humidity_pct=payload.get("humidity_pct"),
                )
                session.add(log)
                await session.commit()
                print(f"저장 완료: factory={payload['factory_id']}, "
                      f"temp={payload.get('temperature_c')}°C, "
                      f"humidity={payload.get('humidity_pct')}%")
        except Exception as e:
            print(f"DB 저장 오류: {e}")
