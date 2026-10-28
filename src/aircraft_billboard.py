"""List-only aircraft slide for the 320x170 LEGO town billboard.

No radar, no Wi-Fi credentials, and no automatic asyncio.run(). The main
billboard calls AircraftSlide.show(). Uses the existing network connection.
Aircraft data provided by adsb.fi: https://adsb.fi/
API documentation: https://github.com/adsbfi/opendata
"""

import asyncio
import math
from time import ticks_ms, ticks_diff, ticks_add

try:
    import requests
except ImportError:
    import urequests as requests

NM_TO_MILES = 1.15078


def distance_miles(lat1, lon1, lat2, lon2):
    """Great-circle surface distance, not aircraft slant range."""
    lat1, lon1, lat2, lon2 = [
        math.radians(float(value)) for value in (lat1, lon1, lat2, lon2)
    ]
    value = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    value = min(1.0, max(0.0, value))
    return 3958.7613 * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def normalize_aircraft(payload, latitude, longitude, radius_miles):
    """Return nearest-first rows; missing/invalid positions are skipped."""
    if not isinstance(payload, dict):
        raise ValueError("Aircraft response is not an object")
    records = payload.get("aircraft")
    if records is None:
        records = payload.get("ac")
    if not isinstance(records, list):
        raise ValueError("Aircraft response has no aircraft list")

    rows = []
    identifiers = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        try:
            lat = float(record["lat"])
            lon = float(record["lon"])
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                continue
            # Exclude old positions even when the API still includes the row.
            if float(record.get("seen_pos", 0)) > 60:
                continue
            distance = distance_miles(latitude, longitude, lat, lon)
            if distance > radius_miles:
                continue
        except (KeyError, TypeError, ValueError):
            continue

        identifier = str(record.get("hex") or "").strip()
        if identifier and identifier in identifiers:
            continue
        if identifier:
            identifiers.add(identifier)
        label = str(record.get("flight") or "").strip()
        if not label:
            label = str(record.get("r") or identifier or "UNKNOWN").strip()
        # The display's built-in font is ASCII. Keep rows predictable.
        label = "".join(c if 32 <= ord(c) <= 126 else "?" for c in label)
        rows.append({"id": identifier, "label": label, "miles": distance})

    rows.sort(key=lambda row: row["miles"])
    return rows


class AircraftSlide:
    def __init__(self, latitude, longitude, radius_miles=20,
                 refresh_seconds=60):
        self.latitude = float(latitude)
        self.longitude = float(longitude)
        self.radius_miles = float(radius_miles)
        if not (-90 <= self.latitude <= 90 and -180 <= self.longitude <= 180):
            raise ValueError("Check aircraft latitude and longitude")
        if not (0 < self.radius_miles <= 250 * NM_TO_MILES):
            raise ValueError("Aircraft radius must be 0 to 287.695 miles")
        self.refresh_ms = max(60, int(refresh_seconds)) * 1000
        self.url = (
            "https://opendata.adsb.fi/api/v3/lat/{}/lon/{}/dist/{:.1f}"
            .format(self.latitude, self.longitude, self.radius_miles / NM_TO_MILES)
        )
        self.rows = None
        self.updated_ms = None
        self.retry_at_ms = None
        self.error = None

    def refresh_due(self):
        return self.retry_at_ms is None or ticks_diff(ticks_ms(), self.retry_at_ms) >= 0

    def refresh(self):
        """Synchronous HTTP: bounded where supported, but not nonblocking."""
        response = None
        delay_ms = self.refresh_ms
        try:
            print("Downloading nearby aircraft...")
            response = requests.get(self.url, timeout=8)
            if response.status_code == 429:
                delay_ms = max(delay_ms, 5 * 60 * 1000)
                try:
                    retry = response.headers.get("Retry-After",
                            response.headers.get("retry-after", "0"))
                    delay_ms = max(delay_ms, int(retry) * 1000)
                except (AttributeError, TypeError, ValueError):
                    pass
                raise ValueError("Aircraft service rate limit; backing off")
            if response.status_code != 200:
                raise ValueError("Aircraft HTTP {}".format(response.status_code))
            rows = normalize_aircraft(response.json(), self.latitude,
                                      self.longitude, self.radius_miles)
            self.rows = rows
            self.updated_ms = ticks_ms()
            self.error = None
            print("Aircraft with recent positions:", len(rows))
            for row in rows[:4]:
                print(row["label"], "{:.1f} miles".format(row["miles"]))
        except Exception as error:
            # A failure is not the same as a successful empty list.
            self.error = str(error)
            print("Aircraft update error:", error)
        finally:
            self.retry_at_ms = ticks_add(ticks_ms(), delay_ms)
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass

    def draw(self, display, background, white, cyan, yellow, gray):
        display.fill_rect(6, 6, display.width - 12, display.height - 12, background)

        def text(message, y, color, scale=1):
            # One line fits within the existing border.
            maximum = (display.width - 24) // (8 * scale)
            display.text(message[:maximum], 12, y, color, scale=scale)

        text("AIRCRAFT NEARBY", 12, cyan, 2)
        if self.rows is None:
            text("Aircraft data unavailable", 57, yellow)
            text("Will retry on a later slide", 78, white)
        elif not self.rows:
            text("No recent positions in range", 57, white)
            text("Within {:.0f} miles".format(self.radius_miles), 78, gray)
        else:
            text("Designation             Miles", 39, gray)
            for index, row in enumerate(self.rows[:4]):
                line = "{:<18} {:>7.1f}".format(row["label"][:18], row["miles"])
                text(line, 54 + index * 18, white)
            text("Showing {} of {} within {:.0f} mi".format(
                min(4, len(self.rows)), len(self.rows), self.radius_miles), 130, gray)

        if self.updated_ms is None:
            status = "adsb.fi | No update yet"
        else:
            age = max(0, ticks_diff(ticks_ms(), self.updated_ms) // 1000)
            stale = self.error is not None or age >= 2 * self.refresh_ms // 1000
            status = "adsb.fi | {}{}s old".format("STALE " if stale else "", age)
        text(status, 149, yellow if self.error else gray)

    async def show(self, display, background, white, cyan, yellow, gray,
                   seconds=10):
        if self.refresh_due():
            display.fill_rect(6, 6, display.width - 12, display.height - 12, background)
            display.text("Updating aircraft...", 20, 70, white)
            await asyncio.sleep_ms(0)
            self.refresh()
        # The ten-second display starts after the request has finished.
        end = ticks_add(ticks_ms(), int(seconds * 1000))
        self.draw(display, background, white, cyan, yellow, gray)
        while ticks_diff(end, ticks_ms()) > 0:
            remaining = ticks_diff(end, ticks_ms())
            await asyncio.sleep_ms(max(1, min(1000, remaining)))

