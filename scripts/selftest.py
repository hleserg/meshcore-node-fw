#!/usr/bin/env python3
"""Verify a flashed node answers the companion protocol over the hardware UART.

    pip install meshcore
    python scripts/selftest.py COM5          # Windows
    python scripts/selftest.py /dev/ttyUSB0  # Linux / macOS

The port is the USB-UART ADAPTER's port, not the board's USB port.

THE DETECT PIN MUST BE HIGH. The companion firmware picks its transport once at
boot: with detect low it comes up on BLE (T114) or as a WiFi access point (V4)
and will not answer on the wire at all. Pull detect to 3.3 V, reboot the node,
and check the boot banner over the board's USB port says HARDWARE UART before
running this.

Wiring - 3.3 V levels, 115200 8N1, RX of the board to TX of the adapter:

    T114 (nRF52840), header P1        V4 (ESP32-S3), header J2
      GND     P1 pin 4                  GND     J2 pin 1
      DETECT  P1 pin 8   GPIO33         DETECT  J2 pin 12  GPIO33   <- 3.3 V
      RX      P1 pin 12  GPIO9          RX      J2 pin 13  GPIO47   <- adapter TX
      TX      P1 pin 13  GPIO10         TX      J2 pin 14  GPIO48   -> adapter RX

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
            print(
                "the port opened but the node never answered.\n"
                "  1. is the detect pin actually HIGH? with it low the node is on BLE / WiFi\n"
                "     and says nothing on the wire - check the boot banner over the board's USB\n"
                "  2. RX and TX swapped (this is most of the remaining cases)\n"
                "  3. no common ground between the adapter and the board",
                file=sys.stderr,
            )
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
