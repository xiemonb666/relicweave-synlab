"""Dump full meta/files of selected assets (read-only)."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def ro(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def main() -> None:
    rel = sys.argv[1]
    role = sys.argv[2]
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    db = ROOT / rel / "metadata.sqlite"
    conn = ro(db)
    try:
        rows = conn.execute(
            "SELECT * FROM assets WHERE role=? ORDER BY created_at LIMIT ?", (role, limit)
        ).fetchall()
        for row in rows:
            rec = dict(row)
            for key in ("meta_json", "qa_json", "files_json"):
                try:
                    rec[key] = json.loads(rec[key] or "{}")
                except Exception:  # noqa: BLE001
                    pass
            print(json.dumps(rec, indent=2, ensure_ascii=False, sort_keys=True, default=str))
            print("-" * 90)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
