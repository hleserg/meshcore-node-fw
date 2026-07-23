#!/usr/bin/env python3
"""Build the meshcore-node-fw firmwares and collect flashable artifacts.

    python scripts/build.py t114     -> dist/t114-companion.uf2
    python scripts/build.py v4       -> dist/v4-factory.bin  + dist/manifest.json
    python scripts/build.py all

The version stamped into the firmware (and reported over the companion protocol
in the self-info response) comes from $FIRMWARE_VERSION, defaulting to "dev".
Used unchanged by CI, so a local build and a release build are the same build.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MESHCORE = ROOT / "external" / "MeshCore"
DIST = ROOT / "dist"

TARGETS = {
    "t114": {
        "env": "t114_companion_serial",
        "platform": "nrf52",
        "artifact": "t114-companion.uf2",
        "label": "Heltec T114 (nRF52840)",
    },
    "v4": {
        "env": "v4_companion_serial",
        "platform": "esp32",
        "artifact": "v4-factory.bin",
        "label": "Heltec WiFi LoRa 32 V4 (ESP32-S3)",
    },
}

# uf2conv family id for the nRF52840
UF2_FAMILY_NRF52840 = "0xADA52840"


def run(cmd, env=None, cwd=MESHCORE):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run(cmd, cwd=str(cwd), env=env, check=True)


def pio(*args, env=None):
    run([sys.executable, "-m", "platformio", *args], env=env)


def version_string() -> str:
    version = os.environ.get("FIRMWARE_VERSION", "dev")
    sha = subprocess.run(
        ["git", "-C", str(MESHCORE), "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    return f"{version}-{sha}" if sha else version


def build_env(env_vars: dict) -> dict:
    """Environment for the pio subprocess, carrying the version defines."""
    build_date = time.strftime("%d-%b-%Y")
    flags = (
        f"{os.environ.get('PLATFORMIO_BUILD_FLAGS', '')} "
        f"-DFIRMWARE_VERSION=\\\"{version_string()}\\\" "
        f"-DFIRMWARE_BUILD_DATE=\\\"{build_date}\\\""
    ).strip()
    env = dict(os.environ)
    env["PLATFORMIO_BUILD_FLAGS"] = flags
    env.update(env_vars)
    return env


def build_t114(spec):
    out = DIST / spec["artifact"]
    pio("run", "-e", spec["env"], env=build_env({}))
    hex_file = MESHCORE / ".pio" / "build" / spec["env"] / "firmware.hex"
    if not hex_file.is_file():
        sys.exit(f"expected {hex_file} after the build")
    # create-uf2.py's custom target writes to $UF2_FILE_PATH; call uf2conv
    # directly so the path handling is identical on Windows and Linux.
    run(
        [
            sys.executable,
            str(MESHCORE / "bin" / "uf2conv" / "uf2conv.py"),
            str(hex_file),
            "-c",
            "-o",
            str(out),
            "-f",
            UF2_FAMILY_NRF52840,
        ]
    )
    return out


def build_v4(spec):
    out = DIST / spec["artifact"]
    env = build_env({"MERGED_BIN_PATH": str(out)})
    pio("run", "-e", spec["env"], env=env)
    # merge-bin.py combines bootloader + partitions + boot_app0 + app into one
    # image that starts at flash offset 0 - which is what ESP Web Tools needs.
    pio("run", "-t", "mergebin", "-e", spec["env"], env=env)
    if not out.is_file():
        sys.exit(f"expected {out} after mergebin")
    return out


def write_manifest(version: str):
    manifest = {
        "name": "MeshCore Companion (UART) - Heltec V4",
        "version": version,
        "new_install_prompt_erase": True,
        "builds": [
            {
                "chipFamily": "ESP32-S3",
                "parts": [{"path": "v4-factory.bin", "offset": 0}],
            }
        ],
    }
    path = DIST / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"  > wrote {path.relative_to(ROOT)}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("targets", nargs="+", choices=[*TARGETS, "all"])
    args = ap.parse_args()

    names = list(TARGETS) if "all" in args.targets else args.targets
    DIST.mkdir(exist_ok=True)

    run([sys.executable, str(ROOT / "scripts" / "prepare.py")], cwd=ROOT)

    for name in names:
        spec = TARGETS[name]
        print(f"\n=== {spec['label']} -> {spec['artifact']} ===", flush=True)
        out = build_t114(spec) if name == "t114" else build_v4(spec)
        print(f"  > {out.relative_to(ROOT)} ({out.stat().st_size} bytes)")
        if name == "v4":
            write_manifest(version_string())

    return 0


if __name__ == "__main__":
    sys.exit(main())
