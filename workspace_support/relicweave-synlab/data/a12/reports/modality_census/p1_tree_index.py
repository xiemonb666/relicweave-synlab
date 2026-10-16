"""Probe 1: full package tree + index/manifest JSON schemas.

READ-ONLY. Writes nothing; prints a report to stdout (redirect to a file).
Repro:
  cd C:\\Users\\xiemo\\Desktop\\ShardForge\\relicweave-synlab
  .venv\\Scripts\\python.exe data\\a12\\reports\\modality_census\\p1_tree_index.py > data\\a12\\reports\\modality_census\\p1_tree_index.out 2>&1
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# script lives at <repo>/data/a12/reports/modality_census/p1_tree_index.py
REPO = Path(__file__).resolve().parents[4]
PKGS = {
    "next_experiment": REPO / "data" / "a12_exports" / "next_experiment" / "training_package",
    "closed_loop": REPO / "data" / "a12_exports" / "closed_loop" / "training_package",
}


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f}{unit}" if unit != "B" else f"{n}B"
        n /= 1024.0
    return f"{n:.1f}GB"


def walk(root: Path):
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for fn in sorted(filenames):
            p = Path(dirpath) / fn
            try:
                st = p.stat()
            except OSError:
                continue
            out.append((p.relative_to(root).as_posix(), st.st_size))
    out.sort(key=lambda t: t[0])
    return out


def schema_of(obj, prefix="", depth=0, maxdepth=3):
    """Recursively describe a JSON object's schema keys."""
    rows = []
    if depth > maxdepth:
        return rows
    if isinstance(obj, dict):
        for k in sorted(obj.keys()):
            v = obj[k]
            t = type(v).__name__
            extra = ""
            if isinstance(v, list):
                extra = f" len={len(v)}"
                if v and isinstance(v[0], (dict, list)):
                    extra += f" elem0={type(v[0]).__name__}"
            elif isinstance(v, dict):
                extra = f" keys={len(v)}"
            elif isinstance(v, (int, float, str, bool)) or v is None:
                s = repr(v)
                extra = f" = {s if len(s) <= 70 else s[:67] + '...'}"
            rows.append(f"    {prefix}{k}  <{t}>{extra}")
            if isinstance(v, dict) and depth + 1 <= maxdepth:
                rows.extend(schema_of(v, prefix + k + ".", depth + 1, maxdepth))
    elif isinstance(obj, list):
        rows.append(f"    {prefix}<list> len={len(obj)}")
    return rows


def main() -> int:
    print("=" * 100)
    print("PROBE 1: PACKAGE TREE + INDEX/MANIFEST JSON")
    print("=" * 100)
    print(f"repo root: {REPO}")

    for name, root in PKGS.items():
        print("\n" + "=" * 100)
        print(f"PACKAGE: {name}")
        print(f"path: {root}")
        print("=" * 100)
        if not root.is_dir():
            print("  MISSING DIRECTORY")
            continue

        files = walk(root)
        total = sum(s for _, s in files)
        print(f"\nFILE COUNT = {len(files)}   TOTAL BYTES = {total} ({human(total)})")

        # full listing with sizes
        print(f"\n--- FULL RELATIVE FILE LISTING ({len(files)} files) ---")
        for rel, size in files:
            print(f"  {size:>12,}  {rel}")

        # suffix / dir rollups
        print("\n--- ROLLUP BY TOP DIRECTORY ---")
        buckets: dict[str, list[int]] = {}
        for rel, size in files:
            top = rel.split("/")[0] if "/" in rel else "<root>"
            buckets.setdefault(top, []).append(size)
        for k in sorted(buckets):
            v = buckets[k]
            print(f"  {k:<28} files={len(v):<6} bytes={sum(v):>14,}  ({human(sum(v))})")

        print("\n--- ROLLUP BY SUFFIX ---")
        suf: dict[str, list[int]] = {}
        for rel, size in files:
            s = Path(rel).suffix.lower() or "<none>"
            suf.setdefault(s, []).append(size)
        for k in sorted(suf):
            v = suf[k]
            print(f"  {k:<14} files={len(v):<6} bytes={sum(v):>14,}")

        # all json files
        jsons = [rel for rel, _ in files if rel.lower().endswith(".json")]
        print(f"\n--- JSON FILES ({len(jsons)}) ---")
        for rel in jsons:
            print(f"  {rel}")

        # dump each json schema
        print("\n--- JSON SCHEMA KEYS + ROW COUNTS ---")
        for rel in jsons:
            p = root / rel
            try:
                with p.open("r", encoding="utf-8") as fh:
                    obj = json.load(fh)
            except Exception as e:  # noqa: BLE001
                print(f"\n  [{rel}]  PARSE ERROR: {e!r}")
                continue
            print(f"\n  [{rel}]  size={p.stat().st_size:,} bytes  toplevel={type(obj).__name__}")
            if isinstance(obj, dict):
                print(f"    TOPLEVEL KEYS ({len(obj)}): {sorted(obj.keys())}")
                print("    SCHEMA:")
                for line in schema_of(obj, maxdepth=3):
                    print(line)
                # row counts: any key that looks like a count/list of rows
                print("    ROW-COUNT-LIKE KEYS:")
                for k in sorted(obj.keys()):
                    v = obj[k]
                    lk = k.lower()
                    if isinstance(v, list):
                        print(f"      {k}: list len={len(v)}")
                    elif isinstance(v, int) and not isinstance(v, bool):
                        if any(t in lk for t in ("count", "rows", "n_", "num", "total", "size", "len", "shard")):
                            print(f"      {k}: int = {v}")
                    elif isinstance(v, dict) and any(
                        t in lk for t in ("count", "rows", "n_", "num", "total", "shard", "channels")
                    ):
                        print(f"      {k}: dict keys={sorted(v.keys())}")
            elif isinstance(obj, list):
                print(f"    LIST len={len(obj)}")
                if obj and isinstance(obj[0], dict):
                    print(f"    elem0 keys: {sorted(obj[0].keys())}")
                    print(f"    elem0: {json.dumps(obj[0], indent=2)[:1500]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
