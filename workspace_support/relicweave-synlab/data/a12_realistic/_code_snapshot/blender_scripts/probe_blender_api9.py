"""Ninth probe: which passes are filter-averaged, and does Material Index carry per-face tags?

Decisive setup: a cube whose visible faces carry **distinct material indices** (1 and 2) and
**distinct face labels** (AOV), rendered twice with very different filter widths.

Run::

    & $env:BLENDER_BIN --background --python blender_scripts/probe_blender_api9.py
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

TMP = tempfile.mkdtemp(prefix="rws_probe9_")


def build():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    bpy.ops.mesh.primitive_cube_add(size=100.0)
    cube = bpy.context.active_object
    cube.pass_index = 5
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
        aov.aov_name = "rws_attr"
        attr = nt.nodes.new("ShaderNodeAttribute")
        attr.attribute_type = "GEOMETRY"
        attr.attribute_name = "rws_face_label"
        nt.links.new(attr.outputs["Fac"], aov.inputs["Value"])
        cube.data.materials.append(mat)
    # every face gets material index 1 except face 2 (material index 2)
    for poly in cube.data.polygons:
        poly.material_index = 2 if poly.index == 2 else 1
    attr = cube.data.attributes.new(name="rws_face_label", type="FLOAT", domain="FACE")
    attr.data.foreach_set("value", np.arange(len(cube.data.polygons), dtype=np.float32) * 10.0)
    cube.data.update()

    cam_data = bpy.data.cameras.new("c")
    cam_data.sensor_width = 36.0
    cam_data.lens = 36.0
    cam = bpy.data.objects.new("c", cam_data)
    scene.collection.objects.link(cam)
    cam.location = (0.0, 0.0, -400.0)
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
    vl.use_pass_position = True
    a = vl.aovs.add()
    a.name = "rws_attr"
    a.type = "VALUE"
    return scene, vl, cube


def read(path):
    img = bpy.data.images.load(path, check_existing=False)
    img.colorspace_settings.name = "Non-Color"
    buf = np.empty(len(img.pixels), dtype=np.float32)
    img.pixels.foreach_get(buf)
    arr = buf.reshape(img.size[1], img.size[0], int(img.channels))
    bpy.data.images.remove(img)
    return arr


def main() -> int:
    out: dict = {"tmp": TMP}
    scene, vl, cube = build()
    out["view_layer_filter_props"] = sorted(a for a in dir(vl) if "filter" in a.lower())
    out["view_layer_pass_props"] = sorted(a for a in dir(vl) if a.startswith("use_pass"))
    try:
        rna = type(vl).bl_rna
        out["rna_props_with_filter"] = sorted(
            p.identifier for p in rna.properties if "filter" in p.identifier.lower())
    except Exception as exc:  # noqa: BLE001
        out["rna_props_with_filter"] = f"{type(exc).__name__}: {exc}"

    tree = bpy.data.node_groups.new(name="probe9", type="CompositorNodeTree")
    tree.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    gout = tree.nodes.new("NodeGroupOutput")
    rl = tree.nodes.new("CompositorNodeRLayers")
    pack = tree.nodes.new("CompositorNodeCombineColor")
    pack.mode = "RGB"
    for dst, src in (("Red", "Depth"), ("Green", "Material Index"),
                     ("Blue", "Object Index"), ("Alpha", "rws_attr")):
        tree.links.new(rl.outputs[src], pack.inputs[dst])
    tree.links.new(pack.outputs["Image"], gout.inputs["Image"])
    scene.compositing_node_group = tree

    for tag, samples, fw in (("f0.01_s1", 1, 0.01), ("f1.5_s16", 16, 1.5), ("f4.0_s64", 64, 4.0)):
        scene.cycles.samples = samples
        scene.cycles.filter_width = fw
        scene.cycles.max_bounces = 0
        scene.cycles.use_denoising = False
        stem = os.path.join(TMP, f"p_{tag}")
        scene.render.filepath = stem
        t0 = time.time()
        bpy.ops.render.render(write_still=True)
        arr = read(stem + ".exr")
        rec = {"seconds": time.time() - t0, "samples": samples, "filter": fw}
        for i, nm in enumerate(("depth", "material_index", "object_index", "aov_attr")):
            plane = arr[:, :, i]
            rec[nm] = {"min": float(plane.min()), "max": float(plane.max()),
                       "mean": float(plane.mean()),
                       "unique": np.unique(np.round(plane, 4))[:12].tolist()}
        out[tag] = rec

    # Position pass separately (world mm) - is it available and is it filtered?
    for link in list(gout.inputs["Image"].links):
        tree.links.remove(link)
    tree.links.new(rl.outputs["Position"], gout.inputs["Image"])
    for tag, samples, fw in (("pos_f0.01_s1", 1, 0.01), ("pos_f4.0_s64", 64, 4.0)):
        scene.cycles.samples = samples
        scene.cycles.filter_width = fw
        stem = os.path.join(TMP, f"p_{tag}")
        scene.render.filepath = stem
        bpy.ops.render.render(write_still=True)
        arr = read(stem + ".exr")
        out[tag] = {"depth_channel_min": float(arr[:, :, 0].min()),
                    "depth_channel_max": float(arr[:, :, 0].max()),
                    "unique_z": np.unique(np.round(arr[:, :, 2], 3))[:6].tolist()}

    report_path = os.path.join(TMP, "probe9.json")
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, default=str)
    print("PROBE9_JSON_BEGIN")
    print(report_path)
    print("PROBE9_JSON_END")
    return 0


if __name__ == "__main__":
    sys.exit(main())
