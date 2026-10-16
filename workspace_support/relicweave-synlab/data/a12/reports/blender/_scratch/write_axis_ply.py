"""Scratch: write the asymmetric PLY the Blender axis probe imports (venv python)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import trimesh

HERE = Path(__file__).resolve().parent
SIZE = (100.0, 60.0, 40.0)


def main() -> int:
    box = trimesh.creation.box(extents=SIZE)
    box.apply_transform(trimesh.transformations.rotation_matrix(np.deg2rad(30.0), [0, 0, 1]))
    box.apply_transform(trimesh.transformations.rotation_matrix(np.deg2rad(15.0), [1, 0, 0]))
    verts = np.asarray(box.vertices, dtype=np.float64)
    faces = np.asarray(box.faces, dtype=np.int64)
    mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
    (HERE / "probe_ply_axis.ply").write_bytes(mesh.export(file_type="ply"))
    np.save(HERE / "probe_ply_axis_verts.npy", verts)
    (HERE / "probe_ply_axis_meta.json").write_text(
        json.dumps({"size_mm": list(SIZE), "n_faces": int(faces.shape[0]),
                    "n_vertices": int(verts.shape[0])}), encoding="utf-8")
    print("wrote", HERE / "probe_ply_axis.ply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
