# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: CC-BY-NC-4.0

"""
Attach the benchmark data release to this code package.

The code resolves data relative to the package directory
(<pkg>/environments/<env>/..., <pkg>/test_cases/variations/<env>/<case>.json).
This command points those two paths at an unpacked data release, by symlink
(default) or by copy.

Usage:
  python -m prompt_injection_benchmark.scripts.link_data /path/to/pib-data
  python -m prompt_injection_benchmark.scripts.link_data /path/to/pib-data --copy
  python -m prompt_injection_benchmark.scripts.link_data --check
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent
ENVS = ("devops", "marketplace", "productivity")
TARGETS = {
    PKG / "environments": "environments",
    PKG / "test_cases" / "variations": "test_cases",
}


def check() -> bool:
    missing = [dst / env for dst in TARGETS for env in ENVS if not (dst / env).is_dir()]
    for m in missing:
        print(f"missing: {m}")
    if missing:
        return False
    n = sum(1 for env in ENVS for _ in (PKG / "test_cases" / "variations" / env).glob("*.json"))
    print(f"data attached ({n} cases)")
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("data_dir", nargs="?", help="unpacked data release (contains environments/ and test_cases/)")
    ap.add_argument("--copy", action="store_true", help="copy instead of symlink")
    ap.add_argument("--force", action="store_true", help="replace existing links/directories")
    ap.add_argument("--check", action="store_true", help="only check that data is attached")
    args = ap.parse_args()

    if args.check:
        sys.exit(0 if check() else 1)
    if not args.data_dir:
        ap.error("data_dir is required unless --check is given")

    data = Path(args.data_dir).resolve()
    if not (data / "SUMMARY.json").exists():
        ap.error(f"{data} does not look like the data release (no SUMMARY.json)")
    for dst, sub in TARGETS.items():
        src = data / sub
        if not src.is_dir():
            ap.error(f"{src} not found")
        if dst.exists() or dst.is_symlink():
            if not args.force:
                ap.error(f"{dst} already exists (use --force to replace it)")
            if dst.is_symlink() or dst.is_file():
                dst.unlink()
            else:
                shutil.rmtree(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if args.copy:
            shutil.copytree(src, dst)
        else:
            dst.symlink_to(src, target_is_directory=True)
        print(f"{'copied' if args.copy else 'linked'} {dst} -> {src}")
    print(json.dumps(json.loads((data / "SUMMARY.json").read_text())["cases"]))
    sys.exit(0 if check() else 1)


if __name__ == "__main__":
    main()
