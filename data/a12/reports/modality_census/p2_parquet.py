"""Probe 2: every .parquet in both packages -- rows, cols, dtypes, low-cardinality value counts.

READ-ONLY.
Repro:
  cd C:\\Users\\xiemo\\Desktop\\ShardForge\\relicweave-synlab
  .venv\\Scripts\\python.exe data\\a12\\reports\\modality_census\\p2_parquet.py > data\\a12\\reports\\modality_census\\p2_parquet.out 2>&1
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

REPO = Path(__file__).resolve().parents[4]
PKGS = {
    "next_experiment": REPO / "data" / "a12_exports" / "next_experiment" / "training_package",
    "closed_loop": REPO / "data" / "a12_exports" / "closed_loop" / "training_package",
}

# columns the census explicitly asks about
LOWCARD = [
    "loss_mask", "valid", "kind", "passed", "role", "label_layer", "split", "source_kind",
    "association_code", "eligible_as_negative", "has_observation", "unique_source_triangle",
    "ambiguous", "sample_valid", "relation_kind", "target_channel", "target_unit", "status",
]


def fmt_dtype(s: pd.Series) -> str:
    return str(s.dtype)


def _hashable(s: pd.Series) -> pd.Series:
    """Map unhashable element types (dict/list/ndarray) to a stable string key."""
    if s.dtype != object or len(s) == 0:
        return s
    probe = s.dropna()
    if len(probe) == 0:
        return s
    v0 = probe.iloc[0]
    if isinstance(v0, (dict, list, tuple, np.ndarray)):
        return s.map(lambda x: "<NA>" if x is None else json.dumps(
            x.tolist() if isinstance(x, np.ndarray) else x, sort_keys=True, default=str))
    return s


def safe_nunique(s: pd.Series) -> int:
    try:
        return int(s.nunique(dropna=True))
    except TypeError:
        return int(_hashable(s).nunique(dropna=True))


def valcounts(s: pd.Series, maxcard: int = 40, top: int = 40):
    """Value counts for low-cardinality columns."""
    n = len(s)
    if n == 0:
        return ["      (empty column)"]
    try:
        nu = safe_nunique(s)
        vc = _hashable(s).value_counts(dropna=False)
    except Exception as e:  # noqa: BLE001
        return [f"      !! error: {e!r}"]
    out = []
    if nu > maxcard:
        return [f"      (high cardinality: nunique={nu} > {maxcard} -> skipped)"]
    nn = int(s.isna().sum())
    try:
        dl = sorted(map(repr, _hashable(s).dropna().unique()))[:maxcard]
    except Exception:  # noqa: BLE001
        dl = ["<unprintable>"]
    out.append(f"      nunique={nu}  n={n}  nulls={nn} ({nn / n:.4%})")
    out.append(f"      distinct_list={dl}")
    for k, v in vc.head(top).items():
        ks = repr(k)
        if len(ks) > 90:
            ks = ks[:87] + "...'"
        out.append(f"        {ks:<42} {v:>10,}  {v / n:>9.4%}")
    return out


def main() -> int:
    print("=" * 110)
    print("PROBE 2: PARQUET TABLES IN BOTH PACKAGES")
    print("=" * 110)
    summary_rows = []

    for pkg, root in PKGS.items():
        print("\n" + "#" * 110)
        print(f"# PACKAGE: {pkg}")
        print("#" * 110)
        if not root.is_dir():
            print("  MISSING")
            continue
        files = sorted(root.rglob("*.parquet"))
        print(f"\n.parquet files found: {len(files)}")

        for p in files:
            rel = p.relative_to(root).as_posix()
            print("\n" + "=" * 110)
            print(f"TABLE: {rel}   ({p.stat().st_size:,} bytes)")
            print("=" * 110)
            pf = pq.ParquetFile(p)
            nrows = pf.metadata.num_rows
            ncols = pf.metadata.num_columns
            nrg = pf.metadata.num_row_groups
            df = pf.read().to_pandas()
            print(f"  ROWS = {nrows:,}   COLS = {ncols}   ROW_GROUPS = {nrg}   (pandas shape={df.shape})")

            print("\n  --- COLUMNS / DTYPES ---")
            for c in df.columns:
                s = df[c]
                extra = ""
                # element type for object/array-ish columns
                if s.dtype == object and len(s) and s.notna().any():
                    v0 = s.dropna().iloc[0]
                    extra = f"  py_elem={type(v0).__name__}"
                    if isinstance(v0, (list, np.ndarray)):
                        extra += f" len0={len(v0)}"
                print(f"    {c:<34} {fmt_dtype(s):<14}{extra}  nunique={safe_nunique(s):,}  nulls={int(s.isna().sum()):,}")

            print("\n  --- LOW-CARDINALITY VALUE COUNTS (requested columns present in this table) ---")
            present = [c for c in LOWCARD if c in df.columns]
            if not present:
                print("    (none of the requested low-card columns present)")
            for c in present:
                print(f"\n    [{c}]  dtype={fmt_dtype(df[c])}")
                for line in valcounts(df[c]):
                    print(line)

            # ---- table specific deep dives ----
            if rel.endswith(("clean.parquet", "physical.parquet", "visible.parquet")):
                print("\n  --- ROLE BREAKDOWN (fragment vs relation) ---")
                if "role" in df.columns:
                    vc = df["role"].value_counts(dropna=False)
                    for k, v in vc.items():
                        print(f"    role={k!r:<20} {v:>10,}  {v / len(df):>9.4%}")
                    print(f"    TOTAL {len(df):,}")
                else:
                    print("    (no 'role' column)")
                # per role x label_layer / kind
                for cross in ("label_layer", "kind", "split", "source_kind"):
                    if "role" in df.columns and cross in df.columns:
                        print(f"\n    crosstab role x {cross}:")
                        ct = pd.crosstab(df["role"], df[cross], dropna=False)
                        print(ct.to_string())
                print("\n  --- area_mm2 DISTRIBUTION ---")
                if "area_mm2" in df.columns:
                    a = pd.to_numeric(df["area_mm2"], errors="coerce")
                    n = int(a.notna().sum())
                    print(f"    n={n}  nulls={int(a.isna().sum())}")
                    if n:
                        q = a.quantile([0, .25, .5, .75, 1.0])
                        print(f"    min={q.loc[0.0]:.6f}  p25={q.loc[.25]:.6f}  median={q.loc[.5]:.6f}  p75={q.loc[.75]:.6f}  max={q.loc[1.0]:.6f}")
                        print(f"    mean={a.mean():.6f}  std={a.std():.6f}  sum={a.sum():.3f}")
                        print(f"    zeros={int((a == 0).sum())}  negatives={int((a < 0).sum())}")
                        # per role
                        if "role" in df.columns:
                            print("    per role:")
                            for r, sub in df.groupby("role", dropna=False):
                                aa = pd.to_numeric(sub["area_mm2"], errors="coerce").dropna()
                                if len(aa):
                                    print(f"      {r!r:<20} n={len(aa):<8} min={aa.min():.4f} median={aa.median():.4f} max={aa.max():.4f}")
                else:
                    print("    (no 'area_mm2' column)")
                print(f"\n  --- ALL COLUMNS WITH FULL DTYPE LIST ---\n    {list(df.columns)}")

            if rel.endswith("correspondence.parquet"):
                print("\n  --- CORRESPONDENCE DEEP DIVE ---")
                print(f"    rows = {len(df):,}")
                if {"fragment_a", "fragment_b"} <= set(df.columns):
                    pairs = df[["fragment_a", "fragment_b"]].apply(tuple, axis=1)
                    print(f"    distinct (fragment_a, fragment_b) pairs = {pairs.nunique():,}")
                    print(f"    distinct fragment_a = {df['fragment_a'].nunique():,}")
                    print(f"    distinct fragment_b = {df['fragment_b'].nunique():,}")
                    print(f"    distinct fragments overall = {pd.unique(pd.concat([df['fragment_a'], df['fragment_b']])).size:,}")
                    print("    top pairs:")
                    for k, v in pairs.value_counts().head(10).items():
                        print(f"      {k}  x{v}")
                else:
                    print(f"    (fragment_a/fragment_b absent; cols={list(df.columns)})")
                if "interface_id" in df.columns:
                    s = df["interface_id"]
                    print(f"\n    interface_id: nunique={s.nunique():,}  nulls={int(s.isna().sum())}")
                    for k, v in s.value_counts(dropna=False).head(30).items():
                        print(f"      {k!r:<30} {v:>8,}")
                    print(f"      n(-1) = {int((s == -1).sum()):,}")
                    print(f"      n(>=0) = {int((s >= 0).sum()):,}")
                if "residual_mm" in df.columns:
                    r = pd.to_numeric(df["residual_mm"], errors="coerce")
                    print(f"\n    residual_mm: n={int(r.notna().sum()):,} nulls={int(r.isna().sum()):,}")
                    print(f"      max={r.max():.6f}  min={r.min():.6f}  median={r.median():.6f}  mean={r.mean():.6f}")
                    print(f"      p90={r.quantile(.9):.6f}  p99={r.quantile(.99):.6f}")
                    if "relation_kind" in df.columns:
                        print("      residual_mm per relation_kind:")
                        for k, sub in df.groupby("relation_kind", dropna=False):
                            rr = pd.to_numeric(sub["residual_mm"], errors="coerce")
                            print(f"        {k!r:<14} n={len(sub):<8} max={rr.max():.6f} median={rr.median():.6f}")
                if "relation_kind" in df.columns:
                    print("\n    per-relation_kind counts:")
                    for k, v in df["relation_kind"].value_counts(dropna=False).items():
                        print(f"      {k!r:<20} {v:>8,}  {v / len(df):>9.4%}")

            if rel.endswith("quality.parquet"):
                print("\n  --- QUALITY DEEP DIVE ---")
                if "target_channel" in df.columns:
                    print("    target_channel values + per-channel row counts:")
                    for k, v in df["target_channel"].value_counts(dropna=False).items():
                        print(f"      {k!r:<40} {v:>8,}  {v / len(df):>9.4%}")
                    print("\n    target_value ranges PER target_channel:")
                    for k, sub in df.groupby("target_channel", dropna=False):
                        if "target_value" in sub.columns:
                            tv = pd.to_numeric(sub["target_value"], errors="coerce")
                            print(f"      channel={k!r:<36} n={len(sub):<8} min={tv.min()} max={tv.max()} median={tv.median()} nulls={int(tv.isna().sum())}")
                if "target_value" in df.columns:
                    tv = pd.to_numeric(df["target_value"], errors="coerce")
                    print(f"\n    target_value overall: n={int(tv.notna().sum()):,} min={tv.min()} max={tv.max()} median={tv.median()} mean={tv.mean()}")

            summary_rows.append((pkg, rel, nrows, ncols))

    print("\n" + "=" * 110)
    print("SUMMARY: ROWS/COLS PER TABLE")
    print("=" * 110)
    print(f"  {'package':<18}{'table':<46}{'rows':>10}{'cols':>7}")
    for pkg, rel, n, c in summary_rows:
        print(f"  {pkg:<18}{rel:<46}{n:>10,}{c:>7}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
