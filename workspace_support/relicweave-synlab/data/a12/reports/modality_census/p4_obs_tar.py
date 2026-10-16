"""Probe 4: obs tar members, array shapes/dtypes, valid.npy + view_pos.npy, plus
verification of the token broadcast hypothesis and frame_id linearity.

READ-ONLY. Tar members are read in-memory via tarfile.extractfile (nothing is
written to disk). The only file this script may create is a temp scratch file
inside the census dir, and it deletes it immediately.
Repro:
  cd C:\\Users\\xiemo\\Desktop\\ShardForge\\relicweave-synlab
  .venv\\Scripts\\python.exe data\\a12\\reports\\modality_census\\p4_obs_tar.py > data\\a12\\reports\\modality_census\\p4_obs_tar.out 2>&1
"""
from __future__ import annotations

import io
import json
import re
import sys
import tarfile
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[4]
CENSUS = Path(__file__).resolve().parent
PKGS = {
    "next_experiment": REPO / "data" / "a12_exports" / "next_experiment" / "training_package",
    "closed_loop": REPO / "data" / "a12_exports" / "closed_loop" / "training_package",
}
OPAQUE_RE = re.compile(r"^([0-9a-f]{24})/(tiles|valid|view_pos)\.npy$")


def main() -> int:
    print("=" * 110)
    print("PROBE 4: OBS TAR MEMBERS + ARRAY SHAPES/DTYPES + valid/view_pos")
    print("=" * 110)

    for pkg, root in PKGS.items():
        print("\n" + "#" * 110)
        print(f"# PACKAGE: {pkg}")
        print("#" * 110)

        # ---- obs index declared channels ----
        oi = root / "deploy" / "obs" / "index.json"
        if oi.is_file():
            o = json.loads(oi.read_text(encoding="utf-8"))
            print(f"\n  [deploy/obs/index.json] schema={o.get('schema')}")
            print(f"    opaque_naming     = {o.get('opaque_naming')!r}")
            print(f"    channels          = {o.get('channels')}")
            print(f"    forbidden_channels= {o.get('forbidden_channels')}")
            rows = o.get("rows", {})
            print(f"    ROWS (fragment entries) = {len(rows)}")
            shapes = Counter()
            views = Counter()
            shards = Counter()
            tc = Counter()
            for fid, r in rows.items():
                shapes[tuple(r["shape"])] += 1
                views[r["views"]] += 1
                shards[r["shard"]] += 1
                tc[tuple(r["truth_channels"])] += 1
            print(f"    distinct row 'shape' values  = {dict(shapes)}")
            print(f"    distinct row 'views' values  = {dict(views)}")
            print(f"    rows per shard               = {dict(shards)}")
            print(f"    distinct 'truth_channels'    = {dict(tc)}   (empty list == no truth)")
            tot_views = sum(r["views"] for r in rows.values())
            tot_tiles = sum(int(np.prod(r["shape"])) for r in rows.values())
            print(f"    SUM views over rows = {tot_views}   SUM shape-elements = {tot_tiles:,}")

        # ---- tar members ----
        obsd = root / "deploy" / "obs"
        for tar in sorted(obsd.glob("shard_*.tar")):
            print("\n" + "=" * 110)
            print(f"TAR: deploy/obs/{tar.name}   ({tar.stat().st_size:,} bytes)")
            print("=" * 110)
            with tarfile.open(tar, "r") as tf:
                members = tf.getmembers()
                print(f"  members = {len(members)}")
                print(f"  member name lengths: {sorted({len(m.name) for m in members})}")
                # naming convention
                bad = [m.name for m in members if not OPAQUE_RE.match(m.name)]
                print(f"  members NOT matching '<24hex>/(tiles|valid|view_pos).npy': {len(bad)} {bad[:5]}")
                opaques = sorted({m.name.split('/')[0] for m in members})
                suffix = Counter(m.name.split('/')[-1] for m in members)
                print(f"  distinct opaque ids = {len(opaques)}")
                print(f"  suffix histogram    = {dict(suffix)}")
                print(f"  member names (all {len(members)}):")
                for m in members:
                    print(f"    {m.size:>12,}  mtime={m.mtime}  {m.name}")
                print(f"  total member bytes = {sum(m.size for m in members):,}")

                # per-member array shapes/dtypes
                print("\n  PER-MEMBER ARRAY SHAPES/DTYPES:")
                per = defaultdict(lambda: {"shapes": Counter(), "dtypes": Counter(), "stats": []})
                for m in members:
                    suf = m.name.split("/")[-1].replace(".npy", "")
                    fh = tf.extractfile(m)
                    arr = np.load(io.BytesIO(fh.read()), allow_pickle=False)
                    per[suf]["shapes"][str(arr.shape)] += 1
                    per[suf]["dtypes"][str(arr.dtype)] += 1
                    if suf == "valid":
                        per[suf]["stats"].append(float(arr.mean()))
                    elif suf == "view_pos":
                        per[suf]["stats"].append((float(arr.min()), float(arr.max()),
                                                  float(np.median(arr)), float(arr.mean())))
                    elif suf == "tiles":
                        per[suf]["stats"].append((float(arr.min()), float(arr.max())))
                for suf in ("tiles", "valid", "view_pos"):
                    info = per[suf]
                    print(f"    {suf+'.npy':<14} shapes={dict(info['shapes'])}")
                    print(f"    {'':<14} dtypes={dict(info['dtypes'])}")
                    if suf == "valid":
                        s = np.array(info["stats"])
                        print(f"    {'':<14} True_frac over {s.size} members: min={s.min():.6f} "
                              f"mean={s.mean():.6f} max={s.max():.6f}")
                    elif suf == "view_pos":
                        s = np.array(info["stats"])
                        print(f"    {'':<14} view_pos min={s[:,0].min():.6f} max={s[:,1].max():.6f} "
                              f"median_range=[{s[:,2].min():.6f},{s[:,2].max():.6f}] mean_range=[{s[:,3].min():.6f},{s[:,3].max():.6f}]")
                    elif suf == "tiles":
                        s = np.array(info["stats"])
                        print(f"    {'':<14} tiles value range min={s[:,0].min()} max={s[:,1].max()}")

                # detailed dump for the first opaque, and verify valid vs tiles relationship
                first = opaques[0]
                print(f"\n  DETAILED DUMP for opaque={first}:")
                got = {}
                for m in members:
                    if not m.name.startswith(first + "/"):
                        continue
                    arr = np.load(io.BytesIO(tf.extractfile(m).read()), allow_pickle=False)
                    got[m.name.split("/")[-1]] = arr
                    print(f"    {m.name:<50} shape={str(arr.shape):<22} dtype={str(arr.dtype):<8} "
                          f"min={arr.min()} max={arr.max()}")
                v = got["valid.npy"]
                t = got["tiles.npy"]
                vp = got["view_pos.npy"]
                print(f"    valid.npy  True_frac={float(v.mean()):.6f}  n_True={int(v.sum()):,}/{v.size:,}")
                print(f"    valid.npy  per-view True counts = {v.reshape(v.shape[0], -1).sum(axis=1).tolist()}")
                print(f"    view_pos.npy dtype={vp.dtype} shape={vp.shape} "
                      f"min={vp.min()} max={vp.max()} median={np.median(vp)}")
                print(f"    view_pos.npy first 16 values = {vp.ravel()[:16].tolist()}")
                print(f"    view_pos.npy n_unique={np.unique(vp).size}  monotonic_non_decreasing={bool(np.all(np.diff(vp.ravel()) >= 0))}")
                # does valid mask correspond to tiles being non-black?  tiles is (V,H,W,3)
                nz = t.any(axis=-1)
                print(f"    tiles.npy  nonblack_frac={float(nz.mean()):.6f}  shape={nz.shape}")
                agree = float((nz == v).mean())
                print(f"    agreement(valid == tiles_any_nonzero) = {agree:.6f}")
                inter = int((nz & v).sum())
                union = int((nz | v).sum())
                print(f"    IoU(valid, tiles_nonzero) = {inter / union if union else float('nan'):.6f}")
                print(f"    n_valid=True -> tiles_nonzero = {int((v & ~nz).sum()):,} (valid but black)")
                print(f"    n_tiles_nonzero -> valid=False = {int((nz & ~v).sum()):,} (black-but-visible / nonblack-but-invalid)")

        # ---- verification: tokens broadcast + frame_id linearity ----
        print("\n" + "=" * 110)
        print("VERIFICATION A: is `tokens` just a broadcast of `token_input`?")
        print("=" * 110)
        for pkg, root in PKGS.items():
            for npz in sorted((root / "deploy" / "tokens").glob("shard_*.npz")):
                with np.load(npz, allow_pickle=False) as z:
                    ks = [k for k in z.keys() if k.endswith("__tokens")]
                    for k in ks[:3]:
                        base = k[: -len("__tokens")]
                        tok = z[k]
                        ti = z[base + "__token_input"]
                        tv = z[base + "__token_view"]
                        bcast = np.all(tok == ti[:, None])
                        print(f"  {pkg}/{npz.name}:{base}")
                        print(f"    tokens{tok.shape} == token_input{ti.shape}[:,None] broadcast -> {bool(bcast)}")
                        print(f"    token_view unique={np.unique(tv).tolist()} shape={tv.shape}")
                        # is token_view also arange % views?
                        nv = tok.shape[0] // tv.size if tv.size else 0
                        exp = (np.arange(tv.size, dtype=np.int32) % (np.unique(tv).size or 1))
                        print(f"    token_view == arange({tv.size}) % {np.unique(tv).size} -> {bool(np.array_equal(tv, exp))}")
                        print(f"    tokens rows = {tok.shape[0]}  token_view len = {tv.size}  n_views = {np.unique(tv).size}"
                              f"  (token_view appears {'once per view' if tok.shape[0] == tv.size else 'REPEATED'})")

        print("\n" + "=" * 110)
        print("VERIFICATION B: frame_id == arange(n_points) % views ?")
        print("=" * 110)
        for pkg, root in PKGS.items():
            for npz in sorted((root / "deploy" / "geometry").glob("shard_*.npz")):
                with np.load(npz, allow_pickle=False) as z:
                    ks = [k for k in z.keys() if k.endswith("__frame_id")]
                    for k in ks[:4]:
                        base = k[: -len("__frame_id")]
                        fi = z[k]
                        n = fi.size
                        nv = int(np.unique(fi).size)
                        exp = (np.arange(n, dtype=np.int32) % nv).astype(np.int32)
                        ok = bool(np.array_equal(fi, exp))
                        # a pure counter would be arange % nv -- check that it is a perfect tiling
                        counts = Counter(fi.tolist())
                        print(f"  {pkg}/{npz.name}:{base} n={n} n_unique={nv} "
                              f"frame_id == arange(n)%%{nv} -> {ok}")
                        print(f"    per-value counts: {dict(sorted(counts.items()))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
