import asyncio

async def main():

    count = 0

    try:
        while True:

            count += 1

            print(
                "Torches: checking room light",
                count
            )

            # Simulate checking the light sensor
            await asyncio.sleep(2)

    except asyncio.CancelledError:

        print("Torches: stopped")

        # Later:
        # turn LEDs off here

        raise