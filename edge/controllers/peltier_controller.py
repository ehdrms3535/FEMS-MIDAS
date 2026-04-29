"""GPIO controller for a Peltier module, relay, MOSFET, and two fans.

Assumptions:
- Raspberry Pi uses BCM GPIO numbering.
- Relay controls the main SMPS output or Peltier power enable.
- MOSFET gate controls Peltier power by PWM.
- Fans are DC fans switched by GPIO-safe driver modules, not directly by GPIO.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import RPi.GPIO as GPIO


@dataclass(frozen=True)
class PeltierPins:
    pwm: int = 18
    relay: int = 23
    fan_hot: Optional[int] = 24
    fan_cold: Optional[int] = 25


class PeltierController:
    """Safe-ish startup/shutdown sequencing for a Peltier cooling unit."""

    def __init__(
        self,
        pins: PeltierPins = PeltierPins(),
        pwm_frequency_hz: int = 1000,
        relay_active_low: bool = True,
        fan_active_low: bool = False,
        fans_powered_by_relay: bool = False,
        fan_spinup_seconds: float = 2.0,
        fan_cooldown_seconds: float = 10.0,
    ) -> None:
        self.pins = pins
        self.pwm_frequency_hz = pwm_frequency_hz
        self.relay_active_low = relay_active_low
        self.fan_active_low = fan_active_low
        self.fans_powered_by_relay = fans_powered_by_relay
        self.fan_spinup_seconds = fan_spinup_seconds
        self.fan_cooldown_seconds = fan_cooldown_seconds
        self._pwm: Optional[GPIO.PWM] = None
        self._duty_cycle = 0.0
        self._is_setup = False

    def setup(self) -> None:
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)

        GPIO.setup(self.pins.pwm, GPIO.OUT, initial=GPIO.LOW)
        GPIO.setup(self.pins.relay, GPIO.OUT, initial=self._relay_level(False))

        for pin in self._fan_pins:
            GPIO.setup(pin, GPIO.OUT, initial=self._fan_level(False))

        self._pwm = GPIO.PWM(self.pins.pwm, self.pwm_frequency_hz)
        self._pwm.start(0)
        self._is_setup = True

    def start(self, duty_cycle: float) -> None:
        self._require_setup()
        if self.fans_powered_by_relay:
            self.set_relay(True)
        else:
            self.set_fans(True)

        time.sleep(self.fan_spinup_seconds)

        if not self.fans_powered_by_relay:
            self.set_relay(True)

        self.set_duty_cycle(duty_cycle)

    def stop(self, keep_fans_running: bool = True) -> None:
        self._require_setup()
        self.set_duty_cycle(0)

        fans_available = self._fan_pins or self.fans_powered_by_relay
        if keep_fans_running and fans_available:
            time.sleep(self.fan_cooldown_seconds)

        self.set_relay(False)
        self.set_fans(False)

    def set_duty_cycle(self, duty_cycle: float) -> None:
        self._require_setup()
        duty = max(0.0, min(100.0, float(duty_cycle)))
        self._duty_cycle = duty
        assert self._pwm is not None
        self._pwm.ChangeDutyCycle(duty)

    def set_relay(self, enabled: bool) -> None:
        self._require_setup()
        GPIO.output(self.pins.relay, self._relay_level(enabled))

    def set_fans(self, enabled: bool) -> None:
        self._require_setup()
        for pin in self._fan_pins:
            GPIO.output(pin, self._fan_level(enabled))

    def cleanup(self) -> None:
        if not self._is_setup:
            return

        try:
            self.set_duty_cycle(0)
            self.set_relay(False)
            self.set_fans(False)
        finally:
            if self._pwm is not None:
                self._pwm.stop()
            GPIO.cleanup([self.pins.pwm, self.pins.relay, *self._fan_pins])
            self._pwm = None
            self._is_setup = False

    @property
    def duty_cycle(self) -> float:
        return self._duty_cycle

    @property
    def _fan_pins(self) -> list[int]:
        return [pin for pin in (self.pins.fan_hot, self.pins.fan_cold) if pin is not None]

    def _relay_level(self, enabled: bool) -> int:
        active = GPIO.LOW if self.relay_active_low else GPIO.HIGH
        inactive = GPIO.HIGH if self.relay_active_low else GPIO.LOW
        return active if enabled else inactive

    def _fan_level(self, enabled: bool) -> int:
        active = GPIO.LOW if self.fan_active_low else GPIO.HIGH
        inactive = GPIO.HIGH if self.fan_active_low else GPIO.LOW
        return active if enabled else inactive

    def _require_setup(self) -> None:
        if not self._is_setup:
            raise RuntimeError("Call setup() before controlling the Peltier module.")
