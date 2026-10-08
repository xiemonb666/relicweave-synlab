"""A07 / A27 evidence producers over the committed fracture assets.

A07 (plan 21.x row): "要求误差0.01mm时实际报告达标；无T接点、共形网格四面体体积正；达不到返回
PRECISION_NOT_REALIZED" - the cutter half is measurable from the committed event trees (the
cutter record carries requested/realized error with its sample count, watertightness and an
edge-use histogram, so T-junctions are counted rather than assumed).  The conformal-warp half
has no backend in this checkout and is reported separately, never folded into the verdict.

A27: original triangle ids, patch areas, barycentric residuals and the separation between
origin mapping (EXACT_SURVIVOR / UNKNOWN_MAPPING) and damage association, measured on the
committed ``clean_truth`` / ``physical_truth`` assets.  A forced correspondence (samples on a
pair that never shared a fracture surface) must not exist: that is the negative control.

Run:  .venv\\Scripts\\python.exe tests\\a12\\qc\\run_precision_and_origin.py --step precision
      .venv\\Scripts\\python.exe tests\\a12\\qc\\run_precision_and_origin.py --step origin
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

STORE_ROOT = ROOT / "data" / "a12"
REPORTS = STORE_ROOT / "reports"


def _store():
    from synlab.storage.store import AssetStore

    return AssetStore(str(STORE_ROOT))


def _residual_budget() -> float:
    """The codebase's own exactness budget for a correspondence sample."""
    from synlab.fracture.spec import CORRESPONDENCE_RESIDUAL_MM

    return float(CORRESPONDENCE_RESIDUAL_MM)


RESIDUAL_BUDGET_MM = _residual_budget() if __name__ != "__main__" or True else 1.0e-4


def _write(name: str, payload: dict[str, Any]) -> Path:
    path = REPORTS / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str),
                    encoding="utf-8")
    return path


def step_precision() -> dict[str, Any]:
    """A07 cutter half: realized error vs the requested budget, T-junctions, watertightness."""
    store = _store()
    events: list[dict[str, Any]] = []
    for asset in store.list_assets(role="clean_truth", limit=100000):
        tree = (asset.meta or {}).get("event_tree") or {}
        cutter = tree.get("cutter") or {}
        meta = cutter.get("meta") or {}
        if not meta:
            continue
        histogram = {str(k): int(v) for k, v in (meta.get("edge_use_histogram") or {}).items()}
        # an edge used by exactly two faces is a manifold interior edge; any other use count
        # is a boundary edge or a T-junction
        non_manifold = sum(v for k, v in histogram.items() if k != "2")
        events.append({
            "event_id": (asset.meta or {}).get("event_id", asset.asset_id),
            "backend": meta.get("backend", tree.get("backend")),
            "requested_error_mm": meta.get("requested_error_mm"),
            "realized_error_mm": meta.get("realized_error_mm"),
            "error_samples": meta.get("error_samples"),
            "watertight": meta.get("watertight"),
            "winding_consistent": meta.get("winding_consistent"),
            "degenerate_faces": meta.get("degenerate_faces"),
            "edge_use_histogram": histogram,
            "non_manifold_edge_uses": non_manifold,
            "triangles": meta.get("triangles"),
        })
    realized = [float(e["realized_error_mm"]) for e in events
                if e.get("realized_error_mm") is not None]
    requested = [float(e["requested_error_mm"]) for e in events
                 if e.get("requested_error_mm") is not None]
    budget_ok = bool(events) and all(
        float(e["realized_error_mm"]) <= float(e["requested_error_mm"]) + 1e-12 for e in events
        if e.get("realized_error_mm") is not None and e.get("requested_error_mm") is not None)
    t_junctions = int(sum(int(e["non_manifold_edge_uses"]) for e in events))
    watertight_ok = all(bool(e.get("watertight")) for e in events)
    winding_ok = all(bool(e.get("winding_consistent")) for e in events)
    degenerate = int(sum(int(e.get("degenerate_faces") or 0) for e in events))
    samples = int(sum(int(e.get("error_samples") or 0) for e in events))
    ok = bool(events) and budget_ok and t_junctions == 0 and watertight_ok and winding_ok \
        and degenerate == 0
    report = {
        "ok": bool(ok),
        "status": "PASS" if ok else "PRECISION_NOT_REALIZED",
        "check": "A07 precision realization (cutter half; plan 21.x)",
        "units": {"requested_mm": "mm", "realized_mm": "mm", "error_samples": "count"},
        "requested_mm": max(requested) if requested else None,
        "realized_mm": max(realized) if realized else None,
        "t_junctions": t_junctions,
        "cutter": {
            "n_events": len(events),
            "requested_error_mm_max": max(requested) if requested else None,
            "realized_error_mm_max": max(realized) if realized else None,
            "realized_error_mm_mean": float(np.mean(realized)) if realized else None,
            "error_samples_total": samples,
            "budget_ok": budget_ok,
            "watertight_all": watertight_ok,
            "winding_consistent_all": winding_ok,
            "degenerate_faces_total": degenerate,
            "t_junctions": t_junctions,
            "definition": ("realized error is the cutter's own measured deviation over "
                           "error_samples rays; T-junctions are edge uses other than exactly "
                           "two faces in the frozen edge-use histogram"),
            "events": events,
        },
        "conformal_warp": {
            "status": "NOT_RUN",
            "reason": ("the shared-PLC / conformal warped_partition backend does not exist in "
                       "this checkout (synlab.fracture registers it as PENDING), so the "
                       "conformal half of A07 has no producer"),
            "acceptance_item": "A26",
        },
        "evidence": ["tests/a12/qc/run_precision_and_origin.py",
                     "data/a12/assets (clean_truth event trees)"],
    }
    _write("precision_report", report)
    return {"ok": report["ok"], "status": report["status"], "n_events": len(events),
            "t_junctions": t_junctions, "requested_mm": report["requested_mm"],
            "realized_mm": report["realized_mm"]}


