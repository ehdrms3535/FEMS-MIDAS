import json
import os
import paho.mqtt.client as mqtt
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()


class EdgeMQTTClient:
    def __init__(self, node_id: str, factory_ids: list):
        self.node_id = node_id
        self.factory_ids = factory_ids
        self.client = mqtt.Client()
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    def connect(self):
        host = os.getenv("MQTT_HOST", "localhost")
        port = int(os.getenv("MQTT_PORT", 1883))
        self.client.connect(host, port)
        self.client.loop_start()
        print(f"MQTT 브로커 연결 중: {host}:{port}")

    def disconnect(self):
        self.client.loop_stop()
        self.client.disconnect()

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            print("브로커 연결 성공")
            for factory_id in self.factory_ids:
                topic = f"factory/{self.node_id}/{factory_id}/command"
                client.subscribe(topic)
                print(f"구독: {topic}")
        else:
            print(f"브로커 연결 실패: {rc}")

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
            print(f"명령 수신: {msg.topic} → {payload}")
        except Exception as e:
            print(f"명령 처리 오류: {e}")

    def publish_telemetry(self, factory_id: int, temperature_c: float, humidity_pct: float):
        payload = {
            "factory_id": factory_id,
            "node_id": self.node_id,
            "temperature_c": round(temperature_c, 2),
            "humidity_pct": round(humidity_pct, 2),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        topic = f"factory/{self.node_id}/{factory_id}/telemetry"
        self.client.publish(topic, json.dumps(payload), qos=1)
        print(f"발행: {topic} → temp={temperature_c}°C, humidity={humidity_pct}%")
