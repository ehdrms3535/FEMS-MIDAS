"""Console simulator for the BTS7960 Peltier controller.

This script injects a fake RPi.GPIO module before importing the real controller,
so it can run on Windows/macOS/Linux without Raspberry Pi hardware.

Examples:
    python edge/simulate_bts7960_peltier.py --demo
    python edge/simulate_bts7960_peltier.py
"""

from __future__ import annotations

import argparse
import sys
import time
import types
from dataclasses import dataclass, field
from typing import Any


@dataclass
class FakeGPIOState:
    mode: str | None = None
    pins: dict[int, dict[str, Any]] = field(default_factory=dict)
    pwm: dict[int, dict[str, float]] = field(default_factory=dict)


class FakePWM:
    def __init__(self, gpio: "FakeGPIO", pin: int, frequency_hz: int) -> None:
        self.gpio = gpio
        self.pin = pin
        self.frequency_hz = frequency_hz
        self.duty_cycle = 0.0
        self.stopped = False
        self.gpio.state.pwm[pin] = {"frequency_hz": float(frequency_hz), "duty": 0.0}
        self.gpio.log(f"PWM create GPIO{pin} @ {frequency_hz}Hz")

    def start(self, duty_cycle: float) -> None:
        self.duty_cycle = float(duty_cycle)
        self.stopped = False
        self.gpio.state.pwm[self.pin]["duty"] = self.duty_cycle
        self.gpio.log(f"PWM start  GPIO{self.pin} duty={self.duty_cycle:.1f}%")

    def ChangeDutyCycle(self, duty_cycle: float) -> None:
        self.duty_cycle = float(duty_cycle)
        self.gpio.state.pwm[self.pin]["duty"] = self.duty_cycle
        self.gpio.log(f"PWM duty   GPIO{self.pin} duty={self.duty_cycle:.1f}%")

    def stop(self) -> None:
        self.stopped = True
        self.gpio.state.pwm[self.pin]["duty"] = 0.0
        self.gpio.log(f"PWM stop   GPIO{self.pin}")


class FakeGPIO(types.ModuleType):
    BCM = "BCM"
    OUT = "OUT"
    IN = "IN"
    HIGH = 1
    LOW = 0

    def __init__(self) -> None:
        super().__init__("RPi.GPIO")
        self.state = FakeGPIOState()

    def log(self, message: str) -> None:
        print(f"[GPIO] {message}")

    def setmode(self, mode: str) -> None:
        self.state.mode = mode
        self.log(f"mode     {mode}")

    def setwarnings(self, enabled: bool) -> None:
        self.log(f"warnings {'on' if enabled else 'off'}")

    def setup(self, pin: int, mode: str, initial: int | None = None) -> None:
        self.state.pins[pin] = {"mode": mode, "level": initial}
        level = "unset" if initial is None else self.level_name(initial)
        self.log(f"setup    GPIO{pin} mode={mode} initial={level}")

    def output(self, pin: int, level: int) -> None:
        self.state.pins.setdefault(pin, {"mode": self.OUT, "level": None})
        self.state.pins[pin]["level"] = level
        self.log(f"output   GPIO{pin} -> {self.level_name(level)}")

    def PWM(self, pin: int, frequency_hz: int) -> FakePWM:
        return FakePWM(self, pin, frequency_hz)

    def cleanup(self, pins: list[int] | tuple[int, ...] | int | None = None) -> None:
        if pins is None:
            cleanup_pins = sorted(self.state.pins)
        elif isinstance(pins, int):
            cleanup_pins = [pins]
        else:
            cleanup_pins = list(pins)

        for pin in cleanup_pins:
            self.state.pins.pop(pin, None)
            self.state.pwm.pop(pin, None)

        self.log(f"cleanup  {cleanup_pins}")

    @staticmethod
    def level_name(level: int | None) -> str:
        if level == FakeGPIO.HIGH:
            return "HIGH"
        if level == FakeGPIO.LOW:
            return "LOW"
        return "None"


fake_gpio = FakeGPIO()
rpi_module = types.ModuleType("RPi")
rpi_module.GPIO = fake_gpio
sys.modules["RPi"] = rpi_module
sys.modules["RPi.GPIO"] = fake_gpio

