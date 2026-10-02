#!/usr/bin/env python
"""Measure fracture-surface realism on a real mother: plane vs rough vs morphology.

Every number is measured on real artifacts produced by the frozen shared-cutter path:

* the mother comes from ``synlab.mothers.api.create_mother`` with the demo vessel's own frozen
  parameters and the requested real material profile;
* the three cutters are built by the package itself (``plane_shared_cut`` through
  ``api.make_closed_cutter``, ``rough_shared_cut`` through ``api.make_closed_cutter``, and
  ``morphology_shared_cut`` through ``morphology.build_morphology_cutter``);
* each event runs through ``synlab.fracture.event.run_shared_cut`` (one shared discrete cutter);
* the audit is ``synlab.fracture.api.audit_fracture`` -- the frozen A06 gates, unrelaxed;
* roughness / correlation length / ridge density are measured by
  ``synlab.fracture.surface_features`` on the *delivered* interface faces and on the realized
  cutter top surface;
* conjugacy comes from the interface patches the event itself built;
* non-planarity is measured as the normal-angle distribution of the delivered interface faces
  against the cut-basis normal plus the discrete dihedral turning of those faces.

Each variant writes its block to the output JSON as soon as it finishes, so a crash late in the
run still leaves the earlier measurements on disk.

Usage:

```powershell
& .venv\\Scripts\\python.exe tests\\a12\\fracture\\_measure_fracture_realism.py `
    --vessel V18 --material M01 --out data\\a12_reports\\fracture_realism_V18_M01.json
```
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

MASTER_SEED = 20261001
LINEAGE_ID = "a12_fracture_realism"


# --------------------------------------------------------------------------------------- json
def _jsonable(value: Any, *, depth: int = 0, max_array: int = 32) -> Any:
    if depth > 7:
        return f"<{type(value).__name__}>"
    if isinstance(value, dict):
        return {str(k): _jsonable(v, depth=depth + 1, max_array=max_array)
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        if len(value) > 512:
            return {"length": len(value)}
        return [_jsonable(v, depth=depth + 1, max_array=max_array) for v in value]
    if isinstance(value, np.ndarray):
        flat = value.reshape(-1)
        if flat.size == 0:
            return {"shape": list(value.shape), "empty": True}
        if flat.size > max_array:
            return {"shape": list(value.shape), "size": int(flat.size),
                    "min": float(np.min(flat)), "max": float(np.max(flat))}
        return [_jsonable(v, depth=depth + 1, max_array=max_array) for v in flat.tolist()]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "as_dict"):
        return _jsonable(value.as_dict(), depth=depth + 1, max_array=max_array)
    return str(value)


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


# ------------------------------------------------------------------------------------ body
def build_mother(vessel_id: str, material_id: str, fixture: str = "") -> tuple[Any, dict[str, Any]]:
    """A real demo mother, or (``--fixture box``) the analytic box fixture used by the tests.

    The fixture path exists because a real mother's cross-section demands more quadtree cells than
    the shared-cutter builder currently survives (see docs/a12/fracture_realism.md); measuring the
    *same* pipeline on a small analytic body separates "the morphology model is wrong" from "the
    mesh builder cannot realize it at that scale".
    """
    import json as _json

    from synlab.seeds import make_rng

    rng = make_rng(MASTER_SEED, LINEAGE_ID, "mothers", vessel_id, material_id)
    if fixture == "box":
        import fixtures as fx

        mother = fx.box_mother((12.0, 12.0, 12.0), mother_id=f"{LINEAGE_ID}_box12")
        return mother, {"demo_mother_id": None, "demo_material_id": None,
                        "source": "tests/a12/fracture/fixtures.py::box_mother((12,12,12))",
                        "note": "analytic fixture body, not a real vessel"}

    from synlab.mothers.api import create_mother, load_mother
    from synlab.storage.store import AssetStore

    demo_root = REPO_ROOT / "data" / "a12_demo"
    manifest = _json.loads((demo_root / "demo_manifest.json").read_text(encoding="utf-8"))
    entry = next(e for e in manifest["entries"] if e["entry_id"] == f"mother:{vessel_id}")
    demo = load_mother(AssetStore(demo_root / "store"), str(entry["asset_id"]))
    mother = create_mother(vessel_id, material_id, dict(demo.params), rng,
                           mother_id=f"{LINEAGE_ID}_{vessel_id}_{material_id}")
    return mother, {"demo_mother_id": demo.mother_id, "demo_material_id": demo.material_id,
                    "demo_params": _jsonable(dict(demo.params)),
                    "source": "synlab.mothers.api.create_mother(demo params, real material)"}


def build_material(material_id: str) -> dict[str, Any]:
    from synlab.materials.api import build_material_profile, default_material_params
    from synlab.seeds import make_rng

    rng = make_rng(MASTER_SEED, LINEAGE_ID, "materials", material_id)
    return build_material_profile(material_id, default_material_params(material_id), rng)


@dataclass
class SurfaceParams:
    """The (origin, mirror, mist) triple the zone statistics are evaluated against."""

    origin_uv_mm: tuple[float, float]
    mirror_radius_mm: float
    mist_radius_mm: float


# ------------------------------------------------------------------- geometry measurements
def _normal_angles(mesh: Any, basis: Any, face_ids: np.ndarray) -> np.ndarray:
    """Angle (deg) between each given face's normal and the cut-basis normal."""
    faces = np.asarray(mesh.faces, dtype=np.int64)
    verts = np.asarray(mesh.vertices, dtype=np.float64)
    ids = np.asarray(face_ids, dtype=np.int64)
    if ids.size == 0:
        return np.zeros(0, dtype=np.float64)
    tri = verts[faces[ids]]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    norm = np.linalg.norm(n, axis=1)
    keep = norm > 0.0
    n = n[keep] / norm[keep][:, None]
    axis_n = np.asarray(basis.normal, dtype=np.float64)
    axis_n = axis_n / max(float(np.linalg.norm(axis_n)), 1e-12)
    cos = np.clip(np.abs(n @ axis_n), 0.0, 1.0)
    return np.degrees(np.arccos(cos))


