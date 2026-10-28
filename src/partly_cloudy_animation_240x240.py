"""Smooth partly-cloudy animation for Chuck's 240 x 240 ST7789.

The stationary sky and sun are drawn once. Each animation step restores and
transfers only the small rectangle covered by the old and new cloud positions.
"""

import asyncio
import math
from machine import Pin, SPI

from st7789_240x240 import ST7789_240X240, WHITE, rgb565


FRAME_DELAY_MS = 30
CLOUD_STEP_PIXELS = 2


async def main():
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
        cs=Pin(10, Pin.OUT),
        dc=Pin(8, Pin.OUT),
        rst=Pin(9, Pin.OUT),
        rotation=0,
        bgr=False,
    )

    print("240 x 240 display initialized")

    sky = rgb565(18, 75, 135)
    sun_yellow = rgb565(255, 205, 30)
    ray_yellow = rgb565(255, 225, 85)
    cloud_light = rgb565(232, 240, 248)
    cloud_shadow = rgb565(165, 185, 205)
    title_blue = rgb565(8, 32, 68)

    frame_y = 34
    frame_width = 240
    frame_height = 164

    cloud_width = 110
    cloud_height = 68
    cloud_y = 54
    maximum_dirty_width = cloud_width + CLOUD_STEP_PIXELS

    def color_bytes(color):
        return bytes(((color >> 8) & 0xFF, color & 0xFF))

    def buffer_fill_rect(
        buffer,
        buffer_width,
        buffer_height,
        x,
        y,
        width,
        height,
        color,
    ):
        if x < 0:
            width += x
            x = 0
        if y < 0:
            height += y
            y = 0
        if x + width > buffer_width:
            width = buffer_width - x
        if y + height > buffer_height:
            height = buffer_height - y
        if width <= 0 or height <= 0:
            return

        row = color_bytes(color) * width
        row_bytes = width * 2

        for row_number in range(y, y + height):
            start = (row_number * buffer_width + x) * 2
            buffer[start:start + row_bytes] = row

    def buffer_circle(
        buffer,
        buffer_width,
        buffer_height,
        cx,
        cy,
        radius,
        color,
    ):
        radius_squared = radius * radius

        for dy in range(-radius, radius + 1):
            half_width = int(math.sqrt(radius_squared - dy * dy))
            buffer_fill_rect(
                buffer,
                buffer_width,
                buffer_height,
                cx - half_width,
                cy + dy,
                half_width * 2 + 1,
                1,
                color,
            )

    def buffer_line(buffer, x0, y0, x1, y1, color, thickness=2):
        dx = abs(x1 - x0)
        sx = 1 if x0 < x1 else -1
        dy = -abs(y1 - y0)
        sy = 1 if y0 < y1 else -1
        error = dx + dy

        while True:
            buffer_fill_rect(
                buffer,
                frame_width,
                frame_height,
                x0,
                y0,
                thickness,
                thickness,
                color,
            )

            if x0 == x1 and y0 == y1:
                break

            twice_error = 2 * error
            if twice_error >= dy:
                error += dy
                x0 += sx
            if twice_error <= dx:
                error += dx
                y0 += sy

    def show_region(buffer, x, y, width, height):
        byte_count = width * height * 2
        display._window(x, y, width, height)
        display.cs.value(0)
        display.dc.value(1)
        display.spi.write(memoryview(buffer)[:byte_count])
        display.cs.value(1)

    def centered_text(message, y, color, scale=1):
        width = len(message) * 8 * scale
        x = (display.width - width) // 2
        display.text(message, x, y, color, scale=scale)

    # Build the stationary background once.
    sky_pixel = color_bytes(sky)
    base_frame = bytearray(sky_pixel * (frame_width * frame_height))

    center_x = 72
    center_y = 57
    inner_radius = 35
    outer_radius = 45

    for ray_number in range(12):
        angle = ray_number * math.pi / 6
        x0 = int(center_x + math.cos(angle) * inner_radius)
        y0 = int(center_y + math.sin(angle) * inner_radius)
        x1 = int(center_x + math.cos(angle) * outer_radius)
        y1 = int(center_y + math.sin(angle) * outer_radius)
        buffer_line(base_frame, x0, y0, x1, y1, ray_yellow)

    buffer_circle(
        base_frame,
        frame_width,
        frame_height,
        center_x,
        center_y,
        27,
        sun_yellow,
    )

    # Build one transparent cloud sprite. A zero-valued pixel is transparent.
    cloud_sprite = bytearray(cloud_width * cloud_height * 2)
    sprite_center_y = 36

    buffer_circle(cloud_sprite, cloud_width, cloud_height, 30, sprite_center_y + 9, 20, cloud_shadow)
    buffer_circle(cloud_sprite, cloud_width, cloud_height, 58, sprite_center_y + 5, 25, cloud_shadow)
    buffer_circle(cloud_sprite, cloud_width, cloud_height, 88, sprite_center_y + 10, 19, cloud_shadow)
    buffer_fill_rect(cloud_sprite, cloud_width, cloud_height, 18, sprite_center_y + 8, 84, 24, cloud_shadow)

    buffer_circle(cloud_sprite, cloud_width, cloud_height, 31, sprite_center_y, 19, cloud_light)
    buffer_circle(cloud_sprite, cloud_width, cloud_height, 58, sprite_center_y - 8, 27, cloud_light)
    buffer_circle(cloud_sprite, cloud_width, cloud_height, 88, sprite_center_y, 18, cloud_light)
    buffer_fill_rect(cloud_sprite, cloud_width, cloud_height, 18, sprite_center_y, 84, 22, cloud_light)

    # Convert the sprite to colored horizontal runs once. Animation frames can
    # then copy those runs instead of redrawing seven circles every time.
    cloud_runs = []

    for row_number in range(cloud_height):
        column = 0

        while column < cloud_width:
            pixel_start = (row_number * cloud_width + column) * 2

            while (
                column < cloud_width
                and cloud_sprite[pixel_start] == 0
                and cloud_sprite[pixel_start + 1] == 0
            ):
                column += 1
                pixel_start += 2

            run_start = column

            while column < cloud_width:
                pixel_start = (row_number * cloud_width + column) * 2
                if (
                    cloud_sprite[pixel_start] == 0
                    and cloud_sprite[pixel_start + 1] == 0
                ):
                    break
                column += 1

            if column > run_start:
                start = (row_number * cloud_width + run_start) * 2
                end = (row_number * cloud_width + column) * 2
                cloud_runs.append(
                    (row_number, run_start, bytes(cloud_sprite[start:end]))
                )

    dirty_buffer = bytearray(maximum_dirty_width * cloud_height * 2)

    def visible_bounds(sprite_x):
        left = max(0, sprite_x)
        right = min(frame_width, sprite_x + cloud_width)

        if right <= left:
            return None

        return left, right

    def restore_and_draw(region_left, region_right, sprite_x=None):
        region_width = region_right - region_left
        row_bytes = region_width * 2

        # Restore this rectangle from the sky-and-sun background.
        for row_number in range(cloud_height):
            source = (
                (cloud_y + row_number) * frame_width + region_left
            ) * 2
            destination = row_number * row_bytes
            dirty_buffer[destination:destination + row_bytes] = (
                base_frame[source:source + row_bytes]
            )

        # Overlay the precomputed cloud runs at the new position.
        if sprite_x is not None:
            for row_number, run_start, run_data in cloud_runs:
                run_left = sprite_x + run_start
                run_right = run_left + len(run_data) // 2
                clipped_left = max(run_left, region_left)
                clipped_right = min(run_right, region_right)

                if clipped_right <= clipped_left:
                    continue

                source_offset = (clipped_left - run_left) * 2
                copy_bytes = (clipped_right - clipped_left) * 2
                destination = (
                    row_number * region_width
                    + clipped_left - region_left
                ) * 2
                dirty_buffer[destination:destination + copy_bytes] = (
                    run_data[source_offset:source_offset + copy_bytes]
                )

        show_region(
            dirty_buffer,
            region_left,
            frame_y + cloud_y,
            region_width,
            cloud_height,
        )

    display.fill(sky)
    display.fill_rect(0, 0, 240, 29, title_blue)
    display.fill_rect(0, 203, 240, 37, title_blue)
    centered_text("WEATHER MOTION", 7, WHITE, scale=2)
    centered_text("PARTLY CLOUDY", 213, WHITE, scale=2)
    show_region(base_frame, 0, frame_y, frame_width, frame_height)

    print("Dirty-rectangle cloud animation started")

    old_x = None
    frame_number = 0
    travel_width = frame_width + cloud_width

    while True:
        new_x = -cloud_width + (
            frame_number * CLOUD_STEP_PIXELS
        ) % travel_width

        old_bounds = visible_bounds(old_x) if old_x is not None else None
        new_bounds = visible_bounds(new_x)

        if old_x is not None and new_x < old_x:
            # The cloud wrapped from the right edge back to the left. Restore
            # the two distant regions separately instead of sending a wide box.
            if old_bounds is not None:
                restore_and_draw(old_bounds[0], old_bounds[1])
            if new_bounds is not None:
                restore_and_draw(new_bounds[0], new_bounds[1], new_x)
        elif old_bounds is not None or new_bounds is not None:
            left_values = []
            right_values = []

            if old_bounds is not None:
                left_values.append(old_bounds[0])
                right_values.append(old_bounds[1])
            if new_bounds is not None:
                left_values.append(new_bounds[0])
                right_values.append(new_bounds[1])

            restore_and_draw(
                min(left_values),
                max(right_values),
                new_x if new_bounds is not None else None,
            )

        old_x = new_x
        frame_number += 1
        await asyncio.sleep_ms(FRAME_DELAY_MS)

