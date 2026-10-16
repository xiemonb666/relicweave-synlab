"""Independent root calculations for the frozen hemispherical-bowl experiment."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree


WORKSPACE = Path(__file__).resolve().parents[2]
OUTPUT = Path(__file__).resolve().parent / "root_geometry_math.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    records = []
    for pattern in ("three_bands", "four_bands"):
        root = WORKSPACE / "vesselforge/data/continuation_20261015/spherical_bowl" / pattern
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        for relative, expected in manifest["files"].items():
            path = root / relative
            assert path.stat().st_size == expected["bytes"] and digest(path) == expected["sha256"]
        with np.load(root / manifest["geometry"]["surface_npz"], allow_pickle=False) as payload:
            vertices = payload["vertices_mm"]
            faces = payload["faces"]
        tri = vertices[faces]
        directed = np.concatenate((faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]))
        edges, counts = np.unique(np.sort(directed, axis=1), axis=0, return_counts=True)
        signs = np.where(directed[:, 0] < directed[:, 1], 1, -1)
        _, inverse = np.unique(np.sort(directed, axis=1), axis=0, return_inverse=True)
        orientation_sum = np.bincount(inverse, weights=signs, minlength=len(edges))
        volume = np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum() / 6.0
        expected_volume = 2 * math.pi / 3 * (12**3 - 8**3)
        assert np.all(counts == 2) and np.all(orientation_sum == 0) and volume > 0
        records.append({
            "pattern": pattern, "manifest_sha256": digest(root / "manifest.json"),
            "vertices": len(vertices), "triangles": len(faces), "edges": len(edges),
            "euler_characteristic": int(len(vertices) - len(edges) + len(faces)),
            "all_edges_two_opposite_uses": True,
            "mesh_signed_volume_mm3": float(volume),
            "mesh_volume_relative_error": float(abs(volume - expected_volume) / expected_volume),
            "all_manifest_payload_digests_verified": True,
        })

    ro, ri, h, delta = .012, .008, .001, .0025
    center = np.array([0., 0., .012])
    axes = [np.arange(-ro + h / 2, ro, h), np.arange(-ro + h / 2, ro, h), np.arange(h / 2, ro, h)]
    x, y, z = np.meshgrid(*axes, indexing="ij")
    candidates = np.column_stack((x.ravel(), y.ravel(), z.ravel()))
    radius = np.linalg.norm(candidates - center, axis=1)
    reference = candidates[(radius >= ri) & (radius <= ro)]
    pairs = cKDTree(reference).query_pairs(delta, output_type="ndarray")
    a = reference[pairs[:, 0]] - center
    d = reference[pairs[:, 1]] - reference[pairs[:, 0]]
    t = np.clip(-np.einsum("ij,ij->i", a, d) / np.einsum("ij,ij->i", d, d), 0, 1)
    minimum_radius = np.linalg.norm(a + t[:, None] * d, axis=1)
    excluded = minimum_radius < ri - 1e-12
    native_pairs = pairs[~excluded]
    degree = np.bincount(native_pairs.ravel(), minlength=len(reference))
    rho, young, nu, gc = 2300., 70e9, .25, 7.6
    bulk = young / (3 * (1 - 2 * nu))
    bond_constant = 18 * bulk / (math.pi * delta**4)
    critical_stretch = math.sqrt(5 * gc / (9 * bulk * delta))
    masses = np.full(len(reference), rho * h**3)
    com = np.average(reference, axis=0, weights=masses)
    r = reference - com
    inertia = (np.sum(masses * np.einsum("ij,ij->i", r, r)) * np.eye(3)
               - np.einsum("i,ij,ik->jk", masses, r, r))
    loading = []
    for alpha in (0., 100., 300.):
        velocity = r @ np.diag([alpha, -.25 * alpha, 0.])
        velocity -= np.average(velocity, axis=0, weights=masses)
        angular = np.cross(r, masses[:, None] * velocity).sum(axis=0)
        omega = np.linalg.solve(inertia, angular)
        velocity -= np.cross(omega, r)
        loading.append({
            "alpha_s_1": alpha,
            "initial_kinetic_energy_J": float(.5 * np.sum(masses[:, None] * velocity**2)),
            "momentum_kg_mps": np.sum(masses[:, None] * velocity, axis=0).tolist(),
            "angular_momentum_kg_m2ps": np.cross(r, masses[:, None] * velocity).sum(axis=0).tolist(),
            "max_initial_speed_mps": float(np.max(np.linalg.norm(velocity, axis=1))),
        })
    result = {
        "schema": "shardforge.root_bowl_geometry_math.v1", "scope": "independent_geometry_and_initial_state_only",
        "source_sha256": digest(Path(__file__)), "asset_checks": records,
        "analytic_volume_mm3": 2 * math.pi / 3 * (12**3 - 8**3),
        "lattice": {
            "point_count": len(reference), "h_m": h, "delta_m": delta,
            "volume_mm3": len(reference) * h**3 * 1e9, "mass_kg": float(masses.sum()),
            "candidate_pairs": len(pairs), "geometric_exclusion_pairs": int(excluded.sum()),
            "retained_pairs": len(native_pairs), "minimum_degree": int(degree.min()),
            "maximum_degree": int(degree.max()), "center_of_mass_m": com.tolist(),
        },
        "material_formula": {"K_pa": bulk, "c_N_m6": bond_constant, "epsilon_c": critical_stretch},
        "loading": loading,
        "physical_fracture_and_training_qualification": "NOT_ASSESSED_BY_THIS_CALCULATION",
    }
    OUTPUT.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