def _dihedral_turning(mesh: Any, basis: Any, face_ids: np.ndarray) -> dict[str, Any]:
    """Discrete curvature proxy: dihedral angle across shared edges of the given faces.

    Two triangles that share an edge and lie on one smooth surface turn by the dihedral angle; a
    plane gives exactly 0.  Reported both as an angle and as a turn per unit length, which is the
    discrete analogue of the curvature the model requested (``requested_curvature_per_mm``).
    """
    faces = np.asarray(mesh.faces, dtype=np.int64)
    verts = np.asarray(mesh.vertices, dtype=np.float64)
    ids = np.asarray(face_ids, dtype=np.int64)
    if ids.size < 2:
        return {"edges": 0, "dihedral_p50_deg": None, "dihedral_p95_deg": None,
                "dihedral_max_deg": None, "turning_p95_deg_per_mm": None}
    tri = verts[faces[ids]]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    norm = np.linalg.norm(n, axis=1)
    ok = norm > 1e-12
    tri, n, ids = tri[ok], n[ok] / norm[ok][:, None], ids[ok]
    if tri.shape[0] < 2:
        return {"edges": 0, "dihedral_p50_deg": None, "dihedral_p95_deg": None,
                "dihedral_max_deg": None, "turning_p95_deg_per_mm": None}
    edge_map: dict[tuple[tuple[float, ...], tuple[float, ...]], list[int]] = {}
    # edge key uses rounded vertex positions, so cross-face identity does not depend on indexing
    quant = np.round(tri, 6)
    for k in range(quant.shape[0]):
        for a, b in ((0, 1), (1, 2), (2, 0)):
            p, q = quant[k, a], quant[k, b]
            key = (tuple(p), tuple(q)) if tuple(p) <= tuple(q) else (tuple(q), tuple(p))
            edge_map.setdefault(key, []).append(k)
    angles: list[float] = []
    lengths: list[float] = []
    for key, members in edge_map.items():
        if len(members) != 2:
            continue
        i, j = members
        cos = float(np.clip(np.dot(n[i], n[j]), -1.0, 1.0))
        angles.append(float(np.degrees(np.arccos(cos))))
        lengths.append(float(np.linalg.norm(np.asarray(key[0]) - np.asarray(key[1]))))
    if not angles:
        return {"edges": 0, "dihedral_p50_deg": None, "dihedral_p95_deg": None,
                "dihedral_max_deg": None, "turning_p95_deg_per_mm": None}
    ang = np.asarray(angles, dtype=np.float64)
    seg = np.asarray(lengths, dtype=np.float64)
    per_mm = ang / np.maximum(seg, 1e-9)
    return {
        "edges": int(ang.size),
        "dihedral_p50_deg": float(np.percentile(ang, 50)),
        "dihedral_p95_deg": float(np.percentile(ang, 95)),
        "dihedral_max_deg": float(ang.max()),
        "turning_p95_deg_per_mm": float(np.percentile(per_mm, 95)),
        "edge_length_p50_mm": float(np.percentile(seg, 50)),
    }


