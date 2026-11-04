"""MicroPython driver for the ST VL53L1X time-of-flight sensor.

Course version for LEGO Project Lab, Project 7.

The initialization values and register procedures are derived from the
STMicroelectronics VL53L1X Ultra Lite Driver distributed under the BSD
3-Clause license. Copyright (c) 2018 STMicroelectronics.

This adaptation provides a small MicroPython API and nonblocking reads for
programs that share the interpreter with other asyncio tasks.
"""

import time


DEFAULT_ADDRESS = 0x29
EXPECTED_MODEL_ID = 0xEACC

SHORT = 1
LONG = 2

# Registers used by the course driver.
_I2C_ADDRESS = 0x0001
_VHV_TIMEOUT = 0x0008
_GPIO_MUX = 0x0030
_GPIO_STATUS = 0x0031
_PHASECAL_TIMEOUT = 0x004B
_TIMEOUT_A = 0x005E
_VCSEL_A = 0x0060
_TIMEOUT_B = 0x0061
_VCSEL_B = 0x0063
_VALID_PHASE_HIGH = 0x0069
_WOI_SD0 = 0x0078
_INITIAL_PHASE_SD0 = 0x007A
_ROI_CENTER = 0x007F
_ROI_SIZE = 0x0080
_INTERRUPT_CLEAR = 0x0086
_MODE_START = 0x0087
_RANGE_STATUS = 0x0089
_RANGE_MM = 0x0096
_OPTICAL_CENTER = 0x013E
_MODEL_ID = 0x010F


# ST Ultra Lite Driver defaults for registers 0x002D through 0x0087.
_DEFAULT_CONFIGURATION = bytes((
    0x00, 0x00, 0x00, 0x01, 0x02, 0x00, 0x02, 0x08, 0x00,
    0x08, 0x10, 0x01, 0x01, 0x00, 0x00, 0x00, 0x00, 0xFF,
    0x00, 0x0F, 0x00, 0x00, 0x00, 0x00, 0x00, 0x20, 0x0B,
    0x00, 0x00, 0x02, 0x0A, 0x21, 0x00, 0x00, 0x05, 0x00,
    0x00, 0x00, 0x00, 0xC8, 0x00, 0x00, 0x38, 0xFF, 0x01,
    0x00, 0x08, 0x00, 0x00, 0x01, 0xCC, 0x0F, 0x01, 0xF1,
    0x0D, 0x01, 0x68, 0x00, 0x80, 0x08, 0xB8, 0x00, 0x00,
    0x00, 0x00, 0x0F, 0x89, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x01, 0x0F, 0x0D, 0x0E, 0x0E, 0x00, 0x00,
    0x02, 0xC7, 0xFF, 0x9B, 0x00, 0x00, 0x00, 0x01, 0x00,
    0x00,
))


_TIMING_BUDGETS_SHORT = {
    15: (0x001D, 0x0027),
    20: (0x0051, 0x006E),
    33: (0x00D6, 0x006E),
    50: (0x01AE, 0x01E8),
    100: (0x02E1, 0x0388),
    200: (0x03E1, 0x0496),
    500: (0x0591, 0x05C1),
}

_TIMING_BUDGETS_LONG = {
    20: (0x001E, 0x0022),
    33: (0x0060, 0x006E),
    50: (0x00AD, 0x00C6),
    100: (0x01CC, 0x01EA),
    200: (0x02D9, 0x02F8),
    500: (0x048F, 0x04A4),
}

_BUDGET_FROM_REGISTER = {
    0x001D: 15,
    0x0051: 20,
    0x001E: 20,
    0x00D6: 33,
    0x0060: 33,
    0x01AE: 50,
    0x00AD: 50,
    0x02E1: 100,
    0x01CC: 100,
    0x03E1: 200,
    0x02D9: 200,
    0x0591: 500,
    0x048F: 500,
}

# Status numbers returned by ST's Ultra Lite Driver.
STATUS_NAMES = {
    0: "valid",
    1: "sigma check failed",
    2: "signal check failed",
    3: "minimum range clipped",
    4: "outside valid phase",
    5: "hardware failure",
    6: "range underflow",
    7: "wraparound",
    9: "crosstalk failure",
    10: "synchronization interrupt",
    11: "range overflow",
    12: "target blurred",
    13: "minimum range failure",
    255: "unknown",
}

_STATUS_FROM_RAW = {
    9: 0,
    6: 1,
    4: 2,
    8: 3,
    5: 4,
    3: 5,
    19: 6,
    7: 7,
    12: 9,
    18: 10,
    22: 11,
    23: 12,
    13: 13,
}


