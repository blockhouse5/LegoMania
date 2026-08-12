import asyncio
from lego import Servo


BRIDGE_DOWN = 20
BRIDGE_UP = 120


bridge = Servo(
    pin=42,
    start_angle=BRIDGE_DOWN
)


async def main():

    print("Drawbridge ready")

    while True:

        print("Raising drawbridge")

        await bridge.move_slowly(
            BRIDGE_UP,
            delay_ms=20
        )

        await asyncio.sleep(3)

        print("Lowering drawbridge")

        await bridge.move_slowly(
            BRIDGE_DOWN,
            delay_ms=20
        )

        await asyncio.sleep(3)