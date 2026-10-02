#!/usr/bin/env python
"""S11 driver: where does the P03 *global SDF* extraction drift come from, and what fixes it.

The measured defect (``data/a12/reports/a09_p03_probe.json``): the P03 ``smooth_recession_field``
level-1 recipe declares a 0.05 mm recession field and realises
``realized_mean_recession_mm = 0.0120``, yet the delivered body loses
``lost_volume_mm3 = 276.58`` (5-6x the 43.54 mm3 linear prediction) and displaces the surface
**outside** the ROI by ``roi_external_drift_mm = 0.2866``.

This driver decomposes that number instead of arguing about it.  Every stage is one real
measurement on one real archived body (default ``data/a12_degrade/store``,
``LIN0000_V02_M01_PAT02_E01-m`` -- the same lineage the a09 probe used):

``--step context``
    The frozen grid: spacing (and its basis), halo, pad, node count, the ROI and -- decisively --
    ``surface_zero_level_rms_mm`` / ``surface_zero_level_max_mm``: how far the **node-sampled**
    ``d0`` field, trilinearly interpolated, is from zero *on the true clean surface*.  That is the
    reconstruction error of the field the level set is extracted from.

``--step extraction``
    ``marching_cubes(d0)`` with **no damage at all** (the exact same grid and the same call
    ``SdfContext.extract`` makes), then measured against the clean body: volume error, face count,
    watertightness, and the same ``_roi_external_drift`` instrument the operator reports.  This is
    the control that separates "the damage field moved the surface" from "re-extracting the level
    set moved the surface".

``--step full``
    The real operator (``physical.operators.run_damage``), with a spy on ``intersect_with_source``
    so the pre-clip candidate and the clipped body are both measured; plus
    ``physical.api.audit_physical`` for the delivered verdict.

``--step narrowband``
    The same body and the same frozen recipe through ``degrade.physical_narrowband`` (the
    narrow-band P03 backend that already exists in this checkout), measured with the **same**
    drift instrument.

``--step sweep``
    Drift vs requested grid spacing and vs declared depth -- the two knobs that decide whether the
    residual is a resolution artefact (fixable by refining) or a modelling one.

Usage::

    python tools/a12_s11_p03_drift.py --step all \
        --store data/a12_degrade/store --out data/a12_reports/s11_p03_drift.json
"""

from __future__ import annotations

import argparse
import gc
import json
import sys
import time
import traceback
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Sequence

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_STORE = "data/a12_degrade/store"
DEFAULT_CONFIG = "configs/a12/sandbox.yaml"
DEFAULT_RECIPE = "P03_depth_light"
DEFAULT_LINEAGE = "LIN0000_V02_M01_PAT02"


# --------------------------------------------------------------------------------------
# instruments
# --------------------------------------------------------------------------------------
def _boundary_edges(mesh: Any) -> int:
    edges = np.asarray(mesh.edges_sorted, dtype=np.int64)
    if len(edges) == 0:
        return 0
    order = np.lexsort(edges.T)
    edges = edges[order]
    same = np.all(edges[1:] == edges[:-1], axis=1)
    starts = np.concatenate([[True], ~same])
    run_id = np.cumsum(starts) - 1
    counts = np.bincount(run_id)
    return int(np.count_nonzero(counts == 1))


def _mesh_summary(mesh: Any, clean: Any, *, n_samples: int = 20000, seed: int = 0) -> dict:
    from synlab.physical import sdf as S

    outside = S.outside_fraction(mesh, clean, n_samples=n_samples, tol_mm=1e-3, seed=seed)
    return {
        "volume_mm3": float(abs(mesh.volume)),
        "volume_error_mm3": float(abs(mesh.volume) - abs(clean.volume)),
        "volume_error_rel": float(abs(mesh.volume) / max(abs(clean.volume), 1e-12) - 1.0),
        "area_mm2": float(mesh.area),
        "n_faces": int(len(mesh.faces)), "n_vertices": int(len(mesh.vertices)),
        "watertight": bool(mesh.is_watertight),
        "winding_consistent": bool(mesh.is_winding_consistent),
        "boundary_edges": _boundary_edges(mesh),
        "euler_number": int(mesh.euler_number),
        "bodies": int(len(S.component_split(mesh))),
        "outside_fraction": float(outside["outside_fraction"]),
        "max_outside_mm": float(outside["max_outside_mm"]),
        "samples": int(outside["samples"]),
    }


