"""Convert a PNG or JPEG into a raw big-endian RGB565 display image.

Usage:
    python make_rgb565_splash.py input.png output.rgb565 WIDTH HEIGHT

The source is resized to fill the requested display without distortion. Any
excess at the edges is cropped from the center.
"""

import sys
from pathlib import Path

from PIL import Image, ImageOps


def rgb565_bytes(image):
    output = bytearray()

    for red, green, blue in image.getdata():
        value = (
            ((red & 0xF8) << 8)
            | ((green & 0xFC) << 3)
            | (blue >> 3)
        )
        output.append((value >> 8) & 0xFF)
        output.append(value & 0xFF)

    return output


def main():
    if len(sys.argv) != 5:
        raise SystemExit(
            "Usage: python make_rgb565_splash.py "
            "input.png output.rgb565 WIDTH HEIGHT"
        )

    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    width = int(sys.argv[3])
    height = int(sys.argv[4])

    with Image.open(input_path) as source:
        source = source.convert("RGB")
        resized = ImageOps.fit(
            source,
            (width, height),
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        )

    output_path.write_bytes(rgb565_bytes(resized))
    expected_size = width * height * 2
    actual_size = output_path.stat().st_size

    if actual_size != expected_size:
        raise RuntimeError(
            "Expected {} bytes but wrote {}".format(
                expected_size,
                actual_size,
            )
        )

    print(
        "Created {}: {} x {}, {} bytes".format(
            output_path,
            width,
            height,
            actual_size,
        )
    )


if __name__ == "__main__":
    main()
