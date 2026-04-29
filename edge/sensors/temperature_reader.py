import board
import adafruit_dht
from datetime import datetime, timezone


class DHT22Reader:
    def __init__(self, factory_id: int, pin=board.D4):
        self.factory_id = factory_id
        self._device = adafruit_dht.DHT22(pin)

    def read(self) -> dict | None:
        try:
            measured_at = datetime.now(timezone.utc).isoformat()
            temperature = self._device.temperature
            humidity = self._device.humidity
            if temperature is None or humidity is None:
                return None
            return {
                "temperature_c": round(temperature, 2),
                "humidity_pct": round(humidity, 2),
                "measured_at": measured_at,
            }
        except RuntimeError as e:
            print(f"[DHT22] 공장 {self.factory_id} 읽기 오류: {e}")
            return None

    def close(self):
        self._device.exit()
