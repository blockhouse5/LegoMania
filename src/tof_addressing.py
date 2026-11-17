import asyncio
from machine import Pin, I2C
from vl53l1x import VL53L1X


SENSOR_SETUP = (
    ("Front left",     0x30, 4),
    ("Front right",    0x31, 5),
    ("Front downward", 0x32, 15),
    ("Rear downward",  0x33, 16),
)


def hex_addresses(addresses):
    return [hex(address) for address in addresses]


async def main():

    # Hold every sensor in shutdown before using the I2C bus.
    shut_pins = []

    for name, address, pin_number in SENSOR_SETUP:
        shut_pin = Pin(pin_number, Pin.OUT, value=0)
        shut_pins.append(shut_pin)

    await asyncio.sleep_ms(50)

    i2c = I2C(
        0,
        sda=Pin(6),
        scl=Pin(7),
        freq=400_000,
    )

    print("All sensors held in shutdown.")
    print("I2C scan:", hex_addresses(i2c.scan()))

    sensors = []

    # Wake and address one sensor at a time.
    for index in range(len(SENSOR_SETUP)):

        name, new_address, pin_number = SENSOR_SETUP[index]
        shut_pin = shut_pins[index]

        print()
        print("Enabling:", name)

        # Release SHUT so the module's pull-up can enable the sensor.
        shut_pin.init(Pin.IN)

        # Allow the sensor to boot at its default address, 0x29.
        await asyncio.sleep_ms(100)

        addresses = i2c.scan()

        print(
            "Before address change:",
            hex_addresses(addresses),
        )

        if 0x29 not in addresses:
            print(
                "ERROR:",
                name,
                "did not appear at 0x29.",
            )
            return

        # This is the only active sensor still using 0x29.
        sensor = VL53L1X(i2c)

        print(
            name,
            "model:",
            hex(sensor.model_id()),
        )

        sensor.set_address(new_address)

        await asyncio.sleep_ms(10)

        addresses = i2c.scan()

        print(
            "After assigning",
            hex(new_address) + ":",
            hex_addresses(addresses),
        )

        if new_address not in addresses:
            print(
                "ERROR:",
                name,
                "did not move to",
                hex(new_address),
            )
            return

        sensors.append((name, new_address, sensor))

    print()
    print("Completed bus scan:")

    completed_scan = i2c.scan()
    print(hex_addresses(completed_scan))

    expected_addresses = {
        address
        for name, address, pin_number in SENSOR_SETUP
    }

    found_addresses = set(completed_scan)

    if found_addresses != expected_addresses:
        print("ERROR: Completed bus does not match.")

        print(
            "Expected:",
            hex_addresses(sorted(expected_addresses)),
        )

        print(
            "Found:",
            hex_addresses(sorted(found_addresses)),
        )

        return

    print(
        "All",
        len(sensors),
        "addresses confirmed.",
    )

    # Apply the Project 7 settings to every sensor.
    for name, address, sensor in sensors:

        sensor.set_distance_mode("short")
        sensor.set_timing_budget(50)
        sensor.set_roi(16, 16)
        sensor.start()

        print(
            name,
            "started at",
            hex(address),
        )

    print()
    print("Four-sensor measurements:")

    latest_readings = [None] * len(sensors)
    latest_status = ["waiting"] * len(sensors)

    while True:

        # Collect any newly available measurements.
        for index in range(len(sensors)):

            name, address, sensor = sensors[index]
            distance_mm = sensor.read()

            if distance_mm is not None:
                latest_readings[index] = distance_mm / 25.4
                latest_status[index] = sensor.status_name()

        output_parts = []

        # Build one clearly labeled output line.
        for index in range(len(sensors)):

            name, address, sensor = sensors[index]
            distance_inches = latest_readings[index]

            if distance_inches is None:
                reading_text = name + ": waiting"
            else:
                reading_text = (
                    name
                    + ": "
                    + str(round(distance_inches, 2))
                    + " in"
                    + " ("
                    + latest_status[index]
                    + ")"
                )

            output_parts.append(reading_text)

        print(" | ".join(output_parts))

        await asyncio.sleep_ms(250)