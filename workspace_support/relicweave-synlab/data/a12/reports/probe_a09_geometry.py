"""A09 stage-2 geometry diagnostic: why is the P03 body open / outside / zero-volume?

Reproduces the operator body of ``P03_depth_light`` level 1 on the archived clean fragment and
measures the marching-cubes candidate *before* the only-remove clip and the accepted body
*after* it, plus the candidate repairs that an assembly-level fix could apply:

* boundary-edge count and watertightness of candidate / accepted / repaired meshes;
* ``trimesh.repair.fill_holes`` (hole count, volume/area delta, watertightness afterwards);
* a second ``intersection`` with the clean body (does the manifold engine close it?);
* dense sampled ``damaged ⊆ clean`` (``max_outside_mm``, outside fraction) per variant;
* the connected bodies each variant splits into, with their volumes.

Usage:
  .venv\\Scripts\\python.exe data/a12/reports/probe_a09_geometry.py --store <store> --out <json>
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


def _boundary_edges(mesh: trimesh.Trimesh) -> int:
    edges = np.asarray(mesh.edges_sorted, dtype=np.int64)
    if len(edges) == 0:
        return 0
    order = np.lexsort(edges.T)
    edges = edges[order]
    same = np.all(edges[1:] == edges[:-1], axis=1)
    # runs of equal edges: count runs whose length is 1 (an edge used by a single face)
    starts = np.concatenate([[True], ~same])
    run_id = np.cumsum(starts) - 1
    counts = np.bincount(run_id)
    return int(np.count_nonzero(counts == 1))


def _summary(mesh: trimesh.Trimesh, clean: trimesh.Trimesh, *, seed: int = 0) -> dict:
    bodies = S.component_split(mesh)
    outside = S.outside_fraction(mesh, clean, n_samples=20000, tol_mm=1e-3, seed=seed)
    return {
        "watertight": bool(mesh.is_watertight),
        "winding_consistent": bool(mesh.is_winding_consistent),
        "boundary_edges": _boundary_edges(mesh),
        "volume_mm3": float(abs(mesh.volume)),
        "area_mm2": float(mesh.area),
        "n_faces": int(len(mesh.faces)),
        "n_vertices": int(len(mesh.vertices)),
        "euler_number": int(mesh.euler_number),
        "bodies": len(bodies),
        "body_volumes": sorted((float(abs(b.volume)) for b in bodies), reverse=True)[:6],
        "body_watertight": [bool(b.is_watertight) for b in bodies][:6],
        "outside_fraction": float(outside["outside_fraction"]),
        "max_outside_mm": float(outside["max_outside_mm"]),
        "samples": int(outside["samples"]),
    }


def probe(store_root: Path, lineage_id: str, recipe_id: str, config: Path) -> dict:
    store = AssetStore(store_root)
    fragments = [store.list_assets(role=ROLE_FRAGMENT_MESH, limit=200)][0]
    best = max(fragments, key=lambda r: float(abs(store.load_mesh(r.asset_id, "mesh").volume)))
    clean = store.load_mesh(best.asset_id, "mesh")
    spec = load_generation_spec(config)
    fragment = SimpleNamespace(mesh=clean, fragment_id=str(best.meta.get("fragment_id")),
                               volume_mm3=float(abs(clean.volume)), is_tiny=False,
                               meta={"material_id": ""})
    recipe = _load_damage_recipe(recipe_id, spec, fragment=fragment,
                                 master_seed=spec.master_seed, lineage_id=lineage_id)

    captured: dict = {}
    original = S.intersect_with_source

    def spy(candidate, source, **kwargs):
        out, info = original(candidate, source, **kwargs)
        captured["candidate"] = candidate.copy()
        captured["accepted"] = out.copy()
        return out, info

    S.intersect_with_source = spy
    try:
        outcome = OPS.run_damage(clean, recipe, fragment=fragment)
    finally:
        S.intersect_with_source = original

    candidate = captured["candidate"]
    accepted = captured["accepted"]
    out: dict = {"store": str(store_root), "fragment_id": fragment.fragment_id,
                 "clean": _summary(clean, clean),
                 "marching_cubes_candidate": _summary(candidate, clean, seed=1),
                 "accepted_after_clip": _summary(accepted, clean, seed=2),
                 "operator_measurements": {k: float(v) for k, v in outcome.measurements.items()},
                 "variants": {}}

    # A. fill the holes of the accepted body
    filled = accepted.copy()
    filled.merge_vertices()
    before_faces = len(filled.faces)
    trimesh.repair.fill_holes(filled)
    trimesh.repair.fix_winding(filled)
    trimesh.repair.fix_inversion(filled)
    out["variants"]["accepted_fill_holes"] = {
        **_summary(filled, clean, seed=3),
        "holes_added_faces": int(len(filled.faces) - before_faces),
    }

    # B. a second intersection with the clean body (only-remove guard again)
    try:
        again, info = S.intersect_with_source(accepted, clean)
        out["variants"]["accepted_intersect_again"] = {
            **_summary(again, clean, seed=4), "clip_info": info}
    except Exception as exc:  # noqa: BLE001 - reported, never hidden
        out["variants"]["accepted_intersect_again"] = {"error": f"{type(exc).__name__}: {exc}"}

    # C. fill holes, then intersect again
    try:
        filled2 = accepted.copy()
        filled2.merge_vertices()
        trimesh.repair.fill_holes(filled2)
        trimesh.repair.fix_winding(filled2)
        trimesh.repair.fix_inversion(filled2)
        again2, info2 = S.intersect_with_source(filled2, clean)
        out["variants"]["fill_then_intersect"] = {
            **_summary(again2, clean, seed=5), "clip_info": info2}
    except Exception as exc:  # noqa: BLE001
        out["variants"]["fill_then_intersect"] = {"error": f"{type(exc).__name__}: {exc}"}

    # D. keep only positive-volume watertight bodies of the accepted mesh
    kept = [b for b in S.component_split(accepted) if float(abs(b.volume)) > 1e-9]
    vol_kept = float(sum(abs(b.volume) for b in kept))
    out["variants"]["positive_volume_bodies_only"] = {
        "bodies_kept": len(kept), "bodies_dropped": len(S.component_split(accepted)) - len(kept),
        "kept_volume_mm3": vol_kept,
        "dropped_volume_mm3": float(abs(accepted.volume)) - vol_kept,
        "body_watertight": [bool(b.is_watertight) for b in kept],
    }
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", required=True)
    parser.add_argument("--lineage", default="LIN0000_V02_M01_PAT02")
    parser.add_argument("--recipe", default="P03_depth_light")
    parser.add_argument("--config", default="configs/a12/sandbox.yaml")
    parser.add_argument("--out", default="data/a12/reports/a09_p03_geometry.json")
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
