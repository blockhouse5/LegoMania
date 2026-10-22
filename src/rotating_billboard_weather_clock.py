"""Rotating LEGO-town billboard with clock and animated Internet weather.

Ordinary messages display for three seconds each. A live clock slide follows
for ten seconds, then current Open-Meteo weather displays for ten seconds.
Weather is refreshed every 15 minutes and the clock is synchronized by NTP.
The weather code automatically selects a small animated weather scene.
"""

import asyncio
import math
import sys
import time
from machine import Pin, SPI
from time import ticks_add, ticks_diff, ticks_ms

try:
    import ntptime
except ImportError:
    ntptime = None

try:
    import requests
except ImportError:
    import urequests as requests


# Reload the editable message file whenever LEGO Project Lab starts this
# program so recently changed messages do not remain cached in memory.
if "billboard_messages" in sys.modules:
    del sys.modules["billboard_messages"]

from billboard_messages import MESSAGES
from st7789_170x320 import ST7789_170X320, WHITE, rgb565


DISPLAY_SECONDS = 3
CLOCK_SECONDS = 10
WEATHER_SECONDS = 10
WEATHER_REFRESH_SECONDS = 15 * 60
ANIMATION_FRAME_MS = 90
ANIMATION_FRAME_COUNT = 8
SPLASH_SECONDS = 5
SPLASH_FILE = "robotics_splash_320x170.rgb565"

# Change these three settings for the student's location. Open-Meteo uses the
# coordinates to select both the weather and the correct local time zone.
LOCATION_NAME = "LYNDEN"
LATITUDE = "48.95"
LONGITUDE = "-122.45"

WEATHER_URL = (
    "https://api.open-meteo.com/v1/forecast"
    "?latitude=" + LATITUDE
    + "&longitude=" + LONGITUDE
    + "&current=temperature_2m,"
    "apparent_temperature,"
    "relative_humidity_2m,"
    "precipitation,"
    "weather_code,"
    "wind_speed_10m"
    "&temperature_unit=fahrenheit"
    "&wind_speed_unit=mph"
    "&precipitation_unit=inch"
    "&timezone=auto"
)


WEEKDAYS = (
    "MONDAY",
    "TUESDAY",
    "WEDNESDAY",
    "THURSDAY",
    "FRIDAY",
    "SATURDAY",
    "SUNDAY",
)

MONTHS = (
    "",
    "JANUARY",
    "FEBRUARY",
    "MARCH",
    "APRIL",
    "MAY",
    "JUNE",
    "JULY",
    "AUGUST",
    "SEPTEMBER",
    "OCTOBER",
    "NOVEMBER",
    "DECEMBER",
)


latest_weather = None
utc_offset_seconds = None
clock_is_synchronized = False


def weather_description(code):
    if code == 0:
        return "Clear"
    if code == 1:
        return "Mostly clear"
    if code == 2:
        return "Partly cloudy"
    if code == 3:
        return "Overcast"
    if code in (45, 48):
        return "Fog"
    if code in (51, 53, 55):
        return "Drizzle"
    if code in (56, 57):
        return "Freezing mist"
    if code in (61, 63, 65):
        return "Rain"
    if code in (66, 67):
        return "Freezing rain"
    if code in (71, 73, 75):
        return "Snow"
    if code == 77:
        return "Snow grains"
    if code in (80, 81, 82):
        return "Rain showers"
    if code in (85, 86):
        return "Snow showers"
    if code == 95:
        return "Thunderstorm"
    if code in (96, 99):
        return "Storm and hail"
    return "Unknown"


def animation_category(code):
    """Convert an Open-Meteo weather code into an animation family."""
    if code in (0, 1):
        return "clear"
    if code == 2:
        return "partly_cloudy"
    if code == 3:
        return "cloudy"
    if code in (45, 48):
        return "fog"
    if 51 <= code <= 67 or 80 <= code <= 82:
        return "rain"
    if 71 <= code <= 77 or 85 <= code <= 86:
        return "snow"
    if code >= 95:
        return "storm"
    return "cloudy"


def synchronize_clock():
    """Set the ESP32 real-time clock to UTC using an Internet time server."""
    global clock_is_synchronized

    if clock_is_synchronized:
        return

    if ntptime is None:
        print("NTP module is unavailable; using weather report time")
        return

    try:
        print("Synchronizing clock...")
        ntptime.settime()
        clock_is_synchronized = True
        print("Clock synchronized")
    except Exception as error:
        print("Clock synchronization error:", error)