from controllers.bts7960_peltier_controller import (  # noqa: E402
    Bts7960PeltierController,
    Bts7960PeltierPins,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Simulate BTS7960 Peltier control in console")
    parser.add_argument("--demo", action="store_true", help="Run a canned start/change/reverse/stop demo")
    parser.add_argument("--duty", type=float, default=30.0, help="Initial demo duty cycle")
    parser.add_argument("--rpwm-pin", type=int, default=18)
    parser.add_argument("--lpwm-pin", type=int, default=19)
    parser.add_argument("--ren-pin", type=int, default=20)
    parser.add_argument("--len-pin", type=int, default=21)
    parser.add_argument("--fan-pin", type=int, default=23)
    parser.add_argument("--pwm-hz", type=int, default=1000)
    return parser.parse_args()


def build_controller(args: argparse.Namespace) -> Bts7960PeltierController:
    pins = Bts7960PeltierPins(
        rpwm=args.rpwm_pin,
        lpwm=args.lpwm_pin,
        r_en=args.ren_pin,
        l_en=args.len_pin,
        fan_mosfet=None if args.fan_pin < 0 else args.fan_pin,
    )
    return Bts7960PeltierController(
        pins=pins,
        pwm_frequency_hz=args.pwm_hz,
        fan_spinup_seconds=0.2,
        fan_cooldown_seconds=0.5,
        reverse_settle_seconds=0.1,
    )


def print_status(controller: Bts7960PeltierController) -> None:
    print("")
    print("[STATUS]")
    print(f"  duty      : {controller.duty_cycle:.1f}%")
    print(f"  direction : {controller.direction}")
    for pin in sorted(fake_gpio.state.pins):
        data = fake_gpio.state.pins[pin]
        print(f"  GPIO{pin:<2}   : mode={data['mode']} level={fake_gpio.level_name(data['level'])}")
    for pin in sorted(fake_gpio.state.pwm):
        data = fake_gpio.state.pwm[pin]
        print(f"  PWM GPIO{pin:<2}: freq={data['frequency_hz']:.0f}Hz duty={data['duty']:.1f}%")
    print("")


def run_demo(controller: Bts7960PeltierController, duty: float) -> None:
    controller.setup()
    print_status(controller)

    print("[DEMO] start forward")
    controller.start(duty, "forward")
    print_status(controller)

    print("[DEMO] raise duty to 50%")
    controller.set_drive(50, "forward")
    print_status(controller)

    print("[DEMO] reverse at 20%")
    controller.set_drive(20, "reverse")
    print_status(controller)

    print("[DEMO] stop")
    controller.stop(keep_fans_running=True)
    print_status(controller)
    controller.cleanup()


def run_repl(controller: Bts7960PeltierController) -> None:
    controller.setup()
    print(
        "\nCommands: start [duty] [forward|reverse], duty <0-100>, "
        "reverse [duty], forward [duty], fans on|off, stop, status, quit\n"
    )
    print_status(controller)

    try:
        while True:
            command = input("sim> ").strip().split()
            if not command:
                continue

            name = command[0].lower()
            try:
                if name in ("quit", "exit", "q"):
                    break
                if name == "status":
                    print_status(controller)
                elif name == "start":
                    duty = float(command[1]) if len(command) > 1 else 30.0
                    direction = command[2] if len(command) > 2 else "forward"
                    controller.start(duty, direction)  # type: ignore[arg-type]
                elif name == "duty":
                    controller.set_drive(float(command[1]), controller.direction)
                elif name in ("forward", "reverse"):
                    duty = float(command[1]) if len(command) > 1 else controller.duty_cycle
                    controller.set_drive(duty, name)  # type: ignore[arg-type]
                elif name == "fans":
                    if len(command) < 2 or command[1] not in ("on", "off"):
                        print("Usage: fans on|off")
                    else:
                        controller.set_fans(command[1] == "on")
                elif name == "stop":
                    controller.stop(keep_fans_running=True)
                else:
                    print("Unknown command. Try: status, start 30, duty 50, reverse 20, stop, quit")
            except (IndexError, ValueError) as exc:
                print(f"Bad command: {exc}")
    finally:
        controller.cleanup()


def main() -> None:
    args = parse_args()
    controller = build_controller(args)
    if args.demo:
        run_demo(controller, args.duty)
    else:
        run_repl(controller)


if __name__ == "__main__":
    main()
