import asyncio

async def main():

    count = 0

    try:
        while True:

            count += 1

            print(
                "Windmill cycle:",
                count
            )

            print("Windmill: ON")

            # Five seconds instead of five minutes
            # for our test.
            await asyncio.sleep(5)

            print("Windmill: OFF")

            # Ten seconds instead of 55 minutes
            # for our test.
            await asyncio.sleep(10)

    except asyncio.CancelledError:

        print("Windmill: stopped")

        # Later:
        # make certain motor is physically OFF

        raise