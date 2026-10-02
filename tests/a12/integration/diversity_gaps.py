"""Extract the per-axis *realised* diversity of the after-store, and the gaps that remain.

Reads the batch reports the diversity runner flushes after every lineage and the store's own asset
metadata, then prints two things the report needs and that a human cannot eyeball:

1. **realised vs declared** -- for every sampled axis, how many distinct values actually reached the
   store (not how many the sampler can emit);
2. **still-closed axes** -- every axis whose realised value set has one member, with the code site
   that pins it.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
STORE = REPO_ROOT / "data" / "a12_diversity" / "store"
RUN_DIR = STORE / "reports" / "diversity_run"


def outcomes() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not RUN_DIR.exists():
        return out
    for path in sorted(RUN_DIR.glob("batch_*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.extend(payload.get("outcomes") or [])
    return out


def store_facts() -> dict[str, Any]:
    db = STORE / "metadata.sqlite"
    if not db.exists():
        return {}
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        roles = {row["role"]: row["n"] for row in conn.execute(
            "SELECT role, COUNT(*) n FROM assets GROUP BY role ORDER BY n DESC")}
        obs_profiles, obs_wd, obs_sizes, obs_views = Counter(), Counter(), Counter(), Counter()
        for row in conn.execute("SELECT meta_json FROM assets WHERE role='obs_result'"):
            meta = json.loads(row["meta_json"] or "{}")
            views = meta.get("views") or []
            if not views:
                continue
            first = views[0]
            obs_profiles[str(first.get("profile_id"))] += 1
            obs_wd[repr(round(float(first.get("working_distance_mm") or 0.0), 3))] += 1
            size = first.get("image_size")
            obs_sizes[str(size)] += 1
            obs_views[str(len(views))] += 1
        degrade_axes = Counter()
        for row in conn.execute(
                "SELECT meta_json FROM assets WHERE role IN ('degrade_variant',"
                " 'degrade_measurement')"):
            meta = json.loads(row["meta_json"] or "{}")
            degrade_axes[f"{meta.get('axis_id')}:L{meta.get('level')}"] += 1
        blob_dupes = {}
        for row in conn.execute("SELECT role, COUNT(*) n FROM assets GROUP BY role, blob_hash "
                                "HAVING n > 1"):
            blob_dupes[row["role"]] = blob_dupes.get(row["role"], 0) + 1
        return {"roles": roles, "obs_profiles": dict(obs_profiles),
                "obs_working_distance_mm": dict(obs_wd), "obs_image_size": dict(obs_sizes),
                "obs_views": dict(obs_views), "degrade_axis_levels": dict(degrade_axes),
                "duplicate_blob_groups": blob_dupes,
                "assets_total": sum(roles.values()),
                "lineages": conn.execute(
                    "SELECT COUNT(DISTINCT lineage_id) FROM assets "
                    "WHERE lineage_id IS NOT NULL").fetchone()[0]}
    finally:
        conn.close()


#: Axes the report must be honest about.  ``site`` is where the value is decided; ``pinned_by`` is
#: what makes it closed today.
AXES: tuple[tuple[str, str, str], ...] = (
    ("断裂后端 backend", "event.backend", "pipeline._div_fracture_spec"),
    ("事件数 n_events", "event.n_events", "pipeline._div_fracture_spec"),
    ("切面法向 plane_normal", "event.plane_normal", "pipeline._div_fracture_spec"),
    ("切面偏移 offset_radius_units", "event.offset_radius_units", "pipeline._div_fracture_spec"),
    ("相机档位 profile_id", "observation.camera.profile_id", "pipeline._div_camera"),
    ("工作距离 working_distance_mm", "observation.camera.realized_working_distance_mm",
     "pipeline._div_camera + cameras.profiles.transform_profile_u"),
    ("灯态 light_mode", "observation.light_mode", "pipeline._div_light"),
    ("视图数 view_count", "observation.view_count", "pipeline._div_observe_spec"),
    ("交付分辨率 delivered_size", "observation.delivered_size", "pipeline._div_observe_spec"),
    ("对焦误差 focus_offset_mm", "observation.focus_offset_mm", "pipeline._div_observe_spec"),
    ("离焦 sigma defocus_sigma_px", "observation.defocus_sigma_px", "pipeline._div_observe_spec"),
    ("曝光 exposure_ev", "observation.exposure_ev", "pipeline._div_observe_spec"),
    ("读出噪声 read_noise_sigma", "observation.read_noise_sigma", "pipeline._div_observe_spec"),
    ("增益 effective_gain", "observation.effective_gain", "pipeline._div_observe_spec"),
    ("花纹参数 pattern.params", "pattern.params", "pipeline._div_pattern_params"),
    ("配色 palette_id", "pattern.palette_id", "pipeline._div_palette"),
    ("退化轴子集 degradation.declared_axes", "degradation.declared_axes",
     "pipeline._div_degradation_config"),
)


def _dig(table: dict[str, Any], path: str) -> Any:
    node: Any = table
    for key in path.split("."):
        if isinstance(node, dict) and key in node:
            node = node[key]
        else:
            return None
    return node


def main() -> int:
    rows = outcomes()
    facts = store_facts()
    print(f"=== after-store: {facts.get('lineages')} lineages, "
          f"{facts.get('assets_total')} assets ===")
    print(json.dumps(facts.get("roles"), ensure_ascii=False))
    print()
    print("=== realised variable values across lineages ===")
    print(f"{'axis':44s} {'distinct':>8s} {'values (first 6)':40s} site")
    closed: list[dict[str, Any]] = []
    for label, path, site in AXES:
        values = []
        for entry in rows:
            value = _dig(entry.get("diversity") or {}, path)
            if value is None:
                continue
            key = json.dumps(value, sort_keys=True, default=str)
            values.append(key)
        distinct = sorted(set(values))
        shown = ", ".join(distinct[:6])[:40]
        print(f"{label:44s} {len(distinct):8d} {shown:40s} {site}")
        if values and len(distinct) <= 1:
            closed.append({"axis": label, "path": path, "site": site,
                           "value": distinct[0] if distinct else None,
                           "lineages": len(values)})
    print()
    print("=== axes still closed (one realised value) ===")
    for item in closed:
        print(f"  - {item['axis']:42s} = {item['value']}  ({item['lineages']} lineages)  @ {item['site']}")
    if not closed:
        print("  (none)")
    print()
    print("=== observation facts from the store ===")
    for key in ("obs_profiles", "obs_working_distance_mm", "obs_image_size", "obs_views"):
        print(f"  {key}: {json.dumps(facts.get(key), ensure_ascii=False)}")
    print(f"  degrade axis:level pairs: {len(facts.get('degrade_axis_levels') or {})}")
    print(f"  duplicate blob groups by role: {json.dumps(facts.get('duplicate_blob_groups'), ensure_ascii=False)}")
    out = REPO_ROOT / "data" / "a12" / "reports" / "diversity_realised.json"
    out.write_text(json.dumps({"closed_axes": closed, "store_facts": facts,
                               "outcomes": [{k: v for k, v in e.items() if k != "diversity"}
                                            for e in rows]},
                              ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
