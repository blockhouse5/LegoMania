
# aircraft_radar_170X320.py
# ESP32-S3 / Waveshare 1.9-inch ST7789 320x170 landscape
#
# Requires:
#   st7789_170x320.py
#   Wi-Fi connection established by boot.py
#   requests or urequests module
#
# Aircraft data: adsb.fi v3 API

import math
import time
import network
import uasyncio as asyncio
from machine import Pin, SPI
from st7789_170x320 import ST7789_170X320, rgb565

try:
    import requests
except ImportError:
    import urequests as requests


# LEGO Lab reloads the selected program, but imported settings can stay cached.
# Reload settings each time its Run control starts main().
import sys


def load_settings():
    global LATITUDE, LONGITUDE, RADIUS_MILES
    global IDLE_REFRESH_SECONDS, ACTIVE_REFRESH_SECONDS, ERROR_REFRESH_SECONDS
    if "radar_settings" in sys.modules:
        del sys.modules["radar_settings"]
    import radar_settings as settings
    LATITUDE = settings.LATITUDE
    LONGITUDE = settings.LONGITUDE
    RADIUS_MILES = settings.RADIUS_MILES
    IDLE_REFRESH_SECONDS = settings.IDLE_REFRESH_SECONDS
    ACTIVE_REFRESH_SECONDS = settings.ACTIVE_REFRESH_SECONDS
    ERROR_REFRESH_SECONDS = settings.ERROR_REFRESH_SECONDS


# ========================================
# COLORS
# ========================================

BLACK = rgb565(0, 0, 0)
WHITE = rgb565(255, 255, 255)
CYAN = rgb565(80, 220, 255)
GREEN = rgb565(50, 255, 120)
GRAY = rgb565(75, 90, 110)
YELLOW = rgb565(255, 220, 50)
RED = rgb565(255, 70, 70)

# Radar location and radius in pixels
RADAR_X = 239
RADAR_Y = 87
RADAR_R = 57


def distance_and_position(lat, lon):
    """Calculate approximate local distance and radar offset."""
    lat_rad = math.radians(LATITUDE)

    north = (lat - LATITUDE) * 69.0
    east = (lon - LONGITUDE) * 69.172 * math.cos(lat_rad)

    distance = math.sqrt(north*north + east*east)

    return distance, east, north


def draw_line(display, x1, y1, x2, y2, color):
    """Bresenham line drawing using fill_rect."""
    dx = abs(x2 - x1)
    dy = -abs(y2 - y1)
    sx = 1 if x1 < x2 else -1
    sy = 1 if y1 < y2 else -1
    error = dx + dy

    while True:
        display.fill_rect(x1, y1, 1, 1, color)

        if x1 == x2 and y1 == y2:
            break

        e2 = 2 * error

        if e2 >= dy:
            error += dy
            x1 += sx

        if e2 <= dx:
            error += dx
            y1 += sy


def draw_circle(display, cx, cy, radius, color):
    """Draw an approximate circle using line segments."""
    previous = None

    for degrees in range(0, 361, 10):
        angle = math.radians(degrees)

        x = int(cx + radius * math.cos(angle))
        y = int(cy + radius * math.sin(angle))

        if previous:
            draw_line(
                display,
                previous[0], previous[1],
                x, y, color
            )

        previous = (x, y)


def draw_aircraft_arrow(display, x, y, heading, color):
    """Draw an aircraft heading arrow centered at x, y."""

    angle = math.radians(heading)

    # Forward direction: 12 pixels
    dx = math.sin(angle)
    dy = -math.cos(angle)

    # Arrow tip
    tip_x = int(x + dx * 12)
    tip_y = int(y + dy * 12)

    # Tail
    tail_x = int(x - dx * 7)
    tail_y = int(y - dy * 7)

    # Perpendicular direction for arrow wings
    px = -dy
    py = dx

    # Left and right wing points
    left_x = int(x - dx * 2 + px * 6)
    left_y = int(y - dy * 2 + py * 6)

    right_x = int(x - dx * 2 - px * 6)
    right_y = int(y - dy * 2 - py * 6)

    # Main body
    draw_line(display, tail_x, tail_y, tip_x, tip_y, color)

    # Arrowhead wings
    draw_line(display, tip_x, tip_y, left_x, left_y, color)
    draw_line(display, tip_x, tip_y, right_x, right_y, color)



