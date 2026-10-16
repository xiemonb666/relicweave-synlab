"""A09 stage-5: can the 6-edge open seam of the global-SDF P03 body be closed honestly?

The accepted body of the shipped P03 path (``operators.erode_interface`` -> marching cubes ->
``intersect_with_source``) is a genuine subset of the clean body (exact instrument: max outside
3.7e-6 mm) but trimesh reports ``is_watertight = False`` with 6 boundary edges, and
``repair.fill_holes`` adds no face.  This probe characterises those boundary edges (geometry,
lengths, coincident vertices) and measures every honest closing strategy:

* ``merge_vertices`` at several tolerances, then re-count boundary edges;
* ``repair.fill_holes`` after welding;
* ``repair.broken_faces``;
* a trimesh re-``process`` (``process=True`` merges + fixes winding).

For each strategy: boundary edges, watertightness, volume delta, and the exact subset check
against the clean body (``trimesh.proximity.signed_distance``, positive = inside).

Usage:
  .venv\\Scripts\\python.exe data/a12/reports/probe_a09_seam.py --store <store> --out <json>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import trimesh

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab.config import load_generation_spec  # noqa: E402
from synlab.physical import operators as OPS  # noqa: E402
from synlab.physical import sdf as S  # noqa: E402
from synlab.pipeline import _load_damage_recipe  # noqa: E402
from synlab.roles import ROLE_FRAGMENT_MESH  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402


def boundary_edge_rows(mesh: trimesh.Trimesh) -> tuple[np.ndarray, np.ndarray]:
    """Return (edges_sorted, lengths) for edges used by exactly one face."""
    edges = np.asarray(mesh.edges_sorted, dtype=np.int64)
    if len(edges) == 0:
        return np.zeros((0, 2), dtype=np.int64), np.zeros(0)
    order = np.lexsort(edges.T)
    sorted_edges = edges[order]
    same = np.all(sorted_edges[1:] == sorted_edges[:-1], axis=1)
    starts = np.concatenate([[True], ~same])
    run_id = np.cumsum(starts) - 1
    counts = np.bincount(run_id)
    unique_edges = sorted_edges[starts]
    once = unique_edges[counts == 1]
    lengths = np.linalg.norm(mesh.vertices[once[:, 0]] - mesh.vertices[once[:, 1]], axis=1)
    return once, lengths


def exact_outside(mesh: trimesh.Trimesh, clean: trimesh.Trimesh, *, n: int = 20000,
                  seed: int = 0) -> dict:
    points, _ = trimesh.sample.sample_surface(mesh, int(n), seed=int(seed) % (2 ** 31))
    signed = np.asarray(trimesh.proximity.signed_distance(clean, np.asarray(points, np.float64)))
    outside = -signed  # trimesh: positive = inside
    return {"outside_points": int(np.count_nonzero(outside > 1e-3)),
            "outside_fraction": float(np.mean(outside > 1e-3)),
            "max_outside_mm": float(outside.max())}


def probe(store_root: Path, lineage_id: str, recipe_id: str, config: Path) -> dict:
    store = AssetStore(store_root)
    fragments = store.list_assets(role=ROLE_FRAGMENT_MESH, limit=200)
    best = max(fragments, key=lambda r: float(abs(store.load_mesh(r.asset_id, "mesh").volume)))
    clean = store.load_mesh(best.asset_id, "mesh")
    spec = load_generation_spec(config)
    fragment = SimpleNamespace(mesh=clean, fragment_id=str(best.meta.get("fragment_id")),
                               volume_mm3=float(abs(clean.volume)), is_tiny=False,
                               meta={"material_id": ""})
    recipe = _load_damage_recipe(recipe_id, spec, fragment=fragment,
                                 master_seed=spec.master_seed, lineage_id=lineage_id)
    outcome = OPS.run_damage(clean, recipe, fragment=fragment)
    accepted = outcome.mesh
    volume0 = float(abs(accepted.volume))

    edges, lengths = boundary_edge_rows(accepted)
    out: dict = {
        "store": str(store_root),
        "accepted": {"watertight": bool(accepted.is_watertight), "n_faces": int(len(accepted.faces)),
                     "n_vertices": int(len(accepted.vertices)), "volume_mm3": volume0,
                     "boundary_edges": int(len(edges))},
        "boundary_edge_lengths_mm": [float(v) for v in lengths],
        "boundary_edge_vertices": [[float(v) for v in accepted.vertices[i]] for i in edges.ravel()],
        "exact_subset_before": exact_outside(accepted, clean, seed=1),
        "strategies": {},
    }
    # coincident-vertex diagnosis: is the seam a pair of unwelded duplicate vertices?
    if len(edges):
        endpoints = accepted.vertices[np.unique(edges.ravel())]
        from scipy.spatial import cKDTree

        tree = cKDTree(endpoints)
        pairs = tree.query_pairs(r=1e-4, output_type="ndarray")
        out["coincident_endpoint_pairs_within_1e-4mm"] = int(len(pairs))
        out["min_endpoint_pair_distance_mm"] = float(
            tree.query(endpoints, k=2)[0][:, 1].min()) if len(endpoints) > 1 else 0.0

    def evaluate(name: str, mesh: trimesh.Trimesh) -> None:
        edges2, _len2 = boundary_edge_rows(mesh)
        out["strategies"][name] = {
            "watertight": bool(mesh.is_watertight),
            "boundary_edges": int(len(edges2)),
            "n_faces": int(len(mesh.faces)),
            "volume_mm3": float(abs(mesh.volume)),
            "volume_delta_mm3": float(abs(mesh.volume) - volume0),
            "exact_subset": exact_outside(mesh, clean, seed=2),
        }

    # 1. merge vertices at several vertex tolerances
    for digits in (8, 7, 6, 5, 4):
        candidate = accepted.copy()
        try:
            candidate.merge_vertices(digits_vertex=int(digits))
            candidate.update_faces(candidate.nondegenerate_faces(height=1e-12))
            candidate.remove_unreferenced_vertices()
            trimesh.repair.fix_winding(candidate)
            evaluate(f"merge_vertices_digits_{digits}", candidate)
        except Exception as exc:  # noqa: BLE001
            out["strategies"][f"merge_vertices_digits_{digits}"] = {
                "error": f"{type(exc).__name__}: {exc}"}

    # 2. weld by an explicit distance tolerance, then fill holes
    for tol in (1e-6, 1e-5, 1e-4, 1e-3):
        candidate = accepted.copy()
        try:
            merged = trimesh.grouping.merge_vertices(
                candidate.vertices, candidate.faces, digits_vertex=None, threshold=float(tol))
            vertices, faces = merged[0], merged[1]
            candidate = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
            trimesh.repair.fix_winding(candidate)
            trimesh.repair.fix_inversion(candidate)
            before = len(boundary_edge_rows(candidate)[0])
            trimesh.repair.fill_holes(candidate)
            trimesh.repair.fix_winding(candidate)
            evaluate(f"weld_threshold_{tol:g}_then_fill_holes", candidate)
            out["strategies"][f"weld_threshold_{tol:g}_then_fill_holes"]["boundary_before_fill"] = int(before)
        except Exception as exc:  # noqa: BLE001
            out["strategies"][f"weld_threshold_{tol:g}_then_fill_holes"] = {
                "error": f"{type(exc).__name__}: {exc}"}

    # 3. trimesh process=True round trip, then fill holes
    candidate = trimesh.Trimesh(vertices=accepted.vertices, faces=accepted.faces, process=True)
    evaluate("trimesh_process_true", candidate)
    trimesh.repair.fill_holes(candidate)
    trimesh.repair.fix_winding(candidate)
    evaluate("trimesh_process_true_then_fill_holes", candidate)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", required=True)
    parser.add_argument("--lineage", default="LIN0000_V02_M01_PAT02")
    parser.add_argument("--recipe", default="P03_depth_light")
    parser.add_argument("--config", default="configs/a12/sandbox.yaml")
    parser.add_argument("--out", default="data/a12/reports/a09_p03_seam.json")
    args = parser.parse_args()
    report = probe(Path(args.store), args.lineage, args.recipe, Path(args.config))
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str),
                      encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
