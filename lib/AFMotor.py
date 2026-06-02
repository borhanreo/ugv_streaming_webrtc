"""Raspberry Pi port of Adafruit Motor Shield v1 (AFMotor).

This module implements the core pieces from Adafruit's AFMotor.h/AFMotor.cpp:
- 74HC595 shift-register latch (direction control)
- DC motor channels M1..M4 with per-channel PWM speed control

Important notes:
- This is for *Motor Shield v1* (L293D + 74HC595). It is NOT for the v2 shield
  (PCA9685 over I2C).
- Raspberry Pi GPIO numbers here are BCM numbers.
- The default pin numbers intentionally mirror the Arduino pin numbers used in
  Adafruit's library (12, 4, 7, 8 and PWM 11, 3, 6, 5). This only works if you
  physically wired those shield header pins to the matching BCM GPIO pins.
  If you used different wiring, pass explicit pins when constructing the driver.

This file is structured so importing it on non-Raspberry Pi systems doesn't
immediately crash; GPIO is only required when you construct/use the driver.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional


try:
    import RPi.GPIO as _GPIO  # type: ignore
except Exception:  # pragma: no cover
    _GPIO = None


# Shift-register bit positions (from AFMotor.h)
MOTOR1_A = 2
MOTOR1_B = 3
MOTOR2_A = 1
MOTOR2_B = 4
MOTOR4_A = 0
MOTOR4_B = 6
MOTOR3_A = 5
MOTOR3_B = 7


# Commands (from AFMotor.h)
FORWARD = 1
BACKWARD = 2
RELEASE = 4


@dataclass(frozen=True)
class AFMotorShieldV1Pins:
    """GPIO pin mapping.

    Defaults mirror the Arduino pin numbers in AFMotor.h. Only keep defaults if
    you've wired the shield header pins to the same-numbered BCM GPIO pins.
    """

    motorlatch: int = 12
    motorclk: int = 4
    motorenable: int = 7
    motordata: int = 8

    # PWM input pins for M1..M4 (defaults mirror Arduino pins 11, 3, 6, 5)
    pwm_m1: int = 11
    pwm_m2: int = 3
    pwm_m3: int = 6
    pwm_m4: int = 5


class AFMotorShieldV1:
    """Controller for Adafruit Motor Shield v1 shift register + PWM lines."""

    def __init__(
        self,
        pins: AFMotorShieldV1Pins | None = None,
        *,
        pwm_hz: int = 1000,
        gpio_module=None,
    ) -> None:
        if pins is None:
            pins = AFMotorShieldV1Pins()
        self._pins = pins
        self._pwm_hz = int(pwm_hz)

        gpio = gpio_module if gpio_module is not None else _GPIO
        if gpio is None:
            raise RuntimeError(
                "RPi.GPIO is not available. Run this on a Raspberry Pi, or pass a compatible GPIO module."
            )

        self._gpio = gpio
        self._latch_state = 0
        self._pwms: Dict[int, "_GPIO.PWM"] = {}
        self._initialized = False

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return

        gpio = self._gpio
        gpio.setmode(gpio.BCM)

        gpio.setup(
            [
                self._pins.motorlatch,
                self._pins.motorclk,
                self._pins.motorenable,
                self._pins.motordata,
                self._pins.pwm_m1,
                self._pins.pwm_m2,
                self._pins.pwm_m3,
                self._pins.pwm_m4,
            ],
            gpio.OUT,
        )

        # reset latch
        self._latch_state = 0
        self.latch_tx()

        # enable outputs (active-low on v1)
        gpio.output(self._pins.motorenable, gpio.LOW)

        # PWM setup for each channel
        self._pwms[1] = gpio.PWM(self._pins.pwm_m1, self._pwm_hz)
        self._pwms[2] = gpio.PWM(self._pins.pwm_m2, self._pwm_hz)
        self._pwms[3] = gpio.PWM(self._pins.pwm_m3, self._pwm_hz)
        self._pwms[4] = gpio.PWM(self._pins.pwm_m4, self._pwm_hz)
        for pwm in self._pwms.values():
            pwm.start(0)

        self._initialized = True

    def latch_tx(self) -> None:
        """Write the 8-bit latch_state to the 74HC595."""
        self._ensure_initialized()
        gpio = self._gpio

        gpio.output(self._pins.motorlatch, gpio.LOW)

        for i in range(8):
            gpio.output(self._pins.motorclk, gpio.LOW)

            mask = 1 << (7 - i)
            gpio.output(self._pins.motordata, gpio.HIGH if (self._latch_state & mask) else gpio.LOW)

            gpio.output(self._pins.motorclk, gpio.HIGH)

        gpio.output(self._pins.motorlatch, gpio.HIGH)

    def _set_latch_bits(self, *, a_bit: int, b_bit: int, cmd: int) -> None:
        if cmd == FORWARD:
            self._latch_state |= (1 << a_bit)
            self._latch_state &= ~(1 << b_bit)
        elif cmd == BACKWARD:
            self._latch_state &= ~(1 << a_bit)
            self._latch_state |= (1 << b_bit)
        elif cmd == RELEASE:
            self._latch_state &= ~(1 << a_bit)
            self._latch_state &= ~(1 << b_bit)
        else:
            raise ValueError(f"Unsupported cmd: {cmd}")

        self.latch_tx()

    def dc_motor(self, motornum: int) -> "AF_DCMotorV1":
        """Create a DC motor channel for M1..M4."""
        if motornum not in (1, 2, 3, 4):
            raise ValueError("motornum must be 1..4")
        return AF_DCMotorV1(self, motornum)

    def _set_pwm_speed_0_255(self, motornum: int, speed: int) -> None:
        self._ensure_initialized()

        if motornum not in self._pwms:
            raise ValueError("motornum must be 1..4")

        clamped = max(0, min(int(speed), 255))
        duty = (clamped / 255.0) * 100.0
        self._pwms[motornum].ChangeDutyCycle(duty)

    def cleanup(self) -> None:
        """Stop PWM and optionally cleanup GPIO."""
        if not self._initialized:
            return

        for pwm in self._pwms.values():
            try:
                pwm.stop()
            except Exception:
                pass

        self._pwms.clear()
        self._initialized = False


class AF_DCMotorV1:
    """DC motor channel implementation, compatible with AFMotor v1 semantics."""

    def __init__(self, shield: AFMotorShieldV1, motornum: int) -> None:
        self._shield = shield
        self._motornum = int(motornum)

        if self._motornum == 1:
            self._a_bit, self._b_bit = MOTOR1_A, MOTOR1_B
        elif self._motornum == 2:
            self._a_bit, self._b_bit = MOTOR2_A, MOTOR2_B
        elif self._motornum == 3:
            self._a_bit, self._b_bit = MOTOR3_A, MOTOR3_B
        elif self._motornum == 4:
            self._a_bit, self._b_bit = MOTOR4_A, MOTOR4_B
        else:
            raise ValueError("motornum must be 1..4")

        # Ensure outputs are in a known state.
        self.run(RELEASE)
        self.setSpeed(0)

    def run(self, cmd: int) -> None:
        self._shield._set_latch_bits(a_bit=self._a_bit, b_bit=self._b_bit, cmd=int(cmd))

    def setSpeed(self, speed: int) -> None:
        """Set motor speed in 0..255 (same as original AFMotor)."""
        self._shield._set_pwm_speed_0_255(self._motornum, speed)


class UGVMotorDriver:
    """Simple 2-motor (left/right) wrapper for a v1 shield."""

    def __init__(
        self,
        *,
        left_motor: int = 1,
        right_motor: int = 2,
        pins: AFMotorShieldV1Pins | None = None,
        pwm_hz: int = 1000,
    ) -> None:
        self._shield = AFMotorShieldV1(pins=pins, pwm_hz=pwm_hz)
        self._left = self._shield.dc_motor(left_motor)
        self._right = self._shield.dc_motor(right_motor)

    def forward(self, *, speed: int = 255) -> None:
        self._left.setSpeed(speed)
        self._right.setSpeed(speed)
        self._left.run(FORWARD)
        self._right.run(FORWARD)

    def backward(self, *, speed: int = 255) -> None:
        self._left.setSpeed(speed)
        self._right.setSpeed(speed)
        self._left.run(BACKWARD)
        self._right.run(BACKWARD)

    def stop(self) -> None:
        self._left.setSpeed(0)
        self._right.setSpeed(0)
        self._left.run(RELEASE)
        self._right.run(RELEASE)

    def cleanup(self) -> None:
        self._shield.cleanup()


# Convenience functions (keep your existing main.py call style)
_default_driver: Optional[UGVMotorDriver] = None


def _get_default_driver() -> UGVMotorDriver:
    global _default_driver
    if _default_driver is None:
        _default_driver = UGVMotorDriver()
    return _default_driver


def af_motor_forward(*, speed: int = 255) -> None:
    _get_default_driver().forward(speed=speed)


def af_motor_backward(*, speed: int = 255) -> None:
    _get_default_driver().backward(speed=speed)


def af_motor_stop() -> None:
    _get_default_driver().stop()
