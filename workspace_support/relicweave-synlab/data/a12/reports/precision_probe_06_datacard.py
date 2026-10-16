"""precision audit probe 06 - training-package data-card precision (dimension 8).

Read only.  Takes a package that ships ``dataset_card.json`` and recomputes a set of the
card's own numbers straight from the package bytes, then reports declaration vs recompute
with the absolute difference.  Which items are checked is data-driven (whatever the card
declares that the probe knows how to recompute), and the count is reported.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[3]


def sha256_file(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--package", required=True)
    ap.add_argument("--out", default="data/a12/reports/precision_probe_06_datacard.json")
    ap.add_argument("--max-arrays", type=int, default=12)
    args = ap.parse_args()

    pkg = (ROOT / args.package).resolve()
    card_path = pkg / "dataset_card.json"
    if not card_path.exists():
        print(f"no dataset_card.json in {pkg}", file=sys.stderr)
        return 2
    card = json.loads(card_path.read_text(encoding="utf-8"))
    checks: list[dict] = []

    def check(item, declared, measured, note=""):
        diff = None
        if isinstance(declared, (int, float)) and isinstance(measured, (int, float)):
            diff = float(measured) - float(declared)
        checks.append({"item": item, "declared": declared, "recomputed": measured,
                       "abs_diff": diff, "match": (declared == measured) if diff is None
                       else bool(abs(diff) <= 1e-9 * max(1.0, abs(float(declared)))),
                       "note": note})

    # ---- 1. per-file sha256 --------------------------------------------------------
    fdecl = card.get("package", {})
    files = fdecl.get("files") if isinstance(fdecl, dict) else None
    n_hash_ok = n_hash_tot = 0
    if isinstance(files, list):
        for row in files:
            rel = row.get("path")
            if not rel:
                continue
            p = pkg / rel
            if not p.exists():
                continue
            n_hash_tot += 1
            if row.get("sha256") and sha256_file(p) == row["sha256"]:
                n_hash_ok += 1
    if n_hash_tot:
        check("package.files sha256 match count", n_hash_tot, n_hash_ok,
              "declared-vs-recomputed file hashes")

    # ---- 2. parquet column statistics ---------------------------------------------
    import pandas as pd
    cols = card.get("columns", {})
    if isinstance(cols, dict):
        for rel, spec in list(cols.items()):
            p = pkg / rel
            if not p.exists() or not rel.endswith(".parquet"):
                continue
            df = pd.read_parquet(p)
            declared_rows = spec.get("rows")
            if declared_rows is not None:
                check(f"{rel}: rows", int(declared_rows), int(len(df)))
            for cname, cspec in (spec.get("columns") or {}).items():
                if cname not in df.columns:
                    continue
                s = df[cname]
                mr = float(s.isna().mean())
                if cspec.get("missing_rate") is not None:
                    check(f"{rel}.{cname}: missing_rate", float(cspec["missing_rate"]),
                          round(mr, 12), "pandas isna mean")
                if cspec.get("n_unique") is not None:
                    try:
                        nu = int(s.nunique(dropna=True))
                    except TypeError:
                        nu = None
                    if nu is not None:
                        check(f"{rel}.{cname}: n_unique", int(cspec["n_unique"]), nu)
                if cspec.get("min") is not None and pd.api.types.is_numeric_dtype(s):
                    check(f"{rel}.{cname}: min", float(cspec["min"]),
                          float(np.nanmin(s.astype(float))))
                if cspec.get("max") is not None and pd.api.types.is_numeric_dtype(s):
                    check(f"{rel}.{cname}: max", float(cspec["max"]),
                          float(np.nanmax(s.astype(float))))
                if cspec.get("mean") is not None and pd.api.types.is_numeric_dtype(s):
                    check(f"{rel}.{cname}: mean", float(cspec["mean"]),
                          float(np.nanmean(s.astype(float))))

    # ---- 3. array statistics: tokens / geometry / obs ------------------------------
    arrays = card.get("arrays", {})
    n_arr_checked = 0
    def arr_block(fam: str, fam_decl):
        nonlocal n_arr_checked
        if not isinstance(fam_decl, dict):
            return
        for key, spec in fam_decl.items():
            if n_arr_checked >= args.max_arrays:
                return
            if not isinstance(spec, dict):
                continue
            shard = spec.get("shard") or spec.get("file")
            ekey = spec.get("array") or spec.get("key") or spec.get("name")
            if not shard or not ekey:
                continue
            path = pkg / shard
            if not path.exists():
                continue
            parts = ekey.split("__")
            if len(parts) != 2:
                continue
            opaque, chan = parts
            try:
                if path.suffix == ".npz":
                    with np.load(path, allow_pickle=False) as z:
                        a = np.asarray(z[ekey]) if ekey in z.files else None
                else:
                    continue
            except Exception:
                continue
            if a is None:
                continue
            n_arr_checked += 1
            if spec.get("dtype") is not None:
                check(f"{fam}:{ekey}: dtype", str(spec["dtype"]), str(a.dtype))
            if spec.get("shape") is not None:
                check(f"{fam}:{ekey}: shape", list(spec["shape"]), list(a.shape))
            if spec.get("true_rate") is not None:
                check(f"{fam}:{ekey}: true_rate", float(spec["true_rate"]),
                      float(np.count_nonzero(a) / a.size))
            if spec.get("nonzero_rate") is not None:
                check(f"{fam}:{ekey}: nonzero_rate", float(spec["nonzero_rate"]),
                      float(np.count_nonzero(a) / a.size))
            if spec.get("missing_rate") is not None and a.dtype.kind == "f":
                check(f"{fam}:{ekey}: missing_rate", float(spec["missing_rate"]),
                      float(np.mean(~np.isfinite(a))))
            if spec.get("min") is not None:
                check(f"{fam}:{ekey}: min", float(spec["min"]), float(np.nanmin(a)))
            if spec.get("max") is not None:
                check(f"{fam}:{ekey}: max", float(spec["max"]), float(np.nanmax(a)))
            if spec.get("effective_rank") is not None and a.ndim == 2:
                sv = np.linalg.svd(a.astype(np.float64), compute_uv=False)
                check(f"{fam}:{ekey}: effective_rank(1e-3)", int(spec["effective_rank"]),
                      int(np.sum(sv > 1e-3 * sv[0])),
                      "rank at 1e-3 relative singular value")
    arr_block("tokens", arrays.get("tokens"))
    arr_block("geometry", arrays.get("geometry"))
    arr_block("obs", arrays.get("obs"))

    # ---- 4. honesty boundaries declared by the card --------------------------------
    hb = card.get("honest_boundaries")
    hb_summary = None
    if isinstance(hb, list):
        hb_summary = {row.get("id"): row.get("status") for row in hb if isinstance(row, dict)}

    out = {"package": args.package, "n_checks": len(checks),
           "n_match": int(sum(1 for c in checks if c["match"])),
           "n_mismatch": int(sum(1 for c in checks if not c["match"])),
           "honest_boundaries": hb_summary,
           "checks": checks}
    (ROOT / args.out).write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print("wrote", args.out)
    print(json.dumps({k: v for k, v in out.items() if k != "checks"}, indent=2,
                     ensure_ascii=False))
    for c in checks:
        if not c["match"]:
            print("MISMATCH:", json.dumps(c, ensure_ascii=False))
    for c in checks[:25]:
        print("ok?" if c["match"] else "BAD", json.dumps(c, ensure_ascii=False)[:220])
    return 0


if __name__ == "__main__":
    sys.exit(main())
