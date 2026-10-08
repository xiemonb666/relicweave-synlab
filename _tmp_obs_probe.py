"""Count observation assets per role / per fragment side in a store root."""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else "data/a12")
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else "_tmp_obs_probe.json")

from synlab.storage.store import AssetStore  # noqa: E402

store = AssetStore(ROOT)
rep: dict = {"root": str(ROOT)}

roles = Counter()
for i in range(0, 400000, 1000):
    batch = store.list_assets(limit=1000, offset=i)
    if not batch:
        break
    for rec in batch:
        roles[rec.role] += 1
rep["role_counts"] = dict(roles.most_common())

# observation assets: fragment_id + lineage
obs = []
for i in range(0, 400000, 1000):
    batch = store.list_assets(role="obs_result", limit=1000, offset=i)
    if not batch:
        break
    obs.extend(batch)
rep["n_obs_assets"] = len(obs)

by_side = Counter()
per_lineage = defaultdict(list)
obs_meta = []
for rec in obs:
    fid = str(rec.meta.get("fragment_id", ""))
    side = fid.rsplit("-", 1)[-1] if "-" in fid else "?"
    by_side[side] += 1
    per_lineage[rec.lineage_id].append(fid)
    obs_meta.append({
        "asset_id": rec.asset_id, "fragment_id": fid,
        "lineage_id": rec.lineage_id,
        "component_id": str(rec.meta.get("component_id", "")),
        "route": str(rec.meta.get("route", "")),
        "data_semantics": rec.meta.get("data_semantics"),
        "run_id": rec.meta.get("run_id"),
        "views": len(rec.meta.get("views", []) or []),
        "keys": sorted(rec.meta.keys()),
    })
rep["obs_by_side"] = dict(by_side)
rep["obs_per_lineage_hist"] = dict(Counter(len(v) for v in per_lineage.values()))
rep["sample_obs_meta"] = obs_meta[:6]
rep["obs_meta_keys_union"] = sorted({k for m in obs_meta for k in m["keys"]})

# fragment meshes
frag = []
for i in range(0, 400000, 1000):
    batch = store.list_assets(role="fragment_mesh", limit=1000, offset=i)
    if not batch:
        break
    frag.extend(batch)
rep["n_fragment_assets"] = len(frag)
frag_by_side = Counter()
for rec in frag:
    fid = str(rec.meta.get("fragment_id", ""))
    frag_by_side[fid.rsplit("-", 1)[-1] if "-" in fid else "?"] += 1
rep["fragment_by_side"] = dict(frag_by_side)
rep["sample_fragment_meta"] = [
    {"asset_id": r.asset_id, "fragment_id": r.meta.get("fragment_id"),
     "lineage_id": r.lineage_id} for r in frag[:4]]

# join: which fragments have an observation, per lineage
obs_frag = {m["fragment_id"] for m in obs_meta}
rep["n_fragments_with_obs"] = len(obs_frag)
rep["n_fragments_total"] = len(frag)
rep["fragments_without_obs_sample"] = sorted(
    {str(r.meta.get("fragment_id", "")) for r in frag} - obs_frag)[:8]

# commits per lineage in this store
rep["lineages"] = sorted(per_lineage)[:10]
rep["n_lineages"] = len(per_lineage)

OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
print(json.dumps({k: v for k, v in rep.items() if k != "sample_obs_meta"}, ensure_ascii=False,
                 indent=2, default=str)[:4000])
