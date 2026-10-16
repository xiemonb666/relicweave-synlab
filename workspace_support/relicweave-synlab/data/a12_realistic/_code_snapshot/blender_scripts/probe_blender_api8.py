"""Eighth probe: Material Index pass, Shader AOV, and AA behaviour of the geometry passes.

Run::

    & $env:BLENDER_BIN --background --python blender_scripts/probe_blender_api8.py
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

TMP = tempfile.mkdtemp(prefix="rws_probe8_")


def build():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    bpy.ops.mesh.primitive_cube_add(size=100.0)
    cube = bpy.context.active_object
    # 3 materials, material_index = face % 3
    for i in range(3):
        mat = bpy.data.materials.new(f"m{i}")
        mat.use_nodes = True
        nt = mat.node_tree
        for node in list(nt.nodes):
            nt.nodes.remove(node)
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        emit = nt.nodes.new("ShaderNodeEmission")
        emit.inputs["Color"].default_value = (0.2 + 0.1 * i, 0.2, 0.2, 1.0)
        nt.links.new(emit.outputs["Emission"], out.inputs["Surface"])
        aov = nt.nodes.new("ShaderNodeOutputAOV")
        aov.aov_name = "rws_const"
        aov.inputs["Value"].default_value = 0.25
        aov2 = nt.nodes.new("ShaderNodeOutputAOV")
        aov2.aov_name = "rws_attr"
        attr = nt.nodes.new("ShaderNodeAttribute")
        attr.attribute_type = "GEOMETRY"
        attr.attribute_name = "rws_face_label"
        nt.links.new(attr.outputs["Fac"], aov2.inputs["Value"])
        cube.data.materials.append(mat)
    for poly in cube.data.polygons:
        poly.material_index = int(poly.index) % 3
    attr = cube.data.attributes.new(name="rws_face_label", type="FLOAT", domain="FACE")
    attr.data.foreach_set("value", np.arange(len(cube.data.polygons), dtype=np.float32))
    cube.data.update()

    cam_data = bpy.data.cameras.new("c")
    cam_data.sensor_width = 36.0
    cam_data.lens = 36.0
    cam = bpy.data.objects.new("c", cam_data)
    scene.collection.objects.link(cam)
    cam.location = (0.0, 0.0, -400.0)
    # camera local -Z (view) must be world +Z, local +Y (up) world +Y
    # -> R = diag(-1, 1, -1) = Ry(180 deg)
    cam.rotation_euler = (0.0, math.pi, 0.0)
    scene.camera = cam
    scene.render.resolution_x = 64
    scene.render.resolution_y = 48
    scene.render.image_settings.file_format = "OPEN_EXR"
    scene.render.image_settings.color_depth = "32"
    scene.render.image_settings.color_mode = "RGBA"
    scene.view_settings.view_transform = "Standard"
    vl = bpy.context.view_layer
    vl.use_pass_z = True
    vl.use_pass_material_index = True
    vl.use_pass_object_index = True
    for name in ("rws_const", "rws_attr"):
        a = vl.aovs.add()
        a.name = name
        a.type = "VALUE"
    return scene, vl, cube


def read(path):
    img = bpy.data.images.load(path, check_existing=False)
    img.colorspace_settings.name = "Non-Color"
    buf = np.empty(len(img.pixels), dtype=np.float32)
    img.pixels.foreach_get(buf)
    arr = buf.reshape(img.size[1], img.size[0], int(img.channels))
    info = {"channels": int(img.channels), "size": list(img.size), "depth": int(img.depth)}
    bpy.data.images.remove(img)
    return arr, info


def main() -> int:
    out: dict = {"tmp": TMP}
    scene, vl, cube = build()
    tree = bpy.data.node_groups.new(name="probe8", type="CompositorNodeTree")
    sock = tree.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    gout = tree.nodes.new("NodeGroupOutput")
    rl = tree.nodes.new("CompositorNodeRLayers")
    pack = tree.nodes.new("CompositorNodeCombineColor")
    pack.mode = "RGB"
    out["rl_sockets"] = sorted(s.name for s in rl.outputs)
    srcs = {"Red": "Depth", "Green": "Material Index", "Blue": "Object Index",
            "Alpha": "rws_attr"}
    for dst, src in srcs.items():
        if src not in rl.outputs:
            out.setdefault("missing", []).append(src)
            continue
        tree.links.new(rl.outputs[src], pack.inputs[dst])
    tree.links.new(pack.outputs["Image"], gout.inputs["Image"])
    scene.compositing_node_group = tree

    for tag, samples, fw in (("aa", 16, 1.5), ("exact", 1, 0.01)):
        scene.cycles.samples = samples
        scene.cycles.filter_width = fw
        scene.cycles.max_bounces = 0
        scene.cycles.use_denoising = False
        stem = os.path.join(TMP, f"p_{tag}")
        scene.render.filepath = stem
        t0 = time.time()
        bpy.ops.render.render(write_still=True)
        arr, info = read(stem + ".exr")
        rec = {"info": info, "seconds": time.time() - t0}
        for i, nm in enumerate(("depth", "material_index", "object_index", "aov_attr")):
            plane = arr[:, :, i]
            rec[nm] = {"min": float(plane.min()), "max": float(plane.max()),
                       "mean": float(plane.mean()),
                       "unique_head": np.unique(np.round(plane, 4))[:10].tolist(),
                       "fractional_fraction": float(np.mean(
                           np.abs(plane - np.rint(plane)) > 1e-3))}
        out[tag] = rec

    # constant AOV alone (no attribute link) -> does a VALUE AOV reach the file at all?
    scene.cycles.samples = 4
    scene.cycles.filter_width = 1.5
    for dst in list(pack.inputs):
        for link in list(dst.links):
            tree.links.remove(link)
    tree.links.new(rl.outputs["rws_const"], pack.inputs["Red"])
    tree.links.new(rl.outputs["rws_const"], gout.inputs["Image"])
    stem = os.path.join(TMP, "p_const")
    scene.render.filepath = stem
    bpy.ops.render.render(write_still=True)
    arr, info = read(stem + ".exr")
    out["const_aov"] = {"info": info,
                        "ch0": {"min": float(arr[:, :, 0].min()),
                                "max": float(arr[:, :, 0].max()),
                                "unique_head": np.unique(np.round(arr[:, :, 0], 4))[:6].tolist()},
                        "alpha": {"min": float(arr[:, :, 3].min()),
                                  "max": float(arr[:, :, 3].max())}}
    # material index alone, straight to the output
    for link in list(gout.inputs["Image"].links):
        tree.links.remove(link)
    tree.links.new(rl.outputs["Material Index"], gout.inputs["Image"])
    stem = os.path.join(TMP, "p_mat")
    scene.render.filepath = stem
    bpy.ops.render.render(write_still=True)
    arr, info = read(stem + ".exr")
    out["material_index_direct"] = {
        "info": info, "unique_head": np.unique(np.round(arr[:, :, 0], 4))[:10].tolist(),
        "face_material_indices": sorted({int(p.material_index) for p in cube.data.polygons})}

    # Blender's C-level render log interleaves with Python's buffered stdout when both go to
    # the same pipe, so the report is written to a file instead of being printed.
    report_path = os.path.join(TMP, "probe8.json")
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, default=str)
    print("PROBE8_JSON_BEGIN")
    print(report_path)
    print("PROBE8_JSON_END")
    return 0


if __name__ == "__main__":
    sys.exit(main())
