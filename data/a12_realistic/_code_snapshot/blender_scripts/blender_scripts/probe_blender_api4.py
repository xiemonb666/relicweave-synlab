"""Fourth probe: one File Output node per pass -> one single-layer EXR per pass.

Run::

    & $env:BLENDER_BIN --background --python blender_scripts/probe_blender_api4.py
"""

from __future__ import annotations

import json
import math
import os
import sys
import tempfile
import time

import bpy
import numpy as np


def build_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    bpy.ops.mesh.primitive_cube_add(size=100.0, location=(0.0, 0.0, 0.0))
    bpy.context.active_object.name = "target_cube"
    bpy.ops.mesh.primitive_plane_add(size=2000.0, location=(0.0, 0.0, 400.0))
    bpy.context.active_object.name = "backdrop"
    cam_data = bpy.data.cameras.new("cam")
    cam_data.sensor_fit = "HORIZONTAL"
    cam_data.sensor_width = 36.0
    cam_data.lens = 36.0
    cam = bpy.data.objects.new("cam", cam_data)
    scene.collection.objects.link(cam)
    cam.location = (0.0, 0.0, -400.0)
    cam.rotation_euler = (math.pi / 2.0, 0.0, 0.0)
    scene.camera = cam
    scene.render.resolution_x = 64
    scene.render.resolution_y = 48
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "OPEN_EXR"
    scene.render.image_settings.color_depth = "32"
    scene.render.image_settings.color_mode = "RGB"
    scene.view_settings.view_transform = "Standard"
    return scene, cam


def load_exr(path: str):
    img = bpy.data.images.load(path)
    img.colorspace_settings.name = "Non-Color"
    n = len(img.pixels)
    info = {"size": list(img.size), "channels": int(img.channels), "n_pixels": n,
            "is_float": bool(img.is_float)}
    if n == 0:
        bpy.data.images.remove(img)
        return info, None
    buf = np.empty(n, dtype=np.float32)
    img.pixels.foreach_get(buf)
    arr = buf.reshape(img.size[1], img.size[0], int(img.channels))
    bpy.data.images.remove(img)
    return info, arr


def main() -> int:
    out: dict = {}
    tmp = tempfile.mkdtemp(prefix="rws_probe4_")
    out["tmp"] = tmp
    scene, cam = build_scene()
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 8
    vl = bpy.context.view_layer
    vl.use_pass_z = True
    vl.use_pass_position = True
    vl.use_pass_ambient_occlusion = True
    vl.use_pass_object_index = True
    vl.use_pass_material_index = True

    aov = vl.aovs.add()
    aov.name = "rws_face_id"
    aov.type = "VALUE"
    out["aov"] = {"name": aov.name, "type": aov.type, "attrs":
                  [a for a in dir(aov) if not a.startswith("_")],
                  "type_enum": [i.identifier for i in
                                type(aov).bl_rna.properties["type"].enum_items]}

    tree = bpy.data.node_groups.new(name="rws_probe4", type="CompositorNodeTree")
    rl = tree.nodes.new("CompositorNodeRLayers")
    out["rl_sockets"] = sorted(s.name for s in rl.outputs)

    wanted = ["Image", "Depth", "Position", "Ambient Occlusion", "Alpha"]
    for want in wanted:
        src = next((s for s in rl.outputs if s.name == want), None)
        if src is None:
            continue
        fo = tree.nodes.new("CompositorNodeOutputFile")
        fo.directory = tmp
        fo.file_name = "pass_" + want.replace(" ", "_").lower()
        try:
            item = fo.file_output_items.new("FLOAT", "value")
            out.setdefault("item_attrs", [a for a in dir(item) if not a.startswith("_")])
        except Exception as exc:  # noqa: BLE001
            out.setdefault("item_errors", {})[want] = f"{type(exc).__name__}: {exc}"
            continue
        dst = next((s for s in fo.inputs if s.name == "value"), None)
        if dst is None:
            out.setdefault("dst_errors", {})[want] = sorted(s.name for s in fo.inputs)
            continue
        tree.links.new(src, dst)
        out.setdefault("nodes", {})[want] = {"file_name": fo.file_name,
                                             "format": str(fo.format.file_format)}
    scene.compositing_node_group = tree

    t0 = time.time()
    bpy.ops.render.render(write_still=False)
    out["render_seconds"] = time.time() - t0
    time.sleep(0.4)
    out["files"] = sorted(os.listdir(tmp))

    for fn in out["files"]:
        path = os.path.join(tmp, fn)
        try:
            info, arr = load_exr(path)
        except Exception as exc:  # noqa: BLE001
            out.setdefault("read_errors", {})[fn] = f"{type(exc).__name__}: {exc}"
            continue
        rec = {"info": info}
        if arr is not None:
            rec.update({"min": float(arr.min()), "max": float(arr.max()),
                        "mean": float(arr.mean()),
                        "center": arr[arr.shape[0] // 2, arr.shape[1] // 2].tolist(),
                        "row_top_mean": arr[-1].reshape(-1, arr.shape[2]).mean(axis=0).tolist(),
                        "row_bottom_mean": arr[0].reshape(-1, arr.shape[2]).mean(axis=0).tolist()})
            flat = arr.reshape(-1, arr.shape[2])
            with np.errstate(invalid="ignore"):
                frac = np.abs(flat - np.rint(np.nan_to_num(flat)))
            rec["non_integral_fraction"] = float(np.mean(frac.max(axis=1) > 1e-4))
        out.setdefault("passes", {})[fn] = rec

    print("PROBE4_JSON_BEGIN")
    print(json.dumps(out, indent=2, default=str))
    print("PROBE4_JSON_END")
    return 0


if __name__ == "__main__":
    sys.exit(main())
