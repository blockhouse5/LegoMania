from machine import Pin
import neopixel
import asyncio

PIXEL_COUNT = 1

pixels = neopixel.NeoPixel(
    Pin(39, Pin.OUT),
    PIXEL_COUNT
)


async def main():

    colors = [
        ("red",       (80, 0, 0)),
        ("green",     (0, 80, 0)),
        ("blue",      (0, 0, 80)),
        ("yellow",    (80, 50, 0)),
        ("orange",    (100, 20, 0)),
        ("warm glow", (80, 15, 2)),
        ("off",       (0, 0, 0)),
    ]

    try:

        while True:

            for name, color in colors:

                pixels[0] = color
                pixels.write()

                print(name, color)

                await asyncio.sleep(1)

    finally:

        pixels[0] = (0, 0, 0)
        pixels.write()