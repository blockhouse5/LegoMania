from machine import Pin, SPI
import uasyncio as asyncio

from st7789_240x240 import (
    ST7789_240X240,
    BLACK,
    WHITE,
    RED,
    GREEN,
    BLUE,
    rgb565,
)


spi = SPI(
    1,
    baudrate=20_000_000,
    polarity=0,
    phase=0,
    sck=Pin(12),
    mosi=Pin(11),
)

display = ST7789_240X240(
    spi=spi,
    cs=10,
    dc=8,
    rst=9,
    rotation=0,
)


async def main():
    display.fill(BLACK)

    yellow = rgb565(255, 210, 0)
    cyan = rgb565(0, 210, 255)

    display.text(
        "WEATHER",
        36,
        20,
        yellow,
        background=BLACK,
        scale=3,
    )

    display.text(
        "Display Test",
        24,
        60,
        WHITE,
        background=BLACK,
        scale=2,
    )

    display.fill_rect(20, 105, 200, 25, RED)
    display.fill_rect(20, 140, 200, 25, GREEN)
    display.fill_rect(20, 175, 200, 25, BLUE)

    display.text(
        "240 x 240",
        48,
        215,
        cyan,
        background=BLACK,
        scale=2,
    )

    while True:
        await asyncio.sleep(1)