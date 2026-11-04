"""
BTS7960 dual-motor library for Raspberry Pi.

BCM GPIO numbering is used.

One BTS7960 module is required for each motor.
"""

from time import sleep
from gpiozero import PWMOutputDevice, DigitalOutputDevice


class BTS7960Motor:
    """
    Controls one DC motor connected to one BTS7960 module.
    """

    def __init__(
        self,
        rpwm_pin,
        lpwm_pin,
        ren_pin,
        len_pin,
        pwm_frequency=1000,
        direction_delay=0.05
    ):
        """
        Create one BTS7960 motor controller.

        Speed is controlled from 0 to 100 percent.
        """

        self.direction_delay = direction_delay

        # Forward PWM pin
        self.r_pwm = PWMOutputDevice(
            rpwm_pin,
            frequency=pwm_frequency,
            initial_value=0
        )

        # Reverse PWM pin
        self.l_pwm = PWMOutputDevice(
            lpwm_pin,
            frequency=pwm_frequency,
            initial_value=0
        )

        # BTS7960 enable pins
        self.r_enable = DigitalOutputDevice(
            ren_pin,
            initial_value=False
        )

        self.l_enable = DigitalOutputDevice(
            len_pin,
            initial_value=False
        )

        # Enable both sides of the BTS7960
        self.enable()

    @staticmethod
    def _speed_value(speed):
        """
        Convert speed from percentage to GPIO Zero value.

        Example:
            50 percent -> 0.5
        """

        speed = float(speed)

        if not 0 <= speed <= 100:
            raise ValueError("Speed must be between 0 and 100")

        return speed / 100.0

    def forward(self, speed=100):
        """
        Run this motor forward.
        """

        pwm_value = self._speed_value(speed)

        # Turn off reverse PWM before moving forward
        self.l_pwm.value = 0

        sleep(self.direction_delay)

        # Apply forward PWM
        self.r_pwm.value = pwm_value

    def reverse(self, speed=100):
        """
        Run this motor in reverse.
        """

        pwm_value = self._speed_value(speed)

        # Turn off forward PWM before moving backward
        self.r_pwm.value = 0

        sleep(self.direction_delay)

        # Apply reverse PWM
        self.l_pwm.value = pwm_value

    def stop(self):
        """
        Stop this motor.
        """

        self.r_pwm.value = 0
        self.l_pwm.value = 0

    def set_speed(self, speed):
        """
        Control direction and speed using one value.

        Positive speed = forward
        Negative speed = reverse
        Zero = stop

        Examples:
            set_speed(60)   -> forward 60%
            set_speed(-40)  -> reverse 40%
            set_speed(0)    -> stop
        """

        if speed > 0:
            self.forward(speed)

        elif speed < 0:
            self.reverse(abs(speed))

        else:
            self.stop()

    def enable(self):
        """
        Enable the BTS7960 motor output.
        """

        self.r_enable.on()
        self.l_enable.on()

    def disable(self):
        """
        Disable the BTS7960 motor output.
        """

        self.stop()
        self.r_enable.off()
        self.l_enable.off()

    def close(self):
        """
        Stop the motor and release GPIO resources.
        """

        self.disable()

        self.r_pwm.close()
        self.l_pwm.close()
        self.r_enable.close()
        self.l_enable.close()


class DualBTS7960:
    """
    Controls a left and right motor.

    Useful for a two-wheel robot or motorized vehicle.
    """

    def __init__(
        self,
        left_pins,
        right_pins,
        pwm_frequency=1000,
        direction_delay=0.05
    ):
        """
        left_pins and right_pins must be dictionaries.

        Example:
            left_pins = {
                "rpwm": 18,
                "lpwm": 19,
                "ren": 23,
                "len": 24
            }
        """

        # Create the left motor controller
        self.left_motor = BTS7960Motor(
            rpwm_pin=left_pins["rpwm"],
            lpwm_pin=left_pins["lpwm"],
            ren_pin=left_pins["ren"],
            len_pin=left_pins["len"],
            pwm_frequency=pwm_frequency,
            direction_delay=direction_delay
        )

        # Create the right motor controller
        self.right_motor = BTS7960Motor(
            rpwm_pin=right_pins["rpwm"],
            lpwm_pin=right_pins["lpwm"],
            ren_pin=right_pins["ren"],
            len_pin=right_pins["len"],
            pwm_frequency=pwm_frequency,
            direction_delay=direction_delay
        )

    def forward(self, speed=100):
        """
        Move both motors forward.
        """

        self.left_motor.forward(speed)
        self.right_motor.forward(speed)

    def reverse(self, speed=100):
        """
        Move both motors backward.
        """

        self.left_motor.reverse(speed)
        self.right_motor.reverse(speed)

    def left(self, speed=50):
        """
        Turn left by:

        - Reversing the left motor
        - Moving the right motor forward
        """

        self.left_motor.reverse(speed)
        self.right_motor.forward(speed)

    def right(self, speed=50):
        """
        Turn right by:

        - Moving the left motor forward
        - Reversing the right motor
        """

        self.left_motor.forward(speed)
        self.right_motor.reverse(speed)

    def soft_left(self, speed=50):
        """
        Make a gentle left turn.

        The left motor stops while the right motor moves forward.
        """

        self.left_motor.stop()
        self.right_motor.forward(speed)

    def soft_right(self, speed=50):
        """
        Make a gentle right turn.

        The right motor stops while the left motor moves forward.
        """

        self.left_motor.forward(speed)
        self.right_motor.stop()

    def stop(self):
        """
        Stop both motors.
        """

        self.left_motor.stop()
        self.right_motor.stop()

    def set_motor_speeds(self, left_speed, right_speed):
        """
        Independently control both motors.

        Positive value = forward
        Negative value = reverse
        Zero = stop

        Example:
            set_motor_speeds(60, 40)
        """

        self.left_motor.set_speed(left_speed)
        self.right_motor.set_speed(right_speed)

    def enable(self):
        """
        Enable both motor controllers.
        """

        self.left_motor.enable()
        self.right_motor.enable()

    def disable(self):
        """
        Disable both motor controllers.
        """

        self.left_motor.disable()
        self.right_motor.disable()

    def close(self):
        """
        Stop both motors and clean up GPIO.
        """

        self.left_motor.close()
        self.right_motor.close()