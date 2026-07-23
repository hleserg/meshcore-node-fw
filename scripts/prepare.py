#!/usr/bin/env python3
"""Prepare the vendored MeshCore checkout for building.

Steps:
  1. make sure the submodule is checked out at its pinned commit
  2. apply every patch in patches/ (skipping ones already applied)
  3. copy pio/meshcore-node-fw.ini -> external/MeshCore/platformio.local.ini
     (MeshCore's root platformio.ini already includes it via `extra_configs`)

Idempotent: safe to run repeatedly. `--reset` throws away any local edits inside
the submodule first, which is what CI wants.
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MESHCORE = ROOT / "external" / "MeshCore"
PATCH_DIR = ROOT / "patches"
INI_SRC = ROOT / "pio" / "meshcore-node-fw.ini"
INI_DST = MESHCORE / "platformio.local.ini"


def run(cmd, **kw):
    kw.setdefault("check", True)
    print("+", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run(cmd, **kw)


def git_meshcore(*args, **kw):
    return run(["git", "-C", str(MESHCORE), *args], **kw)


def patch_state(patch: Path) -> str:
    """'applied', 'pending' or 'broken'."""
    common = ["git", "-C", str(MESHCORE), "apply", "--check"]
    quiet = {"capture_output": True, "check": False}
    if subprocess.run([*common, str(patch)], **quiet).returncode == 0:
        return "pending"
    if subprocess.run([*common, "--reverse", str(patch)], **quiet).returncode == 0:
        return "applied"
    return "broken"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--reset",
        action="store_true",
        help="discard local changes in external/MeshCore before patching",
    )
    args = ap.parse_args()

    if not (MESHCORE / "platformio.ini").is_file():
        print("external/MeshCore is empty - run: git submodule update --init --recursive")
        return 1

    if args.reset:
        git_meshcore("reset", "--hard")
        git_meshcore("clean", "-fd")

    for patch in sorted(PATCH_DIR.glob("*.patch")):
        state = patch_state(patch)
        if state == "applied":
            print(f"  = {patch.name} already applied")
        elif state == "pending":
            git_meshcore("apply", "--whitespace=nowarn", str(patch))
            print(f"  + {patch.name} applied")
        else:
            print(
                f"  ! {patch.name} does not apply cleanly to "
                f"the pinned MeshCore checkout - refresh the patch",
                file=sys.stderr,
            )
            return 1

    shutil.copyfile(INI_SRC, INI_DST)
    print(f"  > {INI_SRC.name} -> {INI_DST.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
