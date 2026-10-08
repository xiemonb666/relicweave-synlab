from __future__ import annotations

import hashlib
import json
import runpy
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from synlab.degrade.physical_narrowband import run_narrowband_damage
from synlab.physical.api import _boundary_loops, _geometry_hash, apply_damage, audit_physical


ROOT = Path.cwd()
OUT = ROOT / "tmp/review_20261003/implementation/physical_qa_repair"
OUT.mkdir(parents=True, exist_ok=True)
helpers = runpy.run_path(str(ROOT / "tests/a12/operators/test_postassembly_qa_20261003.py"))
make_source = helpers["_closed_box_source"]
make_recipe = helpers["_recipe"]
mesh, fragment, source, clean_truth = make_source()
recipe = make_recipe("P02", 4, fragment, source)
result = apply_damage(clean_truth, fragment, recipe, rng=None)
audit = audit_physical(result, mesh)
direct_result = run_narrowband_damage(mesh, recipe, fragment=fragment)
component_mesh = result.components[0].mesh
loops, boundary = _boundary_loops(component_mesh)
loop = loops[0] if loops else []
loop_points = np.asarray(component_mesh.vertices, dtype=np.float64)[np.asarray(loop, dtype=np.int64)] \
    if loop else np.empty((0, 3), dtype=np.float64)
diagonal = (float(np.linalg.norm(loop_points.max(axis=0) - loop_points.min(axis=0)))
            if len(loop_points) else None)


def projection(points: np.ndarray, axes: tuple[int, int], box: tuple[int, int, int, int],
               bounds: np.ndarray) -> list[tuple[int, int]]:
    x0, y0, width, height = box
    lo = bounds[0, list(axes)]
    span = np.maximum(bounds[1, list(axes)] - lo, 1e-9)
    return [(int(x0 + 12 + (point[axes[0]] - lo[0]) * (width - 24) / span[0]),
             int(y0 + height - 14 - (point[axes[1]] - lo[1]) * (height - 38) / span[1]))
            for point in points]


image = Image.new("RGB", (1180, 570), (250, 249, 246))
draw = ImageDraw.Draw(image)
draw.text((24, 14), "P02 L4 production result | postassembly QA FAIL", fill=(25, 25, 25))
draw.text((24, 38), "Synthetic 8 x 8 x 2.4 mm box; actual assembled mesh", fill=(70, 70, 70))
left = (20, 72, 555, 455)
right = (600, 72, 555, 455)
draw.rectangle((left[0], left[1], left[0] + left[2], left[1] + left[3]),
               outline=(170, 170, 170), width=1)
draw.rectangle((right[0], right[1], right[0] + right[2], right[1] + right[3]),
               outline=(170, 170, 170), width=1)
draw.text((left[0] + 12, left[1] + 8), "Y=0 cross-section (X-Z)", fill=(30, 30, 30))
draw.text((right[0] + 12, right[1] + 8), "Top projection (X-Y), boundary loop in red",
          fill=(30, 30, 30))

# The left panel uses the actual mesh section polylines returned by Trimesh.
section = component_mesh.section(plane_origin=np.array([0.0, 0.0, 0.0]),
                                plane_normal=np.array([0.0, 1.0, 0.0]))
section_points = [np.asarray(path, dtype=np.float64)[:, [0, 2]] for path in section.discrete] \
    if section is not None else []
section_all = np.vstack(section_points) if section_points else np.asarray(component_mesh.vertices)[:, [0, 2]]
section_bounds = np.asarray([section_all.min(axis=0), section_all.max(axis=0)])
section_draw_bounds = np.zeros((2, 3), dtype=np.float64)
section_draw_bounds[:, [0, 2]] = section_bounds
for path in section_points:
    coords3 = np.column_stack([path[:, 0], np.zeros(len(path)), path[:, 1]])
    coords = projection(coords3, (0, 2), left, section_draw_bounds)
    if len(coords) >= 2:
        draw.line(coords, fill=(35, 72, 115), width=3)
