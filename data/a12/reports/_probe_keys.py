"""Census of meta keys per role across stores: which generation markers exist where."""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

INTERESTING = (
    "registry_version", "geometry_hash", "stored_geometry_hash", "profile_metrics",
    "z_rim", "z_rim_target_mm", "z_rim_shortfall_mm", "vessel_name", "builder",
    "data_semantics", "mask_semantics", "damage_semantics", "obs_semantics",
    "subset_instrument", "run_id", "vessel_id", "params", "variant",
)


def ro(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def walk_keys(node, prefix="", out=None, depth=0):
    if out is None:
        out = set()
    if depth > 3 or not isinstance(node, dict):
        return out
    for key, value in node.items():
        out.add(f"{prefix}{key}")
        if isinstance(value, dict):
            walk_keys(value, f"{prefix}{key}.", out, depth + 1)
    return out


def main() -> None:
    targets = sys.argv[1:]
    for rel in targets:
        db = ROOT / rel / "metadata.sqlite"
        if not db.exists():
            print(f"!! missing {db}")
            continue
        print("=" * 96)
        print(rel)
        conn = ro(db)
        try:
            seen: dict[str, Counter] = defaultdict(Counter)
            for row in conn.execute("SELECT role, meta_json, qa_json FROM assets"):
                meta = json.loads(row["meta_json"] or "{}")
                keys = walk_keys(meta)
                for key in keys:
                    seen[row["role"]][key] += 1
            for role in sorted(seen):
                hits = {k: v for k, v in sorted(seen[role].items())
                        if any(tok in k for tok in INTERESTING)}
                print(f"  [{role}] {hits}")
        finally:
            conn.close()


if __name__ == "__main__":
    main()
