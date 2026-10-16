"""Probe 3: geometry + tokens npz arrays, and zarr on-disk chunk verification.

READ-ONLY.
Repro:
  cd C:\\Users\\xiemo\\Desktop\\ShardForge\\relicweave-synlab
  .venv\\Scripts\\python.exe data\\a12\\reports\\modality_census\\p3_arrays_zarr.py > data\\a12\\reports\\modality_census\\p3_arrays_zarr.out 2>&1
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[4]
PKGS = {
    "next_experiment": REPO / "data" / "a12_exports" / "next_experiment" / "training_package",
    "closed_loop": REPO / "data" / "a12_exports" / "closed_loop" / "training_package",
}
OPAQUE_RE = re.compile(r"^([0-9a-f]{24})__(.+)$")


def describe(name: str, a: np.ndarray) -> str:
    s = f"    {name:<22} shape={str(a.shape):<16} dtype={str(a.dtype):<10}"
    if a.dtype == bool:
        frac = float(a.mean()) if a.size else float("nan")
        s += f" True_frac={frac:.6f}  n_True={int(a.sum()):,}/{a.size:,}"
    elif a.dtype.kind in "iu":
        s += f" min={a.min() if a.size else 'NA'} max={a.max() if a.size else 'NA'} n_unique={np.unique(a).size}"
    elif a.dtype.kind == "f":
        finite = np.isfinite(a)
        s += (f" min={np.nanmin(a) if a.size else 'NA':.6g} max={np.nanmax(a) if a.size else 'NA':.6g}"
              f" mean={np.nanmean(a) if a.size else 'NA':.6g} nonfinite={int((~finite).sum())}")
    else:
        s += " (n/a)"
    return s


def probe_geometry_or_tokens(root: Path, sub: str) -> dict:
    """sub in {'geometry','tokens'}"""
    d = root / "deploy" / sub
    out = {"npz": [], "channels": Counter(), "opaques": set(), "keys": 0}
    if not d.is_dir():
        return out
    for npz in sorted(d.glob("shard_*.npz")):
        with np.load(npz, allow_pickle=False) as z:
            keys = list(z.keys())
            out["keys"] += len(keys)
            chans = Counter()
            opaques = set()
            shapes = defaultdict(list)
            print(f"\n  --- {sub}/{npz.name}  ({npz.stat().st_size:,} bytes)  keys={len(keys)} ---")
            for k in keys:
                m = OPAQUE_RE.match(k)
                if m:
                    opaques.add(m.group(1))
                    chans[m.group(2)] += 1
                else:
                    chans[f"<NONMATCHING:{k}>"] += 1
                a = z[k]
                out["npz"].append((sub, npz.name, k, a.shape, str(a.dtype)))
                shapes[a.shape[1] if a.ndim > 1 else None].append(a.shape)
            out["channels"] += chans
            out["opaques"] |= opaques
            print(f"      distinct opaque ids in this shard = {len(opaques)}")
            print(f"      channel histogram: {dict(chans)}")
            # key naming convention check
            bad = [k for k in keys if not OPAQUE_RE.match(k)]
            print(f"      keys NOT matching '<24hex>__<channel>': {len(bad)} {bad[:5]}")
            # exact per-channel shapes/dtypes/stats -- dump one representative opaque in full
            first = sorted(opaques)[0] if opaques else None
            if first:
                print(f"      FULL PER-CHANNEL DUMP for opaque={first}:")
                for k in sorted(keys):
                    if k.startswith(first + "__"):
                        a = z[k]
                        print(describe(k.split("__", 1)[1], a))
                        if k.endswith("__frame_id"):
                            u = np.unique(a)
                            print(f"        frame_id unique values (n={u.size}) = {u[:20].tolist()}"
                                  f"{' ...' if u.size > 20 else ''}")
            # aggregate per-channel shape set + dtype set across ALL opaques in shard
            per = defaultdict(lambda: {"shapes": Counter(), "dtypes": Counter(),
                                       "truefrac": [], "min": [], "max": [], "uniq_vals": []})
            for k in keys:
                m = OPAQUE_RE.match(k)
                if not m:
                    continue
                ch = m.group(2)
                a = z[k]
                per[ch]["shapes"][str(a.shape)] += 1
                per[ch]["dtypes"][str(a.dtype)] += 1
                if a.dtype == bool and a.size:
                    per[ch]["truefrac"].append(float(a.mean()))
                elif a.dtype.kind in "iuf" and a.size:
                    per[ch]["min"].append(float(a.min()))
                    per[ch]["max"].append(float(a.max()))
                if ch == "frame_id":
                    per[ch]["uniq_vals"].append(int(np.unique(a).size))
            print(f"      PER-CHANNEL AGGREGATE over {len(opaques)} opaques in this shard:")
            for ch in sorted(per):
                info = per[ch]
                line = f"        {ch:<16} shapes={dict(info['shapes'])} dtypes={dict(info['dtypes'])}"
                print(line)
                if info["truefrac"]:
                    tf = np.array(info["truefrac"])
                    print(f"          True_frac: n={tf.size} min={tf.min():.6f} mean={tf.mean():.6f} max={tf.max():.6f}"
                          f"  total_True={int(round(tf.sum())) if False else ''}")
                if info["min"]:
                    print(f"          values: min={min(info['min']):.6g} max={max(info['max']):.6g}")
                if info["uniq_vals"]:
                    uv = np.array(info["uniq_vals"])
                    print(f"          frame_id n_unique per opaque: min={uv.min()} mean={uv.mean():.2f} max={uv.max()}")
    return out


def main() -> int:
    print("=" * 110)
    print("PROBE 3: GEOMETRY + TOKENS NPZ ARRAYS  /  ZARR ON-DISK VERIFICATION")
    print("=" * 110)

    for pkg, root in PKGS.items():
        print("\n" + "#" * 110)
        print(f"# PACKAGE: {pkg}")
        print("#" * 110)
        if not root.is_dir():
            print("  MISSING")
            continue

        allres = {}
        for sub in ("geometry", "tokens"):
            print("\n" + "=" * 110)
            print(f"== {sub.upper()} NPZ ==")
            print("=" * 110)
            res = probe_geometry_or_tokens(root, sub)
            allres[sub] = res
            print(f"\n  TOTAL keys across all {sub} shards = {res['keys']}")
            print(f"  TOTAL distinct opaque ids           = {len(res['opaques'])}")
            print(f"  CHANNEL HISTOGRAM (all shards)      = {dict(res['channels'])}")

        # ---- zarr ----
        print("\n" + "=" * 110)
        print("== ZARR STORE ==")
        print("=" * 110)
        zr = root / "deploy" / "zarr"
        if not zr.is_dir():
            print("  no zarr dir")
            continue
        groups = sorted([g for g in zr.iterdir() if g.is_dir()])
        print(f"  opaque groups = {len(groups)}  (name lengths {sorted({len(g.name) for g in groups})})")
        arrays = sorted({a.name for g in groups for a in g.iterdir() if a.is_dir()})
        print(f"  array names   = {arrays}")

        # declared vs on-disk chunks
        print("\n  DECLARED (zarr.json) vs ON-DISK chunk files per group:")
        tot_decl = tot_disk = 0
        tot_bytes = 0
        hdr = f"    {'group':<26}{'array':<14}{'shape':>10}{'dtype':>9}{'chunk':>10}{'codec':>8}{'disk_chunks':>12}{'bytes':>12}"
        print(hdr)
        for g in groups:
            for arr in sorted([a for a in g.iterdir() if a.is_dir()]):
                zj = arr / "zarr.json"
                if not zj.is_file():
                    print(f"    {g.name:<26}{arr.name:<14}  *** zarr.json MISSING ***")
                    continue
                o = json.loads(zj.read_text(encoding="utf-8"))
                shape = o.get("shape")
                dtype = o.get("data_type")
                cg = o.get("chunk_grid", {}).get("configuration", {})
                chunk_shape = cg.get("chunk_shape")
                codecs = [c.get("name") for c in o.get("codecs", [])]
                # count real chunk data files
                cdir = arr / "c"
                disk = [p for p in cdir.rglob("*") if p.is_file()] if cdir.is_dir() else []
                nb = sum(p.stat().st_size for p in disk)
                tot_decl += 1
                tot_disk += len(disk)
                tot_bytes += nb
                print(f"    {g.name:<26}{arr.name:<14}{str(shape):>10}{str(dtype):>9}"
                      f"{str(chunk_shape):>10}{'+'.join(codecs):>8}{len(disk):>12}{nb:>12,}")
        print(f"\n    arrays declared = {tot_decl}   on-disk chunk files = {tot_disk}   bytes = {tot_bytes:,}")

        # show a few real chunk paths + confirm they decode
        print("\n  REAL CHUNK PATHS (first 8, with sizes):")
        shown = 0
        for g in groups:
            for arr in sorted([a for a in g.iterdir() if a.is_dir()]):
                cdir = arr / "c"
                if not cdir.is_dir():
                    continue
                for p in sorted([x for x in cdir.rglob("*") if x.is_file()]):
                    print(f"    {p.stat().st_size:>10,}  {p.relative_to(zr).as_posix()}")
                    shown += 1
                    if shown >= 8:
                        break
                if shown >= 8:
                    break
            if shown >= 8:
                break

        # actually READ the store through zarr to prove usability
        print("\n  ZARR READ-BACK TEST (zarr 3.x API):")
        try:
            import zarr
            z = zarr.open_group(str(zr), mode="r")
            names = sorted(z.group_keys())
            print(f"    zarr.open_group OK: {len(names)} groups = {names[:5]}{'...' if len(names) > 5 else ''}")
            g0 = z[names[0]]
            got = {}
            for an in sorted(g0.array_keys()):
                a = g0[an][:]
                got[an] = a
                print(f"    [{names[0]}]/{an}: read shape={a.shape} dtype={a.dtype}")
                if a.dtype == bool:
                    print(f"        True_frac={float(a.mean()):.6f} n_True={int(a.sum()):,}/{a.size:,}")
                elif a.dtype.kind in "iuf":
                    print(f"        min={a.min()} max={a.max()}")
                if an == "frame_id":
                    print(f"        unique={np.unique(a).tolist()}")
            # cross-check zarr vs npz for the same opaque
            for sub in ("geometry",):
                for npz in sorted((root / "deploy" / sub).glob("shard_*.npz")):
                    with np.load(npz, allow_pickle=False) as zz:
                        k = f"{names[0]}__points"
                        if k in zz:
                            same = np.array_equal(zz[k], got["points"])
                            print(f"    CROSS-CHECK {sub}/{npz.name}:{k} vs zarr points -> identical={same}")
                            break
        except Exception as e:  # noqa: BLE001
            print(f"    zarr read FAILED: {e!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
