"""Probe 6: a12_trainable SQLite census + search for any real training-run artifacts.

READ-ONLY (sqlite opened read-only via URI).
Repro:
  cd C:\\Users\\xiemo\\Desktop\\ShardForge\\relicweave-synlab
  .venv\\Scripts\\python.exe data\\a12\\reports\\modality_census\\p6_trainable.py > data\\a12\\reports\\modality_census\\p6_trainable.out 2>&1
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
TR = REPO / "data" / "a12_trainable"


def main() -> int:
    print("=" * 110)
    print("PROBE 6: data/a12_trainable LAYOUT, SQLITE CENSUS, TRAINING-ARTIFACT SEARCH")
    print("=" * 110)

    # ---- layout summary ----
    allf = [p for p in TR.rglob("*") if p.is_file()]
    print(f"\nroot: {TR}")
    print(f"TOTAL FILES = {len(allf):,}   TOTAL BYTES = {sum(p.stat().st_size for p in allf):,}")
    print("\nPER TOP-LEVEL DIR:")
    for d in sorted([p for p in TR.iterdir()]):
        if d.is_dir():
            fs = [p for p in d.rglob("*") if p.is_file()]
            print(f"  {d.name+'/':<14} files={len(fs):<6} bytes={sum(p.stat().st_size for p in fs):>15,}")
        else:
            print(f"  {d.name:<14} (file) bytes={d.stat().st_size:,}")
    print("\nstore/ SUBDIRS:")
    for d in sorted([p for p in (TR / "store").iterdir()]):
        if d.is_dir():
            fs = [p for p in d.rglob("*") if p.is_file()]
            print(f"  store/{d.name+'/':<14} files={len(fs):<6} bytes={sum(p.stat().st_size for p in fs):>15,}")

    # ---- sqlite ----
    db = TR / "store" / "metadata.sqlite"
    print("\n" + "=" * 110)
    print(f"SQLITE: {db}  ({db.stat().st_size:,} bytes)")
    print("=" * 110)
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    cur = con.cursor()
    tabs = [r[0] for r in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
    print(f"  tables ({len(tabs)}): {tabs}")
    for t in tabs:
        n = cur.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        print(f"\n  TABLE {t}: rows={n:,}")
        cols = cur.execute(f'PRAGMA table_info("{t}")').fetchall()
        print(f"    columns ({len(cols)}):")
        for c in cols:
            print(f"      {c[1]:<28} {c[2]:<12} notnull={c[3]} pk={c[5]}")
        # distribution of a few interesting columns
        for probe in ("status", "kind", "role", "split", "asset_type", "qa_status", "state"):
            names = [c[1] for c in cols]
            if probe in names:
                try:
                    rows = cur.execute(
                        f'SELECT "{probe}", COUNT(*) FROM "{t}" GROUP BY 1 ORDER BY 2 DESC LIMIT 20'
                    ).fetchall()
                    print(f"    value counts [{probe}]: {rows}")
                except Exception as e:  # noqa: BLE001
                    print(f"    [{probe}] error {e!r}")

    # explicit asset count
    for t in tabs:
        try:
            n = cur.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            if "asset" in t.lower():
                print(f"\n  *** asset-ish table '{t}' row count = {n:,} ***")
        except Exception:  # noqa: BLE001
            pass
    con.close()

    # count on-disk asset dirs
    ad = TR / "store" / "assets"
    dirs = [d for d in ad.iterdir() if d.is_dir()]
    print(f"\n  on-disk store/assets/ dirs = {len(dirs):,}")
    kinds = {}
    for d in dirs:
        for p in d.iterdir():
            kinds[p.suffix or p.name] = kinds.get(p.suffix or p.name, 0) + 1
    print(f"  file-kind histogram inside asset dirs = {kinds}")

    # ---- search for real training artifacts ----
    print("\n" + "=" * 110)
    print("TRAINING-ARTIFACT SEARCH under data/a12_trainable (checkpoint/optimizer/loss/epoch)")
    print("=" * 110)
    pats = ["*.pt", "*.pth", "*.ckpt", "*.safetensors", "*.onnx", "*.bin", "*optim*", "*loss*",
            "*epoch*", "*train*", "*checkpoint*", "*metric*", "*curve*", "*history*"]
    found = {}
    for pat in pats:
        hits = sorted(TR.rglob(pat))
        hits = [h for h in hits if h.is_file()]
        if hits:
            found[pat] = hits
            print(f"\n  pattern {pat!r}: {len(hits)} hit(s)")
            for h in hits[:10]:
                print(f"    {h.stat().st_size:>12,}  {h.relative_to(TR).as_posix()}")
    if not found:
        print("  NONE FOUND: no checkpoint / optimizer / loss / epoch / metric / curve artifact "
              "exists anywhere in data/a12_trainable.")

    # ---- which files mention epochs/loss at all ----
    print("\n  files whose CONTENT mentions 'epoch' or 'loss' (text scan):")
    n_hit = 0
    for p in allf:
        if p.suffix.lower() not in (".json", ".log", ".txt", ".py", ".yaml", ".yml", ".md"):
            continue
        try:
            txt = p.read_text(encoding="utf-8", errors="ignore").lower()
        except Exception:  # noqa: BLE001
            continue
        if "epoch" in txt or "loss" in txt:
            n_hit += 1
            print(f"    {p.stat().st_size:>10,}  {p.relative_to(TR).as_posix()}")
            if n_hit >= 25:
                print("    ... (truncated)")
                break
    if n_hit == 0:
        print("    (none)")

    # ---- other report jsons in the repo that reference this store ----
    print("\n" + "=" * 110)
    print("RELATED repo reports for this store (data/a12/reports/*trainable*)")
    print("=" * 110)
    for p in sorted((REPO / "data" / "a12" / "reports").glob("*trainable*")):
        print(f"  {p.stat().st_size:>10,}  {p.relative_to(REPO).as_posix()}")
        try:
            o = json.loads(p.read_text(encoding="utf-8"))
            print(f"      keys: {sorted(o.keys()) if isinstance(o, dict) else type(o).__name__}")
        except Exception as e:  # noqa: BLE001
            print(f"      (not json: {e!r})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
