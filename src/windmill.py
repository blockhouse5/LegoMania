import asyncio
from machine import Pin, PWM


MOTOR_IN1 = 6
MOTOR_IN2 = 7

PWM_FREQUENCY = 1000

# Slow speed = 30000
# Medium speed = 42000
# Fast speed = 30000

WINDMILL_SPEED = 60000

motor_1 = PWM(
    Pin(MOTOR_IN1),
    freq=PWM_FREQUENCY,
    duty_u16=0
)

motor_2 = PWM(
    Pin(MOTOR_IN2),
    freq=PWM_FREQUENCY,
    duty_u16=0
)


def stop():
    motor_1.duty_u16(0)
    motor_2.duty_u16(0)


def forward(speed):
    # Make one side low before powering the other.
    motor_2.duty_u16(0)
    motor_1.duty_u16(speed)


def reverse(speed):
    # Make one side low before powering the other.
    motor_1.duty_u16(0)
    motor_2.duty_u16(speed)


async def main():

    try:
        print("Windmill turning forward")
        forward(WINDMILL_SPEED)
        await asyncio.sleep(100)

        print("Windmill stopped")
        stop()
        await asyncio.sleep(2)

        print("Windmill turning backward")
        reverse(WINDMILL_SPEED)
        await asyncio.sleep(100)

        print("Windmill stopped")
        stop()

    finally:
        stop()