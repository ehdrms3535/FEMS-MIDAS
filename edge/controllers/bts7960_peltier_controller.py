"""BTS7960 H-bridge controller for a TEC1-12706 Peltier module.

Hardware split:
- BTS7960 drives the Peltier module.
- Adafruit AO3406 MOSFET driver switches the two cooling fans.
- Raspberry Pi GPIO uses BCM numbering.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal, Optional

import RPi.GPIO as GPIO


Direction = Literal["forward", "reverse"]


@dataclass(frozen=True)
class Bts7960PeltierPins:
    rpwm: int = 18
    lpwm: int = 19
    r_en: int = 20
    l_en: int = 21
    fan_mosfet: Optional[int] = 23


class Bts7960PeltierController:
    """Sequence fans and BTS7960 outputs for a Peltier cooling assembly."""

    def __init__(
        self,
        pins: Bts7960PeltierPins = Bts7960PeltierPins(),
        pwm_frequency_hz: int = 1000,
        fan_active_low: bool = False,
        fan_spinup_seconds: float = 2.0,
        fan_cooldown_seconds: float = 30.0,
        reverse_settle_seconds: float = 0.2,
    ) -> None:
        self.pins = pins
        self.pwm_frequency_hz = pwm_frequency_hz
        self.fan_active_low = fan_active_low
        self.fan_spinup_seconds = fan_spinup_seconds
        self.fan_cooldown_seconds = fan_cooldown_seconds
        self.reverse_settle_seconds = reverse_settle_seconds
        self._rpwm: Optional[GPIO.PWM] = None
        self._lpwm: Optional[GPIO.PWM] = None
        self._duty_cycle = 0.0
        self._direction: Direction = "forward"
        self._is_setup = False

    def setup(self) -> None:
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)

        for pin in (self.pins.rpwm, self.pins.lpwm, self.pins.r_en, self.pins.l_en):
            GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)

        if self.pins.fan_mosfet is not None:
            GPIO.setup(self.pins.fan_mosfet, GPIO.OUT, initial=self._fan_level(False))

        self._rpwm = GPIO.PWM(self.pins.rpwm, self.pwm_frequency_hz)
        self._lpwm = GPIO.PWM(self.pins.lpwm, self.pwm_frequency_hz)
        self._rpwm.start(0)
        self._lpwm.start(0)
        self._is_setup = True

    def start(self, duty_cycle: float, direction: Direction = "forward") -> None:
        self._require_setup()
        self.set_fans(True)
        time.sleep(self.fan_spinup_seconds)
        self.enable_bridge(True)
        self.set_drive(duty_cycle, direction)

    def stop(self, keep_fans_running: bool = True) -> None:
        self._require_setup()
        self.set_drive(0, self._direction)
        self.enable_bridge(False)

        if keep_fans_running and self.pins.fan_mosfet is not None:
            time.sleep(self.fan_cooldown_seconds)

        self.set_fans(False)

    def set_drive(self, duty_cycle: float, direction: Direction = "forward") -> None:
        self._require_setup()
        duty = max(0.0, min(100.0, float(duty_cycle)))

        if direction not in ("forward", "reverse"):
            raise ValueError("direction must be 'forward' or 'reverse'")

        assert self._rpwm is not None
        assert self._lpwm is not None

        if direction != self._direction and self._duty_cycle > 0:
            self._rpwm.ChangeDutyCycle(0)
            self._lpwm.ChangeDutyCycle(0)
            time.sleep(self.reverse_settle_seconds)

        if direction == "forward":
            self._lpwm.ChangeDutyCycle(0)
            self._rpwm.ChangeDutyCycle(duty)
        else:
            self._rpwm.ChangeDutyCycle(0)
            self._lpwm.ChangeDutyCycle(duty)

        self._duty_cycle = duty
        self._direction = direction

    def enable_bridge(self, enabled: bool) -> None:
        self._require_setup()
        level = GPIO.HIGH if enabled else GPIO.LOW
        GPIO.output(self.pins.r_en, level)
        GPIO.output(self.pins.l_en, level)

    def set_fans(self, enabled: bool) -> None:
        self._require_setup()
        if self.pins.fan_mosfet is not None:
            GPIO.output(self.pins.fan_mosfet, self._fan_level(enabled))

    def cleanup(self) -> None:
        if not self._is_setup:
            return

        try:
            self.set_drive(0, self._direction)
            self.enable_bridge(False)
            self.set_fans(False)
        finally:
            if self._rpwm is not None:
                self._rpwm.stop()
            if self._lpwm is not None:
                self._lpwm.stop()

            cleanup_pins = [self.pins.rpwm, self.pins.lpwm, self.pins.r_en, self.pins.l_en]
            if self.pins.fan_mosfet is not None:
                cleanup_pins.append(self.pins.fan_mosfet)
            GPIO.cleanup(cleanup_pins)

            self._rpwm = None
            self._lpwm = None
            self._is_setup = False

    @property
    def duty_cycle(self) -> float:
        return self._duty_cycle

    @property
    def direction(self) -> Direction:
        return self._direction

    def _fan_level(self, enabled: bool) -> int:
        active = GPIO.LOW if self.fan_active_low else GPIO.HIGH
        inactive = GPIO.HIGH if self.fan_active_low else GPIO.LOW
        return active if enabled else inactive

    def _require_setup(self) -> None:
        if not self._is_setup:
            raise RuntimeError("Call setup() before controlling the Peltier module.")
