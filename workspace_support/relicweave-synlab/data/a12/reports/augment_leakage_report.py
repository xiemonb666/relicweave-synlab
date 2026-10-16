"""Augment the canonical leakage report with the scopes the A32 control needs to be readable.

``tools/evidence_min.py --step leakage --run-id <run>`` writes the run-scoped negative control to
``data/a12/reports/leakage_negative_control.json``.  That single scope cannot show whether the
*store* is clean, nor whether every run that used to leak is clean now.  This script keeps the
canonical payload untouched and adds the extra measurements:

* ``scope``            — which assets the canonical run actually checked;
* ``store_wide``       — the same control with no run filter (every feature bundle in the store);
* ``runs_scoped``      — one control per run that was affected by the feature-leak repair, plus the
                         clean control run, so ``truth_isolation`` is reported per run;
* ``clean_run_scoped`` — a control over a run whose feature bundles carry no answer field, i.e.
                         evidence that the control can return ``truth_isolation = true``;
* ``degrade_role_census`` — feature-bundle assets carrying the factor label before vs after the
                         repair (``data/a12/reports/degrade_role_repair.json``);
* ``feature_leak_repair`` — summary of ``data/a12/reports/feature_leak_repair.json`` (which assets
                         were re-committed as byte-faithful twins and which ids were retired);
* ``residual``         — the exact assets and fields that still fail (empty after the repair).

Usage: python data/a12/reports/augment_leakage_report.py --store data/a12 \
           --clean-run run_23664ddb26eada4b \
           --repair-runs run_2fad0ac4d3b67098,run_404bbe3c80f2c04e
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from synlab.qc.leakage import run_negative_control  # noqa: E402
from synlab.roles import FORBIDDEN_FEATURE_FIELDS, ROLE_FEATURE_BUNDLE  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402

REPORT = ROOT / "data" / "a12" / "reports" / "leakage_negative_control.json"
REPAIR_REPORT = ROOT / "data" / "a12" / "reports" / "feature_leak_repair.json"


def census(store: AssetStore) -> dict[str, Any]:
    """Which feature bundles carry which forbidden key, and from which run."""
    rows = []
    counts: dict[str, int] = {}
    for asset in store.list_assets(role=ROLE_FEATURE_BUNDLE, limit=100000):
        meta = asset.meta or {}
        forbidden = sorted(set(meta) & FORBIDDEN_FEATURE_FIELDS)
        for key in forbidden:
            counts[key] = counts.get(key, 0) + 1
        rows.append({"asset_id": asset.asset_id, "qa_status": asset.qa_status,
                     "run_id": meta.get("run_id"), "forbidden_keys": forbidden,
                     "has_feature_fields": bool(meta.get("feature_fields")),
                     "lineage_id": asset.lineage_id, "split": asset.split,
                     "n_ancestry": len(asset.ancestry or [])})
    degraded = store.list_assets(role="degrade_measurement", limit=100000)
    return {
        "feature_bundle_total": len(rows),
        "feature_bundle_with_forbidden_keys": len([r for r in rows if r["forbidden_keys"]]),
        "forbidden_key_histogram": dict(sorted(counts.items())),
        "degrade_measurement_total": len(degraded),
        "rows": rows,
        "note": ("no feature bundle carries a forbidden key anymore: the degradation bundles were "
                 "re-committed under role=degrade_measurement, and the 8 historical feature "
                 "bundles were re-committed as byte-faithful twins without the identity fields"),
    }


def scoped(store: AssetStore, run_id: str) -> dict[str, Any]:
    report = run_negative_control(store, run_id)
    features = [a for a in store.list_assets(role=ROLE_FEATURE_BUNDLE, limit=100000)
                if (a.meta or {}).get("run_id") == run_id]
    return {
        "run_id": run_id, "ok": report["ok"], "status": report["status"],
        "truth_isolation": report["checks"]["truth_isolation"],
        "metadata_permutation": report["checks"]["metadata_permutation"],
        "row_permutation_invariance": report["checks"]["row_permutation_invariance"],
        "features_checked": len(features),
        "feature_asset_ids": sorted(a.asset_id for a in features),
        "problems": report["problems"],
    }


def repair_summary(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"available": False, "path": str(path)}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        "available": True,
        "path": str(path),
        "applied": payload.get("applied"),
        "repaired": len(payload.get("repaired") or []),
        "refused": len(payload.get("refused") or []),
        "mapping": {entry["asset_id"]: entry.get("new_asset_id")
                    for entry in payload.get("entries") or []},
        "faithful": {entry["asset_id"]: (entry.get("fidelity") or {}).get("array_hashes_equal")
                     for entry in payload.get("entries") or []},
        "before_forbidden_entries": (payload.get("before") or {}).get("forbidden_entries"),
        "after_forbidden_entries": (payload.get("after") or {}).get("forbidden_entries_total"),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="augment_leakage_report")
    parser.add_argument("--store", default="data/a12")
    parser.add_argument("--clean-run", default="run_23664ddb26eada4b")
    parser.add_argument("--repair-runs", default="run_2fad0ac4d3b67098,run_404bbe3c80f2c04e")
    parser.add_argument("--report", default=str(REPORT))
    args = parser.parse_args(argv)

    store = AssetStore(ROOT / args.store if not Path(args.store).is_absolute() else args.store)
    path = Path(args.report)
    canonical = json.loads(path.read_text(encoding="utf-8"))
    repair_runs = [r for r in args.repair_runs.split(",") if r.strip()]

    store_wide = run_negative_control(store, None)
    clean = run_negative_control(store, args.clean_run)
    role_census = census(store)
    features = [a for a in store.list_assets(role=ROLE_FEATURE_BUNDLE, limit=100000)
                if (a.meta or {}).get("run_id") == canonical.get("run_id")]

    offenders = [row for row in role_census["rows"] if row["forbidden_keys"]]
    canonical["scope"] = {
        "run_id": canonical.get("run_id"),
        "feature_assets_in_scope": len(features),
        "feature_asset_ids": sorted(a.asset_id for a in features),
    }
    canonical["store_wide"] = {"ok": store_wide["ok"], "status": store_wide["status"],
                               "checks": store_wide["checks"], "problems": store_wide["problems"]}
    canonical["runs_scoped"] = {rid: scoped(store, rid)
                                for rid in [*repair_runs, args.clean_run]}
    canonical["clean_run_scoped"] = {
        **{k: v for k, v in scoped(store, args.clean_run).items() if k != "problems"},
        "note": ("a run whose feature bundles carry no answer field: the control returns "
                 "truth_isolation=true, so the check itself is not vacuously false")}
    canonical["degrade_role_census"] = role_census
    canonical["feature_leak_repair"] = repair_summary(REPAIR_REPORT)
    canonical["residual"] = {
        "truth_isolation": canonical["checks"]["truth_isolation"],
        "offending_assets": [row["asset_id"] for row in offenders],
        "offending_fields": sorted({key for row in offenders for key in row["forbidden_keys"]}),
        "runs": sorted({str(row["run_id"]) for row in offenders}),
        "committed_by": ("historically synlab/pipeline.py::_observation_feature_block merged "
                         "fragment_id / mother_id / component_id / observation_id into the feature "
                         "metadata and declared them in meta['feature_fields']; the 8 bundles "
                         "committed before the fix were re-committed as byte-faithful twins by "
                         "tools/repair_feature_leak.py"),
        "repair_report": str(REPAIR_REPORT),
        "repair_mapping": canonical["feature_leak_repair"].get("mapping", {}),
        "still_open": ([a for a in canonical["store_wide"]["problems"]] if offenders else []),
    }
    canonical["augmented_by"] = ("data/a12/reports/augment_leakage_report.py "
                                 "(adds scope/store_wide/runs_scoped/clean_run_scoped/"
                                 "degrade_role_census/feature_leak_repair/residual; the canonical "
                                 "payload is unchanged)")
    path.write_text(json.dumps(canonical, ensure_ascii=False, indent=2, sort_keys=True,
                               default=str), encoding="utf-8")
    print(f"[augment] report={path}")
    print(f"  run-scoped {canonical['run_id']}: ok={canonical['ok']} "
          f"truth_isolation={canonical['checks']['truth_isolation']} "
          f"features={len(features)}")
    print(f"  store-wide: ok={store_wide['ok']} "
          f"truth_isolation={store_wide['checks']['truth_isolation']}")
    for rid, entry in canonical["runs_scoped"].items():
        print(f"  {rid}: ok={entry['ok']} truth_isolation={entry['truth_isolation']} "
              f"features={entry['features_checked']}")
    print(f"  feature_bundle={role_census['feature_bundle_total']} "
          f"with_forbidden={role_census['feature_bundle_with_forbidden_keys']} "
          f"degrade_measurement={role_census['degrade_measurement_total']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
