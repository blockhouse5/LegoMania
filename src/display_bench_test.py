import asyncio
from machine import Pin, SPI

from st7789_170x320 import (
    ST7789_170X320,
    BLACK,
    RED,
    GREEN,
    BLUE,
    WHITE,
)


async def main():
    # SPI display connections
    spi = SPI(
        1,
        baudrate=20_000_000,
        polarity=0,
        phase=0,
        sck=Pin(12),
        mosi=Pin(11),
    )

    display = ST7789_170X320(
        spi=spi,
        cs=Pin(10, Pin.OUT),
        dc=Pin(9, Pin.OUT),
        rst=Pin(14, Pin.OUT),
        rotation=0,
        bgr=False,
    )

    # Portrait test: each color should cover the entire visible screen.
    for name, color in (
        ("RED", RED),
        ("GREEN", GREEN),
        ("BLUE", BLUE),
        ("WHITE", WHITE),
        ("BLACK", BLACK),
    ):
        print("Display test:", name)
        display.fill(color)
        await asyncio.sleep(2)

    # Landscape edge test.  Every colored strip should touch its screen edge.
    print("Display test: LANDSCAPE EDGES")
    display.rotation(1)
    display.fill(BLACK)

    border = 12
    display.fill_rect(0, 0, display.width, border, RED)
    display.fill_rect(
        0,
        display.height - border,
        display.width,
        border,
        GREEN,
    )
    display.fill_rect(0, 0, border, display.height, BLUE)
    display.fill_rect(
        display.width - border,
        0,
        border,
        display.height,
        WHITE,
    )

    # Keep main() alive while the final test pattern remains on screen.
    while True:
        await asyncio.sleep(1)