# Draw the delivered mesh's actual unique edges and the retained boundary loop from mesh indices.
all_vertices = np.asarray(component_mesh.vertices, dtype=np.float64)
mesh_bounds = np.asarray([all_vertices.min(axis=0), all_vertices.max(axis=0)])
for edge in np.asarray(component_mesh.edges_unique, dtype=np.int64):
    coords = projection(all_vertices[edge], (0, 1), right, mesh_bounds)
    draw.line(coords, fill=(120, 127, 132), width=1)
if len(loop_points):
    loop_xy = projection(loop_points, (0, 1), right, mesh_bounds)
    draw.line(loop_xy + [loop_xy[0]], fill=(210, 35, 35), width=5)
    for index, (x, y) in zip(loop, loop_xy):
        draw.ellipse((x - 6, y - 6, x + 6, y + 6), fill=(210, 35, 35), outline="white", width=1)
        draw.text((x + 7, y - 12), str(index), fill=(160, 20, 20))
draw.text((right[0] + 14, right[1] + right[3] - 44),
          f"{boundary.get('boundary_edges', 0)} boundary edges; loop diagonal {diagonal:.4f} mm",
          fill=(155, 25, 25))
draw.text((24, 545), "The loop is left open: it exceeds the declared 0.001 mm pinhole scale.",
          fill=(70, 45, 45))
png_path = OUT / "p02_postassembly_actual_mesh_and_boundary_loop.png"
image.save(png_path)

# Positive controls use existing P-axis identity and appearance-only routes on the same closed box.
controls = {}
for axis_id, level in (("P01", 0), ("P02", 0), ("P05", 1), ("P06", 1)):
    control_recipe = make_recipe(axis_id, level, fragment, source)
    control = apply_damage(clean_truth, fragment, control_recipe, rng=None)
    control_audit = audit_physical(control, mesh)
    controls[f"{axis_id}:L{level}"] = {
        "physical_result_qa_status": control.qa.get("status"),
        "realized": control.qa.get("realized"),
        "postassembly_status": (control.qa.get("postassembly") or {}).get("status"),
        "audit_status": control_audit.get("status"),
        "failure_codes": control_audit.get("failure_codes"),
    }

payload = {
    "route": "synlab.physical.api.apply_damage",
    "fixture": {"kind": "synthetic_small_closed_box", "vertices": len(mesh.vertices),
                "faces": len(mesh.faces), "source_watertight": bool(mesh.is_watertight),
                "source_volume_mm3": float(abs(mesh.volume))},
    "result": {
        "physical_result_qa": result.qa,
        "physical_audit": audit,
        "component": {"component_id": result.components[0].component_id,
                      "watertight": bool(component_mesh.is_watertight),
                      "volume_mm3": float(abs(component_mesh.volume)),
                      "vertices": len(component_mesh.vertices), "faces": len(component_mesh.faces)},
        "raw_boundary": {"boundary_edges": boundary.get("boundary_edges"),
                         "boundary_vertices": boundary.get("boundary_vertices"),
                         "loops": len(loops), "loop_vertices": loop,
                         "loop_diagonal_mm": diagonal},
        "source_geometry_hash": _geometry_hash(mesh),
        "result_geometry_hash": _geometry_hash(component_mesh),
    },
    "direct_narrowband_route": {
        "physical_result_qa": direct_result.qa,
        "component_watertight": bool(direct_result.components[0].mesh.is_watertight),
        "component_volume_mm3": float(abs(direct_result.components[0].mesh.volume)),
        "component_geometry_hash": _geometry_hash(direct_result.components[0].mesh),
    },
    "positive_controls": controls,
    "visual": {"file": png_path.name, "sha256": hashlib.sha256(png_path.read_bytes()).hexdigest(),
               "description": "Actual assembled-mesh cross section and top projection with the open boundary loop marked."},
}
json_path = OUT / "p02_postassembly_qa_20261003.json"
json_path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
                     encoding="utf-8")
print(json.dumps({"json": str(json_path), "png": str(png_path),
                  "qa_status": result.qa.get("status"), "audit_status": audit.get("status"),
                  "failure_codes": audit.get("failure_codes"),
                  "direct_route_qa_status": direct_result.qa.get("status"),
                  "direct_route_failure_codes": direct_result.qa.get("failure_codes"),
                  "boundary_edges": boundary.get("boundary_edges"),
                  "loop_diagonal_mm": diagonal, "positive_controls": controls},
                 indent=2, sort_keys=True))