def _vertex_residue(mesh: Any, reference: Any) -> dict:
    """``|signed distance to the clean surface|`` of every vertex of ``mesh``.

    This is a *direct* reading of how far the reconstructed surface sits from the surface the
    field was built from -- it needs no sampling and no threshold, so it is the sharpest
    available statement about the extraction error itself.
    """
    from synlab.physical import sdf as S

    verts = np.asarray(mesh.vertices, dtype=np.float64)
    if verts.size == 0:
        return {"n": 0}
    signed = S.scene_for(reference).signed_distance(verts)
    return {
        "n": int(len(verts)),
        "abs_mean_mm": float(np.abs(signed).mean()),
        "abs_p95_mm": float(np.percentile(np.abs(signed), 95)),
        "abs_max_mm": float(np.abs(signed).max()),
        "signed_min_mm": float(signed.min()), "signed_max_mm": float(signed.max()),
        "outside_fraction_of_vertices": float((signed > 1e-3).mean()),
    }


def _drift(body: Any, ctx: Any, halo_mm: float) -> float:
    from synlab.physical.operators import _roi_external_drift

    return float(_roi_external_drift(body, ctx, halo_mm=float(halo_mm)))


# --------------------------------------------------------------------------------------
# setup
# --------------------------------------------------------------------------------------
def load_fragment(store_root: str | Path, *, fragment_id: str | None = None) -> tuple[Any, Any, str]:
    from synlab.roles import ROLE_FRAGMENT_MESH
    from synlab.storage.store import AssetStore

    store = AssetStore(store_root)
    assets = store.list_assets(role=ROLE_FRAGMENT_MESH, limit=100000)
    if not assets:
        raise SystemExit(f"no fragment_mesh asset in {store_root}")
    wanted = [a for a in assets if not fragment_id or str(a.meta.get("fragment_id")) == fragment_id]
    if not wanted:
        wanted = assets
    best = max(wanted, key=lambda r: float(abs(store.load_mesh(r.asset_id, "mesh").volume)))
    mesh = store.load_mesh(best.asset_id, "mesh")
    return store, mesh, str(best.meta.get("fragment_id"))


def build_recipe(config: str | Path, recipe_id: str, lineage_id: str, mesh: Any, name: str):
    from synlab.config import load_generation_spec
    from synlab.pipeline import _load_damage_recipe

    spec = load_generation_spec(config)
    fragment = SimpleNamespace(mesh=mesh, fragment_id=name, volume_mm3=float(abs(mesh.volume)),
                               is_tiny=False, meta={"material_id": ""})
    return spec, fragment, _load_damage_recipe(recipe_id, spec, fragment=fragment,
                                               master_seed=spec.master_seed,
                                               lineage_id=lineage_id)


def _recipe_with_grid(recipe: Any, *, spacing_mm: float | None = None,
                      depth_mm: float | None = None,
                      project_to_level_set: bool | None = None) -> Any:
    from dataclasses import replace

    grid = dict(recipe.grid or {})
    if spacing_mm is not None:
        grid["spacing_mm"] = float(spacing_mm)
    if project_to_level_set is not None:
        grid["project_to_level_set"] = bool(project_to_level_set)
    params = dict(recipe.params or {})
    if depth_mm is not None:
        params["depth_mm"] = float(depth_mm)
    return replace(recipe, grid=grid, params=params)


