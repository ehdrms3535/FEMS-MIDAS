"""Manual control for TEC1-12706 through a BTS7960 and fan MOSFET driver.

Example:
    python edge/peltier_bts7960_manual.py --duty 30 --seconds 300

Use Ctrl+C to stop safely. The script starts fans first, enables the BTS7960,
then applies Peltier PWM. On exit it disables the Peltier before fan cooldown.
"""

from __future__ import annotations

import argparse
import signal
import time

from controllers.bts7960_peltier_controller import (
    Bts7960PeltierController,
    Bts7960PeltierPins,
)


running = True


def handle_signal(signum, frame) -> None:
    global running
    running = False


def optional_pin(value: str) -> int | None:
    pin = int(value)
    return None if pin < 0 else pin


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manual BTS7960 Peltier controller")
    parser.add_argument("--duty", type=float, default=30.0, help="Peltier PWM duty, 0-100")
    parser.add_argument("--seconds", type=float, default=0.0, help="Run time; 0 means until Ctrl+C")
    parser.add_argument("--direction", choices=("forward", "reverse"), default="forward")
    parser.add_argument("--rpwm-pin", type=int, default=18, help="BCM GPIO for BTS7960 RPWM")
    parser.add_argument("--lpwm-pin", type=int, default=19, help="BCM GPIO for BTS7960 LPWM")
    parser.add_argument("--ren-pin", type=int, default=20, help="BCM GPIO for BTS7960 R_EN")
    parser.add_argument("--len-pin", type=int, default=21, help="BCM GPIO for BTS7960 L_EN")
    parser.add_argument("--fan-pin", type=optional_pin, default=23, help="BCM GPIO for AO3406 IN; -1 disables")
    parser.add_argument("--pwm-hz", type=int, default=1000, help="BTS7960 PWM frequency")
    parser.add_argument("--fan-active-low", action="store_true", help="Use for active-low fan drivers")
    parser.add_argument("--fan-spinup", type=float, default=2.0, help="Fan lead time before Peltier starts")
    parser.add_argument("--fan-cooldown", type=float, default=30.0, help="Fan run-on after Peltier stops")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    pins = Bts7960PeltierPins(
        rpwm=args.rpwm_pin,
        lpwm=args.lpwm_pin,
        r_en=args.ren_pin,
        l_en=args.len_pin,
        fan_mosfet=args.fan_pin,
    )
    controller = Bts7960PeltierController(
        pins=pins,
        pwm_frequency_hz=args.pwm_hz,
        fan_active_low=args.fan_active_low,
        fan_spinup_seconds=args.fan_spinup,
        fan_cooldown_seconds=args.fan_cooldown,
    )

    controller.setup()
    started_at = time.monotonic()

    try:
        print(
            "Starting BTS7960 Peltier control: "
            f"duty={args.duty:.1f}%, direction={args.direction}, "
            f"RPWM=GPIO{pins.rpwm}, LPWM=GPIO{pins.lpwm}, "
            f"R_EN=GPIO{pins.r_en}, L_EN=GPIO{pins.l_en}, fan=GPIO{pins.fan_mosfet}"
        )
        controller.start(args.duty, args.direction)

        while running:
            elapsed = time.monotonic() - started_at
            if args.seconds > 0 and elapsed >= args.seconds:
                break
            time.sleep(0.5)
    finally:
        print("Stopping Peltier and cooling down fans...")
        controller.stop(keep_fans_running=True)
        controller.cleanup()
        print("Done.")


if __name__ == "__main__":
    main()
