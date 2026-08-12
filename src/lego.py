from machine import Pin, PWM
import asyncio


class Servo:

    def __init__(
        self,
        pin,
        min_us=1000,
        max_us=2000,
        start_angle=90
    ):

        self.min_us = min_us
        self.max_us = max_us

        self.pwm = PWM(
            Pin(pin),
            freq=50
        )

        self.angle = start_angle

        self._write_angle(
            start_angle
        )


    def _write_angle(
        self,
        angle
    ):

        angle = max(
            0,
            min(
                180,
                angle
            )
        )

        pulse_us = (
            self.min_us
            + (
                self.max_us
                - self.min_us
            )
            * angle
            // 180
        )

        self.pwm.duty_ns(
            pulse_us * 1000
        )

        self.angle = angle


    def move_to(
        self,
        angle
    ):

        self._write_angle(
            angle
        )


    async def move_slowly(
        self,
        angle,
        delay_ms=20
    ):

        target = max(
            0,
            min(
                180,
                angle
            )
        )

        if target == self.angle:
            return

        if target > self.angle:
            step = 1
        else:
            step = -1

        while self.angle != target:

            self._write_angle(
                self.angle + step
            )

            await asyncio.sleep_ms(
                delay_ms
            )