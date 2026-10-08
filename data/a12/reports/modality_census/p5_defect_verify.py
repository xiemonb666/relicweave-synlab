"""Probe 5: verification of two suspected export defects.

  D1. `tokens` (N,256) may be a deterministic pseudo-broadcast of `token_input` (N,)
      -> carries ~zero information beyond the 768-d block-mean RGB vector.
  D2. `view_pos.npy` may be identically zero in every obs member of every shard
      -> the declared "(u position mm)" channel carries no camera-slide position.

READ-ONLY.
Repro:
  cd C:\\Users\\xiemo\\Desktop\\ShardForge\\relicweave-synlab
  .venv\\Scripts\\python.exe data\\a12\\reports\\modality_census\\p5_defect_verify.py > data\\a12\\reports\\modality_census\\p5_defect_verify.out 2>&1
"""
from __future__ import annotations

import io
import sys
import tarfile
from collections import Counter
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[4]
PKGS = {
    "next_experiment": REPO / "data" / "a12_exports" / "next_experiment" / "training_package",
    "closed_loop": REPO / "data" / "a12_exports" / "closed_loop" / "training_package",
}
TOKEN_DIM = 256


def main() -> int:
    print("=" * 110)
    print("PROBE 5: DEFECT VERIFICATION")
    print("=" * 110)

    # ---------------- D1: token structure ----------------
    print("\n" + "#" * 110)
    print("# D1: IS `tokens` A DETERMINISTIC FUNCTION OF `token_input`?")
    print("#     writer = synlab/storage/export.py:262-274 _token_arrays")
    print("#       tokens[:,k] = flat if k==0 else flat*(1-1e-6*k)   <-- 255 scaled copies")
    print("#" * 110)
    for pkg, root in PKGS.items():
        for npz in sorted((root / "deploy" / "tokens").glob("shard_*.npz")):
            with np.load(npz, allow_pickle=False) as z:
                bases = sorted({k[: -len("__tokens")] for k in z.keys() if k.endswith("__tokens")})
                print(f"\n  {pkg}/{npz.name}: {len(bases)} fragments")
                for base in bases[:2]:
                    tok = np.asarray(z[base + "__tokens"])
                    ti = np.asarray(z[base + "__token_input"])
                    n, d = tok.shape
                    # exact column 0 equality
                    c0 = bool(np.array_equal(tok[:, 0], ti))
                    # predicted matrix
                    pred = np.empty_like(tok)
                    for k in range(d):
                        pred[:, k] = ti if k == 0 else ti * (1.0 - 1e-6 * k)
                    exact = bool(np.array_equal(tok, pred))
                    maxdiff = float(np.abs(tok - pred).max())
                    # how redundant: rank of the row space / distinct column spread
                    col0 = tok[:, 0]
                    # spread of each column relative to col0
                    rel = np.abs(tok - col0[:, None]).max(axis=1)
                    print(f"    {base}")
                    print(f"      tokens shape={tok.shape}  token_input shape={ti.shape}")
                    print(f"      tokens[:,0] == token_input              -> {c0}")
                    print(f"      tokens == predicted scaled-copy matrix  -> {exact}  (max abs diff {maxdiff:.3e})")
                    print(f"      max |tokens[i,:] - tokens[i,0]| over rows -> {float(rel.max()):.6e}"
                          f"  (relative to value magnitude ~{float(np.abs(ti).mean()):.4f})")
                    print(f"      => per-row variation across the 256 dims is {float(rel.max()) / max(float(np.abs(ti).mean()), 1e-12):.3e} "
                          f"of the mean magnitude")
                    # effective rank of tiles: how many independent directions?
                    if n > 1:
                        s = np.linalg.svd(tok - tok.mean(axis=0, keepdims=True), compute_uv=False)
                        s = s[s > 0]
                        print(f"      singular values of centered tokens: n_nonzero={s.size} "
                              f"top3={s[:3].round(6).tolist()}  cond={float(s[0] / s[-1]):.4e}" if s.size else "      all-zero spread")

    # ---------------- D2: view_pos zeros ----------------
    print("\n" + "#" * 110)
    print("# D2: IS `view_pos.npy` IDENTICALLY ZERO EVERYWHERE?")
    print("#     writer = synlab/storage/export.py:345")
    print("#       meta_view.get('u_position_mm', 0.0)   <-- silent 0.0 default")
    print("#" * 110)
    for pkg, root in PKGS.items():
        tot = nzero = 0
        vals = []
        for tar in sorted((root / "deploy" / "obs").glob("shard_*.tar")):
            with tarfile.open(tar, "r") as tf:
                for m in tf.getmembers():
                    if not m.name.endswith("view_pos.npy"):
                        continue
                    arr = np.load(io.BytesIO(tf.extractfile(m).read()), allow_pickle=False)
                    tot += 1
                    if not arr.any():
                        nzero += 1
                    vals.append(arr)
                    print(f"  {pkg}/{tar.name}:{m.name}  shape={arr.shape} dtype={arr.dtype} "
                          f"min={arr.min()} max={arr.max()} all_zero={not bool(arr.any())}")
        if tot:
            allv = np.concatenate(vals)
            print(f"\n  {pkg}: view_pos members={tot}  all-zero members={nzero}  "
                  f"({nzero / tot:.1%})  global min={allv.min()} max={allv.max()} n_unique={np.unique(allv).size}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
