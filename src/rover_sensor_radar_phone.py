"""Lesson 11: three VL53L1X channels on an Adafruit 240x240 ST7789.

Run in LEGO Project Lab via async main(). Observation only; no motors.
Requires vl53l1x.py and st7789_240x240.py on the ESP32.
Read-only sensor feed: http://rover.local:8080/sensors
"""
import asyncio
import time
import json
from machine import Pin, I2C, SPI
from vl53l1x import VL53L1X
from st7789_240x240 import ST7789_240X240, rgb565

FRONT_DOWN_FITTED = False  # Set True on a rover with front-down on GPIO15.
SENSORS = (
    ("Front left", 0x30, 4),
    ("Front right", 0x31, 5),
)
if FRONT_DOWN_FITTED:
    SENSORS += (("Front down", 0x32, 15),)

SENSOR_KEYS = ("front_left", "front_right", "front_down", "rear_down")
PLOT_RANGE_IN = 24
EDGE_THRESHOLD_IN = 3.0  # Starting point; check on your assembled rover.
STALE_MS = 1000
REFRESH_MS = 150

BLACK = rgb565(0, 0, 0)
WHITE = rgb565(245, 248, 250)
GRAY = rgb565(70, 92, 109)
CYAN = rgb565(80, 220, 255)
YELLOW = rgb565(255, 212, 70)
GREEN = rgb565(80, 230, 140)
RED = rgb565(255, 85, 85)


def result(record, now):
    mm, status, stamp, error = record
    if error:
        return None, "I2C ERROR"
    if stamp is None:
        return None, "WAITING"
    if time.ticks_diff(now, stamp) > STALE_MS:
        return None, "STALE"
    if status != 0 or mm <= 0:
        return None, "INVALID"
    return mm / 25.4, "VALID"


def sensor_packet(records, now):
    readings = {}
    for i, key in enumerate(SENSOR_KEYS):
        if i >= len(records):
            readings[key] = {"inches": None, "status": "not fitted", "age_ms": None}
            continue
        record = records[i]
        inches, status = result(record, now)
        stamp = record[2]
        age = None if stamp is None else max(0, time.ticks_diff(now, stamp))
        readings[key] = {"inches": inches, "status": status.lower(), "age_ms": age}
    return {"units": "inches", "sensors": readings, "thresholds": {
        "forward_stop": 2.5, "forward_warning": 6.0, "edge_stop": EDGE_THRESHOLD_IN,
    }}


async def request_header(reader):
    data = b""
    while len(data) < 2048:
        chunk = await reader.read(min(256, 2048 - len(data)))
        if not chunk:
            break
        data += chunk
        if b"\r\n\r\n" in data:
            return data.split(b"\r\n", 1)[0].split()
    return ()


async def serve_client(reader, writer, records):
    try:
        request = await asyncio.wait_for_ms(request_header(reader), 1000)
        if len(request) != 3:
            status, body = "400 Bad Request", b'{"error":"bad request"}'
        elif request[0] != b"GET":
            status, body = "405 Method Not Allowed", b'{"error":"read only"}'
        elif request[1] != b"/sensors":
            status, body = "404 Not Found", b'{"error":"use /sensors"}'
        else:
            status = "200 OK"
            body = json.dumps(sensor_packet(records, time.ticks_ms())).encode()
        header = ("HTTP/1.1 {}\r\nContent-Type: application/json\r\n"
                  "Cache-Control: no-store\r\nConnection: close\r\n"
                  "Content-Length: {}\r\n\r\n").format(status, len(body))
        writer.write(header.encode() + body)
        await asyncio.wait_for_ms(writer.drain(), 1000)
    except (OSError, asyncio.TimeoutError):
        pass
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass


def marker_position(side, inches):
    # Screen coordinates are schematic, not a measured bearing.
    offset = round(52 * inches / PLOT_RANGE_IN)
    rise = round(108 * inches / PLOT_RANGE_IN)
    return 120 + side * (13 + offset), 149 - rise


def forward_view(side, inches, state):
    if inches is None:
        return None, state, YELLOW
    if inches > PLOT_RANGE_IN:
        return None, "BEYOND PLOT", GRAY
    return marker_position(side, inches), "RETURN", CYAN


def floor_view(inches):
    if inches is None:
        return "UNKNOWN", YELLOW
    if inches >= EDGE_THRESHOLD_IN:
        return "EDGE", RED
    return "FLOOR", GREEN


def draw_background(display):
    display.fill(BLACK)
    display.text("ROVER RADAR", 32, 8, CYAN, scale=2)
    display.text("LEFT", 42, 29, WHITE)
    display.text("RIGHT", 158, 29, WHITE)
    for y in (41, 68, 95, 122, 149):
        display.fill_rect(27, y, 12, 1, GRAY)
        display.fill_rect(201, y, 12, 1, GRAY)
    for y in range(41, 146, 8):
        display.fill_rect(120, y, 1, 3, GRAY)
    display.fill_rect(112, 156, 17, 10, CYAN)
    display.fill_rect(118, 152, 5, 4, CYAN)
    display.fill_rect(8, 189, 224, 1, GRAY)
    display.text("REAR SENSOR NOT FITTED", 8, 225, GRAY)


