"""Freeze explicit new weak-seam vessel inputs and the source actually executed."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--name", required=True)
    p.add_argument("--peak-force", type=float, default=1600.)
    p.add_argument("--refinement", type=int, default=1)
    p.add_argument("--bonded-control", action="store_true")
    p.add_argument("--node-stride", type=int, default=50)
    p.add_argument("--compression-penalty", type=float, default=0.)
    args = p.parse_args()
    if not args.name.replace("_", "").isalnum() or not 0 <= args.peak_force <= 1600 or args.refinement not in (1, 2) or args.node_stride not in (1, 50) or args.compression_penalty not in (0., 1e15):
        raise ValueError("unreviewed case parameters")
    dest = ROOT/"pgfrag/experiments/cohesive_vessel_20261015"/args.name
    dest.mkdir(parents=True, exist_ok=False)
    meshroot = ROOT/"vesselforge/experiments/continuation_20261015/bowl_tetra/run02/mesh"
    asset = ROOT/"vesselforge/data/continuation_20261015/spherical_bowl/three_bands"
    manifest = json.loads((asset/"manifest.json").read_text(encoding="utf-8"))
    material = manifest["material"]["mechanics"]
    # The bonded diagnostic retains the same peak stiffness and makes the seam
    # nonsoftening over this experiment. It is not a new calibrated material.
    sigma = 1e12 if args.bonded_control else 1e7
    delta0 = sigma/1e15
    gc = 1e12 if args.bonded_control else 7.6
    text = f"""model solid_mechanics_model_cohesive [
  cohesive_inserter [
    cohesive_surfaces = [interface]
  ]
  material elastic [
    name = body
    rho = {material['rho_kg_m3']:.17g}
    E = {material['E_pa']:.17g}
    nu = {material['nu']:.17g}
    finite_deformation = false
  ]
  material cohesive_bilinear [
    name = interface_law
    sigma_c = {sigma:.17g}
    G_c = {gc:.17g}
    beta = 1
    kappa = 1
    delta_0 = {delta0:.17g}
    penalty = {args.compression_penalty:.17g}
    contact_after_breaking = false
  ]
]
"""
    (dest/"material.dat").write_text(text, encoding="utf-8")
    shutil.copy2(meshroot/"mesh.msh", dest/"mesh.msh")
    shutil.copy2(meshroot/"result.json", dest/"mesh_result.json")
    shutil.copy2(asset/"manifest.json", dest/"forge_manifest.json")
    for name in ("cohesive_vessel.py", "cohesive_mesh.py", "cohesive_stability.py"):
        shutil.copy2(ROOT/"pgfrag/src/pgfrag"/name, dest/name)
    case = {
      "schema": "pgfrag.native_cohesive_vessel_case.v1", "case_name": args.name,
      "authorization": "USER_CONTINUATION_20261015_ROOT_REVIEWED_NEW_BOUNDED_EXPERIMENT",
      "classification": "UNVALIDATED_PREINSERTED_WEAK_SEAM_DIAGNOSTIC" if not args.bonded_control else "BONDED_COHESIVE_STIFFNESS_CONTROL",
      "source_forge_manifest_sha256": sha(asset/"manifest.json"),
      "source_mesh_result_sha256": sha(meshroot/"result.json"),
      "bulk_material": material,
      "interface": {"sigma_c_Pa": sigma, "Gc_J_m2": gc, "delta0_m": delta0, "beta": 1, "kappa": 1,
                    "calibration": "NONE", "predefined_plane": "x=0", "penalty_Pa_m": args.compression_penalty,
                    "contact_after_breaking": False},
      "loading": {"peak_force_N": args.peak_force, "pulse_duration_s": 25e-6,
                  "patch_x_threshold_m": .0085, "type": "REFERENCE_DIRECTION_POSITIVE_NODAL_PATCH_FORCES",
                  "profile": "peak*sin(pi*t/25us)^2 for 0<t<25us, else zero",
                  "force_line": "reference complete bulk lumped mass COM y,z; relative-entropy projection with strictly positive weights",
                  "constraints": "NONE; ALL NATIVE DOFS FREE"},
      "time": {"total_s": 50e-6, "initial_bound_fraction": .4, "refinement_factor": args.refinement,
               "dt_policy": "T/(ceil(T/min(.4*independent total critical dt,.4*native bulk dt))*refinement)"},
      "limits": {"max_steps": 40000, "wall_time_s": 300, "output_cap_bytes": 2*1024**3},
      "output": {"node_stride": args.node_stride, "flush_stride": 250, "all_native_qp_steps": True},
      "gates": {"damage_tolerance": 1e-10, "traction_zero_tolerance_Pa": .01,
                "max_abs_principal_small_strain": .01, "max_polar_rotation_rad": .05, "min_det_F": .8,
                "scope": "sampled each saved nodal state; small-strain numerical applicability, not ceramic elasticity/calibration"},
      "limitations": ["prescribed weak seam, not homogeneous free crack path",
                      "no general body contact; prebreak interface compression penalty is explicitly declared; physical interpretation ends at nonpaired surface collision",
                      "initial fixed-normal stiffness bound, not nonlinear accuracy proof",
                      "zero/lowload and half-dt comparisons required before qualification",
                      "material parameters and historical vessel style uncalibrated",
                      "full time series QP native doubles retained; nodal states are declared stride samples"],
    }
    case["input_hashes"] = {name: sha(dest/name) for name in ("mesh.msh", "mesh_result.json", "forge_manifest.json", "material.dat",
                                                            "cohesive_vessel.py", "cohesive_mesh.py", "cohesive_stability.py")}
    (dest/"case.json").write_text(json.dumps(case, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    records = {q.name: {"sha256": sha(q), "bytes": q.stat().st_size} for q in dest.iterdir() if q.is_file()}
    (dest/"source_freeze.json").write_text(json.dumps({"files": records}, indent=2)+"\n", encoding="utf-8")
    print(dest)


if __name__ == "__main__":
    main()
