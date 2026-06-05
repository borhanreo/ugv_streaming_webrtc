"""Serial (UART) communication controller for Arduino Uno.

Translates MQTT command values (defined in Constant) into serial
messages and writes them to the connected Arduino.

Message format:  <motor>,<direction>,<speed>
Examples:
    M1,F,255   — Motor 1 forward at full speed
    M1,B,255   — Motor 1 backward at full speed
    M1,L,200   — Turn left at speed 200
    M1,R,200   — Turn right at speed 200
    M1,S,0     — Stop
"""

from __future__ import annotations

from asyncio import sleep
import logging
from typing import Optional

import serial  # pyserial

from lib import Constant
import main

logger = logging.getLogger(__name__)


class SerialController:
    """Send motor-control commands to an Arduino Uno over UART."""

    # Default serial settings for Arduino Uno
    DEFAULT_PORT = "/dev/ttyUSB0"
    DEFAULT_BAUDRATE = 9600
    DEFAULT_TIMEOUT = 1  # seconds

    def __init__(
        self,
        port: str = DEFAULT_PORT,
        baudrate: int = DEFAULT_BAUDRATE,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._port = port
        self._baudrate = baudrate
        self._timeout = timeout
        self._serial: Optional[serial.Serial] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def open(self) -> None:
        """Open the serial port.  Safe to call multiple times."""
        if self._serial and self._serial.is_open:
            return
        self._serial = serial.Serial(
            port=self._port,
            baudrate=self._baudrate,
            timeout=self._timeout,
        )
        logger.info("Serial port %s opened at %d baud", self._port, self._baudrate)

    def close(self) -> None:
        """Close the serial port."""
        if self._serial and self._serial.is_open:
            self._serial.close()
            logger.info("Serial port %s closed", self._port)

    def __enter__(self) -> "SerialController":
        self.open()
        return self

    def __exit__(self, *_) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Low-level send
    # ------------------------------------------------------------------

    def send_raw(self, message: str) -> None:
        """Send a raw string followed by a newline to the Arduino.

        Args:
            message: Plain ASCII command string, e.g. ``"M1,F,255"``.
        """
        if self._serial is None or not self._serial.is_open:
            raise RuntimeError("Serial port is not open. Call open() first.")
        payload = (message.strip() + "\n").encode("ascii")
        self._serial.write(payload)
        logger.debug("Serial TX: %s", message.strip())

    # ------------------------------------------------------------------
    # Motor command helpers
    # ------------------------------------------------------------------

    def send_motor_command(self, motor: str, direction: str, speed: int) -> None:
        """Send a formatted motor command.

        Args:
            motor:     Motor identifier, e.g. ``"M1"``.
            direction: One of ``"F"`` (forward), ``"B"`` (backward),
                       ``"L"`` (left), ``"R"`` (right), ``"S"`` (stop).
            speed:     PWM speed value 0–255.
        """
        speed = max(0, min(255, int(speed)))
        message = f"{motor},{direction},{speed}"
        self.send_raw(message)

    def send_servo_command(self, servo: str, angle: int) -> None:
        """Send a formatted servo command.

        Args:
            servo: Servo identifier, e.g. ``"S1"``.
            angle: Servo target angle 0–180.
        """
        angle = max(0, min(180, int(angle)))
        message = f"{servo},{angle}"
        self.send_raw(message)

    # ------------------------------------------------------------------
    # MQTT value dispatcher
    # ------------------------------------------------------------------

    def handle_mqtt_command(self, t: int, speed: int = 255) -> None:
        """Translate an MQTT ``t`` value into a serial motor command.

        Args:
            t:     Integer command value from the MQTT payload (see Constant).
            speed: PWM speed to use for movement commands (default 255).
        """
        match t:
            case Constant.MQTT_T_VAL_FORWARD:
                logger.info("MQTT → Forward")
                self.send_motor_command("M1", "F", speed)
                self.send_motor_command("M2", "F", speed)
                self.send_motor_command("M3", "F", speed)
                self.send_motor_command("M4", "F", speed)

            case Constant.MQTT_T_VAL_BACKWARD:
                logger.info("MQTT → Backward")
                self.send_motor_command("M1", "B", speed)
                self.send_motor_command("M2", "B", speed)
                self.send_motor_command("M3", "B", speed)
                self.send_motor_command("M4", "B", speed)

            case Constant.MQTT_T_VAL_LEFT:
                logger.info("MQTT → Left")
                self.send_motor_command("M1", "R", speed)
                self.send_motor_command("M2", "R", speed)
                self.send_motor_command("M3", "F", speed)
                self.send_motor_command("M4", "F", speed)

            case Constant.MQTT_T_VAL_RIGHT:
                logger.info("MQTT → Right")
                self.send_motor_command("M1", "F", speed)
                self.send_motor_command("M2", "F", speed)
                self.send_motor_command("M3", "R", speed)
                self.send_motor_command("M4", "R", speed)

            case Constant.MQTT_T_VAL_STOP | Constant.MQTT_T_VAL_EMERGENCY_STOP:
                logger.info("MQTT → Stop")
                self.send_motor_command("M1", "R", 0)
                self.send_motor_command("M2", "R", 0)
                self.send_motor_command("M3", "R", 0)
                self.send_motor_command("M4", "R", 0)

            case Constant.MQTT_T_VAL_SERVO_ROTATE_TEST:
                logger.info("MQTT → Servo Rotate Test")
                self.send_servo_command("S2", speed) 
            case Constant.MQTT_T_VAL_RPI_RESTART:
                logger.info("MQTT → RPi Restart")
                main.restart_device()
            case _:
                logger.debug("MQTT → unhandled command t=%s", t)