class VL53L1X:
    """VL53L1X interface using a configured MicroPython I2C object."""

    def __init__(self, i2c, address=DEFAULT_ADDRESS, timeout_ms=1000):
        self.i2c = i2c
        self.address = address
        self.last_status = 255
        self._timeout_ms = timeout_ms

        model_id = self.model_id()
        if model_id != EXPECTED_MODEL_ID:
            raise RuntimeError(
                "VL53L1X model ID was %s, expected 0xeacc" % hex(model_id)
            )

        self._write_block(0x002D, _DEFAULT_CONFIGURATION)
        self.start()
        self._wait_until_ready()
        self.clear_interrupt()
        self.stop()

        # Use two VHV loops and retain the previous temperature calibration.
        self._write_u8(_VHV_TIMEOUT, 0x09)
        self._write_u8(0x000B, 0x00)

    def _write_u8(self, register, value):
        self.i2c.writeto_mem(
            self.address, register, bytes((value & 0xFF,)), addrsize=16
        )

    def _write_u16(self, register, value):
        self.i2c.writeto_mem(
            self.address,
            register,
            bytes(((value >> 8) & 0xFF, value & 0xFF)),
            addrsize=16,
        )

    def _write_block(self, register, values):
        self.i2c.writeto_mem(
            self.address, register, values, addrsize=16
        )

    def _read_u8(self, register):
        return self.i2c.readfrom_mem(
            self.address, register, 1, addrsize=16
        )[0]

    def _read_u16(self, register):
        data = self.i2c.readfrom_mem(
            self.address, register, 2, addrsize=16
        )
        return (data[0] << 8) | data[1]

    def _wait_until_ready(self):
        start = time.ticks_ms()
        while not self.data_ready():
            if time.ticks_diff(time.ticks_ms(), start) >= self._timeout_ms:
                raise RuntimeError("VL53L1X measurement timed out")
            time.sleep_ms(2)

    def model_id(self):
        return self._read_u16(_MODEL_ID)

    def start(self):
        self._write_u8(_MODE_START, 0x40)

    def stop(self):
        self._write_u8(_MODE_START, 0x00)

    def clear_interrupt(self):
        self._write_u8(_INTERRUPT_CLEAR, 0x01)

    def data_ready(self):
        mux = self._read_u8(_GPIO_MUX)
        interrupt_polarity = 0 if (mux & 0x10) else 1
        return (self._read_u8(_GPIO_STATUS) & 0x01) == interrupt_polarity

    def read(self):
        """Return a new distance in millimeters, or None if none is ready.

        The completed measurement's status is stored in ``last_status``.
        Reading also clears the sensor interrupt so that the next measurement
        can update.
        """
        if not self.data_ready():
            return None

        raw_status = self._read_u8(_RANGE_STATUS) & 0x1F
        distance_mm = self._read_u16(_RANGE_MM)
        self.last_status = _STATUS_FROM_RAW.get(raw_status, 255)
        self.clear_interrupt()
        return distance_mm

    def status_name(self):
        return STATUS_NAMES.get(self.last_status, "unknown")

    def get_distance_mode(self):
        value = self._read_u8(_PHASECAL_TIMEOUT)
        if value == 0x14:
            return SHORT
        if value == 0x0A:
            return LONG
        return 0

    def set_distance_mode(self, mode):
        """Select SHORT/"short" or LONG/"long" ranging mode."""
        if mode == "short":
            mode = SHORT
        elif mode == "long":
            mode = LONG

        if mode not in (SHORT, LONG):
            raise ValueError("distance mode must be SHORT or LONG")

        budget = self.get_timing_budget()

        if mode == SHORT:
            self._write_u8(_PHASECAL_TIMEOUT, 0x14)
            self._write_u8(_VCSEL_A, 0x07)
            self._write_u8(_VCSEL_B, 0x05)
            self._write_u8(_VALID_PHASE_HIGH, 0x38)
            self._write_u16(_WOI_SD0, 0x0705)
            self._write_u16(_INITIAL_PHASE_SD0, 0x0606)
        else:
            self._write_u8(_PHASECAL_TIMEOUT, 0x0A)
            self._write_u8(_VCSEL_A, 0x0F)
            self._write_u8(_VCSEL_B, 0x0D)
            self._write_u8(_VALID_PHASE_HIGH, 0xB8)
            self._write_u16(_WOI_SD0, 0x0F0D)
            self._write_u16(_INITIAL_PHASE_SD0, 0x0E0E)

        self.set_timing_budget(budget)

    def get_timing_budget(self):
        return _BUDGET_FROM_REGISTER.get(self._read_u16(_TIMEOUT_A), 0)

    def set_timing_budget(self, milliseconds):
        """Set one of ST's supported measurement timing budgets."""
        mode = self.get_distance_mode()
        choices = _TIMING_BUDGETS_SHORT if mode == SHORT else _TIMING_BUDGETS_LONG
        if milliseconds not in choices:
            raise ValueError(
                "unsupported timing budget for this distance mode"
            )
        timeout_a, timeout_b = choices[milliseconds]
        self._write_u16(_TIMEOUT_A, timeout_a)
        self._write_u16(_TIMEOUT_B, timeout_b)

    def set_roi(self, width, height):
        """Set a centered 4x4 through 16x16 SPAD region of interest."""
        if not 4 <= width <= 16 or not 4 <= height <= 16:
            raise ValueError("ROI width and height must be from 4 through 16")

        optical_center = self._read_u8(_OPTICAL_CENTER)
        if width > 10 or height > 10:
            optical_center = 199

        self._write_u8(_ROI_CENTER, optical_center)
        self._write_u8(_ROI_SIZE, ((height - 1) << 4) | (width - 1))

    def get_roi(self):
        value = self._read_u8(_ROI_SIZE)
        return ((value & 0x0F) + 1, ((value >> 4) & 0x0F) + 1)

    def set_address(self, new_address):
        """Change this powered sensor's seven-bit I2C address."""
        if not 0x08 <= new_address <= 0x77:
            raise ValueError("I2C address must be from 0x08 through 0x77")
        self._write_u8(_I2C_ADDRESS, new_address)
        self.address = new_address

