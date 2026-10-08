"""L0 single-mother end-to-end validation *after* the mask/damage semantics fixes.

Runs one real mother through the shipped pipeline (``run_generation`` with ``max_mothers=1`` on
``configs/a12/sandbox.yaml``, the same config the L0 census used) into a persistent store, then
reports what the committed assets actually contain:

* the semantic markers (``data_semantics`` on the run record, the observation metadata and the
  physical-result metadata);
* per view: object pixels, uncertain pixels, ``deployment_mask`` pixels and coverage (the
  delivered mask semantics), the corrected CoC distribution and the fraction below the profile's
  own mark-out;
* ``visible_labels`` QA (the acceptance is QA_PASS with a non-empty visible layer);
* ``physical_result`` QA and its audit failure codes.

Usage:
  .venv\\Scripts\\python.exe data/a12/reports/run_l0_after_fix.py --out <json>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab.cameras.profiles import profile_by_id  # noqa: E402
from synlab.config import load_generation_spec  # noqa: E402
from synlab.observe.render import circle_of_confusion_px  # noqa: E402
from synlab.pipeline import data_semantics, run_generation  # noqa: E402
from synlab.roles import (  # noqa: E402
    ROLE_LABEL_BUNDLE,
    ROLE_OBS_RESULT,
    ROLE_PHYSICAL_RESULT,
    ROLE_VISIBLE_LABELS,
)
from synlab.storage.store import AssetStore  # noqa: E402

DEFAULT_CONFIG = "configs/a12/sandbox.yaml"
DEFAULT_STORE = "data/a12/reports/l0_after_fix/store"


def _view_report(store: AssetStore, obs_id: str, profile_id: str) -> dict:
    record = store.get_asset(obs_id)
    arrays = store.load_arrays(obs_id)
    views = list((record.meta or {}).get("views") or [])
    profile = profile_by_id(profile_id)
    f_number = float(profile.f_number)
    sensor_w = float(profile.meta["sensor_width_mm"])
    markout = float(profile.meta.get("coC_px", 2.0))
    threshold = float((record.meta or {}).get("meta", {}).get("render_spec", {}).get(
        "coc_px_threshold", 0.0)) or None
    rows = []
    for index, view_meta in enumerate(views):
        prefix = f"v{index:03d}."
        if prefix + "depth_z" not in arrays:
            continue
        depth = np.asarray(arrays[prefix + "depth_z"], dtype=np.float64)
        depth[depth < 0] = np.nan
        id_map = np.asarray(arrays[prefix + "id_map"])
        uncertain = np.asarray(arrays[prefix + "uncertain_mask"], dtype=bool)
        mask = np.asarray(arrays[prefix + "deployment_mask"], dtype=bool)
        K = np.asarray(arrays[prefix + "K"], dtype=np.float64)
        height, width = id_map.shape
        obj = id_map >= 0
        D = width / sensor_w
        f_px = 0.5 * (float(K[0, 0]) + float(K[1, 1]))
        focus = float(view_meta.get("working_distance_mm") or profile.working_distance_mm)
        coc = circle_of_confusion_px(depth, focus, f_number, f_px, sampling_px_per_mm=D)
        rows.append({
            "view": index, "view_id": view_meta.get("view_id"),
            "object_px": int(np.count_nonzero(obj)),
            "uncertain_px_on_object": int(np.count_nonzero(uncertain & obj)),
            "deployment_mask_px": int(np.count_nonzero(mask)),
            "deployment_mask_over_object": float(np.count_nonzero(mask)
                                                 / max(int(np.count_nonzero(obj)), 1)),
            "coc_p50_px": float(np.nanpercentile(coc[obj], 50)) if obj.any() else 0.0,
            "coc_p95_px": float(np.nanpercentile(coc[obj], 95)) if obj.any() else 0.0,
            "coc_below_profile_markout_fraction": float(np.mean(coc[obj] <= markout))
            if obj.any() else 0.0,
            "profile_markout_px": markout,
            "pipeline_threshold_px": threshold,
            "depth_span_mm": float(np.nanmax(depth[obj]) - np.nanmin(depth[obj]))
            if obj.any() else 0.0,
        })
    return {"obs_asset": obs_id, "profile_id": profile_id, "views": rows,
            "per_view_meta": [dict(v.get("meta", {})) for v in views]}


def census(store: AssetStore, run_id: str) -> dict:
    assets = store.list_assets(limit=10000)
    out: dict = {
        "run_id": run_id,
        "data_semantics_pipeline": data_semantics(),
        "run_record": {k: v for k, v in (store.get_run(run_id) or {}).items()
                       if k in ("run_id", "status", "meta")},
        "roles": {},
        "qa": {},
        "non_pass": [],
        "visible_labels": [],
        "physical_results": [],
    }
    for asset in assets:
        out["roles"][asset.role] = out["roles"].get(asset.role, 0) + 1
        out["qa"][asset.qa_status] = out["qa"].get(asset.qa_status, 0) + 1
        if asset.qa_status != "QA_PASS":
            out["non_pass"].append(f"{asset.qa_status} {asset.asset_id} ({asset.role})")
    for asset in store.list_assets(role=ROLE_VISIBLE_LABELS, limit=10):
        qa = dict(asset.qa or {})
        arrays = store.load_arrays(asset.asset_id)
        counts = arrays.get("visible_correspondence_visible_counts")
        out["visible_labels"].append({
            "asset_id": asset.asset_id, "qa_status": asset.qa_status,
            "pass": qa.get("pass"), "failures": qa.get("failures"),
            "samples_visible": qa.get("samples_visible"),
            "samples_of_observed_side": qa.get("samples_of_observed_side"),
            "visible_fraction": qa.get("visible_fraction"),
            "per_view": {k: {"visible": v.get("visible"), "projected": v.get("projected"),
                             "not_uncertain": v.get("not_uncertain"),
                             "deployment_ok": v.get("deployment_ok"),
                             "id_ok": v.get("id_ok"), "depth_ok": v.get("depth_ok")}
                         for k, v in (qa.get("per_view") or {}).items()} if False else None,
            "visible_counts_nonzero": int(np.count_nonzero(counts)) if counts is not None else 0,
            "meta_semantics": (asset.meta or {}).get("data_semantics"),
        })
        raw = store.get_asset(asset.asset_id)
        per_view = (raw.qa or {}).get("per_view") or raw.meta.get("per_view")
        out["visible_labels"][-1]["per_view"] = {
            k: {kk: vv for kk, vv in v.items()
                if kk in ("visible", "projected", "not_uncertain", "deployment_ok", "id_ok",
                          "depth_ok")}
            for k, v in (per_view or {}).items()}
    for asset in store.list_assets(role=ROLE_PHYSICAL_RESULT, limit=10):
        meta = dict(asset.meta or {})
        out["physical_results"].append({
            "asset_id": asset.asset_id, "qa_status": asset.qa_status,
            "audit_status": meta.get("audit_status"),
            "audit_failure_codes": meta.get("audit_failure_codes"),
            "damage_semantics": meta.get("damage_semantics"),
            "subset_instrument": meta.get("subset_instrument"),
            "lost_volume_mm3": meta.get("lost_volume_mm3"),
            "lost_volume_ratio": meta.get("lost_volume_ratio"),
            "components": meta.get("components"),
            "ledger_assembly": (meta.get("ledger") or {}).get("assembly"),
            "subset_check": ((meta.get("qa") or {}).get("checks") or {}).get(
                "damaged_subset_clean"),
        })
    observations = store.list_assets(role=ROLE_OBS_RESULT, limit=5)
    if observations:
        out["observation"] = _view_report(store, observations[0].asset_id, "CAM_MID_V3")
    labels = store.list_assets(role=ROLE_LABEL_BUNDLE, limit=5)
    if labels:
        out["label_bundle"] = {"asset_id": labels[0].asset_id, "qa_status": labels[0].qa_status,
                               "meta_keys": sorted(dict(labels[0].meta or {}))}
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--store", default=DEFAULT_STORE)
    parser.add_argument("--max-mothers", type=int, default=1)
    parser.add_argument("--out", default="data/a12/reports/l0_after_fix_census.json")
    parser.add_argument("--skip-run", action="store_true")
    args = parser.parse_args()

    store_root = Path(args.store)
    store = AssetStore(store_root)
    run_id = ""
    if not args.skip_run:
        spec = load_generation_spec(args.config)
        report = run_generation(spec, store_root=store_root, max_mothers=int(args.max_mothers))
        run_id = str(report.get("run_id", ""))
        print(json.dumps({k: v for k, v in report.items() if k != "code_fingerprint"},
                         ensure_ascii=False, indent=2, default=str)[:4000])
    if not run_id:
        runs = store.connect().execute("SELECT run_id FROM runs ORDER BY rowid DESC LIMIT 1")
        rows = runs.fetchall()
        run_id = str(rows[0][0]) if rows else ""
    out = census(store, run_id)
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str),
                      encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