def step_fix(mesh: Any, recipe: Any, fragment: Any, *, n_samples: int) -> dict:
    """The minimal fix: the same operator with the level-set projection on, vs off."""
    from synlab.physical.operators import PROJECT_TO_LEVEL_SET_DEFAULT, SdfContext

    before = step_full(mesh, _recipe_with_grid(recipe, project_to_level_set=False), fragment,
                       n_samples=n_samples)
    after = step_full(mesh, _recipe_with_grid(recipe, project_to_level_set=True), fragment,
                      n_samples=n_samples)
    projection = {}
    pipelines = [
        ((after.get("details") or {}).get("sdf_pipeline") or {}),
        ((after.get("marching_cubes_candidate") or {}).get("level_set_projection") or {}),
    ]
    for pipeline in pipelines:
        if isinstance(pipeline, dict) and pipeline.get("level_set_projection"):
            projection = pipeline["level_set_projection"]
    ctx = SdfContext(mesh, recipe, fragment=fragment)
    return {
        "default": bool(PROJECT_TO_LEVEL_SET_DEFAULT),
        "before": _fix_view(before), "after": _fix_view(after),
        "level_set_projection": projection,
        "effective_spacing_mm": float(ctx.spacing),
        "delta": {
            "drift_mm": (after["operator_measurements"].get("roi_external_drift_mm", 0.0)
                         - before["operator_measurements"].get("roi_external_drift_mm", 0.0)),
            "lost_volume_mm3": (after["operator_measurements"].get("lost_volume_mm3", 0.0)
                                - before["operator_measurements"].get("lost_volume_mm3", 0.0)),
            "linear_predicted_loss_mm3": before["operator_measurements"].get(
                "lost_volume_mm3", 0.0) - after["operator_measurements"].get(
                    "lost_volume_mm3", 0.0),
        },
    }


def _fix_view(step: dict) -> dict:
    measurements = step.get("operator_measurements") or {}
    accepted = step.get("accepted_after_clip") or {}
    candidate = step.get("marching_cubes_candidate") or {}
    return {
        "drift_mm": measurements.get("roi_external_drift_mm"),
        "lost_volume_mm3": measurements.get("lost_volume_mm3"),
        "audit_status": (step.get("audit") or {}).get("status"),
        "failure_codes": (step.get("audit") or {}).get("failure_codes"),
        "roi_external_drift_check": ((step.get("audit") or {}).get("checks") or {}).get(
            "roi_external_drift"),
        "candidate_n_faces": candidate.get("n_faces"),
        "accepted_n_faces": accepted.get("n_faces"),
        "accepted_watertight": accepted.get("watertight"),
        "accepted_boundary_edges": accepted.get("boundary_edges"),
        "accepted_volume_error_mm3": accepted.get("volume_error_mm3"),
    }


