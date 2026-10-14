"""Minimal MicroPython driver for a 170 x 320 ST7789V2 SPI display.

Designed for the Waveshare 1.9-inch LCD Module.  The panel occupies a
170-pixel-wide centered window inside the controller's 240 x 320 memory.
"""

from machine import Pin
from time import sleep_ms
import struct
import framebuf


class ST7789_170X320:
    SWRESET = 0x01
    SLPOUT = 0x11
    NORON = 0x13
    INVON = 0x21
    DISPOFF = 0x28
    DISPON = 0x29
    CASET = 0x2A
    RASET = 0x2B
    RAMWR = 0x2C
    MADCTL = 0x36
    COLMOD = 0x3A

    # width, height, x offset, y offset, MADCTL rotation bits
    _ROTATIONS = (
        (170, 320, 35, 0, 0x00),
        (320, 170, 0, 35, 0x60),
        (170, 320, 35, 0, 0xC0),
        (320, 170, 0, 35, 0xA0),
    )

    def __init__(self, spi, cs, dc, rst, rotation=0, bgr=False):
        self.spi = spi
        self.cs = cs if isinstance(cs, Pin) else Pin(cs, Pin.OUT)
        self.dc = dc if isinstance(dc, Pin) else Pin(dc, Pin.OUT)
        self.rst = rst if isinstance(rst, Pin) else Pin(rst, Pin.OUT)
        self.bgr = bgr

        self.cs.value(1)
        self.dc.value(1)
        self.rst.value(1)

        self._hardware_reset()
        self._command(self.SWRESET)
        sleep_ms(150)
        self._command(self.SLPOUT)
        sleep_ms(120)
        self._command(self.COLMOD, b"\x55")  # 16-bit RGB565 pixels
        self.rotation(rotation)
        self._command(self.INVON)
        self._command(self.NORON)
        sleep_ms(10)
        self._command(self.DISPON)
        sleep_ms(100)

    def _hardware_reset(self):
        self.rst.value(1)
        sleep_ms(10)
        self.rst.value(0)
        sleep_ms(20)
        self.rst.value(1)
        sleep_ms(120)

    def _command(self, command, data=None):
        self.cs.value(0)
        self.dc.value(0)
        self.spi.write(bytes((command,)))
        if data:
            self.dc.value(1)
            self.spi.write(data)
        self.cs.value(1)

    def rotation(self, rotation):
        self.rotation_number = rotation % 4
        (
            self.width,
            self.height,
            self.x_offset,
            self.y_offset,
            madctl,
        ) = self._ROTATIONS[self.rotation_number]

        if self.bgr:
            madctl |= 0x08
        self._command(self.MADCTL, bytes((madctl,)))

    def _window(self, x, y, width, height):
        x_start = x + self.x_offset
        x_end = x_start + width - 1
        y_start = y + self.y_offset
        y_end = y_start + height - 1
        self._command(self.CASET, struct.pack(">HH", x_start, x_end))
        self._command(self.RASET, struct.pack(">HH", y_start, y_end))
        self._command(self.RAMWR)

    def fill(self, color):
        self.fill_rect(0, 0, self.width, self.height, color)

    def fill_rect(self, x, y, width, height, color):
        if x < 0:
            width += x
            x = 0
        if y < 0:
            height += y
            y = 0
        if x + width > self.width:
            width = self.width - x
        if y + height > self.height:
            height = self.height - y
        if width <= 0 or height <= 0:
            return

        self._window(x, y, width, height)
        pixel = bytes(((color >> 8) & 0xFF, color & 0xFF))
        block_pixels = 256
        block = pixel * block_pixels
        remaining = width * height

        self.cs.value(0)
        self.dc.value(1)
        while remaining >= block_pixels:
            self.spi.write(block)
            remaining -= block_pixels
        if remaining:
            self.spi.write(pixel * remaining)
        self.cs.value(1)

    def text(self, message, x, y, color, background=None, scale=1):
        """Draw MicroPython's built-in 8 x 8 font, optionally enlarged."""
        if not message or scale < 1:
            return

        text_width = len(message) * 8
        if background is not None:
            self.fill_rect(
                x,
                y,
                text_width * scale,
                8 * scale,
                background,
            )

        # The monochrome buffer uses one byte per eight horizontal pixels.
        buffer = bytearray(text_width)
        mask = framebuf.FrameBuffer(
            buffer,
            text_width,
            8,
            framebuf.MONO_HLSB,
        )
        mask.fill(0)
        mask.text(message, 0, 0, 1)

        # Draw each horizontal run as one rectangle. This is much faster than
        # opening a new SPI window separately for every illuminated pixel.
        for row in range(8):
            column = 0
            while column < text_width:
                while column < text_width and not mask.pixel(column, row):
                    column += 1
                run_start = column
                while column < text_width and mask.pixel(column, row):
                    column += 1
                if column > run_start:
                    self.fill_rect(
                        x + run_start * scale,
                        y + row * scale,
                        (column - run_start) * scale,
                        scale,
                        color,
                    )


def rgb565(red, green, blue):
    """Convert ordinary 0-255 RGB values to one 16-bit RGB565 color."""
    return ((red & 0xF8) << 8) | ((green & 0xFC) << 3) | (blue >> 3)


BLACK = rgb565(0, 0, 0)
RED = rgb565(255, 0, 0)
GREEN = rgb565(0, 255, 0)
BLUE = rgb565(0, 0, 255)
WHITE = rgb565(255, 255, 255)
