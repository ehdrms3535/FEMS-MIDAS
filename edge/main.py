import os
import time
import signal
from dotenv import load_dotenv
from communication.mqtt_client import EdgeMQTTClient
from sensors.dht22 import DHT22Reader

load_dotenv()

NODE_ID = os.getenv("NODE_ID", "node_A")
FACTORY_IDS = [int(x) for x in os.getenv("FACTORY_IDS", "1,2").split(",")]
INTERVAL = 5  # 센서 읽기 주기 (초)

running = True


def handle_signal(sig, frame):
    global running
    print("종료 신호 수신, 안전 종료 중...")
    running = False


signal.signal(signal.SIGTERM, handle_signal)
signal.signal(signal.SIGINT, handle_signal)


def main():
    print(f"Edge 노드 시작: {NODE_ID}, 공장: {FACTORY_IDS}")

    mqtt = EdgeMQTTClient(NODE_ID, FACTORY_IDS)
    mqtt.connect()
    time.sleep(1)

    sensors = {fid: DHT22Reader(fid) for fid in FACTORY_IDS}

    try:
        while running:
            for factory_id in FACTORY_IDS:
                data = sensors[factory_id].read()
                if data:
                    mqtt.publish_telemetry(
                        factory_id,
                        data["temperature_c"],
                        data["humidity_pct"],
                    )
                else:
                    print(f"공장 {factory_id} 센서 읽기 실패, 건너뜀")
            time.sleep(INTERVAL)
    finally:
        for sensor in sensors.values():
            sensor.close()
        mqtt.disconnect()
        print("Edge 노드 종료 완료")


if __name__ == "__main__":
    main()
