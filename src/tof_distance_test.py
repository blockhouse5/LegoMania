import asyncio
from machine import Pin, I2C
from vl53l1x import VL53L1X

async def main():
    i2c = I2C(
        0,
        sda=Pin(6),
        scl=Pin(7),
        freq=400_000,
    )
    addresses = i2c.scan()
    print("I2C devices:", [hex(a) for a in addresses])
    if 0x29 not in addresses:
        print("Sensor not found. Stop and check the wiring.")
        return
    
    sensor = VL53L1X(i2c)
    sensor.set_distance_mode("short")
    sensor.set_timing_budget(50)
    sensor.set_roi(16, 16)
    sensor.start()

    print("VL53L1X model:", hex(sensor.model_id()))
    print("Aim at a target at least 2 inches away.")
    while True:
        distance_mm = sensor.read()
        if distance_mm is not None:
            distance_inches = distance_mm / 25.4
            print(
                "Distance:", round(distance_inches, 2), "in",
                "| Status:", sensor.status_name(),
            )
        await asyncio.sleep_ms(20)