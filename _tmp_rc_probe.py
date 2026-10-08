"""Root-cause probe: which fragment of a lineage gets an observation, and why."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else "data/a12")
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else "_tmp_rc_probe.json")

from synlab.storage.store import AssetStore  # noqa: E402

store = AssetStore(ROOT)


def all_role(role: str) -> list:
    out = []
    for i in range(0, 400000, 500):
        batch = store.list_assets(role=role, limit=500, offset=i)
        if not batch:
            break
        out.extend(batch)
    return out


obs = all_role("obs_result")
phys = all_role("physical_result")
frag = all_role("fragment_mesh")

obs_by_lin = {r.lineage_id: r for r in obs}
phys_by_lin = {}
for r in phys:
    phys_by_lin.setdefault(r.lineage_id, []).append(r)
frag_by_lin: dict[str, list] = {}
for r in frag:
    frag_by_lin.setdefault(r.lineage_id, []).append(r)

rows = []
for lin in sorted(set(obs_by_lin) & set(phys_by_lin)):
    o = obs_by_lin[lin]
    p = phys_by_lin[lin][-1]
    comps = p.meta.get("components") or {}
    rows.append({
        "lineage": lin,
        "observed_fragment": o.meta.get("fragment_id"),
        "observed_component": o.meta.get("component_id"),
        "physical_components_json": comps,
        "physical_component_ids": comps.get("component_ids") if isinstance(comps, dict) else None,
        "physical_clean_fragment": p.meta.get("clean_fragment_id"),
        "physical_representative_map": p.meta.get("representative_map"),
        "lineage_fragments": sorted(str(f.meta.get("fragment_id")) for f in frag_by_lin.get(lin, [])),
        "n_obs_for_lineage": sum(1 for r in obs if r.lineage_id == lin),
    })

rep = {
    "root": str(ROOT),
    "n_obs": len(obs), "n_physical_result": len(phys), "n_fragment": len(frag),
    "n_lineages_with_obs": len(obs_by_lin),
    "obs_per_lineage": dict(Counter(r.lineage_id for r in obs).most_common(5)),
    "observed_fragment_is_damage_target": None,
    "rows": rows[:6],
}
# is the observed fragment always the physical pack's own fragment?
match = 0
for r in rows:
    pf = str(r["physical_clean_fragment"] or "")
    of = str(r["observed_fragment"] or "")
    if pf and of and pf == of:
        match += 1
rep["observed_fragment_equals_physical_target"] = f"{match}/{len(rows)}"
rep["physical_component_count_hist"] = dict(Counter(
    len(r["physical_component_ids"] or []) for r in rows))

OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
print(json.dumps(rep, ensure_ascii=False, indent=2, default=str)[:3500])
