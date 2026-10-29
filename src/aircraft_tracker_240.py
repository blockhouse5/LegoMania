# aircraft_tracker_240.py
# ESP32-S3 / Adafruit ST7789 240x240
#
# Requires:
#   st7789_240x240.py
#   Wi-Fi connection established by boot.py
#   requests or urequests module
#
# Aircraft data: adsb.fi v3 API

import math
import time
import network
import uasyncio as asyncio
from machine import Pin, SPI
from st7789_240x240 import ST7789_240X240, rgb565

try:
    import requests
except ImportError:
    import urequests as requests


# ========================================
# CONFIGURATION
# ========================================

# LATITUDE = 37.45365
# LONGITUDE = -90.4913

LATITUDE = 49.0011253
LONGITUDE = -122.5528932

RADIUS_MILES = 20
IDLE_REFRESH_SECONDS = 60
ACTIVE_REFRESH_SECONDS = 15
ERROR_REFRESH_SECONDS = 60

# ADS-B altitude can fluctuate slightly even during level flight. Changes no
# larger than this are reported as stable rather than climb or descent.
ALTITUDE_STABLE_TOLERANCE_FT = 100


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
RADAR_X = 120
RADAR_Y = 165
RADAR_R = 58


def distance_and_position(lat, lon):
    """Calculate approximate local distance and radar offset."""
    lat_rad = math.radians(LATITUDE)

    north = (lat - LATITUDE) * 69.0
    east = (lon - LONGITUDE) * 69.172 * math.cos(lat_rad)

    distance = math.sqrt(north * north + east * east)

    return distance, east, north


def aircraft_name(aircraft):
    """Return a readable callsign, falling back to the hexadecimal ID."""
    flight = aircraft.get("flight")

    if isinstance(flight, str):
        flight = flight.strip()

    if flight:
        return str(flight)

    hex_id = aircraft.get("hex")

    if hex_id:
        return str(hex_id).strip()

    return "UNKNOWN"


def aircraft_altitude(aircraft):
    """Return numeric barometric altitude, or geometric altitude if needed."""
    altitude = aircraft.get("alt_baro")

    if not isinstance(altitude, (int, float)):
        altitude = aircraft.get("alt_geom")

    if isinstance(altitude, (int, float)):
        return altitude

    return None


def aircraft_speed_knots(aircraft):
    """Return numeric ground speed in knots, or None when unavailable."""
    speed = aircraft.get("gs")

    if isinstance(speed, (int, float)):
        return speed

    return None


def aircraft_tracking_key(aircraft):
    """Return a stable identity for comparing consecutive API reports."""
    hex_id = aircraft.get("hex")

    if hex_id:
        return str(hex_id).strip().lower()

    return aircraft_name(aircraft)


def aircraft_source(aircraft):
    """Return a readable description of the API's message-source type."""
    source = aircraft.get("type")

    source_labels = {
        "adsb_icao": "ADS-B ICAO",
        "adsb_icao_nt": "ADS-B non-transponder",
        "adsr_icao": "ADS-R rebroadcast",
        "tisb_icao": "TIS-B ICAO",
        "adsc": "ADS-C satellite",
        "mlat": "MLAT position",
        "other": "Other source",
        "mode_s": "Mode S",
        "adsb_other": "ADS-B non-ICAO",
        "adsr_other": "ADS-R non-ICAO",
        "tisb_other": "TIS-B non-ICAO",
        "tisb_trackfile": "TIS-B radar track",
    }

    if isinstance(source, str) and source:
        label = source_labels.get(source, "Unknown source")
        return "{} ({})".format(label, source)

    hex_id = aircraft.get("hex")

    if isinstance(hex_id, str) and hex_id.startswith("~"):
        return "Non-ICAO (source unavailable)"

    return "unknown"


def altitude_trend(aircraft, previous_altitudes):
    """Compare this altitude with the preceding report for the aircraft."""
    key = aircraft_tracking_key(aircraft)
    altitude = aircraft_altitude(aircraft)

    if altitude is None:
        return "unknown", None

    previous = previous_altitudes.get(key)
    previous_altitudes[key] = altitude

    if previous is None:
        return "unknown (first contact)", None

    change = altitude - previous

    if change > ALTITUDE_STABLE_TOLERANCE_FT:
        return "ascending", change

    if change < -ALTITUDE_STABLE_TOLERANCE_FT:
        return "descending", change

    return "stable", change


