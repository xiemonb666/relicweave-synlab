"""Sweep the facet-refinement scheme: conforming? rough? fast? A06 gap?"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import trimesh

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    from manifold3d import Manifold, Mesh
    from synlab.mothers.api import create_mother, default_params, ensure_registered
    from synlab.mothers.measure import thickness_samples
    from synlab.materials.api import build_material_profile, default_material_params
    from synlab.fracture.physics import load_physics_config
    from synlab.fracture import voronoi_event as VE
    from synlab.fracture.voronoi_frag import build_partition
    from synlab.fracture.booleans import tag_source, boolean_intersection

    ensure_registered()
    cfg = load_physics_config()
    vessel = sys.argv[1] if len(sys.argv) > 1 else "V13"
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    mother = create_mother(vessel, "M01", default_params(vessel),
                           np.random.default_rng(20261002))
    mesh = mother.mesh
    thickness = thickness_samples(mesh, np.arange(len(mesh.faces)), max_probes=200)
    profile = build_material_profile("M01", default_material_params("M01"),
                                     np.random.default_rng(11))
    grain = float((profile.get("stats") or {}).get("grain_scale_mm", 0.05))
    wall = float(thickness["median_mm"])
    part, _rep = build_partition(mesh, count, rng=np.random.default_rng(2024),
                                 seed_cfg=cfg.seeds)
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
                                                 wall_mm=wall, grain_mm=grain)
            field_obj.wall_mm = wall
            field_obj.mask_half_width_mm = float(np.clip(2.5 * wall, 0.25, 3.0))
            fields[key] = field_obj
    print(f"{vessel} wall={wall:.3f} grain={grain:.3f} "
          f"amp={next(iter(fields.values())).amplitude_mm:.3f} "
          f"lambda={next(iter(fields.values())).wavelength_min_mm:.2f}", flush=True)
    report = []
    for refine in (0.0, 4.0, 2.0, 1.5, 1.0, 0.75, 0.5):
        t0 = time.perf_counter()
        conforming = 0
        roughness = []
        piece_faces = 0
        piece_vol = 0.0
        for index, cell in enumerate(part.cells):
            selected = {}
            for facet_index, neighbour in enumerate(cell.facet_neighbours):
                if neighbour < 0:
                    continue
                key = (min(cell.index, neighbour), max(cell.index, neighbour))
                if key in fields:
                    selected[facet_index] = fields[key]
            cell_mesh = VE._displaced_cell_mesh(cell, selected,
                                                refinement="fan" if refine <= 0 else "lattice",
                                                refine_mm=refine)
            conforming += int(bool(cell_mesh.metadata.get("conforming_refinement", False)))
            if selected:
                field_obj = next(iter(selected.values()))
                pts = np.asarray(cell_mesh.vertices, dtype=np.float64)
                disp = VE.combined_displacement(list(selected.values()), pts)
                roughness.append(float(np.abs(disp).max()))
            source = tag_source(
                trimesh.Trimesh(vertices=np.asarray(mesh.vertices),
                                faces=np.asarray(mesh.faces), process=False), 1.0, "mother")
            cutter = tag_source(
                trimesh.Trimesh(vertices=cell_mesh.vertices, faces=cell_mesh.faces,
                                process=False), 1000.0 + index, "cell")
            result = boolean_intersection([source, cutter], label="p")
            piece_faces += result.n_faces
            piece_vol += float(abs(result.mesh.volume))
        elapsed = time.perf_counter() - t0
        entry = {
            "refine_mm": refine, "cells": len(part.cells),
            "conforming_cells": conforming,
            "conforming": bool(conforming == len(part.cells)),
            "max_displacement_mm": max(roughness) if roughness else 0.0,
            "piece_faces": piece_faces,
            "piece_volume_mm3": piece_vol,
            "volume_rel": abs(piece_vol - abs(mesh.volume)) / abs(mesh.volume),
            "seconds": round(elapsed, 2),
        }
        report.append(entry)
        print(json.dumps(entry), flush=True)
    (ROOT / "_frac_probe_refine.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
