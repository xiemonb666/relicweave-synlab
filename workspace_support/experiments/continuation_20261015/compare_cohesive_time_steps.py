"""A same-mesh, same-duration sensitivity report, not asymptotic convergence."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT/"pgfrag/data/continuation_20261015"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", default="cohesive_weak_seam_v4")
    parser.add_argument("--half", default="cohesive_weak_seam_halfdt_v2")
    parser.add_argument("--out-name", default="time_sensitivity_v4_halfdt_v2.json")
    args = parser.parse_args()
    if any(Path(n).name != n for n in (args.baseline, args.half, args.out_name)):
        raise ValueError("case/output names must be local names")
    out = ROOT/"pgfrag/experiments/cohesive_vessel_20261015"/args.out_name
    if out.exists():
        raise FileExistsError(out)
    runs = [DATA/args.baseline, DATA/args.half]
    initials = [np.load(p/"initial_state.npz", allow_pickle=False) for p in runs]
    for key in initials[0].files:
        if not np.array_equal(initials[0][key], initials[1][key]):
            raise ValueError(f"fixed mesh input changed: {key}")
    nodes = [np.load(p/"history/node_state.npy", mmap_mode="r") for p in runs]
    qps = [np.load(p/"history/damage.npy", mmap_mode="r") for p in runs]
    energy = [np.load(p/"history/energy_J.npy", mmap_mode="r") for p in runs]
    ledgers = [np.load(p/"history/ledger.npy", mmap_mode="r") for p in runs]
    if len(nodes[1]) != 2*(len(nodes[0])-1)+1 or not np.allclose(ledgers[0][:, 0], ledgers[1][::2, 0], rtol=0, atol=1e-18):
        raise ValueError("same physical-time state alignment failed")
    area = float(initials[0]["qp_area_m2"].sum())
    gcarea = 7.6*area
    summaries = []
    for run, e, l, d in zip(runs, energy, ledgers, qps):
        first = int(np.flatnonzero(np.all(d >= 1-1e-10, axis=1))[0])
        summaries.append({"run": str(run.relative_to(ROOT)), "receipt_sha256": sha(run/"receipt.json"),
                "dt_s": float(l[1, 0]), "steps": len(l)-1,
                "all_qp_full_damage_first_time_s": float(l[first, 0]),
                "final_native_dissipation_J": float(e[-1, 2]),
                "final_dissipation_relative_error_GcAh": float((e[-1, 2]-gcarea)/gcarea),
                "peak_alg_external_balance_error_J": float(np.abs(l[:, 17]).max()),
                "peak_alg_external_balance_error_relative_GcAh": float(np.abs(l[:, 17]).max()/gcarea),
                "final_alg_external_balance_error_relative_total_work": float(l[-1, 17]/l[-1, 3]),
                "contact_energy_max_abs_J": float(np.abs(e[:, 4]).max()),
                "contact_energy_final_J": float(e[-1, 4]),
                "contact_traction_max_Pa": float(np.abs(l[:, 27]).max())})
    dif = np.asarray(nodes[0][-1])-np.asarray(nodes[1][-1])
    mass = initials[0]["mass_kg"][:, 0]
    rms = lambda a: float(np.sqrt(np.sum(mass[:, None]*a*a)/mass.sum()))
    result = {"schema": "pgfrag.native_cohesive_time_sensitivity.v1", "status": "TWO_LEVEL_FIXED_MESH_SENSITIVITY_ONLY",
        "GcAh_J": gcarea, "discrete_interface_area_m2": area,
        "runs": summaries,
        "final_mass_weighted_displacement_difference_m": rms(dif[:, 0]),
        "final_max_nodal_displacement_difference_m": float(np.linalg.norm(dif[:, 0], axis=1).max()),
        "final_mass_weighted_velocity_difference_mps": rms(dif[:, 1]),
        "final_mass_weighted_velocity_relative_difference": rms(dif[:, 1])/rms(nodes[1][-1, :, 1]),
        "native_dissipation_difference_relative_GcAh": float((energy[1][-1, 2]-energy[0][-1, 2])/gcarea),
        "limitations": ["two dt levels do not establish asymptotic convergence", "fixed h=1.5mm; mesh/orientation sensitivity outstanding",
                        "weak seam/material uncalibrated; large final K must not hide fracture-energy errors"],
        "source_script_sha256": sha(Path(__file__))}
    out.write_text(json.dumps(result, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
