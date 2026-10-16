"""Compare the native elastic-seam and perfect-bond response at identical loads."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT/"pgfrag/data/continuation_20261015"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(run, receipt_name):
    receipt = json.loads((run/receipt_name).read_text())
    for name, row in receipt["files"].items():
        p = run/name
        if p.stat().st_size != row["bytes"] or sha(p) != row["sha256"]:
            raise ValueError(f"source receipt mismatch: {name}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seam-name", default="bonded_cohesive_control_v1")
    parser.add_argument("--out-name", default="control_comparison_v1.json")
    args = parser.parse_args()
    if Path(args.out_name).name != args.out_name or not args.seam_name.replace("_", "").isalnum():
        raise ValueError("output/case name must be a local name")
    out = ROOT/"pgfrag/experiments/cohesive_vessel_20261015"/args.out_name
    if out.exists():
        raise FileExistsError(out)
    bulk = ROOT/"pgfrag/data/control_bonded_bulk/run_attempt_01"
    seam = DATA/("cohesive_"+args.seam_name)
    verify(bulk, "run_receipt.json"); verify(seam, "receipt.json")
    with np.load(bulk/"history.npz", allow_pickle=False) as a:
        diag = a["diagnostics"].copy()
    with np.load(seam/"initial_state.npz", allow_pickle=False) as a:
        unit = a["unit_external_load"][:, 0]
    patch_u = np.load(seam/"history/patch_displacement_x_m.npy", mmap_mode="r")
    ledger = np.load(seam/"history/ledger.npy", mmap_mode="r")
    response = np.asarray(patch_u) @ unit[unit != 0]
    if not np.allclose(diag[:, 0], ledger[:, 0], rtol=0, atol=1e-18) or not np.array_equal(diag[:, 1], ledger[:, 1]):
        raise ValueError("physical time or force profile mismatch")
    peak = int(np.argmax(diag[:, 1])); window = diag[:, 0] <= 25e-6
    delta = response-diag[:, 4]
    controls = {}
    for name in dict.fromkeys(("zero_control_v1", "low_control_v1", "low_elastic_control_v1", "bonded_cohesive_control_v1", args.seam_name)):
        p = DATA/("cohesive_"+name)
        verify(p, "receipt.json")
        damage = np.load(p/"history/damage.npy", mmap_mode="r")
        energy = np.load(p/"history/energy_J.npy", mmap_mode="r")
        nodes = np.load(p/"history/node_state.npy", mmap_mode="r")
        controls[name] = {"receipt_sha256": sha(p/"receipt.json"), "max_damage": float(damage.max()),
                    "native_dissipation_min_J": float(energy[:, 2].min()), "native_dissipation_final_J": float(energy[-1, 2]),
                    "max_saved_abs_displacement_m": float(np.abs(nodes[:, :, 0]).max()),
                    "max_saved_abs_velocity_mps": float(np.abs(nodes[:, :, 1]).max())}
    rms = lambda x: float(np.sqrt(np.mean(x*x)))
    result = {"schema": "pgfrag.native_cohesive_control_comparison.v1", "status": "TRANSIENT_COMPLIANCE_DIAGNOSTIC",
       "same_mesh_bulk_parameters_load_and_physical_time": True,
       "source_receipt_sha256": {"bulk": sha(bulk/"run_receipt.json"), "elastic_seam": sha(seam/"receipt.json")},
       "peak_load_time_s": float(diag[peak, 0]), "peak_force_N": float(diag[peak, 1]),
       "bulk_response_peak_load_m": float(diag[peak, 4]), "seam_response_peak_load_m": float(response[peak]),
       "relative_response_difference_at_peak_load": float(delta[peak]/diag[peak, 4]),
       "pulse_window_response_RMS_relative_difference": rms(delta[window])/rms(diag[window, 4]),
       "full_window_response_RMS_relative_difference": rms(delta)/rms(diag[:, 4]),
       "pulse_window_max_abs_difference_relative_bulk_peak_response": float(np.abs(delta[window]).max()/np.abs(diag[window, 4]).max()),
       "declared_2percent_transient_compliance_gate": bool(abs(delta[peak]/diag[peak, 4]) <= .02 and rms(delta[window])/rms(diag[window, 4]) <= .02),
       "controls": controls,
       "limitations": ["transient same-pulse compliance diagnostic, not a static compliance measurement",
                       "100N weak-seam control has nonzero damage; it is retained and not counted as an undamaged control",
                       "1N weak-seam case and 100N reinforced elastic seam are separate controls; no fracture-load retuning",
                       "does not calibrate material, demonstrate mesh convergence or qualify full physical packages"],
       "source_script_sha256": sha(Path(__file__))}
    out.write_text(json.dumps(result, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