def draw_radar(display, aircraft_list):
    """Draw all nearby aircraft on the radar."""

    # Radar circles and crosshairs
    draw_circle(display, RADAR_X, RADAR_Y, RADAR_R, GRAY)
    draw_circle(display, RADAR_X, RADAR_Y, RADAR_R // 2, GRAY)

    draw_line(
        display,
        RADAR_X - RADAR_R, RADAR_Y,
        RADAR_X + RADAR_R, RADAR_Y,
        GRAY
    )

    draw_line(
        display,
        RADAR_X, RADAR_Y - RADAR_R,
        RADAR_X, RADAR_Y + RADAR_R,
        GRAY
    )

    # Home position
    display.fill_rect(RADAR_X - 2, RADAR_Y - 2, 5, 5, GREEN)
    display.text("N", RADAR_X - 4, RADAR_Y - RADAR_R - 12, CYAN)

    scale = RADAR_R / RADIUS_MILES

    print("RADAR RECEIVED:", len(aircraft_list), "aircraft")

    for index in range(len(aircraft_list) - 1, -1, -1):
        aircraft = aircraft_list[index]
        distance, east, north = distance_and_position(
            aircraft["lat"], aircraft["lon"]
        )

        if distance > RADIUS_MILES:
            continue

        x = round(RADAR_X + east * scale)
        y = round(RADAR_Y - north * scale)

        print(
            "RADAR:",
            aircraft.get("flight"),
            "distance:", round(distance, 1),
            "x:", x,
            "y:", y,
            "heading:", aircraft.get("track")
        )

        heading = aircraft.get("track")

        # Closest aircraft is yellow
        color = YELLOW if index == 0 else CYAN

        if isinstance(heading, (int, float)):
            draw_aircraft_arrow(
                display, x, y, heading, color
            )
        else:
            display.fill_rect(x - 2, y - 2, 5, 5, color)



def get_aircraft():
    """Retrieve nearby aircraft from adsb.fi."""
    radius_nm = RADIUS_MILES / 1.15078

    url = (
        "https://opendata.adsb.fi/api/v3/lat/"
        "{}/lon/{}/dist/{:.1f}".format(
            LATITUDE, LONGITUDE, radius_nm
        )
    )

    response = None

    try:
        response = requests.get(url)
        data = response.json()
    finally:
        if response:
            response.close()

    aircraft = data.get("aircraft")

    if aircraft is None:
        aircraft = data.get("ac")

    if not isinstance(aircraft, list):
        raise ValueError("Invalid aircraft response")

    nearby = []

    for ac in aircraft:
        lat = ac.get("lat")
        lon = ac.get("lon")

        if lat is None or lon is None:
            continue

        distance, east, north = distance_and_position(
            lat, lon
        )

        if distance > RADIUS_MILES:
            continue

        ac["distance_miles"] = distance
        nearby.append(ac)

    nearby.sort(key=lambda a: a["distance_miles"])

    return nearby

def draw_display(display, aircraft_list, status):
    """Draw details on the left and the 20-mile radar on the right."""
    aircraft = aircraft_list[0] if aircraft_list else None
    display.fill(BLACK)
    display.text("AIRCRAFT TRACKER", 8, 5, CYAN)
    display.fill_rect(0, 20, 320, 1, GRAY)
    display.fill_rect(158, 24, 1, 130, GRAY)

    if aircraft:
        flight = (aircraft.get("flight") or "").strip()
        if not flight:
            flight = aircraft.get("hex") or "UNKNOWN"
        plane_type = aircraft.get("t") or "Unknown"
        altitude = aircraft.get("alt_baro")
        if not isinstance(altitude, (int, float)):
            altitude = aircraft.get("alt_geom")
        speed = aircraft.get("gs")
        heading = aircraft.get("track")

        # Nine enlarged characters fit within the details column.
        display.text(flight[:9], 6, 30, WHITE, scale=2)
        display.text(("TYPE: " + plane_type)[:18], 6, 54, CYAN)
        display.text("DIST: {:.1f} MI".format(
            aircraft["distance_miles"]), 6, 72, WHITE)
        if isinstance(altitude, (int, float)):
            display.text("ALT: {} FT".format(int(altitude))[:18],
                         6, 90, WHITE)
        if isinstance(speed, (int, float)):
            display.text("SPD: {} MPH".format(int(speed * 1.15078))[:18],
                         6, 108, WHITE)
        if isinstance(heading, (int, float)):
            display.text("HDG: {} DEG".format(int(heading))[:18],
                         6, 126, WHITE)
    else:
        display.text("NO AIRCRAFT", 12, 54, YELLOW)
        display.text("WITHIN 20 MILES", 6, 74, WHITE)

    draw_radar(display, aircraft_list)
    display.fill_rect(0, 158, 320, 12, BLACK)
    display.text("{} AIRCRAFT | {}".format(
        len(aircraft_list), status)[:39], 2, 160, CYAN)


def update_status(display, count, last_success_ms, api_error=False):
    """Update status without redrawing the radar."""

    display.fill_rect(0, 158, 320, 12, BLACK)

    if last_success_ms is None:
        age_text = "NEVER"
    else:
        age_seconds = time.ticks_diff(
            time.ticks_ms(), last_success_ms
        ) // 1000

        age_text = "{}S AGO".format(age_seconds)

    if api_error:
        status = "API ERROR"
        color = RED
    elif last_success_ms is None:
        status = "WAITING"
        color = YELLOW
    else:
        status = age_text
        color = CYAN

    display.text(
        "{} PLANES  {}".format(count, status)[:39],
        2, 160, color
    )


async def main():
    load_settings()
    spi = SPI(
        1,
        baudrate=20_000_000,
        polarity=0,
        phase=0,
        sck=Pin(12),
        mosi=Pin(11)
    )

    display = ST7789_170X320(
        spi=spi,
        cs=Pin(10, Pin.OUT),
        dc=Pin(9, Pin.OUT),
        rst=Pin(14, Pin.OUT),
        rotation=1,
        bgr=False
    )

    display.fill(BLACK)
    display.text("AIRCRAFT TRACKER", 8, 30, CYAN)
    display.text("STARTING...", 8, 60, WHITE)

    wlan = network.WLAN(network.STA_IF)

    # Wait until Wi-Fi is connected
    while not wlan.isconnected():
        display.fill_rect(0, 90, 320, 16, BLACK)
        display.text("WAITING FOR WIFI", 8, 90, YELLOW)
        await asyncio.sleep(2)

    # Main aircraft monitoring loop


    aircraft_list = []
    last_success_ms = None
    api_error = False

    while True:
        try:
            aircraft_list = get_aircraft()
            count = len(aircraft_list)

            refresh = (
                ACTIVE_REFRESH_SECONDS
                if count > 0
                else IDLE_REFRESH_SECONDS
            )

            last_success_ms = time.ticks_ms()
            api_error = False

            draw_display(
                display,
                aircraft_list,
                "LIVE"
            )

            print(
                "Aircraft nearby:", count,
                "| Next update:", refresh, "seconds"
            )

            for ac in aircraft_list:
                print(
                    (ac.get("flight") or ac.get("hex") or "UNKNOWN").strip(),
                    "{:.1f} miles".format(ac["distance_miles"]),
                    "heading:", ac.get("track")
                )

        except Exception as error:
            print("Aircraft API error:", error)
            api_error = True
            refresh = ERROR_REFRESH_SECONDS

        # Update elapsed time every second.
        # Only the status strip is redrawn.
        for remaining in range(refresh):
            update_status(
                display,
                len(aircraft_list),
                last_success_ms,
                api_error
            )
            await asyncio.sleep(1)


def run():
    """Start explicitly; importing this module does not start the tracker."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Radar stopped. You can now save radar_settings.py.")
    finally:
        asyncio.new_event_loop()


if __name__ == "__main__":
    run()
