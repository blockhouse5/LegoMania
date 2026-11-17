"""Lesson 11: four VL53L1X sensors and an Adafruit 240x240 monitor.

LEGO Lab: stop tof_addressing.py, then run this program (async main).
Thonny: import rover_sensor_monitor; rover_sensor_monitor.run()
Required on the ESP32: vl53l1x.py and st7789_240x240.py.
This program owns the sensors and display; it does not control motors.
"""
import asyncio
import time
from machine import Pin, I2C, SPI
from vl53l1x import VL53L1X
from st7789_240x240 import ST7789_240X240, rgb565

SENSOR_SETUP = (
    ("Front left", 0x30, 4),
    ("Front right", 0x31, 5),
    ("Front down", 0x32, 15),
    ("Rear down", 0x33, 16),
)
REFRESH_MS = 250
STALE_MS = 1000
BLACK = rgb565(0, 0, 0)
WHITE = rgb565(255, 255, 255)
CYAN = rgb565(80, 220, 255)
YELLOW = rgb565(255, 210, 40)
RED = rgb565(255, 80, 80)
GRAY = rgb565(80, 90, 100)


def make_display():
    spi = SPI(1, baudrate=20_000_000, polarity=0, phase=0,
              sck=Pin(12), mosi=Pin(11))
    return ST7789_240X240(spi, cs=Pin(10, Pin.OUT),
                         dc=Pin(8, Pin.OUT), rst=Pin(9, Pin.OUT),
                         rotation=0, bgr=False)


def describe(record, now):
    """Only fresh status-0 measurements are displayed as usable inches."""
    if record["error"]:
        return "--", "I2C ERROR", RED
    stamp = record["stamp"]
    if stamp is None:
        return "--", "WAITING", YELLOW
    if time.ticks_diff(now, stamp) > STALE_MS:
        return "--", "STALE", YELLOW
    if record["status"] != 0:
        return "--", "INVALID S{}".format(record["status"]), YELLOW
    return "{:.2f} in".format(record["mm"] / 25.4), "VALID", WHITE


async def main():
    display = make_display()
    display.fill(BLACK)
    display.text("ROVER SENSOR MONITOR", 8, 8, CYAN)
    display.text("Assigning addresses...", 8, 35, WHITE)
    print("Sensor monitor: starting. Stop other sensor/display programs.")
    shut_pins = []
    sensors = []
    try:
        for name, address, gpio in SENSOR_SETUP:
            shut_pins.append(Pin(gpio, Pin.OUT, value=0))
        await asyncio.sleep_ms(50)
        i2c = I2C(0, sda=Pin(6), scl=Pin(7), freq=400_000)
        if i2c.scan():
            raise RuntimeError("Bus not empty with all sensors shut down")
        for index, (name, address, gpio) in enumerate(SENSOR_SETUP):
            shut_pins[index].init(Pin.IN)  # release to board pull-up
            await asyncio.sleep_ms(100)
            if 0x29 not in i2c.scan():
                raise RuntimeError(name + " missing at 0x29")
            sensor = VL53L1X(i2c)
            model = sensor.model_id()
            if model != 0xEACC:
                raise RuntimeError(name + " wrong model " + hex(model))
            sensor.set_address(address)
            sensors.append(sensor)
            if address not in i2c.scan():
                raise RuntimeError(name + " address assignment failed")
            print(name, hex(address), "model", hex(model))
            await asyncio.sleep_ms(10)
        scan = i2c.scan()
        print("Completed scan:", [hex(a) for a in scan])
        if set(scan) != {row[1] for row in SENSOR_SETUP}:
            raise RuntimeError("Final I2C scan does not match setup")
        for sensor in sensors:
            sensor.set_distance_mode("short")
            sensor.set_timing_budget(50)
            sensor.set_roi(16, 16)
            sensor.start()

        records = [dict(mm=None, status=None, stamp=None, error=False)
                   for _ in sensors]
        previous = [None] * len(sensors)
        display.fill(BLACK)
        display.text("ROVER SENSOR MONITOR", 8, 7, CYAN)
        for i, (name, address, gpio) in enumerate(SENSOR_SETUP):
            y = 30 + i * 46
            display.fill_rect(6, y - 3, 228, 1, GRAY)
            display.text(name + " " + hex(address), 8, y, CYAN)
        display.text("OBSERVE ONLY - NO MOTORS", 8, 222, CYAN)
        last_draw = time.ticks_ms()
        last_print = last_draw
        while True:
            for i, sensor in enumerate(sensors):
                rec = records[i]
                try:
                    mm = sensor.read()  # None means no new result yet
                    if mm is not None:
                        rec["mm"] = mm
                        rec["status"] = sensor.last_status
                        rec["stamp"] = time.ticks_ms()
                        rec["error"] = False
                except OSError as error:
                    if not rec["error"]:
                        print(SENSOR_SETUP[i][0], "I2C error:", error)
                    rec["error"] = True
                await asyncio.sleep_ms(0)
            now = time.ticks_ms()
            if time.ticks_diff(now, last_draw) >= REFRESH_MS:
                for i, rec in enumerate(records):
                    value, status, color = describe(rec, now)
                    screen = (value, status, color)
                    if screen != previous[i]:
                        y = 30 + i * 46
                        display.fill_rect(8, y + 12, 224, 30, BLACK)
                        display.text(value, 8, y + 13, color, scale=2)
                        display.text(status, 8, y + 33, color)
                        previous[i] = screen
                last_draw = now
            if time.ticks_diff(now, last_print) >= 2000:
                for i, rec in enumerate(records):
                    value, status, color = describe(rec, now)
                    detail = sensors[i].status_name() if rec["stamp"] is not None else "waiting"
                    print(SENSOR_SETUP[i][0], value, status,
                          "| raw mm:", rec["mm"], "|", detail)
                last_print = now
            await asyncio.sleep_ms(20)
    except Exception as error:
        display.fill(BLACK)
        display.text("SENSOR SETUP ERROR", 8, 10, RED)
        message = str(error)
        for i in range(0, min(len(message), 168), 28):
            display.text(message[i:i+28], 8, 38 + (i // 28) * 15, WHITE)
        display.text("See LEGO Lab Output", 8, 190, YELLOW)
        print("Sensor monitor error:", error)
        raise
    finally:
        for sensor in sensors:
            try:
                sensor.stop()
            except Exception:
                pass
            await asyncio.sleep_ms(0)
        for pin in shut_pins:
            pin.init(Pin.OUT, value=0)


def run():
    """For Thonny/standalone use only, not inside LEGO Lab's event loop."""
    asyncio.run(main())
