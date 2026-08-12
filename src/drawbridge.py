import asyncio
from lego import Servo, Button


SERVO_PIN = 42
BUTTON_PIN = 41

BRIDGE_DOWN = 20
BRIDGE_UP = 120


bridge = Servo(
    pin=SERVO_PIN,
    start_angle=BRIDGE_DOWN
)

button = Button(
    pin=BUTTON_PIN
)


async def main():

    print("Drawbridge ready")
    print("Press the button to raise or lower")

    bridge_is_up = False

    while True:

        await button.pressed()

        if bridge_is_up:

            print("Lowering drawbridge")

            await bridge.move_slowly(
                BRIDGE_DOWN,
                delay_ms=20
            )

            bridge_is_up = False

        else:

            print("Raising drawbridge")

            await bridge.move_slowly(
                BRIDGE_UP,
                delay_ms=20
            )

            bridge_is_up = True