def print_aircraft_details(aircraft, previous_altitudes):
    """Print one expanded line for an aircraft in the current report."""
    altitude = aircraft_altitude(aircraft)
    heading = aircraft.get("track")
    plane_type = aircraft.get("t") or "Unknown"
    trend, altitude_change = altitude_trend(
        aircraft, previous_altitudes
    )

    if altitude is None:
        altitude_text = "unknown"
    else:
        altitude_text = "{} ft".format(int(round(altitude)))

    if isinstance(heading, (int, float)):
        heading_text = "{} deg".format(int(round(heading)))
    else:
        heading_text = "unknown"

    if altitude_change is not None and trend != "stable":
        trend_text = "{} ({:+} ft)".format(
            trend, int(round(altitude_change))
        )
    else:
        trend_text = trend

    print(
        aircraft_name(aircraft),
        "| distance: {:.1f} miles".format(
            aircraft["distance_miles"]
        ),
        "| heading:", heading_text,
        "| type:", plane_type,
        "| source:", aircraft_source(aircraft),
        "| altitude:", altitude_text,
        "|", trend_text,
    )


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
                x, y, color,
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
        GRAY,
    )

    draw_line(
        display,
        RADAR_X, RADAR_Y - RADAR_R,
        RADAR_X, RADAR_Y + RADAR_R,
        GRAY,
    )

    # Home position
    display.fill_rect(RADAR_X - 2, RADAR_Y - 2, 5, 5, GREEN)
    display.text("N", RADAR_X - 4, RADAR_Y - RADAR_R - 12, CYAN)

    scale = RADAR_R / RADIUS_MILES

    for index, aircraft in enumerate(aircraft_list):
        distance, east, north = distance_and_position(
            aircraft["lat"], aircraft["lon"]
        )

        if distance > RADIUS_MILES:
            continue

        x = round(RADAR_X + east * scale)
        y = round(RADAR_Y - north * scale)

        heading = aircraft.get("track")

        # Closest aircraft is yellow
        color = YELLOW if index == 0 else CYAN

        if isinstance(heading, (int, float)):
            draw_aircraft_arrow(display, x, y, heading, color)
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

        distance, east, north = distance_and_position(lat, lon)

        if distance > RADIUS_MILES:
            continue

        ac["distance_miles"] = distance
        nearby.append(ac)

    nearby.sort(key=lambda a: a["distance_miles"])

    return nearby


def draw_display(display, aircraft_list, status):
    """Draw the complete aircraft tracker screen."""
    aircraft = aircraft_list[0] if aircraft_list else None
    count = len(aircraft_list)

    display.fill(BLACK)

    display.text("AIRCRAFT TRACKER", 24, 5, CYAN)
    display.fill_rect(0, 20, 240, 1, GRAY)

    if aircraft:
        flight = aircraft_name(aircraft)
        plane_type = aircraft.get("t") or "Unknown"
        distance = aircraft["distance_miles"]
        altitude = aircraft_altitude(aircraft)
        speed = aircraft_speed_knots(aircraft)
        heading = aircraft.get("track")

        display.text(flight[:14], 12, 30, WHITE, scale=2)
        display.text("TYPE: " + plane_type[:12], 12, 51, CYAN)

        display.text(
            "DIST: {:.1f} MI".format(distance),
            12, 67, WHITE,
        )

        if altitude is not None:
            display.text(
                "ALT: {} FT".format(int(altitude)),
                12, 80, WHITE,
            )

        if speed is not None:
            display.text(
                "SPD: {} MPH".format(int(speed * 1.15078)),
                12, 93, WHITE,
            )

        if isinstance(heading, (int, float)):
            display.text(
                "HDG: {} DEG".format(int(heading)),
                12, 106, WHITE,
            )

    else:
        display.text("NO AIRCRAFT", 64, 42, YELLOW)
        display.text("WITHIN 20 MILES", 52, 58, WHITE)

    draw_radar(display, aircraft_list)

    # Bottom status strip
    display.fill_rect(0, 229, 240, 11, BLACK)
    display.text(
        "{} AIRCRAFT | {}".format(count, status)[:30],
        2, 231, CYAN,
    )


def update_status(display, count, last_success_ms, api_error=False):
    """Update status without redrawing the radar."""
    display.fill_rect(0, 229, 240, 11, BLACK)

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
        "{} PLANES  {}".format(count, status)[:29],
        2, 231, color,
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

    display.fill(BLACK)
    display.text("AIRCRAFT TRACKER", 24, 30, CYAN)
    display.text("STARTING...", 72, 60, WHITE)

    wlan = network.WLAN(network.STA_IF)

    # Wait until Wi-Fi is connected.
    while not wlan.isconnected():
        display.fill_rect(0, 90, 240, 16, BLACK)
        display.text("WAITING FOR WIFI", 40, 90, YELLOW)
        await asyncio.sleep(2)

    # Main aircraft monitoring loop.
    aircraft_list = []
    last_success_ms = None
    api_error = False

    # Altitudes are kept by ICAO hex ID so each new API report can be compared
    # with the preceding report for that aircraft.
    previous_altitudes = {}

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

            draw_display(display, aircraft_list, "LIVE")

            print(
                "Aircraft nearby:", count,
                "| Next update:", refresh, "seconds",
            )

            for ac in aircraft_list:
                print_aircraft_details(ac, previous_altitudes)

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
                api_error,
            )
            await asyncio.sleep(1)


asyncio.run(main())
