"""Debug: how many cells of a partition are valid manifold solids (with / without roughness)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import trimesh

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    from manifold3d import Manifold, Mesh
    from synlab.mothers.api import create_mother, default_params, ensure_registered
    from synlab.mothers.measure import thickness_samples
    from synlab.fracture.physics import load_physics_config
    from synlab.fracture import voronoi_event as VE
    from synlab.fracture.voronoi_frag import build_partition, polyhedron_volume

    ensure_registered()
    cfg = load_physics_config()
    vessel = sys.argv[1] if len(sys.argv) > 1 else "V13"
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    mother = create_mother(vessel, "M01", default_params(vessel),
                           np.random.default_rng(20261002))
    mesh = mother.mesh
    th = thickness_samples(mesh, np.arange(len(mesh.faces)), max_probes=200)
    part, _rep = build_partition(mesh, count, rng=np.random.default_rng(2024),
                                 seed_cfg=cfg.seeds)
    wall = float(th["min_mm"])
    half = float(np.clip(2.5 * wall, 0.25, 3.0))
    fields: dict = {}
    for cell in part.cells:
        for facet_index, neighbour in enumerate(cell.facet_neighbours):
            if neighbour < 0:
                continue
            key = (min(cell.index, neighbour), max(cell.index, neighbour))
            if key in fields:
                continue
            position = VE._position_of(part, neighbour)
            pair = VE._matching_facets(cell, facet_index, part.cells[position])
            if pair is None:
                continue
            field_obj = VE.facet_roughness_field(cell, part.cells[position], pair[0], config=cfg,
                                                 wall_mm=wall, grain_mm=2.6)
            field_obj.wall_mm = wall
            field_obj.mask_half_width_mm = half
            fields[key] = field_obj

    def status(cell_mesh):
        return Manifold(Mesh(np.asarray(cell_mesh.vertices, dtype=np.float32),
                             np.asarray(cell_mesh.faces, dtype=np.uint32))).status()

    for label, use_fields in (("plain", False), ("rough", True)):
        print(f"--- {label} (wall={wall:.2f} half={half:.2f} amp="
              f"{next(iter(fields.values())).amplitude_mm if fields else 0:.3f})")
        for index, cell in enumerate(part.cells):
            selected = {}
            if use_fields:
                for facet_index, neighbour in enumerate(cell.facet_neighbours):
                    if neighbour < 0:
                        continue
                    key = (min(cell.index, neighbour), max(cell.index, neighbour))
                    if key in fields:
                        selected[facet_index] = fields[key]
            cell_mesh = VE._displaced_cell_mesh(cell, selected)
            print(f"   cell {index}: tris={len(cell_mesh.faces)} verts={len(cell_mesh.vertices)} "
                  f"wt={cell_mesh.is_watertight} vol={cell_mesh.volume:.1f} "
                  f"poly={polyhedron_volume(cell.faces):.1f} status={status(cell_mesh)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