# --------------------------------------------------------------------------------------
# steps
# --------------------------------------------------------------------------------------
def step_context(mesh: Any, recipe: Any, fragment: Any) -> dict:
    from synlab.physical import sdf as S
    from synlab.physical.operators import SdfContext

    ctx = SdfContext(mesh, recipe, fragment=fragment)
    b_fn = _field_function(ctx, recipe)
    halo = _halo_for(recipe, ctx)
    anchors = np.asarray(ctx.anchors, dtype=np.float64)
    anchor_values = b_fn(anchors)
    # the linear (small-recession) volume prediction: depth * b(face centroid) integrated over the
    # ROI faces, exactly the form the narrow-band backend reports as
    # ``linearised_predicted_loss_mm3`` -- so the two backends are compared on one formula.
    centroids = np.asarray(mesh.triangles_center, dtype=np.float64)[ctx.roi_ids]
    face_values = b_fn(centroids)
    face_areas = np.asarray(mesh.area_faces, dtype=np.float64)[ctx.roi_ids]
    return {
        "mesh": {"volume_mm3": float(abs(mesh.volume)), "n_faces": int(len(mesh.faces)),
                 "n_vertices": int(len(mesh.vertices)), "area_mm2": float(mesh.area),
                 "watertight": bool(mesh.is_watertight)},
        "grid": ctx.grid.as_dict(),
        "spacing_basis": ctx.spacing_info.get("basis"),
        "spacing_candidates": ctx.spacing_info.get("criteria"),
        "pad_mm": float(ctx.pad_mm),
        "halo_mm": float(halo),
        "roi": {"faces": int(len(ctx.roi_ids)),
                "area_mm2": float(ctx.interface_area_mm2),
                "anchors": int(len(ctx.anchors))},
        "sdf_backend": ctx.sdf_info.get("backend"),
        # the decisive number: the node-sampled d0, *trilinearly interpolated*, evaluated on the
        # true clean surface.  It is zero only if the sampled field really represents the body.
        "surface_zero_level_rms_mm": float(ctx.sdf_info.get("surface_zero_level_rms_mm", 0.0)),
        "surface_zero_level_max_mm": float(ctx.sdf_info.get("surface_zero_level_max_mm", 0.0)),
        "surface_check_samples": int(ctx.sdf_info.get("surface_check_samples", 0)),
        "field_declared": {"depth_mm": float(recipe.parameter("depth_mm", 0.0)),
                           "corr_length_mm": float(recipe.parameter("corr_length_mm", 0.0))},
        "field_realised_on_roi_anchors": {
            "max_mm": float(anchor_values.max()), "mean_mm": float(anchor_values.mean()),
            "zero_fraction": float((anchor_values <= 0).mean())},
        "field_realised_on_roi_face_centroids": {
            "max_mm": float(face_values.max()), "mean_mm": float(face_values.mean())},
        "linear_predicted_loss_mm3": float(np.sum(face_areas * face_values)),
    }


def _field_function(ctx: Any, recipe: Any):
    """The operator's own ``b_fn`` (the declared, normalised recession field)."""
    from synlab.physical import fields as F

    field = F.FourierField.from_payload(recipe.basis["field"])
    anchor_values = np.clip(field(ctx.anchors), 0.0, 1.0)
    normalizer = float(max(np.percentile(anchor_values, 99.0), 1e-6))
    depth = float(recipe.parameter("depth_mm", 0.0))
    return lambda points: depth * np.clip(field(points) / normalizer, 0.0, 1.0)


def _halo_for(recipe: Any, ctx: Any) -> float:
    return float(recipe.parameter("depth_mm", 0.0)) * 2.0 + float(
        recipe.meta.get("halo_mm", 3.0 * ctx.spacing + 1.0))


def step_extraction(mesh: Any, recipe: Any, fragment: Any, *, n_samples: int,
                    spacing_mm: float | None = None, depth_mm: float | None = None) -> dict:
    from synlab.physical import sdf as S
    from synlab.physical.operators import SdfContext

    use = _recipe_with_grid(recipe, spacing_mm=spacing_mm, depth_mm=depth_mm)
    ctx = SdfContext(mesh, use, fragment=fragment)
    halo = _halo_for(use, ctx)
    started = time.perf_counter()
    body = S.marching_cubes_mesh(ctx.d0, ctx.grid)
    seconds = time.perf_counter() - started
    summary = _mesh_summary(body, mesh, n_samples=n_samples, seed=1)
    residue = _vertex_residue(body, mesh)
    drift = _drift(body, ctx, halo)
    out = {
        "requested": {"spacing_mm": spacing_mm, "depth_mm": depth_mm},
        "effective_spacing_mm": float(ctx.spacing),
        "grid_shape": list(ctx.grid.shape),
        "halo_mm": halo,
        "extraction_seconds": float(seconds),
        "mesh": summary, "vertex_residue_vs_clean": residue,
        "roi_external_drift_mm": drift,
        "surface_zero_level_rms_mm": float(ctx.sdf_info.get("surface_zero_level_rms_mm", 0.0)),
        "surface_zero_level_max_mm": float(ctx.sdf_info.get("surface_zero_level_max_mm", 0.0)),
    }
    del body
    gc.collect()
    return out


