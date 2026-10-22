"""Rotating LEGO-town billboard with clock and Internet weather slides.

Ordinary messages display for three seconds each. A live clock slide follows
for ten seconds, then current Open-Meteo weather displays for ten seconds.
Weather is refreshed every 15 minutes and the clock is synchronized by NTP.
"""

import asyncio
import sys
import time
from machine import Pin, SPI

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
from st7789_240x240 import ST7789_240X240, WHITE, rgb565


DISPLAY_SECONDS = 3
CLOCK_SECONDS = 10
WEATHER_SECONDS = 10
WEATHER_REFRESH_SECONDS = 15 * 60
SPLASH_SECONDS = 5
SPLASH_FILE = "nanny_pepe_240X240.rgb565"

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

    display = ST7789_240X240(
        spi=spi,
        cs=Pin(10, Pin.OUT),
        dc=Pin(8, Pin.OUT),
        rst=Pin(9, Pin.OUT),
        rotation=0,
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

    message_colors = (
        WHITE,
        cyan,
        border,
        green,
    )

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
            display.fill_rect(15, 9, 210, 29, background)
            centered_text("ROBOTICS LAB", 15, WHITE, scale=2)
            display.fill_rect(25, 207, 190, 25, background)
            centered_text("STARTING...", 212, yellow, scale=2)
            print("Startup splash displayed")

        except Exception as error:
            print("Startup splash error:", error)
            display.fill(background)
            centered_text("ROBOTICS LAB", 50, WHITE, scale=2)
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
        centered_text(date_line, 63, WHITE, scale=1)

    def draw_clock_time(date_and_time, live_clock):
        year, month, day, hour, minute, second, weekday, yearday = date_and_time

        # Erase only the changing portion so the date does not flash each second.
        display.fill_rect(8, 98, display.width - 16, 57, background)

        if live_clock:
            time_line = twelve_hour_time(hour, minute, second)
            centered_text(time_line, 103, cyan, scale=2)
            centered_text("INTERNET-SYNCHRONIZED", 139, gray)
        else:
            time_line = twelve_hour_time(hour, minute)
            centered_text(time_line, 103, cyan, scale=2)
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

    def draw_weather():
        clear_inside()

        if latest_weather is None:
            centered_text("WEATHER", 45, yellow, scale=3)
            centered_text("Waiting for update", 95, WHITE, scale=2)
            return

        current = latest_weather["current"]
        temperature = round(current["temperature_2m"])
        feels_like = round(current["apparent_temperature"])
        humidity = round(current["relative_humidity_2m"])
        wind_speed = round(current["wind_speed_10m"])
        precipitation = current["precipitation"]
        code = current["weather_code"]
        description = weather_description(code)
        color = condition_color(code)

        observation_time = current["time"]
        if "T" in observation_time:
            update_time = observation_time.split("T")[1]
        else:
            update_time = observation_time

        centered_text(LOCATION_NAME + " WEATHER", 12, WHITE, scale=2)
        centered_text(str(temperature) + " F", 39, color, scale=4)

        description_scale = 2 if len(description) <= 18 else 1
        centered_text(description, 78, color, scale=description_scale)
        centered_text(
            "Feels " + str(feels_like) + " F   Humidity " + str(humidity) + "%",
            106,
            WHITE,
        )
        centered_text(
            "Wind " + str(wind_speed) + " mph   Rain "
            + "{:.2f}".format(precipitation) + " in",
            125,
            light_blue,
        )
        centered_text("Updated " + update_time, 146, gray)

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
        draw_weather()
        await asyncio.sleep(WEATHER_SECONDS)

    # Keep a reference for MicroPython implementations that aggressively
    # collect tasks. This line is not normally reached.
    await weather_task