def download_weather():
    response = None

    try:
        print("Downloading weather...")
        response = requests.get(WEATHER_URL)

        if response.status_code != 200:
            print("Weather HTTP error:", response.status_code)
            return None

        weather_data = response.json()
        print("Weather data updated")
        return weather_data

    except Exception as error:
        print("Weather download error:", error)
        return None

    finally:
        if response is not None:
            response.close()


async def weather_updater():
    """Refresh weather and retry clock synchronization independently."""
    global latest_weather, utc_offset_seconds

    while True:
        synchronize_clock()
        new_weather = download_weather()

        # Retain the previous successful reading if a later request fails.
        if new_weather is not None:
            latest_weather = new_weather
            utc_offset_seconds = new_weather.get("utc_offset_seconds", 0)
            print("UTC offset seconds:", utc_offset_seconds)

        await asyncio.sleep(WEATHER_REFRESH_SECONDS)


def weekday_from_date(year, month, day):
    """Return Monday=0 through Sunday=6 for a calendar date."""
    # Zeller's congruence: its result uses Saturday=0, so convert afterward.
    if month < 3:
        month += 12
        year -= 1

    year_of_century = year % 100
    century = year // 100
    zeller_day = (
        day
        + (13 * (month + 1)) // 5
        + year_of_century
        + year_of_century // 4
        + century // 4
        + 5 * century
    ) % 7

    return (zeller_day + 5) % 7


def weather_report_datetime():
    """Parse Open-Meteo's local timestamp as a clock fallback."""
    if latest_weather is None:
        return None

    try:
        stamp = latest_weather["current"]["time"]
        date_text, time_text = stamp.split("T")
        year, month, day = [int(value) for value in date_text.split("-")]
        hour, minute = [int(value) for value in time_text.split(":")[:2]]
        weekday = weekday_from_date(year, month, day)
        return (year, month, day, hour, minute, 0, weekday, 0)
    except Exception as error:
        print("Weather time parsing error:", error)
        return None


def current_local_datetime():
    """Return local time and whether it is advancing from the NTP clock."""
    if clock_is_synchronized and utc_offset_seconds is not None:
        local_seconds = time.time() + utc_offset_seconds
        return time.localtime(local_seconds), True

    return weather_report_datetime(), False


def twelve_hour_time(hour, minute, second=None):
    suffix = "AM" if hour < 12 else "PM"
    display_hour = hour % 12

    if display_hour == 0:
        display_hour = 12

    if second is None:
        return "{}:{:02d} {}".format(display_hour, minute, suffix)

    return "{}:{:02d}:{:02d} {}".format(
        display_hour,
        minute,
        second,
        suffix,
    )


