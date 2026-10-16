"""Probe: locate the store that owns the next-experiment release assets."""
import os
import sqlite3
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TARGETS = ["asset_027cb9b9a8c031c86ba7"]
found: list[tuple[str, int]] = []
for db in sorted(REPO.glob("data/**/metadata.sqlite")):
    try:
        con = sqlite3.connect(str(db))
    except Exception as exc:                                  # noqa: BLE001
        print(f"{db}: open failed {exc}")
        continue
    try:
        total = con.execute("SELECT COUNT(1) FROM assets").fetchone()[0]
    except Exception as exc:                                  # noqa: BLE001
        print(f"{db}: no assets table ({exc})")
        con.close()
        continue
    hits = []
    for target in TARGETS:
        try:
            n = con.execute("SELECT COUNT(1) FROM assets WHERE asset_id = ?",
                            (target,)).fetchone()[0]
        except Exception:                                     # noqa: BLE001
            n = -1
        hits.append(n)
    runs = []
    try:
        runs = con.execute("SELECT COUNT(1) FROM runs").fetchone()[0]
    except Exception:                                         # noqa: BLE001
        runs = -1
    print(f"{db.relative_to(REPO)}: assets={total} runs={runs} target_hits={hits}")
    if any(n > 0 for n in hits):
        found.append((str(db), total))
    con.close()
print("--- owners ---")
for path, total in found:
    print(path, total)
