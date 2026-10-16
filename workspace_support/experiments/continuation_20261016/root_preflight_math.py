"""Independent NumPy readback of the completed full-size zero-step preflight."""
from pathlib import Path
import hashlib
import json
import math

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
CASE_ROOT = ROOT / "pgfrag/experiments/continuation_20261016/reference_vessel_preflight/run_attempt_02"
RUN = CASE_ROOT / "native_preflight/run01"


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    result = json.loads((RUN / "result.json").read_text())
    receipt = json.loads((RUN / "receipt.json").read_text())
    case = json.loads((CASE_ROOT / "inputs/case.json").read_text())
    bound = json.loads((RUN / "initial_bound.json").read_text())
    assert result["status"] == "ZERO_STEP_PREFLIGHT_PASS" and result["solver_steps"] == 0
    for name, row in receipt["files"].items():
        p = RUN / name
        assert p.stat().st_size == row["bytes"] and sha(p) == row["sha256"]
    for name, digest in case["input_hashes"].items():
        assert sha(CASE_ROOT / "inputs" / name) == digest
    with np.load(RUN / "initial_state.npz", allow_pickle=False) as data:
        x = data["rest_nodes_m"]
        tet = data["tets"]
        pairs = data["cohesive_pairs"]
        mass = data["mass_kg"]
        force = data["unit_external_load"]
        qp_area = data["qp_area_m2"]
        blocked = data["blocked"]
    p = x[tet]
    six_v = np.einsum("ij,ij->i", p[:, 1] - p[:, 0],
                      np.cross(p[:, 2] - p[:, 0], p[:, 3] - p[:, 0]))
    assert np.all(six_v > 0)
    volume = float(np.sum(six_v) / 6)
    rho = case["bulk_material"]["rho_kg_m3"]
    complete_mass = rho * volume
    assert np.all(mass > 0) and np.allclose(mass, mass[:, :1], rtol=0, atol=0)
    native_mass = float(mass[:, 0].sum())
    assert np.isclose(native_mass, complete_mass, rtol=1e-12, atol=1e-15)
    a, b = x[pairs[:, 0]], x[pairs[:, 1]]
    assert np.array_equal(a, b)
    area = .5 * np.linalg.norm(np.cross(a[:, 1] - a[:, 0], a[:, 2] - a[:, 0]), axis=1)
    assert np.all(area > 0) and np.allclose(qp_area.reshape(-1, 3), area[:, None] / 3,
                                          rtol=1e-12, atol=1e-18)
    com = np.sum(x * mass[:, :1], axis=0) / native_mass
    net_force = force.sum(axis=0)
    net_torque = np.cross(x - com, force).sum(axis=0)
    assert np.linalg.norm(net_force) < 1e-12 and np.linalg.norm(net_torque) < 1e-10
    assert not blocked.any()
    total_s = case["time"]["total_s"]
    maximum_dt = min(case["time"]["initial_bound_fraction"] * bound["critical_time_step_s"],
                     .4 * bound["bulk_only_native_dt_s"])
    steps = math.ceil(total_s / maximum_dt) * case["time"].get("refinement_factor", 1)
    assert steps == bound["steps"] and np.isclose(total_s / steps, bound["dt_s"], rtol=1e-14)
    sigma = case["interface"]["sigma_c_Pa"]
    gc = case["interface"]["Gc_J_m2"]
    e = case["bulk_material"]["E_pa"]
    nu = case["bulk_material"]["nu"]
    out = {
        "status": "INDEPENDENT_ZERO_STEP_READBACK_PASS",
        "source_native_receipt_sha256": sha(RUN / "receipt.json"),
        "solver_steps": 0,
        "native_nodes": len(x), "tets": len(tet), "cohesive_facets": len(pairs),
        "qp_count": len(qp_area), "tetrahedral_volume_m3": volume,
        "rho_times_volume_kg": complete_mass, "native_lumped_mass_kg": native_mass,
        "interface_one_side_area_m2": float(area.sum()),
        "paired_rest_coordinates_equal": True,
        "reference_net_unit_force": net_force.tolist(),
        "reference_net_unit_torque_about_com": net_torque.tolist(),
        "all_dofs_free": True, "selected_dt_s": total_s / steps, "forecast_steps": steps,
        "placeholder_weak_law_design_scales": {
            "nominal_sigma_times_area_N": sigma * float(area.sum()),
            "Gc_times_discrete_area_J": gc * float(area.sum()),
            "bilinear_final_opening_m": 2 * gc / sigma,
            "Eprime_Gc_over_sigma_squared_m": e / (1 - nu**2) * gc / sigma**2,
            "interpretation": "dimensional weak-law scales, not specimen measurements, a cohesive-zone resolution certificate or a new loading prescription",
        },
        "limitations": ["v5 geometry/resource diagnostic; no evolution", "uncalibrated placeholder material",
                        "exterior surface ancestry is still unbound on this mesh"],
    }
    path = Path(__file__).with_suffix(".json")
    if path.exists():
        raise FileExistsError(path)
    path.write_text(json.dumps(out, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(out, allow_nan=False))


if __name__ == "__main__":
    main()
