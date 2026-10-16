"""Step 18: full-chain smoke on the new geometry, into a NEW store root.

Runs the real ``synlab.pipeline.run_generation`` (mother -> material -> pattern -> fracture ->
physical -> observe -> truth/labels) with

* ``data/a12/reports/geom_fix/geom_v11_sandbox.yaml`` (a copy of the closed-loop config that
  only draws P1+P2-affected vessels V01 and V06), and
* ``store_root = data/a12_geom_v11/store``.

The frozen ``data/a12`` store is never opened for writing.  Everything the run produces is
read back from the new store and written to ``s18_new_store_smoke.json``.

Usage:  python s18_new_store_smoke.py [--root DIR] [--config PATH]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from synlab.config import load_generation_spec  # noqa: E402
from synlab.pipeline import plan_generation, run_generation  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402

CHAIN_ROLES = ("mother_mesh", "material_profile", "pattern_recipe", "pattern_channels",
               "cutter", "fragment_mesh", "physical_component", "physical_result",
               "obs_result", "obs_view", "obs_fused", "feature_bundle", "clean_truth",
               "visible_labels", "label_bundle", "provenance", "coverage")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="data/a12_geom_v11/store")
    ap.add_argument("--config", default=str(HERE / "geom_v11_sandbox.yaml"))
    ap.add_argument("--out", default=str(HERE / "s18_new_store_smoke.json"))
    args = ap.parse_args(argv[1:])

    root = Path(args.root)
    if not root.is_absolute():
        root = REPO / root
    spec = load_generation_spec(args.config)
    plan = plan_generation(spec)
    started = time.time()
    report = run_generation(spec, store_root=root)
    seconds = time.time() - started

    store = AssetStore(root)
    rows = report.get("rows") or []
    per_lineage = []
    for row in rows:
        lineage_id = row.get("lineage_id")
        assets = [a for a in store.list_assets(limit=5000) if a.lineage_id == lineage_id]
        roles: dict[str, int] = {}
        for asset in assets:
            roles[asset.role] = roles.get(asset.role, 0) + 1
        mother_asset = next((a for a in assets if a.role == "mother_mesh"), None)
        per_lineage.append({
            "lineage_id": lineage_id,
            "vessel_id": row.get("vessel_id"),
            "material_id": row.get("material_id"),
            "pattern_id": row.get("pattern_id"),
            "split": row.get("split"),
            "accepted": row.get("accepted"),
            "fragments": row.get("fragments"),
            "observations": row.get("observations"),
            "stages": row.get("stages"),
            "roles": roles,
            "chain_roles_present": sorted(r for r in CHAIN_ROLES if roles.get(r)),
            "missing_chain_roles": sorted(r for r in CHAIN_ROLES if not roles.get(r)),
            "n_assets": len(assets),
            "registry_version": (mother_asset.meta or {}).get("registry_version")
            if mother_asset else None,
            "mother_geometry_hash": (mother_asset.meta or {}).get("geometry_hash")
            if mother_asset else None,
            "mother_profile_metrics": {
                k: (mother_asset.meta or {}).get("profile_metrics", {}).get(k)
                for k in ("z_rim", "z_rim_target_mm", "z_rim_shortfall_mm", "r_max")
            } if mother_asset else None,
            "ancestry": sorted(mother_asset.ancestry or []) if mother_asset else None,
        })

    all_assets = store.list_assets(limit=5000)
    run_ids = sorted({a.run_id for a in all_assets if a.run_id})
    payload = {
        "schema": "a12.mother_geometry.new_store_smoke.v1",
        "config": str(Path(args.config)),
        "store_root": str(root),
        "frozen_store_untouched": "data/a12" not in str(root).replace("\\", "/").split("/store")[0]
        or not str(root).replace("\\", "/").startswith("data/a12/"),
        "seconds": round(seconds, 2),
        "run_id": report.get("run_id"),
        "spec_hash": report.get("spec_hash"),
        "planned": report.get("planned"),
        "attempted": report.get("attempted", len(rows)),
        "accepted": report.get("accepted"),
        "failed": report.get("failed", len(report.get("failures") or [])),
        "quarantined": report.get("quarantined"),
        "failures": report.get("failures"),
        "seconds_reported": report.get("seconds"),
        "vessels": report.get("vessels"),
        "patterns": report.get("patterns"),
        "materials": report.get("materials"),
        "per_lineage": per_lineage,
        "store_census": {
            "n_assets": len(all_assets),
            "roles": {r: sum(1 for a in all_assets if a.role == r)
                      for r in sorted({a.role for a in all_assets})},
            "run_ids": run_ids,
            "qa_pass": sum(1 for a in all_assets if a.qa_status == "QA_PASS"),
            "qa_fail": sum(1 for a in all_assets if a.qa_status == "QA_FAIL"),
            "lineages": sorted({a.lineage_id for a in all_assets if a.lineage_id}),
        },
        "coverage_ledger": report,
    }
    out = Path(args.out)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str),
                   encoding="utf-8")

    print(f"store={root}")
    print(f"run_id={payload['run_id']} planned={payload['planned']} "
          f"accepted={payload['accepted']} failed={payload['failed']} "
          f"quarantined={payload['quarantined']} seconds={payload['seconds']}")
    for row in per_lineage:
        print(f"  {row['lineage_id']} ({row['vessel_id']}) accepted={row['accepted']} "
              f"fragments={row['fragments']} obs={row['observations']} "
              f"assets={row['n_assets']} registry_version={row['registry_version']} "
              f"z_rim={row['mother_profile_metrics'].get('z_rim') if row['mother_profile_metrics'] else None}")
        print(f"      roles={sorted(row['roles'])}")
        if row["missing_chain_roles"]:
            print(f"      MISSING={row['missing_chain_roles']}")
    print(f"  store: {payload['store_census']['n_assets']} assets, "
          f"qa_pass={payload['store_census']['qa_pass']} "
          f"qa_fail={payload['store_census']['qa_fail']}")
    print(f"wrote {out}")
    return 0 if (payload["accepted"] or 0) >= 1 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
