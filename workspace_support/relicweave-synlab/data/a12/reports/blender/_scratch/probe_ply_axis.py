"""Scratch: measure what Blender's PLY importer does to the object frame.

The PLY itself is written by the *venv* python (see ``write_axis_ply.py``): Blender's own
interpreter has numpy but no trimesh.  Run with the portable Blender binary::

    & $env:BLENDER_BIN --background --factory-startup --python-exit-code 1 \
        --python data/a12/reports/blender/_scratch/probe_ply_axis.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import bpy  # type: ignore  # noqa: E402
import numpy as np  # type: ignore  # noqa: E402

HERE = Path(os.path.abspath(__file__)).parent
OUT = HERE / "probe_ply_axis.json"
PLY = HERE / "probe_ply_axis.ply"
verts = np.load(HERE / "probe_ply_axis_verts.npy").astype(np.float64)
SIZE = json.loads((HERE / "probe_ply_axis_meta.json").read_text())["size_mm"]


def measure(forward: str, up: str) -> dict:
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    props = bpy.ops.wm.ply_import.get_rna_type().properties.keys()
    kwargs = {"filepath": str(PLY)}
    if "forward_axis" in props:
        kwargs["forward_axis"] = forward
    if "up_axis" in props:
        kwargs["up_axis"] = up
    bpy.ops.wm.ply_import(**kwargs)
    obj = bpy.context.selected_objects[0] if bpy.context.selected_objects else \
        bpy.data.objects[[k for k in bpy.data.objects.keys()][-1]]
    mesh = obj.data
    co = np.empty(len(mesh.vertices) * 3, dtype=np.float64)
    mesh.vertices.foreach_get("co", co)
    data_verts = co.reshape(-1, 3)
    M = np.array(obj.matrix_world)
    world_verts = data_verts @ M[:3, :3].T + M[:3, 3][None, :]
    # match vertices by brute force (import may reorder)
    def match_err(candidate: np.ndarray) -> float:
        dist = np.linalg.norm(candidate[:, None, :] - verts[None, :, :], axis=2)
        return float(np.abs(dist.min(axis=1)).max())

    return {
        "forward_axis": forward, "up_axis": up,
        "matrix_world": M.round(6).tolist(),
        "n_vertices": int(data_verts.shape[0]), "n_faces": int(len(mesh.polygons)),
        "max_error_data_space_mm": match_err(data_verts),
        "max_error_world_space_mm": match_err(world_verts),
        "bbox_data_mm": (data_verts.max(axis=0) - data_verts.min(axis=0)).round(4).tolist(),
        "bbox_world_mm": (world_verts.max(axis=0) - world_verts.min(axis=0)).round(4).tolist(),
        "bbox_expected_mm": list(SIZE),
    }


def main() -> int:
    report = {"cases": []}
    for forward, up in (("NEGATIVE_Y", "Z"), ("Y", "Z"), ("NEGATIVE_Z", "Y"),
                        ("X", "Z"), ("NEGATIVE_X", "Z")):
        try:
            report["cases"].append(measure(forward, up))
        except Exception as exc:  # noqa: BLE001
            report["cases"].append({"forward_axis": forward, "up_axis": up,
                                    "error": f"{type(exc).__name__}: {exc}"})
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("RWS_PLYAXIS " + json.dumps(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
