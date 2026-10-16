"""Root calculation from the measured, zero-step Akantu topology and masses."""
import dataclasses
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pgfrag/src"))
EXP = ROOT / "pgfrag/experiments/free_cohesive_patch_20261015"
sys.path.insert(0, str(EXP))
from pgfrag.cohesive_stability import mass_normalized_stiffness_bound
from free_patch_contract import build_native_lineage, read_gmsh22, surface_nodes


def main():
    archive = EXP / "preflight_readback_02/native_zero_step_state.npz"
    state = dict(np.load(archive, allow_pickle=False))
    mesh = read_gmsh22(EXP / "block_2x2x4mm.msh")
    lineage = build_native_lineage(mesh, state["native_nodes"], state["native_bulk_tets"],
                                   state["native_cohesive_connectivity"], expected_area_m2=4e-6)
    ancestor = {int(k): int(v) for k, v in lineage["native_node_to_input_node_zero_based"].items()}
    pairs = []
    for row in state["native_cohesive_connectivity"]:
        a = {ancestor[int(i)]: int(i) for i in row[:3]}
        b = {ancestor[int(i)]: int(i) for i in row[3:]}
        assert set(a) == set(b)
        order = sorted(a)
        pairs.append([[a[i] for i in order], [b[i] for i in order]])
    blocked = np.zeros((len(state["native_nodes"]), 3), dtype=bool)
    for group in ("top", "bottom"):
        source_nodes = surface_nodes(mesh, group)
        blocked[[i for i, source in ancestor.items() if source in source_nodes], 2] = True
    for source, components in ((0, [0, 1]), (2, [1])):
        ids = [i for i, origin in ancestor.items() if origin == source]
        assert len(ids) == 1
        blocked[ids[0], components] = True
    kn = 70e6 / 2.1714285714285715e-8
    bounds = {}
    for name, normal_stiffness in (("initial_anisotropic", kn), ("isotropic_material_envelope", 9 * kn)):
        bound = mass_normalized_stiffness_bound(
            state["native_nodes"], state["native_bulk_tets"], np.asarray(pairs, dtype=np.int64),
            2500., 70e9, .22, normal_stiffness, 9 * kn, blocked,
            native_point_mass_kg=state["mass_kg"], validate_dense_eigenvalue=True,
        )
        bounds[name] = {k: v for k, v in dataclasses.asdict(bound).items() if not isinstance(v, np.ndarray)}
    result = {
        "schema": "shardforge.root_cohesive_initial_bound.v1",
        "preflight_state_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "calculation_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "kernel_source_sha256": hashlib.sha256((ROOT / "pgfrag/src/pgfrag/cohesive_stability.py").read_bytes()).hexdigest(),
        "measured_quadrature_points_per_facet": 3, "bounds": bounds,
        "proposed_dt_s": 2e-9,
        "proposed_fraction": .5,
        "proposed_dt_passes_initial_bound": 2e-9 <= bounds["isotropic_material_envelope"]["recommended_time_step_s"],
        "scope": "initial linear positive-stiffness high-frequency bound; evolving current-normal geometry, softening accuracy and contact require separate checks",
    }
    output = Path(__file__).with_suffix(".json")
    output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
