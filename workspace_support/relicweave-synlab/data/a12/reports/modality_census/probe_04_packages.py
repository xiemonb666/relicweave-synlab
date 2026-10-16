"""Probe 04: training/export package structure + table schemas (READ ONLY)."""
from __future__ import annotations
import json, tarfile, collections, sys
from pathlib import Path
import numpy as np

ROOT = Path(r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab")
OUT = ROOT / "data" / "a12" / "reports" / "modality_census"
PKGS = {
    "next_experiment": ROOT / "data" / "a12_exports" / "next_experiment" / "training_package",
    "closed_loop": ROOT / "data" / "a12_exports" / "closed_loop" / "training_package",
}

L = []
w = L.append


def walk(pkg: Path, label: str) -> None:
    w("=" * 100)
    w(f"## PACKAGE {label}  root={pkg}")
    if not pkg.exists():
        w("  MISSING")
        return
    files = sorted([p for p in pkg.rglob("*") if p.is_file()])
    w(f"  files={len(files)}  total_MB={sum(p.stat().st_size for p in files)/1e6:.1f}")
    for p in files:
        rel = p.relative_to(pkg).as_posix()
        w(f"    {rel:60s} {p.stat().st_size/1e6:10.3f} MB")
    w("")
    # every json
    for p in files:
        rel = p.relative_to(pkg).as_posix()
        if p.suffix == ".json":
            try:
                j = json.loads(p.read_text(encoding="utf-8"))
            except Exception as e:  # noqa: BLE001
                w(f"  -- {rel}: json error {e}")
                continue
            w(f"  -- {rel}  top-keys={sorted(j)[:40] if isinstance(j, dict) else type(j).__name__}")
            s = json.dumps(j, ensure_ascii=False, default=str)
            w(f"     body[:1500]: {s[:1500]}")
            w("")
    # parquet
    try:
        import pandas as pd
        for p in files:
            if p.suffix == ".parquet":
                try:
                    df = pd.read_parquet(p)
                except Exception as e:  # noqa: BLE001
                    w(f"  -- {p.name}: parquet read failed {e}")
                    continue
                rel = p.relative_to(pkg).as_posix()
                w(f"  -- {rel}  rows={len(df)} cols={len(df.columns)}")
                w(f"     columns: {list(df.columns)}")
                w(f"     dtypes: {dict(df.dtypes.astype(str))}")
                w(f"     head3: {df.head(3).to_dict('records')}")
                w("")
    except ImportError as e:
        w(f"  pandas unavailable: {e}")
    # npz shards
    for p in files:
        if p.suffix == ".npz":
            rel = p.relative_to(pkg).as_posix()
            try:
                with np.load(p, allow_pickle=False) as z:
                    w(f"  -- {rel}  keys={len(z.files)}")
                    for k in z.files[:120]:
                        a = z[k]
                        w(f"       {k:44s} {str(a.shape):26s} {a.dtype}")
                    if len(z.files) > 120:
                        w(f"       ... {len(z.files)-120} more keys")
            except Exception as e:  # noqa: BLE001
                w(f"  -- {rel}: npz read failed {e}")
            w("")
    # tar members
    for p in files:
        if p.suffix == ".tar":
            rel = p.relative_to(pkg).as_posix()
            try:
                with tarfile.open(p, "r") as tf:
                    names = tf.getnames()
                w(f"  -- {rel}  members={len(names)}")
                for n in names[:40]:
                    w(f"       {n}")
                if len(names) > 40:
                    w(f"       ... {len(names)-40} more")
                # suffix histogram
                suf = collections.Counter(Path(n).suffix for n in names)
                w(f"       suffix histogram: {dict(suf)}")
            except Exception as e:  # noqa: BLE001
                w(f"  -- {rel}: tar read failed {e}")
            w("")


for label, pkg in PKGS.items():
    walk(pkg, label)

txt = "\n".join(L)
(OUT / "probe_04_packages.txt").write_text(txt, encoding="utf-8")
print(txt[:20000])
print(f"\n...wrote probe_04_packages.txt ({len(txt)} chars)")
