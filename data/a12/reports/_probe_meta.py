"""Read-only probes: mother_mesh meta keys, feature_bundle validity, run meta, label rows.

Run with the venv python. Prints sections to stdout.
"""
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


def dump(obj, indent=2):
    print(json.dumps(obj, indent=indent, ensure_ascii=False, default=str, sort_keys=True))


def section(title: str) -> None:
    print("\n" + "=" * 100)
    print(title)
    print("=" * 100)


def probe_mother_meta(db: Path, limit: int = 4) -> None:
    section(f"mother_mesh meta — {db.relative_to(ROOT)}")
    conn = ro(db)
    try:
        rows = conn.execute(
            "SELECT asset_id, qa_status, meta_json FROM assets WHERE role='mother_mesh' ORDER BY created_at LIMIT ?",
            (limit,),
        ).fetchall()
        n = conn.execute("SELECT COUNT(*) FROM assets WHERE role='mother_mesh'").fetchone()[0]
        print(f"mother_mesh count={n}; showing {len(rows)}")
        for row in rows:
            meta = json.loads(row["meta_json"] or "{}")
            print(f"--- {row['asset_id']} qa={row['qa_status']}")
            print("  top-level keys:", sorted(meta.keys()))
            for key in ("registry_version", "geometry_hash", "vessel_id", "vessel", "run_id",
                        "lineage_id", "profile", "metrics", "data_semantics"):
                if key in meta:
                    value = meta[key]
                    text = json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)
                    print(f"  {key} = {text[:400]}")
    finally:
        conn.close()


def probe_geometry_keys(db: Path) -> None:
    section(f"mother_mesh geometry keys histogram — {db.relative_to(ROOT)}")
    conn = ro(db)
    try:
        rv = Counter()
        has_shortfall = Counter()
        has_target = Counter()
        vessels = Counter()
        for row in conn.execute("SELECT meta_json FROM assets WHERE role='mother_mesh'"):
            meta = json.loads(row["meta_json"] or "{}")
            rv[str(meta.get("registry_version"))] += 1
            vessels[str(meta.get("vessel_id") or meta.get("vessel"))] += 1
            prof = meta.get("profile") if isinstance(meta.get("profile"), dict) else {}
            metrics = (prof or {}).get("metrics") or meta.get("metrics") or {}
            has_target[str("z_rim_target_mm" in metrics)] += 1
            has_shortfall[str("z_rim_shortfall_mm" in metrics)] += 1
        print("registry_version:", dict(rv))
        print("has z_rim_target_mm in metrics:", dict(has_target))
        print("has z_rim_shortfall_mm in metrics:", dict(has_shortfall))
        print("vessels:", dict(vessels))
    finally:
        conn.close()


def probe_feature_arrays(db: Path, limit: int = 3) -> None:
    section(f"feature_bundle payload — {db.relative_to(ROOT)}")
    conn = ro(db)
    try:
        rows = conn.execute(
            "SELECT asset_id, qa_status, files_json, meta_json FROM assets WHERE role='feature_bundle' ORDER BY created_at LIMIT ?",
            (limit,),
        ).fetchall()
        n = conn.execute("SELECT COUNT(*) FROM assets WHERE role='feature_bundle'").fetchone()[0]
        print(f"feature_bundle count={n}; showing {len(rows)}")
        for row in rows:
            files = json.loads(row["files_json"] or "{}")
            npz = ROOT / Path(*str(files.get("arrays", "")).split("/"))
            print(f"--- {row['asset_id']} qa={row['qa_status']} npz={npz.exists()} {npz}")
            if npz.exists():
                import numpy as np

                with np.load(npz, allow_pickle=False) as data:
                    for key in data.files:
                        arr = data[key]
                        print(f"    {key}: shape={arr.shape} dtype={arr.dtype}")
    finally:
        conn.close()


def probe_run_meta(db: Path) -> None:
    section(f"runs meta — {db.relative_to(ROOT)}")
    conn = ro(db)
    try:
        for row in conn.execute("SELECT run_id, status, scope, profile, meta_json FROM runs ORDER BY created_at"):
            meta = json.loads(row["meta_json"] or "{}")
            ds = meta.get("data_semantics")
            print(f"{row['run_id']} status={row['status']} scope={row['scope']} profile={row['profile']} "
                  f"data_semantics={json.dumps(ds, ensure_ascii=False, sort_keys=True) if ds else None}")
            extra = {k: v for k, v in meta.items() if k != "data_semantics"}
            if extra:
                print("    other meta keys:", sorted(extra.keys())[:20])
    finally:
        conn.close()


def probe_release_meta(db: Path) -> None:
    section(f"releases — {db.relative_to(ROOT)}")
    conn = ro(db)
    try:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        if "releases" not in tables:
            print("no releases table")
            return
        for row in conn.execute("SELECT release_id, manifest_hash, scope, profile, manifest_path, meta_json FROM releases"):
            meta = json.loads(row["meta_json"] or "{}")
            print(f"{row['release_id']} scope={row['scope']} profile={row['profile']}")
            print(f"    manifest_path={row['manifest_path']} manifest_hash={row['manifest_hash']}")
            print(f"    meta={json.dumps(meta, ensure_ascii=False, sort_keys=True)[:600]}")
    finally:
        conn.close()


def main() -> None:
    targets = sys.argv[1:] or ["data/a12"]
    for rel in targets:
        db = ROOT / rel / "metadata.sqlite" if (ROOT / rel).is_dir() else ROOT / rel
        if not db.exists():
            print(f"!! missing {db}")
            continue
        probe_run_meta(db)
        probe_mother_meta(db)
        probe_geometry_keys(db)
        probe_feature_arrays(db)
        probe_release_meta(db)


if __name__ == "__main__":
    main()