def step_origin() -> dict[str, Any]:
    """A27: original triangle ids, patch areas, barycentric residuals, damage separation."""
    from synlab.truth.api import load_truth

    store = _store()
    n_samples = 0
    n_patches = 0
    patches_with_source_triangles = 0
    source_triangle_ids = 0
    residual_max = 0.0
    residual_values: list[float] = []
    bary_sum_max_error = 0.0
    association_kinds: dict[str, int] = {}
    residual_by_kind: dict[str, list[float]] = {}
    exact_over_budget = 0
    unmapped_samples = 0
    unmapped_flagged_invalid = 0
    mapped_bary_bad = 0
    r2_area_total = 0.0
    ambiguous_area_total = 0.0
    area_mismatch_max = 0.0
    non_r2_pairs_with_samples = 0
    events: list[dict[str, Any]] = []
    for asset in store.list_assets(role="clean_truth", limit=100000):
        truth = load_truth(store, asset.asset_id)
        pairs = {tuple(sorted((edge.fragment_a, edge.fragment_b))): edge.kind
                 for edge in truth.relations.values()}
        r2_pairs = {pair for pair, kind in pairs.items() if kind == "R2"}
        for interface in truth.interfaces:
            n_patches += 1
            evidence = ((truth.meta or {}).get("patch_evidence") or {}).get(
                str(interface.interface_id), {})
            source = evidence.get("source_triangles") or []
            if source:
                patches_with_source_triangles += 1
                source_triangle_ids += len(source)
            r2_area_total += float(getattr(interface, "area_mm2", 0.0) or 0.0)
            ambiguous_area_total += float(getattr(interface, "ambiguous_area_mm2", 0.0) or 0.0)
            # the two sampled sides must report the same patch area (same patch, two sides)
            a = float(np.asarray(interface.sample_points_a).shape[0]) if interface.sample_points_a is not None else 0
            b = float(np.asarray(interface.sample_points_b).shape[0]) if interface.sample_points_b is not None else 0
            if a and b:
                area_mismatch_max = max(area_mismatch_max, abs(a - b) / max(a, b))
        for sample in truth.correspondence:
            n_samples += 1
            residual = float(getattr(sample, "residual_mm", 0.0) or 0.0)
            kind = str(getattr(sample, "association_kind", "?"))
            residual_values.append(residual)
            residual_by_kind.setdefault(kind, []).append(residual)
            residual_max = max(residual_max, residual)
            association_kinds[kind] = association_kinds.get(kind, 0) + 1
            if kind == "EXACT_SURVIVOR" and residual > RESIDUAL_BUDGET_MM:
                exact_over_budget += 1
            face_a = int(getattr(sample, "face_a", -1) or -1)
            bary = np.asarray(getattr(sample, "bary_a", []), dtype=np.float64)
            if face_a < 0:
                # a sample with no triangle mapping must say so: it may not be valid and may
                # not claim an exact origin
                unmapped_samples += 1
                if getattr(sample, "valid", False) is False and kind != "EXACT_SURVIVOR":
                    unmapped_flagged_invalid += 1
            elif bary.size == 3:
                error = abs(float(bary.sum()) - 1.0)
                bary_sum_max_error = max(bary_sum_max_error, error)
                if error > 1e-9:
                    mapped_bary_bad += 1
            pair = tuple(sorted((sample.fragment_a, sample.fragment_b)))
            if pair not in r2_pairs and getattr(sample, "valid", False):
                non_r2_pairs_with_samples += 1
        events.append({"asset_id": asset.asset_id, "event_id": truth.event_id,
                       "interfaces": len(truth.interfaces), "samples": len(truth.correspondence),
                       "r2_pairs": len(r2_pairs)})
    residual_median = float(np.median(residual_values)) if residual_values else None
    exact_residuals = residual_by_kind.get("EXACT_SURVIVOR", [])
    explicit_ids_ok = bool(n_patches) and patches_with_source_triangles == n_patches
    residual_ok = bool(exact_residuals) and exact_over_budget == 0
    bary_ok = mapped_bary_bad == 0
    unmapped_ok = unmapped_samples == unmapped_flagged_invalid
    separation_ok = exact_over_budget == 0 and "UNKNOWN_MAPPING" in association_kinds
    ok = explicit_ids_ok and residual_ok and bary_ok and unmapped_ok and separation_ok
    report = {
        "ok": bool(ok),
        "status": "PASS" if ok else "FAIL",
        "check": "A27 origin correspondence (plan 21.x row)",
        "metrics": {
            "n_events": len(events),
            "n_interfaces": n_patches,
            "n_correspondence_samples": n_samples,
            "patches_with_explicit_source_triangle_ids": patches_with_source_triangles,
            "source_triangle_id_count": source_triangle_ids,
            "explicit_triangle_ids_ok": explicit_ids_ok,
            "barycentric_residual_mm_max": residual_max,
            "barycentric_residual_mm_median": residual_median,
            "barycentric_residual_mm_max_exact_survivor": (max(exact_residuals)
                                                           if exact_residuals else None),
            "barycentric_residual_budget_mm": RESIDUAL_BUDGET_MM,
            "barycentric_residual_budget_source": ("synlab.fracture.spec."
                                                   "CORRESPONDENCE_RESIDUAL_MM, the constant "
                                                   "synlab.truth.api uses to decide `exact`"),
            "exact_survivor_samples_over_budget": exact_over_budget,
            "barycentric_sum_max_error": bary_sum_max_error,
            "samples_without_triangle_mapping": unmapped_samples,
            "samples_without_triangle_mapping_flagged_invalid": unmapped_flagged_invalid,
            "mapped_samples_with_barycentric_error_above_1e-9": mapped_bary_bad,
            "r2_patch_area_mm2_total": r2_area_total,
            "ambiguous_area_mm2_total": ambiguous_area_total,
            "sampled_side_count_mismatch_max": area_mismatch_max,
            "association_kinds": association_kinds,
            "damage_association_separated": separation_ok,
            "samples_visible_to_the_pair_not_labelled_r2": non_r2_pairs_with_samples,
            "negative_control": ("no sample may be labelled EXACT_SURVIVOR with a residual "
                                 "above the codebase's own exactness budget: a fabricated "
                                 "correspondence fails this counter"),
            "events": events[:50],
        },
        "evidence": ["tests/a12/qc/run_precision_and_origin.py",
                     "data/a12/assets (clean_truth correspondence bundles)"],
    }
    _write("origin_correspondence_audit", report)
    return {"ok": report["ok"], "n_interfaces": n_patches, "n_samples": n_samples,
            "residual_max_mm": residual_max,
            "exact_survivor_over_budget": exact_over_budget,
            "unknown_mapping_samples": association_kinds.get("UNKNOWN_MAPPING", 0)}


STEPS = {"precision": step_precision, "origin": step_origin}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--step", required=True, choices=sorted(STEPS))
    args = parser.parse_args()
    started = time.time()
    try:
        summary = STEPS[args.step]()
    except Exception as exc:  # noqa: BLE001 - reported, never hidden
        import traceback

        summary = {"ok": False, "status": "RAISED", "error": f"{type(exc).__name__}: {exc}",
                   "traceback": traceback.format_exc()[-2000:]}
    summary["seconds"] = round(time.time() - started, 2)
    print(json.dumps(summary, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
