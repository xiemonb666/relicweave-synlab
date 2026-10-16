"""Campaign survey: real counts from the store + ledger + plan (read-only).

Writes ``data/a12_campaign/campaign_survey.json`` and prints a compact human summary.
Nothing here invents a number: every count comes from ``store.list_assets`` (asset records),
the batch ledger (per-mother outcomes) or the deterministic plan.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from synlab.config import load_generation_spec  # noqa: E402
from synlab.pipeline import plan_generation  # noqa: E402
from synlab.registry import load_all  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402

CONFIG = "configs/a12/realistic.yaml"
ROOT = REPO / "data" / "a12_campaign" / "store"
LEDGER = REPO / "data" / "a12_campaign" / "campaign_ledger.json"
OUT = REPO / "data" / "a12_campaign" / "campaign_survey.json"

#: Roles that hold a rendered observation (one asset per observed endpoint).
OBS_ROLE = "obs_result"
#: Metadata key the pipeline stamps on each observation asset to say which endpoint it is.
OBS_ENDPOINT_KEY = "observation_role"


def main() -> int:
    load_all()
    spec = load_generation_spec(REPO / CONFIG)
    plan = plan_generation(spec)
    store = AssetStore(ROOT)

    records = list(store.list_assets(limit=1000000))
    by_lineage: dict[str, list] = defaultdict(list)
    for rec in records:
        if rec.lineage_id:
            by_lineage[rec.lineage_id].append(rec)

    role_counts = Counter(rec.role for rec in records)
    per_lineage = {}
    for lineage in plan.lineages:
        recs = by_lineage.get(lineage.lineage_id, [])
        roles = Counter(r.role for r in recs)
        obs = [r for r in recs if r.role == OBS_ROLE]
        obs_views = []
        for r in obs:
            meta = r.meta or {}
            views = meta.get("views")
            obs_views.append(len(views) if isinstance(views, (list, dict)) else 0)
        facts = [(r.meta or {}).get("observation_facts") or {} for r in obs]
        per_lineage[lineage.lineage_id] = {
            "mother_index": lineage.mother_index,
            "split": lineage.split,
            "vessel_id": lineage.vessel_id,
            "material_id": lineage.material_id,
            "pattern_id": lineage.pattern_id,
            "layer_combo_id": lineage.layer_combo_id,
            "assets": len(recs),
            "roles": dict(roles),
            "obs_assets": len(obs),
            "endpoint_obs_assets": sum(
                1 for f in facts if str(f.get("role")) == "fracture_event_endpoint"),
            "target_obs_assets": sum(
                1 for f in facts if str(f.get("role")) == "physical_damage_target"),
            "views_total": sum(obs_views),
            "views_per_obs": obs_views,
            "obs_semantics": sorted({str((r.meta or {}).get("obs_semantics")) for r in obs}),
            "damage_states": dict(Counter(str(f.get("damage_state")) for f in facts)),
            "accepted": roles.get("label_bundle", 0) > 0,
            "obs_asset_ids": [r.asset_id for r in obs],
        }

    accepted = {lid: e for lid, e in per_lineage.items() if e["accepted"]}
    attempted = {lid: e for lid, e in per_lineage.items() if e["assets"] > 0}

    def tally(key: str, entries) -> dict[str, int]:
        return dict(sorted(Counter(e[key] for e in entries.values()).items()))

    ledger = {}
    if LEDGER.exists():
        try:
            ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
        except Exception:
            ledger = {}
    failures = Counter()
    for row in ledger.get("batches", []):
        if row.get("error"):
            failures[f"{row['vessel_id']}|{row['material_id']}|{row['pattern_id']}|"
                     f"{row.get('layer_combo_id')}|{row['error']}"] += 1
    ledger_r2 = sum(int(r.get("r2_pairs") or 0) for r in ledger.get("batches", []) if r.get("ok"))
    ledger_frag = sum(int(r.get("fragments") or 0) for r in ledger.get("batches", []) if r.get("ok"))
    ledger_obs = sum(int(r.get("observations") or 0) for r in ledger.get("batches", []) if r.get("ok"))

    planned_vessels = sorted({l.vessel_id for l in plan.lineages})
    planned_materials = sorted({l.material_id for l in plan.lineages})
    planned_patterns = sorted({l.pattern_id for l in plan.lineages})
    planned_layers = sorted({l.layer_combo_id for l in plan.lineages if l.layer_combo_id})

    def missing(planned, entries, key):
        have = {e[key] for e in entries.values() if e.get(key)}
        return [p for p in planned if p not in have]

    survey = {
        "config": CONFIG,
        "store": str(ROOT.relative_to(REPO)).replace("\\", "/"),
        "planned_mothers": len(plan.lineages),
        "lineages_with_assets": len(attempted),
        "accepted_lineages": len(accepted),
        "failed_lineages": sorted(set(attempted) - set(accepted)),
        "never_attempted": len(plan.lineages) - len(attempted),
        "assets_total": len(records),
        "assets_by_role": dict(sorted(role_counts.items())),
        "totals_accepted": {
            "fragments_store": sum(e["roles"].get("fragment_mesh", 0) for e in accepted.values()),
            "fragments_ledger": ledger_frag,
            "observations_store": sum(e["obs_assets"] for e in accepted.values()),
            "observations_ledger": ledger_obs,
            "endpoint_observations_store": sum(e["endpoint_obs_assets"]
                                               for e in accepted.values()),
            "target_observations_store": sum(e["target_obs_assets"] for e in accepted.values()),
            "views": sum(e["views_total"] for e in accepted.values()),
            "r2_pairs_ledger": ledger_r2,
            "feature_bundles": sum(e["roles"].get("feature_bundle", 0) for e in accepted.values()),
            "label_bundles": sum(e["roles"].get("label_bundle", 0) for e in accepted.values()),
            "physical_results": sum(e["roles"].get("physical_result", 0)
                                    for e in accepted.values()),
            "clean_truth": sum(e["roles"].get("clean_truth", 0) for e in accepted.values()),
        },
        "coverage_accepted": {
            "vessels": tally("vessel_id", accepted),
            "materials": tally("material_id", accepted),
            "patterns": tally("pattern_id", accepted),
            "layer_combos": tally("layer_combo_id", accepted),
            "splits": tally("split", accepted),
        },
        "coverage_attempted": {
            "vessels": tally("vessel_id", attempted),
            "materials": tally("material_id", attempted),
            "patterns": tally("pattern_id", attempted),
            "layer_combos": tally("layer_combo_id", attempted),
        },
        "uncovered_accepted": {
            "vessels": missing(planned_vessels, accepted, "vessel_id"),
            "materials": missing(planned_materials, accepted, "material_id"),
            "patterns": missing(planned_patterns, accepted, "pattern_id"),
            "layer_combos": missing(planned_layers, accepted, "layer_combo_id"),
        },
        "uncovered_attempted": {
            "vessels": missing(planned_vessels, attempted, "vessel_id"),
            "materials": missing(planned_materials, attempted, "material_id"),
            "patterns": missing(planned_patterns, attempted, "pattern_id"),
            "layer_combos": missing(planned_layers, attempted, "layer_combo_id"),
        },
        "obs_semantics_seen": sorted({s for e in per_lineage.values() for s in e["obs_semantics"]
                                      if s != "None"}),
        "failure_reasons": dict(sorted(failures.items())),
        "per_lineage": per_lineage,
    }
    OUT.write_text(json.dumps(survey, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({k: v for k, v in survey.items() if k != "per_lineage"},
                     ensure_ascii=False, indent=2)[:6000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
