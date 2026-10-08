"""Reconnaissance for the implicit-sheet backend: measure the real numbers first.

Writes a JSON report of everything the design depends on: mother size, cut frame, material
cross-section footprint, the morphology field's shortest wavelength, and the implied sampling
cost for the sheet triangulation.  Nothing here is a product artefact; it is the evidence used
to choose the meshing strategy.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "tests" / "a12" / "fracture"))

MASTER_SEED = 20261001
LINEAGE_ID = "a12_fracture_implicit"


def build_mother(vessel_id: str, material_id: str):
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
    return mother


def build_material(material_id: str):
    from synlab.materials.api import build_material_profile, default_material_params
    from synlab.seeds import make_rng

    rng = make_rng(MASTER_SEED, LINEAGE_ID, "materials", material_id)
    return build_material_profile(material_id, default_material_params(material_id), rng)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vessel", default="V18")
    parser.add_argument("--material", default="M01")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    out = Path(args.out) if args.out else (
        REPO_ROOT / "data" / "a12_reports" / "implicit"
        / f"recon_{args.vessel}_{args.material}.json")
    report: dict = {"vessel": args.vessel, "material": args.material}
    t0 = time.time()
    mother = build_mother(args.vessel, args.material)
    profile = build_material(args.material)
    report["mother_seconds"] = time.time() - t0
    mesh = mother.mesh
    report["mother"] = {
        "mother_id": mother.mother_id, "vertices": int(len(mesh.vertices)),
        "faces": int(len(mesh.faces)), "watertight": bool(mesh.is_watertight),
        "volume_mm3": float(abs(mesh.volume)), "area_mm2": float(mesh.area),
        "bounds": np.asarray(mesh.bounds).tolist(),
    }

    from synlab.fracture import morphology as morph
    from synlab.fracture.api import _default_basis
    from synlab.fracture.spec import FractureSpec
    from synlab.seeds import make_rng

    rng = make_rng(MASTER_SEED, LINEAGE_ID, "basis", args.vessel, args.material)
    basis = _default_basis(mother, rng, FractureSpec())
    report["basis"] = {
        "origin": np.asarray(basis.origin).tolist(),
        "e_u": np.asarray(basis.e_u).tolist(), "e_v": np.asarray(basis.e_v).tolist(),
        "normal": np.asarray(basis.normal).tolist(),
        "u_range": [float(x) for x in basis.u_range],
        "v_range": [float(x) for x in basis.v_range],
        "material_u_range": [float(x) for x in basis.meta["material_u_range"]],
        "material_v_range": [float(x) for x in basis.meta["material_v_range"]],
        "w_min_mm": float(basis.meta["w_min_mm"]), "w_max_mm": float(basis.meta["w_max_mm"]),
        "basis_id": basis.basis_id,
    }

    t0 = time.time()
    prepared = morph.prepare_morphology(mother, material_profile=profile, rng=rng, basis=basis,
                                       event_id="recon")
    report["prepare_seconds"] = time.time() - t0
    params = prepared["base_params"]
    report["morphology_params"] = {
        "requested_rms_mm": float(params.requested_rms_mm),
        "correlation_length_mm": float(params.correlation_length_mm),
        "dome_amplitude_mm": float(params.dome_amplitude_mm),
        "dome_radius_mm": float(params.dome_radius_mm),
        "mirror_radius_mm": float(params.mirror_radius_mm),
        "mist_radius_mm": float(params.mist_radius_mm),
        "hackle_count": int(params.hackle_count),
        "hackle_amplitude_mm": float(params.hackle_amplitude_mm),
        "rib_amplitude_mm": float(params.rib_amplitude_mm),
        "pit_count": int(params.pit_count), "pit_radius_mm": float(params.pit_radius_mm),
        "pit_depth_mm": float(params.pit_depth_mm),
        "fiber_period_mm": float(params.fiber_period_mm),
        "fiber_amplitude_mm": float(params.fiber_amplitude_mm),
        "glaze_strip_width_mm": float(params.glaze_strip_width_mm),
        "glaze_roughness_ratio": float(params.glaze_roughness_ratio),
        "requested_curvature_per_mm": float(params.requested_curvature_per_mm),
        "predicted_amplitude_scale": float(params.predicted_amplitude_scale),
        "bands": [list(b) for b in params.bands],
        "notes": list(params.notes),
    }
    wavelengths = [float(b[1]) for b in params.bands if float(b[0]) > 0.0]
    lam_min = min(wavelengths) if wavelengths else float("inf")
    report["wavelength_min_mm"] = lam_min
    report["sample_spacing_5_per_lambda_mm"] = lam_min / 5.0

    tris_uv = prepared["tris_uv"]
    report["cross_section"] = {
        "triangles": int(np.asarray(tris_uv).reshape(-1, 3, 2).shape[0]),
        "area_mm2": float(prepared["core_area_mm2"]),
        "bbox": [float(np.min(tris_uv[:, :, 0])), float(np.max(tris_uv[:, :, 0])),
                 float(np.min(tris_uv[:, :, 1])), float(np.max(tris_uv[:, :, 1]))],
        "extent_mm": [float(x) for x in prepared["extent_mm"]],
        "origin_uv": [float(x) for x in prepared["origin_uv"]],
    }
    frame_area = (float(basis.u_range[1] - basis.u_range[0])
                  * float(basis.v_range[1] - basis.v_range[0]))
    delta = lam_min / 5.0
    report["cost"] = {
        "frame_area_mm2": frame_area,
        "cross_section_area_mm2": float(prepared["core_area_mm2"]),
        "delta_mm": delta,
        "tensor_cells_band_bbox": float(np.prod([
            (report["cross_section"]["bbox"][1] - report["cross_section"]["bbox"][0]) / delta,
            (report["cross_section"]["bbox"][3] - report["cross_section"]["bbox"][2]) / delta])),
        "footprint_cells": float(prepared["core_area_mm2"] / delta ** 2),
        "tensor_cells_whole_frame": float(frame_area / delta ** 2),
    }

    # how much of the frame is actually material?  (decides tensor-grid waste)
    from synlab.fracture import cut as cut_mod

    t0 = time.time()
    window, norm_uv = cut_mod.build_band_window(basis, morph.build_morphology_field(
        basis, mesh, params, rng=rng, cross_section=(tris_uv, prepared["core_area_mm2"],
                                                     prepared["cross_info"])), mesh)
    report["band_window_seconds"] = time.time() - t0
    step = float(window.step_mm)
    values = np.asarray(window.values)
    report["band_window"] = {
        "step_mm": step, "shape": list(values.shape),
        "core_cells": int(np.asarray(window.core).sum()),
        "core_area_mm2": float(np.asarray(window.core).sum() * step ** 2),
        "touch_cells": int((values > 0.0).sum()),
        "touch_area_mm2": float((values > 0.0).sum() * step ** 2),
        "halo_mm": float(window.halo_mm), "margin_mm": float(window.margin_mm),
        "raw_stats": {k: v for k, v in window.stats.items() if not isinstance(v, list)},
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str),
                   encoding="utf-8")
    print(f"wrote {out}")
    print(json.dumps({k: report[k] for k in ("wavelength_min_mm", "cost")},
                     ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
