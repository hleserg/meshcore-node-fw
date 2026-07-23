#!/usr/bin/env python3
"""Verify a flashed node answers the companion protocol over the hardware UART.

    pip install meshcore
    python scripts/selftest.py COM5          # Windows
    python scripts/selftest.py /dev/ttyUSB0  # Linux / macOS

Wire the USB-UART adapter to the header pins (3.3 V levels, 115200 8N1):

    T114 (nRF52840, header P1)     V4 (ESP32-S3, header J3)
      GPIO9  (P0.09) RX <- TX        GPIO47 RX <- TX
      GPIO10 (P0.10) TX -> RX        GPIO48 TX -> RX
      GND               <-> GND      GND       <-> GND

A successful run prints the node's self-info (public key, firmware version,
radio settings). Those radio values come from the node's runtime preferences -
nothing about the frequency plan is baked into the firmware.
"""

import argparse
import asyncio
import sys

try:
    from meshcore import MeshCore
except ImportError:
    sys.exit("meshcore is not installed - run: pip install meshcore")


async def run(port: str, baudrate: int, debug: bool) -> int:
    print(f"opening {port} @ {baudrate} ...", flush=True)
    mc = await MeshCore.create_serial(port, baudrate, debug=debug)
    try:
        if not mc.is_connected:
            print("connected, but the node never answered - check RX/TX wiring", file=sys.stderr)
            return 1

        info = mc.self_info
        if not info:
            print("no self-info in the reply", file=sys.stderr)
            return 1

        print("\nself-info:")
        for key in sorted(info):
            print(f"  {key:<20} {info[key]}")
        print("\nOK - the companion protocol is alive on the hardware UART.")
        return 0
    finally:
        await mc.disconnect()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("port", help="serial port of the USB-UART adapter, e.g. COM5 or /dev/ttyUSB0")
    ap.add_argument("-b", "--baudrate", type=int, default=115200)
    ap.add_argument("-d", "--debug", action="store_true", help="dump the raw framed traffic")
    args = ap.parse_args()
    return asyncio.run(run(args.port, args.baudrate, args.debug))


if __name__ == "__main__":
    sys.exit(main())
