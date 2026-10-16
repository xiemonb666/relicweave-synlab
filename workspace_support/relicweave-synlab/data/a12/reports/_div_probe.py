"""Probe: find every synlab store on disk and dump its role census + meta key samples.

Read-only.  Writes nothing except stdout.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def stores() -> list[Path]:
    out = []
    for db in sorted(ROOT.joinpath("data").rglob("metadata.sqlite")):
        # the store db lives at <store_root>/metadata.sqlite
        out.append(db.parent)
    return out


def probe(root: Path) -> dict:
    db = root / "metadata.sqlite"
    info: dict = {"store": str(root.relative_to(ROOT)).replace("\\", "/")}
    try:
        conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
    except Exception as exc:
        return {**info, "error": f"{type(exc).__name__}: {exc}"}
    try:
        roles = conn.execute("SELECT role, COUNT(*) n FROM assets GROUP BY role ORDER BY n DESC")
        info["roles"] = {r["role"]: r["n"] for r in roles}
        info["assets_total"] = conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
        info["blobs_total"] = conn.execute("SELECT COUNT(*) FROM blobs").fetchone()[0]
        lin = conn.execute(
            "SELECT COUNT(DISTINCT lineage_id) FROM assets WHERE lineage_id IS NOT NULL")
        info["lineages"] = lin.fetchone()[0]
        # one sample meta per role, keys only
        samples: dict[str, list[str]] = {}
        for role in info["roles"]:
            row = conn.execute(
                "SELECT meta_json, qa_json FROM assets WHERE role=? LIMIT 1", (role,)).fetchone()
            meta = json.loads(row["meta_json"] or "{}")
            qa = json.loads(row["qa_json"] or "{}")
            samples[role] = {
                "meta_keys": sorted(meta.keys()),
                "qa_keys": sorted(qa.keys()),
            }
        info["samples"] = samples
    except Exception as exc:
        info["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        conn.close()
    return info


def main() -> int:
    only = sys.argv[1:] or None
    out = []
    for root in stores():
        rel = str(root.relative_to(ROOT)).replace("\\", "/")
        if only and not any(o in rel for o in only):
            continue
        out.append(probe(root))
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
