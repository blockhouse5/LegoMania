from machine import Pin
import neopixel
import asyncio
import random

PIXEL_COUNT = 5

pixels = neopixel.NeoPixel(
    Pin(39, Pin.OUT),
    PIXEL_COUNT
)


def all_off():

    for pixel_number in range(PIXEL_COUNT):
        pixels[pixel_number] = (0, 0, 0)

    pixels.write()


async def torch(pixel_number):

    while True:

        # Normal warm-orange flame
        red = random.randint(75, 110)
        green = random.randint(12, 30)
        blue = random.randint(0, 3)

        # Occasional brief dimming
        if random.randint(1, 12) == 1:
            red = random.randint(35, 65)
            green = random.randint(5, 15)
            blue = 0

        pixels[pixel_number] = (
            red,
            green,
            blue
        )

        pixels.write()

        # Each torch chooses its own delay.
        delay = random.randint(45, 110)
        await asyncio.sleep_ms(delay)


async def main():

    all_off()

    try:

        await asyncio.gather(
            torch(0),
            torch(1),
            torch(2),
            torch(3),
            torch(4)
        )

    finally:

        all_off()