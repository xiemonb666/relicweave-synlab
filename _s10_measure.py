import json, tarfile, io
import numpy as np
from pathlib import Path
pkgs = {
  "trainable": Path(r"data\a12_exports\trainable\next_experiment\training_package"),
  "negfix": Path(r"data\a12_exports\negfix\next_experiment\training_package"),
}
for name, pkg in pkgs.items():
    idx = json.loads((pkg/"deploy"/"obs"/"index.json").read_text(encoding="utf-8"))
    per_shard = {}
    for fid, row in idx["rows"].items():
        per_shard.setdefault(row["shard"], []).append((fid, row["opaque"]))
    print("===", name, pkg.name)
    allv = []
    for shard, members in sorted(per_shard.items()):
        path = pkg/"deploy"/shard
        if not path.exists(): continue
        vals = []
        with tarfile.open(path) as tar:
            for fid, opaque in members:
                key = f"{opaque}/view_pos.npy"
                try:
                    f = tar.extractfile(key)
                except KeyError:
                    continue
                if f is None: continue
                v = np.load(io.BytesIO(f.read()))
                vals.extend(np.asarray(v, dtype=np.float64).tolist())
        if vals:
            a = np.abs(np.asarray(vals))
            allv.extend(vals)
            print(f"   {shard}: views={len(vals)} absmax={a.max():.2f} mm  min={min(vals):.2f} max={max(vals):.2f}")
    if allv:
        a = np.abs(np.asarray(allv))
        print(f"   TOTAL views={len(allv)} absmax={a.max():.2f} mm  signed range [{min(allv):.2f}, {max(allv):.2f}]")
        m = pkg/"export_manifest.json"
        if m.exists():
            man = json.loads(m.read_text(encoding="utf-8"))
            vp = (((man.get("files") or []) and None) or None)