def step_full(mesh: Any, recipe: Any, fragment: Any, *, n_samples: int) -> dict:
    from synlab.physical import sdf as S
    from synlab.physical.api import apply_damage, audit_physical
    from synlab.physical.operators import SdfContext
    from synlab.seeds import derive_named_rngs

    captured: dict[str, Any] = {}
    original = S.intersect_with_source

    def spy(candidate, source, **kwargs):
        out, info = original(candidate, source, **kwargs)
        captured["candidate"] = candidate.copy()
        captured["accepted"] = out.copy()
        captured["clip"] = dict(info)
        return out, info

    clean_stub = SimpleNamespace(mother_id="S11", event_id="S11_E01", version=1)
    rng = derive_named_rngs(20261001, "S11_LIN")["damage"]
    S.intersect_with_source = spy
    started = time.perf_counter()
    try:
        result = apply_damage(clean_stub, fragment, recipe, rng)
    finally:
        S.intersect_with_source = original
    seconds = time.perf_counter() - started
    ctx = SdfContext(mesh, recipe, fragment=fragment)
    halo = _halo_for(recipe, ctx)
    out: dict[str, Any] = {
        "seconds": float(seconds),
        "operator_measurements": {k: float(v) for k, v in (result.meta.get("measured") or {}).items()},
        "operator_units": _jsonable(result.meta.get("measurement_units")),
        "qa_status": result.qa.get("status"),
        "realized": result.qa.get("realized"),
        "component_count": len(result.components),
        "ledger": _jsonable(result.meta.get("ledger")),
        "details": {"sdf_pipeline": _jsonable((result.meta.get("details") or {}).get("sdf_pipeline")),
                    "roi": _jsonable((result.meta.get("details") or {}).get("roi"))},
        "halo_mm": halo,
    }
    candidate = captured.get("candidate")
    if candidate is not None:
        out["marching_cubes_candidate"] = _mesh_summary(candidate, mesh, n_samples=n_samples,
                                                        seed=2)
        out["marching_cubes_candidate"]["vertex_residue_vs_clean"] = _vertex_residue(candidate,
                                                                                     mesh)
        out["marching_cubes_candidate"]["roi_external_drift_mm"] = _drift(candidate, ctx, halo)
        out["clip"] = _jsonable(captured.get("clip"))
    accepted = captured.get("accepted")
    if accepted is not None:
        out["accepted_after_clip"] = _mesh_summary(accepted, mesh, n_samples=n_samples, seed=3)
        out["accepted_after_clip"]["roi_external_drift_mm"] = _drift(accepted, ctx, halo)
    audit = audit_physical(result, mesh)
    out["audit"] = {
        "status": audit.get("status"), "failure_codes": audit.get("failure_codes"),
        "measured": {k: float(v) for k, v in (audit.get("measured") or {}).items()
                     if isinstance(v, (int, float))},
        "checks": {k: _jsonable(v) for k, v in (audit.get("checks") or {}).items()},
    }
    del candidate, accepted
    gc.collect()
    return out


def step_narrowband(mesh: Any, recipe: Any, fragment: Any, *, n_samples: int) -> dict:
    from synlab.degrade.physical_narrowband import run_narrowband_damage
    from synlab.physical import sdf as S
    from synlab.physical.api import audit_physical
    from synlab.physical.operators import SdfContext

    started = time.perf_counter()
    result = run_narrowband_damage(mesh, recipe, fragment=fragment, rng=None)
    seconds = time.perf_counter() - started
    ctx = SdfContext(mesh, recipe, fragment=fragment)
    halo = _halo_for(recipe, ctx)
    representative = next((c for c in result.components if c.is_representative),
                          result.components[0] if result.components else None)
    body = representative.mesh if representative is not None else None
    out: dict[str, Any] = {
        "seconds": float(seconds),
        "measured": _jsonable(result.meta.get("measured") or {}),
        "measured_scalars": {k: float(v) for k, v in (result.meta.get("measured") or {}).items()
                             if isinstance(v, (int, float)) and not isinstance(v, bool)},
        "ledger": _jsonable(result.meta.get("ledger")),
        "component_count": len(result.components),
        "audit_status": (audit_physical(result, mesh).get("status")),
        "backend": result.meta.get("damage_backend"),
        "narrowband_detail": _jsonable((result.meta.get("details") or {}).get("narrowband")),
    }
    if body is not None:
        out["body"] = _mesh_summary(body, mesh, n_samples=n_samples, seed=4)
        out["body"]["roi_external_drift_mm"] = _drift(body, ctx, halo)
        out["body"]["vertex_residue_vs_clean"] = _vertex_residue(body, mesh)
    del body
    gc.collect()
    return out


