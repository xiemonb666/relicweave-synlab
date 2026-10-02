#!/usr/bin/env python
"""Stage 2 driver: one mother, one cut plane, three cases (plane / M03 / M07).

Every number is measured on real artifacts:

* the mother comes from ``synlab.mothers.api.create_mother`` with the demo vessel's own frozen
  parameters (``data/a12_demo/demo_manifest.json``);
* the material profiles come from ``synlab.materials.api.build_material_profile``;
* the wall thickness comes from the frozen mother audit (``morphology.wall_thickness``);
* the cut basis is *one* basis, shared by all three cases, so the comparison is apples to apples;
* the shared cutter goes through ``synlab.fracture.cut.build_closed_cutter`` and both sides through
  ``synlab.fracture.event.run_shared_cut``;
* ``Ra`` / ``Rz`` come from ``surface_features.amplitude_statistics`` on the ``w`` residual of the
  **delivered interface faces** after ``detrend_plane``; the correlation length from
  ``correlation_length`` and the crest-line density from ``ridge_density``;
* conjugacy from ``surface_features.conjugate_profile_consistency`` and the A06 numbers from
  ``synlab.fracture.api.audit_fracture``.

Usage::

    .venv\\Scripts\\python.exe tests\\a12\\fracture\\_run_physical_layer_matrix.py --vessel V18
"""

from __future__ import annotations

import argparse
import json
import pickle
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

MASTER_SEED = 20261001
LINEAGE_ID = "a12_physical_layer"


class MeasurementRuler:
    """The three fields the surface-feature tools read off a parameter record.

    Module level (not a closure) so the measurement bundles stay picklable.
    """

    __slots__ = ("origin_uv_mm", "mirror_radius_mm", "mist_radius_mm")

    def __init__(self, *, origin_uv_mm: tuple[float, float], mirror_radius_mm: float,
                 mist_radius_mm: float) -> None:
        self.origin_uv_mm = (float(origin_uv_mm[0]), float(origin_uv_mm[1]))
        self.mirror_radius_mm = float(mirror_radius_mm)
        self.mist_radius_mm = float(mist_radius_mm)


# ---------------------------------------------------------------------------- json helper
def jsonable(value: Any, *, depth: int = 0, max_array: int = 24) -> Any:
    if depth > 8:
        return f"<{type(value).__name__}>"
    if isinstance(value, dict):
        return {str(k): jsonable(v, depth=depth + 1, max_array=max_array)
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        if len(value) > 512:
            return {"length": len(value),
                    "head": [jsonable(v, depth=depth + 1, max_array=max_array)
                             for v in value[:8]]}
        return [jsonable(v, depth=depth + 1, max_array=max_array) for v in value]
    if isinstance(value, np.ndarray):
        flat = value.reshape(-1)
        if flat.size == 0:
            return {"shape": list(value.shape), "empty": True}
        if flat.size > max_array:
            info: dict[str, Any] = {"shape": list(value.shape), "size": int(flat.size)}
            if flat.dtype.kind in "fiub":
                info["min"] = float(np.min(flat))
                info["max"] = float(np.max(flat))
                info["mean"] = float(np.mean(flat))
            return info
        return [jsonable(v, depth=depth + 1, max_array=max_array) for v in flat.tolist()]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "as_dict"):
        return jsonable(value.as_dict(), depth=depth + 1, max_array=max_array)
    return str(value)


def error_record(exc: BaseException) -> dict[str, Any]:
    return {"code": getattr(getattr(exc, "code", None), "value", type(exc).__name__),
            "stage": getattr(exc, "stage", ""), "message": str(exc)[:800],
            "measurements": jsonable(getattr(exc, "measurements", None)),
            "traceback_tail": traceback.format_exc()[-2000:]}


