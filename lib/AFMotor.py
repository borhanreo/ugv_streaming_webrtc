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
import os
import threading
from typing import Any, Dict, Optional


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

    # Servo header signal pins (Servo1=shield D10, Servo2=shield D9 on v1).
    # These are NOT driven by the shield ICs; they are just connected to the
    # microcontroller pins. On a Raspberry Pi build, wire those shield header
    # pins to the BCM GPIO pins you choose and configure them here.
    servo_1: int | None = None
    servo_2: int | None = None


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
        self._pwms: Dict[int, Any] = {}
        self._servo_pwms: Dict[int, Any] = {}
        self._servo_angles: Dict[int, int] = {}
        self._initialized = False

        # Servo defaults for most hobby servos (SG90/MG90S etc.).
        self._servo_freq_hz = 50
        self._servo_min_pulse_us = 500
        self._servo_max_pulse_us = 2500

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return

        gpio = self._gpio
        gpio.setmode(gpio.BCM)

        output_pins = [
            self._pins.motorlatch,
            self._pins.motorclk,
            self._pins.motorenable,
            self._pins.motordata,
            self._pins.pwm_m1,
            self._pins.pwm_m2,
            self._pins.pwm_m3,
            self._pins.pwm_m4,
        ]
        if self._pins.servo_1 is not None:
            output_pins.append(self._pins.servo_1)
        if self._pins.servo_2 is not None:
            output_pins.append(self._pins.servo_2)

        gpio.setup(output_pins, gpio.OUT)

        # enable outputs (active-low on v1)
        gpio.output(self._pins.motorenable, gpio.LOW)

        # PWM setup for each channel
        self._pwms[1] = gpio.PWM(self._pins.pwm_m1, self._pwm_hz)
        self._pwms[2] = gpio.PWM(self._pins.pwm_m2, self._pwm_hz)
        self._pwms[3] = gpio.PWM(self._pins.pwm_m3, self._pwm_hz)
        self._pwms[4] = gpio.PWM(self._pins.pwm_m4, self._pwm_hz)
        for pwm in self._pwms.values():
            pwm.start(0)

        # Servo PWM (if configured)
        if self._pins.servo_1 is not None:
            self._servo_pwms[1] = gpio.PWM(self._pins.servo_1, self._servo_freq_hz)
            self._servo_pwms[1].start(0)
        if self._pins.servo_2 is not None:
            self._servo_pwms[2] = gpio.PWM(self._pins.servo_2, self._servo_freq_hz)
            self._servo_pwms[2].start(0)

        # Mark initialized before any method that might call back into init.
        self._initialized = True

        # Reset latch (all outputs low) using raw TX to avoid recursion.
        self._latch_state = 0
        self._latch_tx_raw()

    def _latch_tx_raw(self) -> None:
        """Write the 8-bit latch_state to the 74HC595 without init checks."""
        gpio = self._gpio

        gpio.output(self._pins.motorlatch, gpio.LOW)

        for i in range(8):
            gpio.output(self._pins.motorclk, gpio.LOW)

            mask = 1 << (7 - i)
            gpio.output(
                self._pins.motordata,
                gpio.HIGH if (self._latch_state & mask) else gpio.LOW,
            )

            gpio.output(self._pins.motorclk, gpio.HIGH)

        gpio.output(self._pins.motorlatch, gpio.HIGH)

    def latch_tx(self) -> None:
        """Write the 8-bit latch_state to the 74HC595."""
        self._ensure_initialized()
        self._latch_tx_raw()

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

        for pwm in self._servo_pwms.values():
            try:
                pwm.stop()
            except Exception:
                pass

        self._pwms.clear()
        self._servo_pwms.clear()
        self._servo_angles.clear()
        self._initialized = False

    def _servo_angle_to_duty(self, angle: int) -> float:
        # Clamp typical servo range.
        a = max(0, min(int(angle), 180))
        span_us = self._servo_max_pulse_us - self._servo_min_pulse_us
        pulse_us = self._servo_min_pulse_us + (span_us * (a / 180.0))
        period_us = 1_000_000.0 / float(self._servo_freq_hz)
        return float((pulse_us / period_us) * 100.0)

    def servo_set_angle(self, servo_num: int, *, angle: int) -> None:
        """Set servo angle in degrees (0..180).

        Servo1/Servo2 correspond to the shield servo headers.
        You must wire the shield servo *signal* pin to the configured BCM GPIO.
        """
        self._ensure_initialized()
        servo_num = int(servo_num)
        if servo_num not in (1, 2):
            raise ValueError("servo_num must be 1 or 2")
        if servo_num not in self._servo_pwms:
            raise RuntimeError(
                "Servo pins are not configured. Set AFMotorShieldV1Pins(servo_1=..., servo_2=...) "
                "or set env vars UGV_SHIELD_SERVO1_GPIO / UGV_SHIELD_SERVO2_GPIO."
            )

        duty = self._servo_angle_to_duty(angle)
        self._servo_pwms[servo_num].ChangeDutyCycle(duty)
        self._servo_angles[servo_num] = max(0, min(int(angle), 180))

    def servo_step(self, servo_num: int, *, delta: int, default_angle: int = 90) -> None:
        current = self._servo_angles.get(int(servo_num), int(default_angle))
        self.servo_set_angle(int(servo_num), angle=current + int(delta))


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
        self._lock = threading.Lock()

    def forward(self, *, speed: int = 255) -> None:
        with self._lock:
            self._left.setSpeed(speed)
            self._right.setSpeed(speed)
            self._left.run(FORWARD)
            self._right.run(FORWARD)

    def backward(self, *, speed: int = 255) -> None:
        with self._lock:
            self._left.setSpeed(speed)
            self._right.setSpeed(speed)
            self._left.run(BACKWARD)
            self._right.run(BACKWARD)

    def turn_left(self, *, speed: int = 255) -> None:
        """Turn left (differential drive): stop/slow left, drive right forward."""
        with self._lock:
            self._left.setSpeed(0)
            self._left.run(RELEASE)
            self._right.setSpeed(speed)
            self._right.run(FORWARD)

    def turn_right(self, *, speed: int = 255) -> None:
        """Turn right (differential drive): stop/slow right, drive left forward."""
        with self._lock:
            self._right.setSpeed(0)
            self._right.run(RELEASE)
            self._left.setSpeed(speed)
            self._left.run(FORWARD)

    def stop(self) -> None:
        with self._lock:
            self._left.setSpeed(0)
            self._right.setSpeed(0)
            self._left.run(RELEASE)
            self._right.run(RELEASE)
    
    def cleanup(self) -> None:
        self._shield.cleanup()

    # Servo helpers (shield Servo1/Servo2 headers)
    def servo1_angle(self, angle: int) -> None:
        with self._lock:
            self._shield.servo_set_angle(1, angle=int(angle))

    def servo2_angle(self, angle: int) -> None:
        with self._lock:
            self._shield.servo_set_angle(2, angle=int(angle))

    def servo1_step(self, *, delta: int, default_angle: int = 90) -> None:
        with self._lock:
            self._shield.servo_step(1, delta=int(delta), default_angle=int(default_angle))

    def servo2_step(self, *, delta: int, default_angle: int = 90) -> None:
        with self._lock:
            self._shield.servo_step(2, delta=int(delta), default_angle=int(default_angle))


