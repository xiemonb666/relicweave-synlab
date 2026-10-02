#!/usr/bin/env python
"""Can gmsh 4.15.2 give a *conformal* tetrahedral mesh of a real mother with internal partition
surfaces, in an acceptable time?

Plan G10.4 asks the ``warped_partition`` backend for "conformal mesh + shared warp".  Before wiring
any of that into the pipeline this probe measures the cost on the real geometry:

* the mother's own closed surface is loaded into gmsh (as STL, via the OCC-free native kernel), so
  the domain is the real body;
* the internal partition facets of an N-cell Voronoi partition are embedded as mesh constraints
  (their corner points are created as geometry points and embedded in the volume);
* the volume is meshed and the report records node/tet/``2-D`` element counts, wall time, and the
  count of volume-mesh faces that lie **on** a partition plane (``internal_partition_faces``) --
  the measurement that decides whether the internal surfaces really are respected.

No assertions: it writes ``data/a12_reports/_fprec_gmsh_probe.json`` and prints it.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
TESTS_A12 = Path(__file__).resolve().parents[2]
for _path in (str(REPO_ROOT), str(TESTS_A12)):
    if _path not in sys.path:
        sys.path.insert(0, _path)


def mother_of(vessel: str, material: str):
    from synlab.mothers.api import create_mother, default_params, ensure_registered

    ensure_registered()
    mother = create_mother(vessel, material, default_params(vessel),
                           np.random.default_rng(20261002))
    mother.vessel_id = vessel
    mother.material_id = material
    return mother


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vessel", default="V13")
    ap.add_argument("--material", default="M01")
    ap.add_argument("--cells", type=int, default=4)
    ap.add_argument("--mesh-mm", type=float, default=6.0)
    ap.add_argument("--embed", action="store_true", help="embed the facet corner points")
    ap.add_argument("--json", default="data/a12_reports/_fprec_gmsh_probe.json")
    args = ap.parse_args()

    import gmsh

    import trimesh

    from synlab.fracture.physics import load_physics_config
    from synlab.fracture.voronoi_frag import build_partition

    record: dict[str, object] = {
        "gmsh_version": str(getattr(gmsh, "__version__", "?")),
        "vessel": args.vessel, "material": args.material, "cells": args.cells,
        "mesh_mm": args.mesh_mm, "embed": bool(args.embed),
    }
    mother = mother_of(args.vessel, args.material)
    mesh = trimesh.Trimesh(vertices=np.asarray(mother.mesh.vertices, dtype=np.float64),
                           faces=np.asarray(mother.mesh.faces, dtype=np.int64), process=False)
    record["mother_faces"] = int(len(mesh.faces))
    record["mother_volume_mm3"] = float(abs(mesh.volume))
    record["mother_watertight"] = bool(mesh.is_watertight)

    config = load_physics_config()
    partition, seed_report = build_partition(mesh, args.cells,
                                             rng=np.random.default_rng(20261002),
                                             seed_cfg=config.seeds)
    record["partition_cells"] = int(len(partition.cells))
    record["seed_report_cells"] = int(seed_report.get("cells", 0))

    facets: dict[tuple[int, int], np.ndarray] = {}
    for cell in partition.cells:
        for facet_index, neighbour in enumerate(cell.facet_neighbours):
            if neighbour < 0:
                continue
            key = (min(int(cell.index), int(neighbour)), max(int(cell.index), int(neighbour)))
            if key not in facets:
                facets[key] = np.asarray(cell.faces[facet_index].vertices, dtype=np.float64)
    record["internal_facets"] = len(facets)
    corners = np.vstack(list(facets.values())) if facets else np.zeros((0, 3))
    record["facet_corners"] = int(corners.shape[0])
    record["facet_corner_unique"] = int(np.unique(np.round(corners, 9), axis=0).shape[0])

    stl_path = Path("data/a12_reports/_fprec_gmsh_mother.stl")
    stl_path.parent.mkdir(parents=True, exist_ok=True)
    mesh.export(stl_path)

    started = time.time()
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("Mesh.MeshSizeMax", float(args.mesh_mm))
        gmsh.option.setNumber("Mesh.MeshSizeMin", float(args.mesh_mm) * 0.2)
        gmsh.model.add("mother")
        gmsh.merge(str(stl_path))
        gmsh.model.geo.synchronize()
        surfaces = [t for (_dim, t) in gmsh.model.getEntities(2)]
        volumes = [t for (_dim, t) in gmsh.model.getEntities(3)]
        record["loaded_surfaces"] = len(surfaces)
        record["loaded_volumes"] = len(volumes)
        if not volumes:
            # The native kernel keeps an imported STL as a set of discrete triangles and creates no
            # topology, so there is no volume to fill.  Try the OpenCASCADE route: import the same
            # file as a shape, heal the seams and ask for the closed solid.
            record["native_import_volumes"] = 0
            step = time.time()
            try:
                gmsh.model.occ.importShapes(str(stl_path))
                gmsh.model.occ.synchronize()
                gmsh.model.occ.removeAllDuplicates()
                gmsh.model.occ.healShapes()
                gmsh.model.occ.synchronize()
                surfaces = [t for (_dim, t) in gmsh.model.getEntities(2)]
                volumes = [t for (_dim, t) in gmsh.model.getEntities(3)]
                record["occ_import_s"] = round(time.time() - step, 3)
                record["occ_surfaces"] = len(surfaces)
                record["occ_volumes"] = len(volumes)
            except Exception as occ_exc:  # noqa: BLE001
                record["occ_error"] = f"{type(occ_exc).__name__}: {occ_exc}"
        if not volumes:
            record["note"] = ("the loaded mother surface does not become a closed volume entity "
                              "for gmsh (neither the native STL merge nor the OCC import + heal "
                              "produced one), so a volume mesh cannot be generated from it as-is")
            record["mesh_time_s"] = round(time.time() - started, 3)
            return _write(record, args.json)
        gmsh.model.addPhysicalGroup(2, surfaces, tag=1)
        gmsh.model.addPhysicalGroup(3, volumes, tag=2)
        embedded = 0
        if args.embed and corners.size:
            surface_tag = surfaces[0]
            for point in np.unique(np.round(corners, 9), axis=0):
                tag = gmsh.model.geo.addPoint(float(point[0]), float(point[1]), float(point[2]),
                                              float(args.mesh_mm) * 0.2)
                gmsh.model.geo.synchronize()
                gmsh.model.mesh.embed(0, [tag], 3, volumes[0])
                embedded += 1
        record["embedded_points"] = embedded
        record["premesh_s"] = round(time.time() - started, 3)
        gmsh.model.mesh.generate(3)
        record["mesh_time_s"] = round(time.time() - started, 3)
        node_tags, coords, _ = gmsh.model.mesh.getNodes()
        coords = np.asarray(coords, dtype=np.float64).reshape(-1, 3)
        record["nodes"] = int(len(node_tags))
        tets = 0
        for _etype, tags in zip(*gmsh.model.mesh.getElements(3)[0:2]):
            tets += int(len(tags))
        record["tets"] = tets
        # how many volume-mesh faces lie on a partition plane?
        face_count = 0
        on_plane = 0
        planes = []
        for cell in partition.cells:
            for facet_index, neighbour in enumerate(cell.facet_neighbours):
                if neighbour < 0:
                    continue
                face = cell.faces[facet_index]
                planes.append((np.asarray(face.plane.normal, dtype=np.float64),
                               float(face.plane.offset)))
        normals = np.asarray([p[0] for p in planes], dtype=np.float64).reshape(-1, 3)
        offsets = np.asarray([p[1] for p in planes], dtype=np.float64).reshape(-1)
        etypes2, etags2, enodes2 = gmsh.model.mesh.getElements(2)
        for enodes in enodes2:
            arr = np.asarray(enodes, dtype=np.int64).reshape(-1, 3)
            centroids = coords[arr - 1].mean(axis=1)
            face_count += int(arr.shape[0])
            dist = np.abs(centroids @ normals.T - offsets[None, :])
            on_plane += int(np.sum(np.min(dist, axis=1) <= 1e-6))
        record["surface_faces"] = face_count
        record["surface_faces_on_partition_plane"] = on_plane
        record["surface_faces_on_partition_ratio"] = (
            float(on_plane) / float(face_count) if face_count else None)
    except Exception as exc:  # noqa: BLE001 - the probe reports, it never repairs
        record["error"] = f"{type(exc).__name__}: {exc}"
        record["mesh_time_s"] = round(time.time() - started, 3)
    finally:
        try:
            gmsh.finalize()
        except Exception:  # noqa: BLE001
            pass
    return _write(record, args.json)


def _write(record: dict, path: str) -> int:
    text = json.dumps(record, indent=2, ensure_ascii=False)
    Path(path).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
