"""Probe: which store root holds the next-experiment assets?"""
import os
import sqlite3

TARGET = "asset_027cb9b9a8c031c86ba7"
for path in ("data/a12/metadata.sqlite", "data/a12/store/metadata.sqlite"):
    if not os.path.exists(path):
        print(path, "MISSING")
        continue
    con = sqlite3.connect(path)
    try:
        total = con.execute("SELECT COUNT(1) FROM assets").fetchone()[0]
        hit = con.execute("SELECT COUNT(1) FROM assets WHERE asset_id = ?", (TARGET,)).fetchone()[0]
        print(f"{path}: assets={total} has_target={hit} bytes={os.path.getsize(path)}")
        rows = con.execute(
            "SELECT role, COUNT(1) FROM assets GROUP BY role ORDER BY role").fetchall()
        print("   roles:", rows)
    except Exception as exc:                                  # noqa: BLE001
        print(path, "ERR", type(exc).__name__, exc)
    finally:
        con.close()
print("--- listing ---")
for directory in ("data/a12", "data/a12/store"):
    print(directory, sorted(os.listdir(directory))[:14])