def draw_forward(display, index, previous, current):
    if previous == current:
        return
    if previous and previous[0] and previous[0] != current[0]:
        x, y = previous[0]
        display.fill_rect(x - 3, y - 3, 7, 7, BLACK)
    point, label, color = current
    if point and (not previous or previous[0] != point):
        x, y = point
        display.fill_rect(x - 2, y - 3, 5, 7, color)
        display.fill_rect(x - 3, y - 2, 7, 5, color)
    if not previous or previous[1:] != current[1:]:
        x = 8 + 116 * index
        display.fill_rect(x, 172, 108, 12, BLACK)
        display.text(label, x, 174, color)


async def main():
    pins = []
    sensors = []
    display = None
    server = None
    try:
        spi = SPI(1, baudrate=20_000_000, polarity=0, phase=0,
                  sck=Pin(12), mosi=Pin(11))
        display = ST7789_240X240(spi, cs=Pin(10, Pin.OUT),
                                 dc=Pin(8, Pin.OUT), rst=Pin(9, Pin.OUT),
                                 rotation=0, bgr=False)
        display.fill(BLACK)
        display.text("Assigning addresses...", 8, 35, WHITE)

        # Hold every fitted module low, then release one at a time.
        for name, address, gpio in SENSORS:
            pins.append(Pin(gpio, Pin.OUT, value=0))
        await asyncio.sleep_ms(200)
        bus = I2C(0, sda=Pin(6), scl=Pin(7), freq=100_000)
        if bus.scan():
            raise RuntimeError("Bus not empty with sensors off")
        expected = []
        for index, (name, address, gpio) in enumerate(SENSORS):
            pins[index].init(Pin.IN)  # Let the module pull SHUT high.
            await asyncio.sleep_ms(200)
            if 0x29 not in bus.scan():
                raise RuntimeError(name + " missing at 0x29")
            sensor = VL53L1X(bus)
            if sensor.model_id() != 0xEACC:
                raise RuntimeError(name + " incorrect model ID")
            sensor.set_address(address)
            sensors.append(sensor)
            expected.append(address)
            if sorted(bus.scan()) != expected:
                raise RuntimeError(name + " address check failed")
            print(name, "GPIO", gpio, "at", hex(address))
        print("Final scan:", [hex(a) for a in bus.scan()])

        for sensor in sensors:
            sensor.set_distance_mode("short")
            sensor.set_timing_budget(50)
            sensor.set_roi(16, 16)
            sensor.start()

        records = [(None, None, None, False) for _ in sensors]
        async def handle_client(reader, writer):
            await serve_client(reader, writer, records)

        try:
            server = await asyncio.start_server(handle_client, "0.0.0.0", 8080, backlog=2)
            print("Read-only feed: http://rover.local:8080/sensors")
        except OSError as exc:
            print("Port 8080 did not start; onboard radar still running:", exc)
        previous = [None, None]
        previous_floor = None
        draw_background(display)
        last_print = time.ticks_ms()
        last_draw = time.ticks_add(last_print, -REFRESH_MS)

        while True:
            for i, sensor in enumerate(sensors):
                try:
                    mm = sensor.read()
                    if mm is not None:
                        records[i] = (mm, sensor.last_status, time.ticks_ms(), False)
                except OSError as exc:
                    mm, status, stamp, error = records[i]
                    if not error:
                        print(SENSORS[i][0], "I2C error:", exc)
                    records[i] = (mm, status, stamp, True)
                await asyncio.sleep_ms(0)

            now = time.ticks_ms()
            if time.ticks_diff(now, last_draw) >= REFRESH_MS:
                for i in (0, 1):
                    inches, state = result(records[i], now)
                    current = forward_view(-1 if i == 0 else 1, inches, state)
                    draw_forward(display, i, previous[i], current)
                    previous[i] = current
                floor = (floor_view(result(records[2], now)[0])
                         if FRONT_DOWN_FITTED else ("NOT FITTED", GRAY))
                if floor != previous_floor:
                    display.fill_rect(8, 195, 224, 21, BLACK)
                    display.text(floor[0], 8, 197, floor[1], scale=2)
                    previous_floor = floor
                last_draw = now

            if time.ticks_diff(now, last_print) >= 2000:
                for i, record in enumerate(records):
                    inches, state = result(record, now)
                    shown = "--" if inches is None else "{:.2f} in".format(inches)
                    print(SENSORS[i][0], shown, state, "| raw mm:", record[0],
                          "| status:", record[1])
                last_print = now
            await asyncio.sleep_ms(20)
    except Exception as exc:
        print("Rover radar error:", exc)
        if display is not None:
            display.fill(BLACK)
            display.text("ROVER RADAR ERROR", 8, 10, RED)
            message = str(exc)
            for i in range(0, min(len(message), 168), 28):
                display.text(message[i:i + 28], 8, 36 + (i // 28) * 14, WHITE)
            display.text("See LEGO Lab Output", 8, 153, YELLOW)
        raise
    finally:
        for pin in pins:
            pin.init(Pin.OUT, value=0)
        if server is not None:
            server.close()
            await server.wait_closed()