async def main():
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
        rotation=1,
        bgr=False,
    )

    background = rgb565(5, 20, 55)
    border = rgb565(255, 190, 30)
    cyan = rgb565(40, 220, 255)
    yellow = rgb565(255, 210, 0)
    gray = rgb565(175, 185, 195)
    light_blue = rgb565(130, 195, 255)
    magenta = rgb565(255, 80, 210)
    green = rgb565(130, 255, 100)
    sky = rgb565(18, 75, 135)
    cloud_light = rgb565(232, 240, 248)
    cloud_shadow = rgb565(145, 165, 190)
    fog_light = rgb565(185, 205, 220)
    snow_blue = rgb565(190, 225, 255)

    message_colors = (
        WHITE,
        cyan,
        border,
        green,
    )

    # Only this small rectangle changes during the weather animation. Sending
    # one prepared RGB565 frame is much faster than redrawing the whole screen.
    icon_x = 12
    icon_y = 40
    icon_width = 128
    icon_height = 72

    # Retain prepared frames between weather slides. Rebuild them only when
    # the current weather requires a different animation family.
    cached_animation_category = None
    cached_animation_frames = None

    def draw_border():
        thickness = 6
        display.fill_rect(0, 0, display.width, thickness, border)
        display.fill_rect(
            0,
            display.height - thickness,
            display.width,
            thickness,
            border,
        )
        display.fill_rect(0, 0, thickness, display.height, border)
        display.fill_rect(
            display.width - thickness,
            0,
            thickness,
            display.height,
            border,
        )

    def clear_inside():
        display.fill_rect(
            6,
            6,
            display.width - 12,
            display.height - 12,
            background,
        )

    def centered_text(message, y, color, scale=1):
        text_width = len(message) * 8 * scale
        x = max(7, (display.width - text_width) // 2)
        display.text(message, x, y, color, scale=scale)

    def centered_text_in_region(message, left, width, y, color, scale=1):
        text_width = len(message) * 8 * scale
        x = left + max(0, (width - text_width) // 2)
        display.text(message, x, y, color, scale=scale)

    def show_splash():
        """Stream a full-screen raw RGB565 image without loading it into RAM."""
        expected_bytes = display.width * display.height * 2
        bytes_written = 0

        try:
            display._window(0, 0, display.width, display.height)
            display.cs.value(0)
            display.dc.value(1)

            try:
                with open(SPLASH_FILE, "rb") as image_file:
                    while True:
                        image_data = image_file.read(4096)

                        if not image_data:
                            break

                        display.spi.write(image_data)
                        bytes_written += len(image_data)
            finally:
                display.cs.value(1)

            if bytes_written != expected_bytes:
                raise ValueError(
                    "Splash image has {} bytes; expected {}".format(
                        bytes_written,
                        expected_bytes,
                    )
                )

            # Add crisp text after the bitmap is transferred. This avoids
            # relying on image-generation software to spell words correctly.
            display.fill_rect(55, 9, 210, 29, background)
            centered_text("ROBOTICS LAB", 15, WHITE, scale=2)
            display.fill_rect(65, 137, 190, 25, background)
            centered_text("STARTING...", 142, yellow, scale=2)
            print("Startup splash displayed")

        except Exception as error:
            print("Startup splash error:", error)
            display.fill(background)
            centered_text("ROBOTICS LAB", 50, WHITE, scale=3)
            centered_text("STARTING...", 105, yellow, scale=2)

    def largest_scale_that_fits(lines):
        longest_line = max(len(line) for line in lines)
        available_width = display.width - 28

        for scale in (3, 2, 1):
            if longest_line * 8 * scale <= available_width:
                return scale

        return 1

    def draw_message(lines, color):
        clear_inside()

        scale = largest_scale_that_fits(lines)
        line_height = 8 * scale
        line_gap = 10
        total_height = (
            len(lines) * line_height
            + (len(lines) - 1) * line_gap
        )
        y = (display.height - total_height) // 2

        for line in lines:
            text_width = len(line) * 8 * scale
            x = (display.width - text_width) // 2
            display.text(line, x, y, color, scale=scale)
            y += line_height + line_gap

    def condition_color(code):
        if code in (0, 1):
            return yellow
        if code in (2, 3, 45, 48):
            return gray
        if 51 <= code <= 67:
            return cyan
        if 71 <= code <= 86:
            return WHITE
        if code >= 95:
            return magenta
        return WHITE

    def draw_clock_date(date_and_time):
        year, month, day, hour, minute, second, weekday, yearday = date_and_time
        clear_inside()
        centered_text(WEEKDAYS[weekday], 20, yellow, scale=3)
        date_line = "{} {}, {}".format(MONTHS[month], day, year)
        centered_text(date_line, 63, WHITE, scale=2)

    def draw_clock_time(date_and_time, live_clock):
        year, month, day, hour, minute, second, weekday, yearday = date_and_time

        # Erase only the changing portion so the date does not flash each second.
        display.fill_rect(8, 98, display.width - 16, 57, background)

        if live_clock:
            time_line = twelve_hour_time(hour, minute, second)
            centered_text(time_line, 103, cyan, scale=3)
            centered_text("INTERNET-SYNCHRONIZED", 139, gray)
        else:
            time_line = twelve_hour_time(hour, minute)
            centered_text(time_line, 103, cyan, scale=3)
            centered_text("WEATHER REPORT TIME", 139, gray)

    async def show_clock():
        last_date = None

        for second_number in range(CLOCK_SECONDS):
            date_and_time, live_clock = current_local_datetime()

            if date_and_time is None:
                if second_number == 0:
                    clear_inside()
                    centered_text("DATE AND TIME", 48, yellow, scale=3)
                    centered_text("Waiting for Internet", 101, WHITE, scale=2)
            else:
                date_key = date_and_time[:3]

                if date_key != last_date:
                    draw_clock_date(date_and_time)
                    last_date = date_key

                draw_clock_time(date_and_time, live_clock)

            await asyncio.sleep(1)

    def color_bytes(color):
        return bytes(((color >> 8) & 0xFF, color & 0xFF))

    def buffer_fill(buffer, color):
        buffer[:] = color_bytes(color) * (icon_width * icon_height)

    def buffer_fill_rect(buffer, x, y, width, height, color):
        """Draw a clipped rectangle into an RGB565 animation buffer."""
        if x < 0:
            width += x
            x = 0
        if y < 0:
            height += y
            y = 0
        if x + width > icon_width:
            width = icon_width - x
        if y + height > icon_height:
            height = icon_height - y
        if width <= 0 or height <= 0:
            return

        row = color_bytes(color) * width
        row_bytes = width * 2

        for row_number in range(y, y + height):
            start = (row_number * icon_width + x) * 2
            buffer[start:start + row_bytes] = row

    def buffer_circle(buffer, center_x, center_y, radius, color):
        radius_squared = radius * radius

        for change_y in range(-radius, radius + 1):
            half_width = int(math.sqrt(radius_squared - change_y * change_y))
            buffer_fill_rect(
                buffer,
                center_x - half_width,
                center_y + change_y,
                half_width * 2 + 1,
                1,
                color,
            )

    def buffer_line(buffer, x0, y0, x1, y1, color, thickness=2):
        """Draw a line into a frame using Bresenham's line algorithm."""
        change_x = abs(x1 - x0)
        step_x = 1 if x0 < x1 else -1
        change_y = -abs(y1 - y0)
        step_y = 1 if y0 < y1 else -1
        error = change_x + change_y

        while True:
            buffer_fill_rect(buffer, x0, y0, thickness, thickness, color)

            if x0 == x1 and y0 == y1:
                break

            twice_error = 2 * error
            if twice_error >= change_y:
                error += change_y
                x0 += step_x
            if twice_error <= change_x:
                error += change_x
                y0 += step_y

    def draw_sun(buffer, center_x, center_y, phase, rotating=True):
        rotation = phase * math.pi / 24 if rotating else 0

        for ray_number in range(12):
            angle = ray_number * math.pi / 6 + rotation
            x0 = int(center_x + math.cos(angle) * 20)
            y0 = int(center_y + math.sin(angle) * 20)
            x1 = int(center_x + math.cos(angle) * 28)
            y1 = int(center_y + math.sin(angle) * 28)
            buffer_line(buffer, x0, y0, x1, y1, yellow)

        buffer_circle(buffer, center_x, center_y, 16, yellow)

    def draw_cloud(buffer, x, y):
        shadow_y = y + 5
        buffer_circle(buffer, x + 17, shadow_y, 11, cloud_shadow)
        buffer_circle(buffer, x + 34, y, 15, cloud_shadow)
        buffer_circle(buffer, x + 51, shadow_y, 11, cloud_shadow)
        buffer_fill_rect(buffer, x + 7, y + 5, 55, 15, cloud_shadow)

        buffer_circle(buffer, x + 17, y, 10, cloud_light)
        buffer_circle(buffer, x + 34, y - 6, 14, cloud_light)
        buffer_circle(buffer, x + 51, y, 10, cloud_light)
        buffer_fill_rect(buffer, x + 7, y, 55, 12, cloud_light)

    def draw_raindrops(buffer, phase, storm=False):
        rain_color = light_blue if storm else cyan

        for drop_number, drop_x in enumerate((31, 48, 65, 82, 99)):
            drop_y = 44 + ((phase * 7 + drop_number * 9) % 22)
            buffer_line(
                buffer,
                drop_x,
                drop_y,
                drop_x - 3,
                drop_y + 6,
                rain_color,
                2,
            )

    def draw_snowflakes(buffer, phase):
        positions = ((31, 0), (48, 13), (65, 5), (82, 20), (99, 9))

        for flake_x, offset in positions:
            flake_y = 45 + ((phase * 5 + offset) % 20)
            buffer_fill_rect(buffer, flake_x, flake_y, 3, 3, snow_blue)
            buffer_fill_rect(buffer, flake_x - 2, flake_y + 1, 7, 1, snow_blue)

    def make_animation_frame(category, phase):
        frame = bytearray(icon_width * icon_height * 2)
        buffer_fill(frame, sky)

        # Move forward for half the loop and backward for the other half. This
        # prevents a visible sideways jump when the animation repeats.
        motion = (
            phase
            if phase < ANIMATION_FRAME_COUNT // 2
            else ANIMATION_FRAME_COUNT - 1 - phase
        )

        if category == "clear":
            draw_sun(frame, 64, 36, phase, rotating=True)

        elif category == "partly_cloudy":
            draw_sun(frame, 39, 27, phase, rotating=False)
            draw_cloud(frame, 43 + motion * 3, 41)

        elif category == "cloudy":
            draw_cloud(frame, 5 + motion * 2, 34)
            draw_cloud(frame, 60 - motion * 2, 44)

        elif category == "fog":
            draw_cloud(frame, 30, 28)
            offset = motion
            for line_number in range(3):
                line_y = 48 + line_number * 8
                buffer_fill_rect(frame, 11 + offset, line_y, 86, 3, fog_light)
                buffer_fill_rect(frame, 104 - offset, line_y, 13, 3, fog_light)

        elif category == "rain":
            draw_cloud(frame, 30, 28)
            draw_raindrops(frame, phase)

        elif category == "snow":
            draw_cloud(frame, 30, 28)
            draw_snowflakes(frame, phase)

        elif category == "storm":
            draw_cloud(frame, 30, 25)
            draw_raindrops(frame, phase, storm=True)
            if phase in (1, 2):
                lightning = rgb565(255, 245, 100)
                buffer_line(frame, 65, 42, 58, 55, lightning, 4)
                buffer_line(frame, 58, 55, 67, 53, lightning, 4)
                buffer_line(frame, 67, 53, 60, 68, lightning, 4)

        return frame

    def show_icon_frame(frame):
        """Send one complete icon frame in a single fast SPI transfer."""
        display._window(icon_x, icon_y, icon_width, icon_height)
        display.cs.value(0)
        display.dc.value(1)
        display.spi.write(frame)
        display.cs.value(1)

    def draw_weather_text(current):
        clear_inside()

        temperature = round(current["temperature_2m"])
        feels_like = round(current["apparent_temperature"])
        humidity = round(current["relative_humidity_2m"])
        wind_speed = round(current["wind_speed_10m"])
        precipitation = current["precipitation"]
        code = current["weather_code"]
        description = weather_description(code)
        color = condition_color(code)

        observation_time = current["time"]
        update_time = (
            observation_time.split("T")[1]
            if "T" in observation_time
            else observation_time
        )

        centered_text(LOCATION_NAME + " WEATHER", 10, WHITE, scale=2)

        right_x = 145
        right_width = display.width - right_x - 7
        centered_text_in_region(
            str(temperature) + " F",
            right_x,
            right_width,
            42,
            color,
            scale=4,
        )

        description_scale = 2 if len(description) <= 10 else 1
        centered_text_in_region(
            description,
            right_x,
            right_width,
            82,
            color,
            scale=description_scale,
        )
        centered_text_in_region(
            "Feels " + str(feels_like) + " F",
            right_x,
            right_width,
            105,
            WHITE,
        )

        centered_text(
            "Humidity " + str(humidity) + "%   Wind " + str(wind_speed) + " mph",
            122,
            WHITE,
        )
        centered_text(
            "Rain " + "{:.2f}".format(precipitation) + " in   Updated " + update_time,
            139,
            light_blue,
        )

    async def show_animated_weather():
        nonlocal cached_animation_category, cached_animation_frames

        if latest_weather is None:
            clear_inside()
            centered_text("WEATHER", 45, yellow, scale=3)
            centered_text("Waiting for update", 95, WHITE, scale=2)
            await asyncio.sleep(WEATHER_SECONDS)
            return

        current = latest_weather["current"]
        code = current["weather_code"]
        category = animation_category(code)

        print("Weather code:", code, "Animation:", category)
        draw_weather_text(current)

        # Frame construction is deliberately separated from playback. Once
        # built, each animation step is only one fast transfer over SPI.
        if category != cached_animation_category:
            print("Building", category, "animation frames")
            frames = []

            for phase in range(ANIMATION_FRAME_COUNT):
                frames.append(make_animation_frame(category, phase))
                await asyncio.sleep_ms(0)

            cached_animation_category = category
            cached_animation_frames = frames
        else:
            frames = cached_animation_frames

        stop_time = ticks_add(ticks_ms(), WEATHER_SECONDS * 1000)
        frame_number = 0

        while ticks_diff(stop_time, ticks_ms()) > 0:
            show_icon_frame(frames[frame_number])
            frame_number = (frame_number + 1) % len(frames)
            await asyncio.sleep_ms(ANIMATION_FRAME_MS)

    display.fill(background)
    show_splash()
    await asyncio.sleep(SPLASH_SECONDS)

    display.fill(background)
    draw_border()

    # Start the independent Internet updater. Yield once so it can attempt its
    # initial NTP synchronization and weather download before messages begin.
    weather_task = asyncio.create_task(weather_updater())
    await asyncio.sleep(0)

    while True:
        for message_number, lines in enumerate(MESSAGES):
            color = message_colors[message_number % len(message_colors)]
            print("Billboard message:", message_number + 1)
            draw_message(lines, color)
            await asyncio.sleep(DISPLAY_SECONDS)

        print("Billboard date and time slide")
        await show_clock()

        print("Billboard weather slide")
        await show_animated_weather()

    # Keep a reference for MicroPython implementations that aggressively
    # collect tasks. This line is not normally reached.
    await weather_task
