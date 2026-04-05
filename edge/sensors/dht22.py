import time

# GPIO 핀 매핑 (공장별)
GPIO_PIN_MAP = {
    1: 4,   # node_A 공장1 → GPIO 4
    2: 5,   # node_A 공장2 → GPIO 5
    3: 4,   # node_B 공장3 → GPIO 4
    4: 5,   # node_B 공장4 → GPIO 5
}


class DHT22Reader:
    def __init__(self, factory_id: int):
        self.factory_id = factory_id
        self.gpio_pin = GPIO_PIN_MAP[factory_id]
        self._sensor = None
        self._init_sensor()

    def _init_sensor(self):
        try:
            import board
            import adafruit_dht
            pin = getattr(board, f"D{self.gpio_pin}")
            self._sensor = adafruit_dht.DHT22(pin)
        except Exception as e:
            print(f"센서 초기화 실패 (factory={self.factory_id}): {e}")

    def read(self):
        if self._sensor is None:
            return None

        for attempt in range(3):
            try:
                temperature = self._sensor.temperature
                humidity = self._sensor.humidity
                if temperature is not None and humidity is not None:
                    return {
                        "temperature_c": round(temperature, 2),
                        "humidity_pct": round(humidity, 2),
                    }
            except RuntimeError:
                # DHT22는 간헐적으로 읽기 실패 → 재시도
                time.sleep(2)
            except Exception as e:
                print(f"센서 읽기 오류 (factory={self.factory_id}): {e}")
                return None

        print(f"센서 연속 실패 (factory={self.factory_id})")
        return None

    def close(self):
        if self._sensor:
            self._sensor.exit()
