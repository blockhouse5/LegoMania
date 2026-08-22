from machine import Pin
import neopixel
import asyncio

PIXEL_COUNT = 5

pixels = neopixel.NeoPixel(
    Pin(39, Pin.OUT),
    PIXEL_COUNT
)


def all_off():

    for pixel_number in range(PIXEL_COUNT):
        pixels[pixel_number] = (0, 0, 0)

    pixels.write()


async def main():

    try:

        while True:

            for pixel_number in range(PIXEL_COUNT):

                all_off()

                pixels[pixel_number] = (80, 15, 2)
                pixels.write()

                print("Pixel", pixel_number, "is on")

                await asyncio.sleep(1)

    finally:

        all_off()