# Convenience functions (keep your existing main.py call style)
_default_driver: Optional[UGVMotorDriver] = None


# Default wiring for this project (BCM numbering).
# Shield PWM pins: D11->GPIO20, D3->GPIO21, D6->GPIO23, D5->GPIO24
# Shift-register pins (direction): D12->GPIO12, D4->GPIO4, D7->GPIO7, D8->GPIO8
_SERVO1_GPIO = os.environ.get("UGV_SHIELD_SERVO1_GPIO")
_SERVO2_GPIO = os.environ.get("UGV_SHIELD_SERVO2_GPIO")

DEFAULT_PINS = AFMotorShieldV1Pins(
    motorlatch=12,
    motorclk=4,
    motorenable=7,
    motordata=8,
    pwm_m1=20,
    pwm_m2=21,
    pwm_m3=23,
    pwm_m4=24,
    servo_1=int(_SERVO1_GPIO) if _SERVO1_GPIO else None,
    servo_2=int(_SERVO2_GPIO) if _SERVO2_GPIO else None,
)


def _get_default_driver() -> UGVMotorDriver:
    global _default_driver
    if _default_driver is None:
        _default_driver = UGVMotorDriver(pins=DEFAULT_PINS)
    return _default_driver


def af_motor_forward(*, speed: int = 255) -> None:
    _get_default_driver().forward(speed=speed)


def af_motor_backward(*, speed: int = 255) -> None:
    _get_default_driver().backward(speed=speed)


def af_motor_stop() -> None:
    _get_default_driver().stop()


def af_motor_turn_left(*, speed: int = 255) -> None:
    _get_default_driver().turn_left(speed=speed)


def af_motor_turn_right(*, speed: int = 255) -> None:
    _get_default_driver().turn_right(speed=speed)


def af_servo1_angle(*, angle: int) -> None:
    """Set shield Servo1 angle (0..180)."""
    _get_default_driver().servo1_angle(angle)


def af_servo2_angle(*, angle: int) -> None:
    """Set shield Servo2 angle (0..180)."""
    _get_default_driver().servo2_angle(angle)


def af_servo1_step(*, delta: int, default_angle: int = 90) -> None:
    """Move shield Servo1 by delta degrees (negative/positive)."""
    _get_default_driver().servo1_step(delta=delta, default_angle=default_angle)


def af_servo2_step(*, delta: int, default_angle: int = 90) -> None:
    """Move shield Servo2 by delta degrees (negative/positive)."""
    _get_default_driver().servo2_step(delta=delta, default_angle=default_angle)