def step_sweep(mesh: Any, recipe: Any, fragment: Any, *, n_samples: int,
               spacings: Sequence[float], depths: Sequence[float]) -> dict:
    grid_rows = []
    for spacing in spacings:
        row = step_extraction(mesh, recipe, fragment, n_samples=n_samples, spacing_mm=spacing)
        grid_rows.append(row)
    depth_rows = []
    for depth in depths:
        row = step_extraction(mesh, recipe, fragment, n_samples=n_samples, depth_mm=depth)
        radius = float(np.linalg.norm(np.asarray(mesh.bounds[1]) - np.asarray(mesh.bounds[0])))
        depth_rows.append({**row, "bbox_diagonal_mm": radius})
    return {"spacing_sweep": grid_rows, "depth_sweep": depth_rows}


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


# --------------------------------------------------------------------------------------
def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="a12_s11_p03_drift")
    parser.add_argument("--step", default="all",
                        choices=("context", "extraction", "full", "narrowband", "sweep", "fix",
                                 "all"))
    parser.add_argument("--store", default=DEFAULT_STORE)
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--recipe", default=DEFAULT_RECIPE)
    parser.add_argument("--lineage", default=DEFAULT_LINEAGE)
    parser.add_argument("--fragment", default=None)
    parser.add_argument("--samples", type=int, default=20000)
    parser.add_argument("--spacings", default="0.25,0.5,1.0")
    parser.add_argument("--depths", default="0.0,0.00625,0.0125,0.025,0.05")
    parser.add_argument("--out", default="data/a12_reports/s11_p03_drift.json")
    args = parser.parse_args(argv)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"schema": "synlab.a12.s11.p03_drift.v1",
                              "store": args.store, "recipe_id": args.recipe,
                              "lineage_id": args.lineage, "step": args.step}
    try:
        store, mesh, fragment_id = load_fragment(args.store, fragment_id=args.fragment)
        spec, fragment, recipe = build_recipe(args.config, args.recipe, args.lineage, mesh,
                                              fragment_id)
        report["fragment_id"] = fragment_id
        report["config"] = args.config
        report["recipe"] = {"axis_id": recipe.axis_id, "variant": recipe.variant,
                            "level": int(recipe.level), "params": _jsonable(recipe.params),
                            "roi": _jsonable(recipe.roi), "qa": _jsonable(recipe.qa),
                            "grid": _jsonable(recipe.grid),
                            "basis_source": recipe.meta.get("basis_source")}
        if args.step in ("context", "all"):
            report["context"] = step_context(mesh, recipe, fragment)
        if args.step in ("extraction", "all"):
            report["extraction_only"] = step_extraction(mesh, recipe, fragment,
                                                        n_samples=args.samples)
        if args.step in ("full", "all"):
            report["full"] = step_full(mesh, recipe, fragment, n_samples=args.samples)
        if args.step in ("narrowband", "all"):
            report["narrowband"] = step_narrowband(mesh, recipe, fragment,
                                                   n_samples=args.samples)
        if args.step in ("sweep", "all"):
            report["sweep"] = step_sweep(
                mesh, recipe, fragment, n_samples=min(args.samples, 5000),
                spacings=[float(v) for v in args.spacings.split(",") if v],
                depths=[float(v) for v in args.depths.split(",") if v != ""])
        if args.step in ("fix", "all"):
            report["fix"] = step_fix(mesh, recipe, fragment, n_samples=min(args.samples, 20000))
        report["ok"] = True
    except BaseException as exc:  # noqa: BLE001 - a crash is an outcome
        report["ok"] = False
        report["escaped_exception"] = f"{type(exc).__name__}: {exc}"
        report["traceback"] = traceback.format_exc()[-4000:]
    out.write_text(json.dumps(_jsonable(report), ensure_ascii=False, indent=2, sort_keys=True,
                              default=str), encoding="utf-8")
    print(json.dumps(_summary(report), ensure_ascii=False, indent=2, default=str))
    print(f"wrote {out}")
    return 0 if report.get("ok") else 1


