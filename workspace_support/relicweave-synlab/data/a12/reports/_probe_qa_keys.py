"""Census of qa_json keys for mother_mesh / physical_result / visible_labels."""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def ro(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def main() -> None:
    rel = sys.argv[1]
    role = sys.argv[2]
    db = ROOT / rel / "metadata.sqlite"
    conn = ro(db)
    try:
        keys: Counter = Counter()
        samples = 0
        for row in conn.execute("SELECT qa_json FROM assets WHERE role=?", (role,)):
            qa = json.loads(row["qa_json"] or "{}")
            samples += 1
            for key in qa:
                keys[key] += 1
            checks = qa.get("checks") if isinstance(qa.get("checks"), dict) else {}
            for key in checks:
                keys[f"checks.{key}"] += 1
        print(f"{rel} role={role} n={samples}")
        for key, count in sorted(keys.items()):
            print(f"   {key}: {count}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
