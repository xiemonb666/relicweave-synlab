"""One-shot: add version="1.1" to the 15 A1-affected register_vessel decorators.

A1 affects exactly V01-V12, V15, V16, V17 (the vessels whose builders call
``common.wall_points``).  The version string is written into every mother meta by
``synlab.mothers.api._wrap_assembly`` and it also changes ``REGISTRY.fingerprint()``, which is
the cheapest possible "old data vs new data" marker.

Idempotent: re-running the script reports the decorators that already carry a version.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]

TARGETS = {
    "synlab/mothers/vessels/group_revolve.py": ["V01", "V02", "V03", "V04", "V05", "V06",
                                                "V07", "V08", "V11", "V12"],
    "synlab/mothers/vessels/group_composite.py": ["V09", "V10", "V15", "V16", "V17"],
}
VERSION = "1.1"


def main() -> int:
    total = 0
    for rel, ids in TARGETS.items():
        path = REPO / rel
        text = path.read_text(encoding="utf-8")
        for vid in ids:
            pattern = re.compile(
                r'(@register_vessel\("' + re.escape(vid) + r'", "[^"]+", param_model=[A-Za-z_]+,\n)')
            match = pattern.search(text)
            if match is None:
                print(f"MISS {vid}: decorator not found in {rel}")
                continue
            head = match.group(1)
            # look ahead a few lines for an existing version=
            tail_start = match.end()
            window = text[tail_start:tail_start + 400]
            if re.search(r'version=', window.split(')\n')[0] if ')\n' in window else window):
                print(f"SKIP {vid}: already carries version")
                continue
            replacement = head + f'                 version="{VERSION}",\n'
            text = text[:match.start()] + replacement + text[match.end():]
            total += 1
            print(f"OK   {vid} -> version={VERSION} ({rel})")
        path.write_text(text, encoding="utf-8")
    print(f"patched {total} decorators")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
