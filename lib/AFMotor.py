# AFMotor.py — Raspberry Pi version of Adafruit Motor Shield library

import RPi.GPIO as GPIO
import time

# Pin definitions (match your wiring)
MOTORLATCH = 12
MOTORCLK = 4
MOTORENABLE = 7
MOTORDATA = 8

# Setup GPIO
GPIO.setmode(GPIO.BCM)
GPIO.setup([MOTORLATCH, MOTORCLK, MOTORENABLE, MOTORDATA], GPIO.OUT)

class AFMotorController:
    def __init__(self):
        self.latch_state = 0
        self.enable()

    def enable(self):
        GPIO.output(MOTORENABLE, GPIO.LOW)  # enable outputs

    def latch_tx(self):
        # Simulate shift-register writing
        GPIO.output(MOTORLATCH, GPIO.LOW)
        for i in range(8):
            bit = (self.latch_state >> (7 - i)) & 1
            GPIO.output(MOTORDATA, bit)
            GPIO.output(MOTORCLK, GPIO.HIGH)
            GPIO.output(MOTORCLK, GPIO.LOW)
        GPIO.output(MOTORLATCH, GPIO.HIGH)

class AF_DCMotor:
    def __init__(self, motornum, pwm_pin, dir_pin):
        self.motornum = motornum
        self.pwm_pin = pwm_pin
        self.dir_pin = dir_pin
        GPIO.setup([pwm_pin, dir_pin], GPIO.OUT)
        self.pwm = GPIO.PWM(pwm_pin, 1000)  # 1kHz PWM
        self.pwm.start(0)

    def setSpeed(self, speed):
        self.pwm.ChangeDutyCycle(min(max(speed, 0), 100))

    def run(self, direction):
        GPIO.output(self.dir_pin, GPIO.HIGH if direction == "FORWARD" else GPIO.LOW)