"""Manual Raspberry Pi Peltier controller.

Example:
    python edge/peltier_manual.py --duty 40 --seconds 300

Use Ctrl+C to stop safely. The script turns fans on first, enables the relay,
then applies MOSFET PWM. On exit it disables PWM/relay before stopping fans.
"""

from __future__ import annotations

import argparse
import signal
import time

from controllers.peltier_controller import PeltierController, PeltierPins


running = True


def handle_signal(signum, frame) -> None:
    global running
    running = False


def optional_pin(value: str) -> int | None:
    pin = int(value)
    return None if pin < 0 else pin


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manual Peltier PWM controller")
    parser.add_argument("--duty", type=float, default=30.0, help="PWM duty cycle, 0-100")
    parser.add_argument("--seconds", type=float, default=0.0, help="Run time; 0 means until Ctrl+C")
    parser.add_argument("--pwm-pin", type=int, default=18, help="BCM GPIO pin for MOSFET PWM")
    parser.add_argument("--relay-pin", type=int, default=23, help="BCM GPIO pin for relay module")
    parser.add_argument("--fan-hot-pin", type=optional_pin, default=24, help="BCM GPIO pin; -1 disables")
    parser.add_argument("--fan-cold-pin", type=optional_pin, default=25, help="BCM GPIO pin; -1 disables")
    parser.add_argument("--pwm-hz", type=int, default=1000, help="PWM frequency in Hz")
    parser.add_argument("--relay-active-high", action="store_true", help="Use for active-high relay modules")
    parser.add_argument("--fan-active-low", action="store_true", help="Use for active-low fan drivers")
    parser.add_argument("--fans-on-relay", action="store_true", help="Fans are powered through the relay output")
    parser.add_argument("--fan-spinup", type=float, default=2.0, help="Fan lead time before Peltier starts")
    parser.add_argument("--fan-cooldown", type=float, default=10.0, help="Fan run-on time after Peltier stops")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    pins = PeltierPins(
        pwm=args.pwm_pin,
        relay=args.relay_pin,
        fan_hot=args.fan_hot_pin,
        fan_cold=args.fan_cold_pin,
    )
    controller = PeltierController(
        pins=pins,
        pwm_frequency_hz=args.pwm_hz,
        relay_active_low=not args.relay_active_high,
        fan_active_low=args.fan_active_low,
        fans_powered_by_relay=args.fans_on_relay,
        fan_spinup_seconds=args.fan_spinup,
        fan_cooldown_seconds=args.fan_cooldown,
    )

    started_at = time.monotonic()
    controller.setup()

    try:
        print(
            "Starting Peltier: "
            f"duty={args.duty:.1f}%, pwm=GPIO{pins.pwm}, relay=GPIO{pins.relay}, "
            f"fans={controller._fan_pins or 'disabled'}"
        )
        controller.start(args.duty)

        while running:
            elapsed = time.monotonic() - started_at
            if args.seconds > 0 and elapsed >= args.seconds:
                break
            time.sleep(0.5)
    finally:
        print("Stopping Peltier safely...")
        controller.stop(keep_fans_running=True)
        controller.cleanup()
        print("Done.")


if __name__ == "__main__":
    main()