def _summary(report: dict) -> dict:
    out: dict[str, Any] = {"ok": report.get("ok"), "step": report.get("step"),
                           "fragment_id": report.get("fragment_id")}
    if "escaped_exception" in report:
        out["escaped_exception"] = report["escaped_exception"]
        out["traceback"] = report.get("traceback")
        return out
    ctx = report.get("context")
    if ctx:
        out["context"] = {"spacing_mm": ctx["grid"]["spacing_mm"], "basis": ctx["spacing_basis"],
                          "grid_shape": ctx["grid"]["shape"], "halo_mm": ctx["halo_mm"],
                          "roi_faces": ctx["roi"]["faces"],
                          "surface_zero_level_rms_mm": ctx["surface_zero_level_rms_mm"],
                          "surface_zero_level_max_mm": ctx["surface_zero_level_max_mm"],
                          "linear_predicted_loss_mm3": ctx["linear_predicted_loss_mm3"]}
    ext = report.get("extraction_only")
    if ext:
        out["extraction_only"] = {"drift_mm": ext["roi_external_drift_mm"],
                                  "volume_error_mm3": ext["mesh"]["volume_error_mm3"],
                                  "n_faces": ext["mesh"]["n_faces"],
                                  "watertight": ext["mesh"]["watertight"],
                                  "vertex_abs_max_mm": ext["vertex_residue_vs_clean"]["abs_max_mm"]}
    full = report.get("full")
    if full:
        m = full["operator_measurements"]
        out["full"] = {"drift_mm": m.get("roi_external_drift_mm"),
                       "lost_volume_mm3": m.get("lost_volume_mm3"),
                       "audit": full["audit"]["status"],
                       "failure_codes": full["audit"]["failure_codes"]}
    nb = report.get("narrowband")
    if nb:
        m = nb["measured_scalars"]
        out["narrowband"] = {"drift_mm": m.get("roi_external_drift_mm"),
                             "lost_volume_mm3": m.get("lost_volume_mm3"),
                             "linear_mm3": m.get("linearised_predicted_loss_mm3"),
                             "components": nb["component_count"], "audit": nb["audit_status"]}
    fix = report.get("fix")
    if fix:
        out["fix"] = {"default": fix["default"], "delta": fix["delta"],
                      "projection": {k: fix["level_set_projection"].get(k)
                                     for k in ("applied", "accepted_fraction",
                                               "residual_before_mm", "residual_after_mm",
                                               "reason")},
                      "before": fix["before"], "after": fix["after"]}
    sweep = report.get("sweep")
    if sweep:
        out["spacing_sweep"] = [{"spacing_mm": r["effective_spacing_mm"],
                                 "drift_mm": r["roi_external_drift_mm"],
                                 "volume_error_mm3": r["mesh"]["volume_error_mm3"],
                                 "n_faces": r["mesh"]["n_faces"]}
                                for r in sweep["spacing_sweep"]]
        out["depth_sweep"] = [{"depth_mm": r["requested"]["depth_mm"],
                               "drift_mm": r["roi_external_drift_mm"],
                               "volume_error_mm3": r["mesh"]["volume_error_mm3"]}
                              for r in sweep["depth_sweep"]]
    return out


if __name__ == "__main__":
    raise SystemExit(main())
