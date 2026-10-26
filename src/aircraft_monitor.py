
import csv
import json
import math
import time
import urllib.request
from datetime import datetime
from pathlib import Path

# ==========================================
# CONFIGURATION - ENTER LOCATION HERE
# ==========================================

LATITUDE = 37.45365     # Grandson's latitude
LONGITUDE = -90.49130     # Grandson's longitude

RADIUS_MILES = 20
POLL_SECONDS = 60
PASS_TIMEOUT_SECONDS = 300

# ==========================================

KM_PER_MILE = 1.609344
FEET_PER_METER = 3.28084

OUTPUT_DIR = Path("aircraft_data")
OUTPUT_DIR.mkdir(exist_ok=True)

SIGHTINGS_FILE = OUTPUT_DIR / "sightings.csv"
PASSES_FILE = OUTPUT_DIR / "passes.csv"

active = {}
completed_passes = 0
total_sightings = 0
successful_polls = 0
start_time = datetime.now()


def timestamp():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def distance_miles(lat1, lon1, lat2, lon2):
    """Great-circle ground distance using Haversine."""
    r = 3958.7613

    a1, a2 = math.radians(lat1), math.radians(lat2)
    da = a2 - a1
    dl = math.radians(lon2 - lon1)

    a = (math.sin(da / 2) ** 2
         + math.cos(a1) * math.cos(a2)
         * math.sin(dl / 2) ** 2)

    return 2 * r * math.asin(min(1, math.sqrt(a)))


def append_csv(path, fields, record):
    new_file = not path.exists()

    with path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)

        if new_file:
            writer.writeheader()

        writer.writerow(record)


SIGHTING_FIELDS = [
    "time", "hex", "flight", "type",
    "distance_miles", "altitude_ft",
    "speed_mph", "heading", "latitude", "longitude"
]

PASS_FIELDS = [
    "first_seen", "last_seen", "hex", "flight",
    "type", "closest_miles", "altitude_ft",
    "observations"
]


def get_aircraft():
    radius_nm = RADIUS_MILES / 1.15078

    url = (
        "https://opendata.adsb.fi/api/v3/lat/"
        f"{LATITUDE}/lon/{LONGITUDE}/dist/{radius_nm:.1f}"
    )

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "EducationalAircraftMonitor/1.0"}
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        data = json.load(response)

    if not isinstance(data, dict):
        raise ValueError("Unexpected API response")

    aircraft = data.get("aircraft")

    if aircraft is None:
        aircraft = data.get("ac")

    if not isinstance(aircraft, list):
        raise ValueError(
            f"Unexpected aircraft API response. Keys: {list(data.keys())}"
        )

    return aircraft


def finish_pass(hex_id):
    global completed_passes

    item = active.pop(hex_id)

    append_csv(PASSES_FILE, PASS_FIELDS, {
        "first_seen": item["first_seen"],
        "last_seen": item["last_seen"],
        "hex": hex_id,
        "flight": item["flight"],
        "type": item["type"],
        "closest_miles": round(item["closest"], 2),
        "altitude_ft": item["altitude"],
        "observations": item["observations"]
    })

    completed_passes += 1


def process_aircraft(aircraft):
    global total_sightings

    now = time.time()
    observed = set()

    for ac in aircraft:
        lat = ac.get("lat")
        lon = ac.get("lon")
        hex_id = ac.get("hex")

        if lat is None or lon is None or not hex_id:
            continue

        try:
            distance = distance_miles(
                LATITUDE, LONGITUDE, float(lat), float(lon)
            )
        except (ValueError, TypeError):
            continue

        if distance > RADIUS_MILES:
            continue

        observed.add(hex_id)

        flight = (ac.get("flight") or "").strip()
        plane_type = ac.get("t") or "Unknown"

        altitude = ac.get("alt_baro")
        if not isinstance(altitude, (int, float)):
            altitude = ac.get("alt_geom")
        if not isinstance(altitude, (int, float)):
            altitude = None

        speed = ac.get("gs")
        speed_mph = (
            round(speed * 1.15078)
            if isinstance(speed, (int, float)) else None
        )

        record = {
            "time": timestamp(),
            "hex": hex_id,
            "flight": flight,
            "type": plane_type,
            "distance_miles": round(distance, 2),
            "altitude_ft": altitude,
            "speed_mph": speed_mph,
            "heading": ac.get("track"),
            "latitude": lat,
            "longitude": lon
        }

        append_csv(SIGHTINGS_FILE, SIGHTING_FIELDS, record)
        total_sightings += 1

        if hex_id not in active:
            active[hex_id] = {
                "first_seen": record["time"],
                "last_seen": record["time"],
                "last_time": now,
                "flight": flight,
                "type": plane_type,
                "closest": distance,
                "altitude": altitude,
                "observations": 0
            }

            print(f"  NEW: {flight or hex_id} "
                  f"at {distance:.1f} miles")

        item = active[hex_id]
        item["last_seen"] = record["time"]
        item["last_time"] = now
        item["observations"] += 1

        if flight:
            item["flight"] = flight

        if distance < item["closest"]:
            item["closest"] = distance
            item["altitude"] = altitude

    # A pass ends when an aircraft hasn't been observed
    # for PASS_TIMEOUT_SECONDS.
    for hex_id in list(active):
        if now - active[hex_id]["last_time"] > PASS_TIMEOUT_SECONDS:
            finish_pass(hex_id)

    return len(observed)


def main():
    global successful_polls

    if not (-90 <= LATITUDE <= 90 and -180 <= LONGITUDE <= 180):
        raise ValueError("Invalid latitude or longitude")

    if LATITUDE == 0.0 and LONGITUDE == 0.0:
        raise ValueError("Enter your grandson's coordinates first")

    print("\nAIRCRAFT TRAFFIC MONITOR")
    print("=" * 45)
    print(f"Location: {LATITUDE}, {LONGITUDE}")
    print(f"Radius: {RADIUS_MILES} miles")
    print(f"Polling: every {POLL_SECONDS} seconds")
    print(f"Started: {timestamp()}")
    print("Press Ctrl+C to stop.\n")

    try:
        while True:
            try:
                aircraft = get_aircraft()
                count = process_aircraft(aircraft)
                successful_polls += 1

                elapsed = datetime.now() - start_time

                print(
                    f"[{datetime.now():%H:%M:%S}] "
                    f"Nearby: {count} | "
                    f"Active: {len(active)} | "
                    f"Completed passes: {completed_passes} | "
                    f"Running: {str(elapsed).split('.')[0]}",
                    flush=True
                )

            except Exception as e:
                print(f"API error: {e}", flush=True)

            time.sleep(POLL_SECONDS)

    except KeyboardInterrupt:
        print("\nStopping monitor...")

    finally:
        for hex_id in list(active):
            finish_pass(hex_id)

        print("\nSESSION SUMMARY")
        print("=" * 45)
        print(f"Successful polls: {successful_polls}")
        print(f"Aircraft observations: {total_sightings}")
        print(f"Recorded passes: {completed_passes}")
        print(f"Data directory: {OUTPUT_DIR.resolve()}")


if __name__ == "__main__":
    main()
