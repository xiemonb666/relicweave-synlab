"""Locate the open edges of the warped cell solid: which facet planes do their endpoints lie on?"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
TESTS_A12 = Path(__file__).resolve().parents[2]
for _path in (str(REPO_ROOT), str(TESTS_A12)):
    if _path not in sys.path:
        sys.path.insert(0, _path)


def main() -> int:
    import trimesh

    from synlab.fracture import warped
    from synlab.fracture.physics import load_physics_config
    from synlab.fracture.voronoi_frag import build_partition
    from synlab.mothers.api import create_mother, default_params, ensure_registered

    ensure_registered()
    mother = create_mother("V13", "M01", default_params("V13"), np.random.default_rng(20261002))
    mesh = trimesh.Trimesh(vertices=np.asarray(mother.mesh.vertices, dtype=np.float64),
                           faces=np.asarray(mother.mesh.faces, dtype=np.int64), process=False)
    config = load_physics_config()
    partition, _seed = build_partition(mesh, 3, rng=np.random.default_rng(20261002),
                                       seed_cfg=config.seeds)
    warp = warped.make_warp_field(wall_mm=11.657917121080864, grain_mm=4.0)
    facets, report = warped._mesh_all_facets(partition, warp)
    print("mesh report:", {k: v for k, v in report.items() if k != "mesh_size_ladder"})
    cell = partition.cells[0]
    solid = warped.warped_cell_mesh(cell, facets, warp)
    verts = np.asarray(solid.vertices, dtype=np.float64)
    faces = np.asarray(solid.faces, dtype=np.int64)
    counter: dict[tuple[int, int], int] = {}
    for tri in faces:
        for k in range(3):
            a, b = int(tri[k]), int(tri[(k + 1) % 3])
            key = (a, b) if a < b else (b, a)
            counter[key] = counter.get(key, 0) + 1
    bad = [(e, u) for e, u in counter.items() if u != 2]
    print(f"faces={faces.shape[0]} verts={verts.shape[0]} bad={len(bad)}")
    lengths = np.asarray([np.linalg.norm(verts[a] - verts[b]) for (a, b), _u in bad])
    order = np.argsort(-lengths)
    planes = []
    for facet_index, neighbour in enumerate(cell.facet_neighbours):
        if neighbour < 0:
            continue
        face = cell.faces[facet_index]
        key = (min(int(cell.index), int(neighbour)), max(int(cell.index), int(neighbour)))
        planes.append((key, np.asarray(face.plane.normal, dtype=np.float64),
                       float(face.plane.offset)))
    for pick in order[:6]:
        (a, b), use = bad[int(pick)]
        print(f"\nbad edge use={use} len={float(lengths[int(pick)]):.6f}")
        for tag, index in (("a", a), ("b", b)):
            point = verts[index]
            line = [f"  {tag} v{index} ({point[0]:.4f},{point[1]:.4f},{point[2]:.4f})"]
            for key, normal, offset in planes:
                line.append(f"dist_to_facet{key}={abs(float(point @ normal) - offset):.3e}")
            print(" ".join(line))
    # per-facet-plane classification of the open edges
    tally: dict[str, int] = {}
    for (a, b), use in bad:
        if use == 2:
            continue
        mid = 0.5 * (verts[a] + verts[b])
        hit = "none"
        for key, normal, offset in planes:
            if abs(float(mid @ normal) - offset) <= 1.0e-6:
                hit = str(key)
        tally[hit] = tally.get(hit, 0) + 1
    print("\nopen edges by facet plane:", tally)
    # how many open edges are *short* (interior of a facet) vs *long*
    print("open edge length buckets:",
          {"<1mm": int(np.sum(lengths < 1.0)), "1-10mm": int(np.sum((lengths >= 1) & (lengths < 10))),
           ">=10mm": int(np.sum(lengths >= 10))})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