def _mesh_health(mesh: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"watertight": bool(mesh.is_watertight),
                           "faces": int(len(mesh.faces)),
                           "volume_mm3": float(abs(mesh.volume))}
    try:
        from synlab.mothers.audit import self_intersection_report

        report = self_intersection_report(mesh)
        out["self_intersecting"] = not bool(report.get("ok"))
        out["self_intersection_method"] = "synlab.mothers.audit.self_intersection_report"
        out["self_intersection_pairs"] = int(report.get("intersecting_pairs", 0))
    except BaseException as exc:  # noqa: BLE001 - a missing checker is reported, never hidden
        out["self_intersecting"] = None
        out["self_intersection_method"] = f"unavailable: {type(exc).__name__}: {exc}"[:200]
    return out


def _interface_ids(fragment: Any, cutter_mesh: Any) -> np.ndarray:
    from synlab.fracture.event import _interface_faces

    ids, _sources, _centres = _interface_faces(fragment, cutter_mesh)
    return np.asarray(ids, dtype=np.int64)


class _FootprintMask:
    """Boolean ``(u, v)`` raster of the fracture footprint, exposing ``is_exactly_one``.

    ``surface_features.measure_cutter_surface`` restricts its samples through the frozen material
    band envelope.  That envelope is only available as a live object for the morphology field, so
    for the plane/rough comparison the restriction is rebuilt from the footprint the event itself
    delivered (the interface faces of the produced fragments).  Using one criterion for all three
    variants is what makes their cutter-surface numbers comparable.
    """

    def __init__(self, u: np.ndarray, v: np.ndarray, *, step_mm: float = 0.25, pad_cells: int = 1):
        self.step_mm = float(step_mm)
        self.u0 = float(np.min(u)) - pad_cells * self.step_mm
        self.v0 = float(np.min(v)) - pad_cells * self.step_mm
        self.nu = int(np.ceil((float(np.max(u)) - self.u0) / self.step_mm)) + 1 + pad_cells
        self.nv = int(np.ceil((float(np.max(v)) - self.v0) / self.step_mm)) + 1 + pad_cells
        mask = np.zeros((self.nu, self.nv), dtype=bool)
        gi = np.clip(((u - self.u0) / self.step_mm).astype(np.int64), 0, self.nu - 1)
        gj = np.clip(((v - self.v0) / self.step_mm).astype(np.int64), 0, self.nv - 1)
        mask[gi, gj] = True
        for _ in range(max(int(pad_cells), 0)):
            grown = mask.copy()
            grown[1:, :] |= mask[:-1, :]
            grown[:-1, :] |= mask[1:, :]
            grown[:, 1:] |= mask[:, :-1]
            grown[:, :-1] |= mask[:, 1:]
            mask = grown
        self.mask = mask
        self.core_area_mm2 = float(mask.sum()) * self.step_mm ** 2

    def is_exactly_one(self, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        uu = np.asarray(u, dtype=np.float64)
        vv = np.asarray(v, dtype=np.float64)
        gi = np.floor((uu - self.u0) / self.step_mm).astype(np.int64)
        gj = np.floor((vv - self.v0) / self.step_mm).astype(np.int64)
        inside = (gi >= 0) & (gi < self.nu) & (gj >= 0) & (gj < self.nv)
        out = np.zeros(np.broadcast(uu, vv).shape, dtype=bool)
        out[inside] = self.mask[gi[inside], gj[inside]]
        return out

    def as_dict(self) -> dict[str, Any]:
        return {"step_mm": self.step_mm, "shape": [self.nu, self.nv],
                "core_area_mm2": self.core_area_mm2,
                "source": "delivered interface-face footprint (same criterion for all variants)"}


def measure_variant(result: Any, cutter_mesh: Any, basis: Any, params: Any, *, n_samples: int,
                    label: str) -> dict[str, Any]:
    """Everything that can be measured on one finished event, from the artifacts themselves."""
    from synlab.fracture import surface_features as sf

    frags = list(result.fragments)
    delivered = sf.measure_interface_surface(frags, basis, params, cutter_mesh=cutter_mesh,
                                             n_samples=int(n_samples))
    conjugate = sf.conjugate_profile_consistency(frags, result.interfaces, basis)

    all_ids: list[np.ndarray] = []
    health: list[dict[str, Any]] = []
    for fragment in frags:
        ids = _interface_ids(fragment, cutter_mesh)
        all_ids.append(ids)
        entry = {"fragment_id": fragment.fragment_id, "interface_faces": int(ids.size),
                 "volume_mm3": float(fragment.volume_mm3)}
        entry.update(_mesh_health(fragment.mesh))
        entry["is_tiny"] = bool(fragment.is_tiny)
        health.append(entry)

    ids_cat = np.concatenate(all_ids) if all_ids else np.zeros(0, dtype=np.int64)
    angles = np.concatenate([_normal_angles(f.mesh, basis, i)
                             for f, i in zip(frags, all_ids)]) if all_ids \
        else np.zeros(0, dtype=np.float64)
    turning = [_dihedral_turning(f.mesh, basis, i) for f, i in zip(frags, all_ids)]
    turning_ok = [t for t in turning if t["dihedral_p95_deg"] is not None]

    # cutter top surface restricted to the delivered footprint (one criterion for all variants)
    cutter_stats: dict[str, Any] = {}
    if ids_cat.size:
        u_all: list[np.ndarray] = []
        v_all: list[np.ndarray] = []
        for fragment, ids in zip(frags, all_ids):
            if ids.size == 0:
                continue
            # triangle_vertices_local returns (3 * n_faces, 3) in the (u, v, w) basis
            tri = sf.triangle_vertices_local(fragment.mesh, basis, ids)
            u_all.append(tri[:, 0])
            v_all.append(tri[:, 1])
        if u_all:
            mask = _FootprintMask(np.concatenate(u_all), np.concatenate(v_all))
            cutter_stats = sf.measure_cutter_surface(cutter_mesh, basis, params, window=mask,
                                                     n_samples=int(n_samples))
            cutter_stats["footprint"] = mask.as_dict()

    return {
        "label": label,
        "delivered": _jsonable(delivered),
        "cutter_surface": _jsonable(cutter_stats),
        "conjugate": _jsonable(conjugate),
        "normals": {
            "interface_faces": int(ids_cat.size),
            "angle_mean_deg": float(np.mean(angles)) if angles.size else None,
            "angle_p50_deg": float(np.percentile(angles, 50)) if angles.size else None,
            "angle_p95_deg": float(np.percentile(angles, 95)) if angles.size else None,
            "angle_p99_deg": float(np.percentile(angles, 99)) if angles.size else None,
            "angle_max_deg": float(angles.max()) if angles.size else None,
            "frac_gt_0p5deg": float(np.mean(angles > 0.5)) if angles.size else None,
            "frac_gt_2deg": float(np.mean(angles > 2.0)) if angles.size else None,
        },
        "curvature": {
            "edges": int(sum(t["edges"] for t in turning)),
            "dihedral_p50_deg": (float(np.mean([t["dihedral_p50_deg"] for t in turning_ok]))
                                 if turning_ok else None),
            "dihedral_p95_deg": (float(np.mean([t["dihedral_p95_deg"] for t in turning_ok]))
                                 if turning_ok else None),
            "dihedral_max_deg": (float(max(t["dihedral_max_deg"] for t in turning_ok))
                                 if turning_ok else None),
            "turning_p95_deg_per_mm": (float(np.mean([t["turning_p95_deg_per_mm"]
                                                      for t in turning_ok]))
                                       if turning_ok else None),
            "per_fragment": _jsonable(turning),
        },
        "mesh_health": _jsonable(health),
    }


# ------------------------------------------------------------------------------------ main
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vessel", default="V18")
    parser.add_argument("--material", default="M01")
    parser.add_argument("--fixture", default="", help="'box' to measure the analytic box fixture")
    parser.add_argument("--samples", type=int, default=600_000)
    parser.add_argument("--out", default="")
    parser.add_argument("--budget", type=float, default=0.01)
    parser.add_argument("--max-cells", type=int, default=400_000)
    parser.add_argument("--rms", type=float, default=0.05)
    parser.add_argument("--skip-plane", action="store_true")
    parser.add_argument("--skip-rough", action="store_true")
    parser.add_argument("--skip-morphology", action="store_true")
    args = parser.parse_args()

    from synlab.fracture import surface_features as sf
    from synlab.fracture.api import _default_basis, audit_fracture, make_closed_cutter
    from synlab.fracture.event import run_shared_cut
    from synlab.fracture.morphology import (
        BACKEND_MORPHOLOGY, MORPHOLOGY_META_KEY, build_morphology_cutter, prepare_morphology,
    )
    from synlab.fracture.spec import BACKEND_PLANE, BACKEND_ROUGH, FractureSpec
    from synlab.seeds import make_rng

    out_path = Path(args.out) if args.out else (
        REPO_ROOT / "data" / "a12_reports"
        / f"fracture_realism_{args.vessel}_{args.material}.json")

    report: dict[str, Any] = {
        "vessel_id": args.vessel, "material_id": args.material, "master_seed": MASTER_SEED,
        "lineage_id": LINEAGE_ID, "error_budget_mm": float(args.budget),
        "max_cells": int(args.max_cells), "rough_target_rms_mm": float(args.rms),
        "probe": "tests/a12/fracture/_measure_fracture_realism.py",
        "variants": {},
    }
    started = time.time()

    mother, mother_info = build_mother(args.vessel, args.material, args.fixture)
    profile = build_material(args.material)
    bounds = np.asarray(mother.mesh.bounds, dtype=np.float64)
    report["mother"] = {
        "mother_id": mother.mother_id, "material_id": mother.material_id,
        "faces": int(len(mother.mesh.faces)), "vertices": int(len(mother.mesh.vertices)),
        "watertight": bool(mother.mesh.is_watertight),
        "volume_mm3": float(abs(mother.mesh.volume)), "area_mm2": float(mother.mesh.area),
        "extent_mm": (bounds[1] - bounds[0]).tolist(),
        "self_intersecting": _mesh_health(mother.mesh).get("self_intersecting"),
        **mother_info,
    }
    report["material_profile"] = {"stats": _jsonable(profile.get("stats")),
                                 "appearance": _jsonable(profile.get("appearance"))}
    print(f"[mother] {args.vessel}/{args.material} faces={report['mother']['faces']} "
          f"vol={report['mother']['volume_mm3']:.1f} "
          f"extent={np.round(bounds[1] - bounds[0], 2).tolist()}", flush=True)

    rng = make_rng(MASTER_SEED, LINEAGE_ID, "fracture", args.vessel, args.material)
    basis = _default_basis(mother, rng, FractureSpec())
    report["basis"] = {"basis_id": basis.basis_id,
                       "origin": np.round(basis.origin, 6).tolist(),
                       "normal": np.round(basis.normal, 8).tolist()}

    # one body measurement, shared by all three variants: same basis, same wall, same origin
    prepared = prepare_morphology(
        mother, material_profile=profile, rng=rng, basis=basis,
        event_id=f"{LINEAGE_ID}_{args.vessel}_{args.material}",
        error_budget_mm=float(args.budget), max_cells=int(args.max_cells))
    base_params = prepared["base_params"]
    params = sf_params = base_params  # FractureMorphologyParams already carries origin/mirror/mist
    report["prepared"] = {
        "wall": base_params.wall, "material": base_params.material,
        "origin_uv_mm": list(base_params.origin_uv_mm),
        "origin_world_mm": list(base_params.origin_world_mm),
        "core_area_mm2": float(prepared["core_area_mm2"]),
        "cross_section": _jsonable(prepared["cross_info"]),
        "predicted_amplitude_scale": float(base_params.predicted_amplitude_scale),
        "requested_curvature_per_mm": float(base_params.requested_curvature_per_mm),
        "curvature_budget_per_mm": float(base_params.curvature_budget_per_mm),
        "requested_rms_mm": float(base_params.requested_rms_mm),
        "mirror_radius_mm": float(base_params.mirror_radius_mm),
        "mist_radius_mm": float(base_params.mist_radius_mm),
        "correlation_length_mm": float(base_params.correlation_length_mm),
        "hackle_count": int(base_params.hackle_count),
        "hackle_spacing_at_mirror_mm": float(base_params.hackle_spacing_at_mirror_mm),
        "rib_spacing_at_mirror_mm": float(base_params.rib_spacing_at_mirror_mm),
        "pit_count": int(base_params.pit_count),
        "pit_radius_mm": float(base_params.pit_radius_mm),
        "pit_depth_mm": float(base_params.pit_depth_mm),
        "pit_area_fraction": float(base_params.pit_area_fraction),
        "dome_radius_mm": float(base_params.dome_radius_mm),
        "dome_amplitude_mm": float(base_params.dome_amplitude_mm),
        "bands": _jsonable(base_params.bands),
        "notes": list(base_params.notes),
    }
    del sf_params
    print(f"[prepare] wall p05={base_params.wall['p05_mm']:.3f} "
          f"sigma_f={base_params.sigma_f_mpa:.1f}MPa r_mirror={base_params.mirror_radius_mm:.3f} "
          f"sigma_r0={base_params.requested_rms_mm:.4f}mm "
          f"lc={base_params.correlation_length_mm:.4f}mm", flush=True)
    _write(out_path, report)

    def run_one(label: str, backend: str, *, target_rms: float) -> None:
        block: dict[str, Any] = {}
        t0 = time.time()
        try:
            spec = FractureSpec(backend=backend, error_budget_mm=float(args.budget),
                                max_cutter_cells=int(args.max_cells),
                                target_rms_mm=float(target_rms))
            cutter = make_closed_cutter(mother, spec, rng, basis=basis)
            cut_s = time.time() - t0
            t1 = time.time()
            result = run_shared_cut(mother, cutter, event_id=f"{LINEAGE_ID}_{label}",
                                    backend=backend)
            ev_s = time.time() - t1
            qa = audit_fracture(result, mother)
            measured = measure_variant(result, cutter.mesh, basis, params,
                                       n_samples=int(args.samples), label=label)
            cutter_health = _mesh_health(cutter.mesh)
            block = {
                "status": "OK", "backend": backend,
                "cutter_seconds": round(cut_s, 3), "event_seconds": round(ev_s, 3),
                "cutter": {
                    "triangles": int(cutter.triangles),
                    "cells": int(cutter.meta.get("cells", 0)),
                    "requested_error_mm": float(cutter.requested_error_mm),
                    "realized_error_mm": float(cutter.realized_error_mm),
                    "precision_ladder": _jsonable(cutter.meta.get("precision_ladder")),
                    "precision_ladder_attempts": cutter.meta.get("precision_ladder_attempts"),
                    "leaf_level": cutter.meta.get("leaf_level"),
                    "cell_size_min_mm": cutter.meta.get("cell_size_min_mm"),
                    "height_field_summary": {
                        k: cutter.meta.get("height_field", {}).get(k) for k in
                        ("target_rms_mm", "realized_rms_mm", "wavelength_min_mm", "max_slope")
                    },
                    **cutter_health,
                },
                "audit": _jsonable(qa),
                **measured,
                "interfaces": int(len(result.interfaces)),
                "interface_area_mm2": float(sum(float(p.area_mm2) for p in result.interfaces)),
            }
            if backend == BACKEND_MORPHOLOGY:
                block["morphology_meta_present"] = {
                    "patches": all(MORPHOLOGY_META_KEY in p.meta for p in result.interfaces),
                    "fragments": all(MORPHOLOGY_META_KEY in f.meta for f in result.fragments),
                }
                block["result_meta"] = _jsonable({
                    k: v for k, v in dict(result.meta).items() if k != MORPHOLOGY_META_KEY})
            print(f"[{label}] {cut_s:.1f}s+{ev_s:.1f}s tri={block['cutter']['triangles']} "
                  f"cells={block['cutter']['cells']} err={block['cutter']['realized_error_mm']:.3e} "
                  f"Ra={measured['delivered'].get('Ra_mm')} "
                  f"Rz={measured['delivered'].get('Rz_mm')} "
                  f"lc={measured['delivered'].get('correlation_length_mm')} "
                  f"gap_p95={qa.get('gap_p95_mm_max')} nrm_p95={qa.get('normal_angle_p95_deg_max')} "
                  f"passed={qa.get('passed')}", flush=True)
            if qa.get("failures"):
                print(f"[{label}] QA FAILURES {qa['failures']}", flush=True)
        except BaseException as exc:  # noqa: BLE001 - a failure is a measurement
            code = getattr(getattr(exc, "code", None), "value", type(exc).__name__)
            block = {"status": "FAILED", "backend": backend,
                     "seconds": round(time.time() - t0, 3),
                     "error": _jsonable({
                         "code": str(code), "stage": getattr(exc, "stage", ""),
                         "message": str(exc)[:600],
                         "measurements": getattr(exc, "measurements", None),
                         "traceback_tail": traceback.format_exc()[-1500:]})}
            print(f"[{label}] FAILED {code} @ {getattr(exc, 'stage', '')}\n"
                  f"    {str(exc)[:300]}", flush=True)
        report["variants"][label] = block
        report["duration_s"] = round(time.time() - started, 3)
        _write(out_path, report)  # partial evidence survives a later crash

    if not args.skip_plane:
        run_one("plane", BACKEND_PLANE, target_rms=0.0)
    if not args.skip_rough:
        run_one("rough", BACKEND_ROUGH, target_rms=float(args.rms))
    if not args.skip_morphology:
        # the morphology variant is built by its own entry point (the API gate is exercised by
        # tests/a12/fracture/test_fracture_realism.py, not by this measurement probe)
        block: dict[str, Any] = {}
        t0 = time.time()
        try:
            cutter, field, mparams, cutter_report = build_morphology_cutter(
                mother, rng=rng, prepared=prepared, basis=basis,
                event_id=f"{LINEAGE_ID}_{args.vessel}_{args.material}_morphology",
                error_budget_mm=float(args.budget), max_cells=int(args.max_cells))
            cut_s = time.time() - t0
            t1 = time.time()
            result = run_shared_cut(
                mother, cutter, event_id=f"{LINEAGE_ID}_morphology", backend=BACKEND_MORPHOLOGY,
                extra_meta={MORPHOLOGY_META_KEY: mparams.as_dict()})
            ev_s = time.time() - t1
            qa = audit_fracture(result, mother)
            measured = measure_variant(result, cutter.mesh, basis, mparams,
                                       n_samples=int(args.samples), label="morphology")
            block = {
                "status": "OK", "backend": BACKEND_MORPHOLOGY,
                "cutter_seconds": round(cut_s, 3), "event_seconds": round(ev_s, 3),
                "cutter": {
                    "triangles": int(cutter.triangles),
                    "cells": int(cutter_report.get("cells", 0)),
                    "leaf_level": int(cutter_report.get("leaf_level", 0)),
                    "requested_error_mm": float(cutter.requested_error_mm),
                    "realized_error_mm": float(cutter.realized_error_mm),
                    "cell_size_min_mm": float(cutter_report.get("cell_size_min_mm", 0.0)),
                    "seed_cell_mm": float(cutter_report.get("seed_cell_mm", 0.0)),
                    "refine_iterations": int(cutter_report.get("refine_iterations", 0)),
                    "precision_amplitude_scale": float(
                        cutter_report.get("precision_amplitude_scale", 1.0)),
                    "cell_demand_estimate": _jsonable(cutter_report.get("cell_demand_estimate")),
                    "height_field_summary": {
                        "wavelength_min_mm": float(field.wavelength_min_mm),
                        "realized_rms_mm": float(field.realized_rms_mm),
                        "relief_amplitude_mm": float(
                            field.meta.get("relief_amplitude_mm", 0.0)),
                        "relief_rms_mm": float(field.meta.get("relief_rms_mm", 0.0)),
                        "relief_peak_to_valley_mm": float(
                            field.meta.get("relief_peak_to_valley_mm", 0.0)),
                        "max_slope": float(field.max_slope),
                        "curvature_bound_per_mm": float(field.curvature_bound()),
                        "width_mm": float(getattr(field.window, "step_mm", 0.0)),
                        "band_core_area_mm2": float(
                            field.window.as_dict().get("core_area_mm2", 0.0)),
                    },
                    "wall": field.morphology.wall if field.morphology else None,
                    **_mesh_health(cutter.mesh),
                },
                "audit": _jsonable(qa),
                **measured,
                "interfaces": int(len(result.interfaces)),
                "interface_area_mm2": float(sum(float(p.area_mm2) for p in result.interfaces)),
                "morphology_meta_present": {
                    "patches": all(MORPHOLOGY_META_KEY in p.meta for p in result.interfaces),
                    "fragments": all(MORPHOLOGY_META_KEY in f.meta for f in result.fragments),
                },
                "result_meta": _jsonable({
                    k: v for k, v in dict(result.meta).items() if k != MORPHOLOGY_META_KEY}),
            }
            print(f"[morphology] {cut_s:.1f}s+{ev_s:.1f}s tri={block['cutter']['triangles']} "
                  f"cells={block['cutter']['cells']} "
                  f"err={block['cutter']['realized_error_mm']:.3e} "
                  f"scale={block['cutter']['precision_amplitude_scale']:.4f} "
                  f"Ra={measured['delivered'].get('Ra_mm')} "
                  f"Rz={measured['delivered'].get('Rz_mm')} "
                  f"lc={measured['delivered'].get('correlation_length_mm')} "
                  f"gap_p95={qa.get('gap_p95_mm_max')} nrm_p95={qa.get('normal_angle_p95_deg_max')} "
                  f"passed={qa.get('passed')}", flush=True)
            if qa.get("failures"):
                print(f"[morphology] QA FAILURES {qa['failures']}", flush=True)
        except BaseException as exc:  # noqa: BLE001 - a failure is a measurement
            code = getattr(getattr(exc, "code", None), "value", type(exc).__name__)
            block = {"status": "FAILED", "backend": BACKEND_MORPHOLOGY,
                     "seconds": round(time.time() - t0, 3),
                     "error": _jsonable({
                         "code": str(code), "stage": getattr(exc, "stage", ""),
                         "message": str(exc)[:600],
                         "measurements": getattr(exc, "measurements", None),
                         "traceback_tail": traceback.format_exc()[-1500:]})}
            print(f"[morphology] FAILED {code} @ {getattr(exc, 'stage', '')}\n"
                  f"    {str(exc)[:300]}", flush=True)
        report["variants"]["morphology"] = block
        report["duration_s"] = round(time.time() - started, 3)
        _write(out_path, report)

    # ------------------------------------------------------------------ contrast summary
    variants = report["variants"]

    def pick(label: str, *path: str) -> Any:
        node: Any = variants.get(label) or {}
        for key in path:
            if not isinstance(node, dict):
                return None
            node = node.get(key)
        return node

    report["contrast"] = {
        "Ra_mm": {k: pick(k, "delivered", "Ra_mm") for k in variants},
        "Rq_mm": {k: pick(k, "delivered", "Rq_mm") for k in variants},
        "Rz_mm": {k: pick(k, "delivered", "Rz_mm") for k in variants},
        "Rt_mm": {k: pick(k, "delivered", "Rt_mm") for k in variants},
        "correlation_length_mm": {k: pick(k, "delivered", "correlation_length_mm")
                                  for k in variants},
        "ridge_lines_per_mm": {k: pick(k, "delivered", "ridge_lines_per_mm") for k in variants},
        "normal_angle_p95_deg": {k: pick(k, "normals", "angle_p95_deg") for k in variants},
        "normal_angle_max_deg": {k: pick(k, "normals", "angle_max_deg") for k in variants},
        "dihedral_p95_deg": {k: pick(k, "curvature", "dihedral_p95_deg") for k in variants},
        "cutter_realized_error_mm": {k: pick(k, "cutter", "realized_error_mm")
                                     for k in variants},
        "audit_gap_p95_mm": {k: pick(k, "audit", "gap_p95_mm_max") for k in variants},
        "audit_normal_p95_deg": {k: pick(k, "audit", "normal_angle_p95_deg_max")
                                 for k in variants},
        "audit_volume_rel_diff": {k: pick(k, "audit", "volume_rel_diff") for k in variants},
        "audit_passed": {k: pick(k, "audit", "passed") for k in variants},
        "conjugate_gap_p95_mm": {k: pick(k, "conjugate", "conjugate_gap_p95_mm")
                                 for k in variants},
        "profile_correlation_min": {k: pick(k, "conjugate", "profile_correlation_min")
                                    for k in variants},
        "self_intersecting": {k: pick(k, "mesh_health") is not None
                              and any(e.get("self_intersecting") for e in
                                      (pick(k, "mesh_health") or []))
                              for k in variants},
    }
    report["duration_s"] = round(time.time() - started, 3)
    _write(out_path, report)
    print(f"[written] {out_path}", flush=True)
    ok = all((variants.get(k) or {}).get("status") == "OK"
             for k in ("plane", "morphology") if k in variants)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