# ---------------------------------------------------------------------------- inputs
def build_mother(vessel_id: str, material_id: str) -> tuple[Any, dict[str, Any]]:
    import json as _json

    from synlab.mothers.api import create_mother, load_mother
    from synlab.seeds import make_rng
    from synlab.storage.store import AssetStore

    demo_root = REPO_ROOT / "data" / "a12_demo"
    manifest = _json.loads((demo_root / "demo_manifest.json").read_text(encoding="utf-8"))
    entry = next(e for e in manifest["entries"] if e["entry_id"] == f"mother:{vessel_id}")
    demo = load_mother(AssetStore(demo_root / "store"), str(entry["asset_id"]))
    rng = make_rng(MASTER_SEED, LINEAGE_ID, "mothers", vessel_id, material_id)
    mother = create_mother(vessel_id, material_id, dict(demo.params), rng,
                           mother_id=f"{LINEAGE_ID}_{vessel_id}_{material_id}")
    return mother, {"demo_mother_id": demo.mother_id, "demo_material_id": demo.material_id,
                    "demo_params": jsonable(dict(demo.params)),
                    "source": "synlab.mothers.api.create_mother(demo params, real material)"}


def build_material(material_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    from synlab.materials.api import (build_material_profile, canonical_material_params,
                                      default_material_params)
    from synlab.seeds import make_rng

    params = default_material_params(material_id)
    canonical = canonical_material_params(material_id, params)
    rng = make_rng(MASTER_SEED, LINEAGE_ID, "materials", material_id)
    profile = build_material_profile(material_id, params, rng)
    return profile, {"params": jsonable(canonical),
                     "profile_hash": profile.get("profile_hash"),
                     "stats": jsonable(profile.get("stats")),
                     "appearance": jsonable(profile.get("appearance")),
                     "layers": jsonable(profile.get("layers"))}


# ---------------------------------------------------------------------------- measurement
def measure_delivered(result: Any, basis: Any, params: Any, *, cutter_mesh: Any,
                      n_samples: int) -> dict[str, Any]:
    """Explicit Ra / Rz / correlation length / crest density on the delivered interface faces.

    This is the same population ``measure_interface_surface`` uses (the frozen
    ``event._interface_faces`` criterion: every vertex on the cutter surface *and* the face normal
    (anti)parallel to it), but the three hard indicators are called individually so each one can be
    reported on its own and re-checked by a reader.
    """
    from synlab.fracture import surface_features as sf
    from synlab.fracture.event import _interface_faces

    rng = np.random.default_rng(20261001)
    triangles: list[np.ndarray] = []
    faces_total = 0
    faces_by_fragment: dict[str, int] = {}
    for fragment in result.fragments:
        ids, _sources, _centres = _interface_faces(fragment, cutter_mesh)
        faces_by_fragment[fragment.fragment_id] = int(ids.size)
        if ids.size == 0:
            continue
        faces_total += int(ids.size)
        local = sf.triangle_vertices_local(fragment.mesh, basis, ids)
        triangles.append(local.reshape(-1, 3, 3))
    if not triangles:
        return {"samples": 0, "note": "no interface faces in the result",
                "faces_by_fragment": faces_by_fragment}
    soup = np.concatenate(triangles, axis=0)
    samples = sf._sample_triangles(soup, int(n_samples), rng)
    u, v, w = samples["u"], samples["v"], samples["w"]
    if u.size < 64:
        return {"samples": int(u.size), "note": "fewer than 64 samples",
                "faces_by_fragment": faces_by_fragment}
    detrend = sf.detrend_plane(u, v, w)
    residual = detrend["residual"]
    amplitude = sf.amplitude_statistics(u, v, residual)
    correlation = sf.correlation_length(u, v, residual)
    origin = tuple(params.origin_uv_mm)
    mirror = float(params.mirror_radius_mm)
    mist = float(params.mist_radius_mm)
    radii = [max(mirror * 1.2, 0.5), max(mist, mirror * 1.5), max(3.0 * mirror, 3.0),
             max(6.0 * mirror, 6.0), max(12.0 * mirror, 12.0)]
    ridges = sf.ridge_density(u, v, residual, origin, radii)
    radius = np.hypot(u - origin[0], v - origin[1])
    zones = {}
    for name, selector in (("mirror", radius < mirror),
                           ("mist", (radius >= mirror) & (radius < mist)),
                           ("hackle", radius >= mist)):
        if int(selector.sum()) < 32:
            zones[name] = {"samples": int(selector.sum())}
            continue
        stats = sf.amplitude_statistics(u[selector], v[selector], residual[selector])
        zones[name] = {"samples": int(selector.sum()), "Ra_mm": stats["Ra_mm"],
                       "Rq_mm": stats["Rq_mm"], "Rz_mm": stats["Rz_mm"]}
    return {
        "samples": int(u.size), "interface_faces": int(faces_total),
        "faces_by_fragment": faces_by_fragment,
        "measured_area_mm2": float(soup.shape[0] * 0.0 + samples["total_area_mm2"]),
        "waviness_rms_mm": float(detrend["waviness_rms_mm"]),
        "plane_coef": [float(x) for x in detrend["coef"]],
        "Ra_mm": float(amplitude["Ra_mm"]), "Rq_mm": float(amplitude["Rq_mm"]),
        "Rz_mm": float(amplitude["Rz_mm"]), "Rt_mm": float(amplitude["Rt_mm"]),
        "Rz_cells": int(amplitude["Rz_cells"]),
        "correlation_length_mm": float(correlation["correlation_length_mm"]),
        "correlation_bins": int(correlation["bins"]),
        "correlation_step_mm": float(correlation["step_mm"]),
        "correlation_anisotropy": float(correlation.get("anisotropy", 0.0)),
        "ridge_lines_per_mm_mean": float(ridges["lines_per_mm_mean"]),
        "ridge_lines_per_mm_max": float(ridges["lines_per_mm_max"]),
        "ridge_circles": jsonable(ridges["circles"]),
        "residual_rms_mm": float(np.sqrt(np.mean(residual ** 2))),
        "zones": zones,
        "correlation_profile": jsonable(correlation.get("profile")),
    }


def resolvability(correlation_length_mm: float, rms_mm: float,
                  ladder: tuple[float, ...] = (0.039, 0.078, 0.117, 0.156, 0.195)
                  ) -> dict[str, Any]:
    out: dict[str, Any] = {"ladder_mm_per_px": list(ladder),
                           "correlation_length_mm": float(correlation_length_mm),
                           "residual_rms_mm": float(rms_mm)}
    rows = []
    for mm_per_px in ladder:
        rows.append({
            "mm_per_px": float(mm_per_px),
            "px_per_correlation_length": (float(correlation_length_mm / mm_per_px)
                                          if correlation_length_mm > 0 else 0.0),
            "px_per_residual_rms": (float(rms_mm / mm_per_px) if rms_mm > 0 else 0.0),
            "correlation_resolved_3px": bool(correlation_length_mm / mm_per_px >= 3.0),
        })
    out["rows"] = rows
    out["resolved_rungs_3px"] = [row["mm_per_px"] for row in rows
                                 if row["correlation_resolved_3px"]]
    return out


# ---------------------------------------------------------------------------- cases
def run_case(kind: str, *, mother: Any, basis: Any, profile: dict[str, Any] | None,
             rng: np.random.Generator, event_id: str, budget: float, max_cells: int,
             n_samples: int) -> dict[str, Any]:
    from synlab.fracture import surface_features as sf
    from synlab.fracture.api import audit_fracture, make_closed_cutter
    from synlab.fracture.event import result_basis, run_shared_cut
    from synlab.fracture.morphology import MORPHOLOGY_META_KEY, build_morphology_cutter
    from synlab.fracture.spec import BACKEND_PLANE, BACKEND_ROUGH, FractureSpec

    started = time.time()
    if kind == "plane":
        spec = FractureSpec(backend=BACKEND_PLANE)
        cutter = make_closed_cutter(mother, spec, rng, basis=basis)
        result = run_shared_cut(mother, cutter, event_id=event_id, backend=BACKEND_PLANE)
        params = None
        field = None
        cutter_report: dict[str, Any] = {}
        surface = None
    elif kind == "rough":
        # the frozen pre-existing non-planar backend, for reference only: its coefficients are
        # drawn from the RNG and carry no material input, which is exactly the gap the
        # morphology backend closes.
        spec = FractureSpec(backend=BACKEND_ROUGH, target_rms_mm=0.05)
        cutter = make_closed_cutter(mother, spec, rng, basis=basis)
        result = run_shared_cut(mother, cutter, event_id=event_id, backend=BACKEND_ROUGH)
        params = None
        field = None
        cutter_report = {}
        surface = None
    elif kind.startswith("morphology:"):
        material_id = kind.split(":", 1)[1]
        assert profile is not None
        cutter, field, params, cutter_report = build_morphology_cutter(
            mother, material_profile=profile, rng=rng, basis=basis, event_id=event_id,
            error_budget_mm=float(budget), max_cells=int(max_cells))
        result = run_shared_cut(
            mother, cutter, event_id=event_id, backend="morphology_shared_cut",
            extra_meta={MORPHOLOGY_META_KEY: params.as_dict(),
                        "cutter_cells": int(cutter_report.get("cells", 0)),
                        "cutter_realized_error_mm": float(cutter.realized_error_mm),
                        "material_id": material_id})
        record = params.as_dict()
        for patch in result.interfaces:
            patch.meta[MORPHOLOGY_META_KEY] = record
        for fragment in result.fragments:
            fragment.meta[MORPHOLOGY_META_KEY] = record
        surface = sf.measure_cutter_surface(cutter.mesh, basis, params, window=field.window,
                                            n_samples=int(n_samples))
    else:
        raise ValueError(f"unknown case kind {kind!r}")
    event_seconds = time.time() - started
    qa = audit_fracture(result, mother)
    # the basis the *result* itself now carries (this is the exposure this stage adds)
    exposed = result_basis(result)
    basis_matches = bool(np.allclose(np.asarray(exposed.origin, dtype=np.float64),
                                     np.asarray(basis.origin, dtype=np.float64), atol=1e-12)
                         and np.allclose(np.asarray(exposed.normal, dtype=np.float64),
                                         np.asarray(basis.normal, dtype=np.float64), atol=1e-12))
    # measurement origin: the plane baseline has no morphology record, so the origin is derived
    # with the same frozen rule (morphology.initiate_origin) on the same cross-section.
    if params is None:
        from synlab.fracture.morphology import flat_cross_section, initiate_origin, wall_thickness

        tris_uv, core_area, cross_info = flat_cross_section(basis, mother.mesh)
        wall = wall_thickness(mother, max_probes=320)
        origin_uv = initiate_origin(tris_uv, wall.p05_mm)
        origin_world = basis.to_world(np.array([[origin_uv[0], origin_uv[1], 0.0]]))[0]
        params = MeasurementRuler(origin_uv_mm=(float(origin_uv[0]), float(origin_uv[1])),
                                  mirror_radius_mm=0.8, mist_radius_mm=1.44)
    else:
        cross_info = cutter_report.get("flat_cross_section")
        core_area = float(cutter_report.get("core_area_mm2", 0.0))

    delivered = measure_delivered(result, basis, params, cutter_mesh=cutter.mesh,
                                  n_samples=int(n_samples))
    conjugate = sf.conjugate_profile_consistency(result.fragments, result.interfaces, basis)
    row = {
        "kind": kind, "status": "OK", "seconds": round(event_seconds, 3),
        "event_id": event_id,
        "basis": {"basis_id": basis.basis_id,
                  "origin_mm": np.round(np.asarray(basis.origin, dtype=np.float64), 6).tolist(),
                  "normal": np.round(np.asarray(basis.normal, dtype=np.float64), 8).tolist(),
                  "e_u": np.round(np.asarray(basis.e_u, dtype=np.float64), 8).tolist(),
                  "e_v": np.round(np.asarray(basis.e_v, dtype=np.float64), 8).tolist(),
                  "exposed_on_result": True,
                  "exposed_matches_cutter_basis": basis_matches,
                  "record_key": "basis_record"},
        "cut_origin_uv_mm": [float(params.origin_uv_mm[0]), float(params.origin_uv_mm[1])],
        "cutter": {
            "triangles": int(cutter.triangles),
            "cells": int(cutter_report.get("cells", 0) or cutter.meta.get("cells", 0) or 0),
            "realized_error_mm": float(cutter.realized_error_mm),
            "requested_error_mm": float(cutter.requested_error_mm),
            "watertight": bool(cutter.mesh.is_watertight),
            "winding_consistent": bool(cutter.mesh.is_winding_consistent),
            "volume_mm3": float(abs(cutter.mesh.volume)),
            "precision_amplitude_scale": float(
                cutter_report.get("precision_amplitude_scale", 1.0)),
        },
        "morphology_params": (params.as_dict() if hasattr(params, "as_dict") else None),
        "cutter_surface": jsonable(surface) if surface is not None else None,
        "delivered": delivered,
        "resolvability": resolvability(float(delivered.get("correlation_length_mm", 0.0)),
                                       float(delivered.get("residual_rms_mm", 0.0))),
        "conjugate": jsonable(conjugate),
        "qa": jsonable(qa),
        "fragments": [{"fragment_id": f.fragment_id, "faces": int(len(f.mesh.faces)),
                       "volume_mm3": float(f.volume_mm3),
                       "watertight": bool(f.mesh.is_watertight),
                       "interface_faces": int(np.sum(np.asarray(f.face_origin_kind) == 1))}
                      for f in result.fragments],
        "interfaces": len(result.interfaces),
        "interface_area_mm2": float(sum(float(p.area_mm2) for p in result.interfaces)),
    }
    bundle = {"kind": kind, "label": None, "result": result, "cutter_mesh": cutter.mesh,
              "basis": basis, "field": field, "params": params,
              "origin_uv_mm": (float(params.origin_uv_mm[0]), float(params.origin_uv_mm[1])),
              "material_id": (kind.split(":", 1)[1] if kind.startswith("morphology:") else "")}
    return row, bundle


# ---------------------------------------------------------------------------- main
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vessel", default="V18")
    parser.add_argument("--material", default="M03")
    parser.add_argument("--compare-material", default="M07")
    parser.add_argument("--samples", type=int, default=400_000)
    parser.add_argument("--budget", type=float, default=0.01)
    parser.add_argument("--max-cells", type=int, default=400_000)
    parser.add_argument("--out", default="")
    parser.add_argument("--bundle", default="")
    parser.add_argument("--cases", default="plane,morphology,m09")
    args = parser.parse_args()

    from synlab.fracture.api import _default_basis
    from synlab.fracture.morphology import wall_thickness
    from synlab.fracture.spec import FractureSpec
    from synlab.seeds import make_rng

    out_path = Path(args.out) if args.out else (
        REPO_ROOT / "data" / "a12_reports" / "physical_layer"
        / f"matrix_{args.vessel}_{args.material}_vs_{args.compare_material}.json")
    bundle_path = Path(args.bundle) if args.bundle else (
        REPO_ROOT / "data" / "a12_reports" / "physical_layer"
        / f"bundle_{args.vessel}.pkl")

    report: dict[str, Any] = {
        "stage": "physical_layer_three_case_matrix",
        "vessel_id": args.vessel,
        "material_ids": [args.material, args.compare_material],
        "master_seed": MASTER_SEED, "lineage_id": LINEAGE_ID,
        "error_budget_mm": float(args.budget), "max_cells": int(args.max_cells),
        "samples_per_measurement": int(args.samples),
    }
    started = time.time()
    mother, mother_info = build_mother(args.vessel, args.material)
    bounds = np.asarray(mother.mesh.bounds, dtype=np.float64)
    report["mother"] = {
        "mother_id": mother.mother_id, "material_id": mother.material_id,
        "faces": int(len(mother.mesh.faces)), "vertices": int(len(mother.mesh.vertices)),
        "watertight": bool(mother.mesh.is_watertight),
        "volume_mm3": float(abs(mother.mesh.volume)), "area_mm2": float(mother.mesh.area),
        "extent_mm": (bounds[1] - bounds[0]).tolist(), **mother_info,
    }
    print(f"[mother] {mother.mother_id} faces={report['mother']['faces']} "
          f"vol={report['mother']['volume_mm3']:.1f} "
          f"extent={np.round(bounds[1] - bounds[0], 2).tolist()} "
          f"watertight={report['mother']['watertight']}", flush=True)

    profiles: dict[str, dict[str, Any]] = {}
    report["materials"] = {}
    for material_id in (args.material, args.compare_material):
        profile, info = build_material(material_id)
        profiles[material_id] = profile
        from synlab.fracture.morphology import material_fracture_inputs

        info["fracture_inputs"] = material_fracture_inputs(
            profile, material_id=material_id).as_dict()
        report["materials"][material_id] = info
        print(f"[material] {material_id} grain={info['fracture_inputs']['grain_scale_mm']}mm "
              f"pore={info['fracture_inputs']['pore_scale_mm']}mm "
              f"porosity={info['fracture_inputs']['porosity']:.4f} "
              f"glaze={info['fracture_inputs']['glaze_thickness_mm']}mm "
              f"fiber={info['fracture_inputs']['fiber_amount']}", flush=True)

    # one basis for all three cases
    rng = make_rng(MASTER_SEED, LINEAGE_ID, "fracture", args.vessel, "shared_basis")
    basis = _default_basis(mother, rng, FractureSpec())
    wall = wall_thickness(mother, max_probes=320)
    report["wall_thickness"] = wall.as_dict()
    report["basis"] = {"basis_id": basis.basis_id,
                       "origin_mm": np.round(np.asarray(basis.origin, dtype=np.float64),
                                             6).tolist(),
                       "normal": np.round(np.asarray(basis.normal, dtype=np.float64),
                                          8).tolist(),
                       "u_range": list(basis.u_range), "v_range": list(basis.v_range),
                       "h_scale_mm": float(basis.h_scale_mm)}
    print(f"[wall] min={wall.min_mm:.3f} p05={wall.p05_mm:.3f} median={wall.median_mm:.3f} "
          f"max={wall.max_mm:.3f} probes={wall.probes}", flush=True)
    print(f"[basis] {basis.basis_id} normal={np.round(basis.normal, 5).tolist()} "
          f"origin={np.round(basis.origin, 3).tolist()}", flush=True)

    cases: list[tuple[str, str]] = []
    for token in str(args.cases).split(","):
        token = token.strip()
        if not token:
            continue
        if token == "plane":
            cases.append(("plane", "plane"))
        elif token in ("morphology", "m03"):
            cases.append((f"morphology:{args.material}", f"morphology_{args.material}"))
        elif token in ("compare", "m07"):
            cases.append((f"morphology:{args.compare_material}",
                          f"morphology_{args.compare_material}"))
        elif token == "rough":
            cases.append(("rough", "rough"))
        else:
            raise SystemExit(f"unknown case token {token!r}")

    report["cases"] = {}
    bundles: dict[str, Any] = {"vessel_id": args.vessel, "cases": {}}
    for kind, label in cases:
        event_id = f"{LINEAGE_ID}_{args.vessel}_{label}"
        case_rng = make_rng(MASTER_SEED, LINEAGE_ID, "fracture", args.vessel, label)
        try:
            row, bundle = run_case(kind, mother=mother, basis=basis,
                                   profile=profiles.get(kind.split(":")[-1]),
                                   rng=case_rng, event_id=event_id, budget=float(args.budget),
                                   max_cells=int(args.max_cells), n_samples=int(args.samples))
            bundle["label"] = label
            bundles["cases"][label] = bundle
            delivered = row["delivered"]
            print(f"[{label}] {row['seconds']:.2f}s cut_tris={row['cutter']['triangles']} "
                  f"cells={row['cutter']['cells']} err={row['cutter']['realized_error_mm']:.3e} "
                  f"Ra={delivered.get('Ra_mm'):.6f} Rz={delivered.get('Rz_mm'):.6f} "
                  f"lc={delivered.get('correlation_length_mm'):.5f} "
                  f"ridge={delivered.get('ridge_lines_per_mm_mean'):.4f}/mm "
                  f"gapP95={row['qa'].get('gap_p95_mm_max'):.3e} "
                  f"nP95={row['qa'].get('normal_angle_p95_deg_max'):.4f} "
                  f"conj={row['conjugate'].get('conjugate_gap_p95_mm'):.3e} "
                  f"passed={row['qa'].get('passed')}", flush=True)
            if row["qa"].get("failures"):
                print(f"[{label}] QA FAILURES {row['qa']['failures']}", flush=True)
        except BaseException as exc:  # noqa: BLE001 - a failure is a measurement
            row = {"kind": kind, "status": "FAILED", "error": error_record(exc)}
            print(f"[{label}] FAILED {row['error']['code']} @ {row['error']['stage']}\n"
                  f"    {row['error']['message']}", flush=True)
        report["cases"][label] = row

    report["duration_s"] = round(time.time() - started, 3)
    text = json.dumps(jsonable(report), ensure_ascii=False, indent=1)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    print(f"[written] {out_path} ({len(text) / 1024:.0f} KiB)", flush=True)
    if bundles["cases"]:
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        with bundle_path.open("wb") as handle:
            pickle.dump(bundles, handle, protocol=4)
        print(f"[written] {bundle_path} "
              f"({bundle_path.stat().st_size / 1024 / 1024:.1f} MiB) "
              f"cases={sorted(bundles['cases'])}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
