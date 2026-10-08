"""Fifth probe: the exact pass recipe the A12 worker uses.

Validates, in one render:

* File Output item format override -> single-layer OPEN_EXR per pass, readable in numpy,
* per-face ``material_index`` assignment -> Material Index pass carries face labels,
* ``pass_index`` -> Object Index pass,
* Shader AOV driven by a face-domain INT attribute -> per-face id pass,
* Depth/Position pass values against analytic geometry, row order, AA behaviour,
* Cycles denoising (RGB only) availability.

Run::

    & $env:BLENDER_BIN --background --python blender_scripts/probe_blender_api5.py
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

PASSES = ("Image", "Depth", "Position", "Object Index", "Material Index", "rws_face_id")


def build_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    bpy.ops.mesh.primitive_cube_add(size=100.0, location=(0.0, 0.0, 0.0))
    cube = bpy.context.active_object
    cube.name = "target_cube"
    cube.pass_index = 7
    bpy.ops.mesh.primitive_plane_add(size=2000.0, location=(0.0, 0.0, 400.0))
    back = bpy.context.active_object
    back.name = "backdrop"
    back.pass_index = 3

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
    scene.view_settings.view_transform = "Standard"
    scene.render.film_transparent = False
    scene.world = bpy.data.worlds.new("w")
    scene.world.use_nodes = True
    bg = scene.world.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (0.05, 0.05, 0.06, 1.0)
    bg.inputs[1].default_value = 1.0
    return scene, cube, back, cam


def add_face_attributes(mesh, face_ids, surface_tags, n_materials):
    attr_id = mesh.attributes.new(name="rws_face_id", type="INT", domain="FACE")
    attr_id.data.foreach_set("value", [int(v) for v in face_ids])
    attr_tag = mesh.attributes.new(name="rws_surface_tag", type="INT", domain="FACE")
    attr_tag.data.foreach_set("value", [int(v) for v in surface_tags])
    mesh.update()
    for _ in range(n_materials):
        mat = bpy.data.materials.new("tagmat")
        mat.use_nodes = True
        mesh.materials.append(mat)


def add_aov_material(mesh):
    """Material that writes the per-face attribute into the Shader AOV."""
    nt = mesh.materials[0].node_tree
    for node in list(nt.nodes):
        nt.nodes.remove(node)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    emit = nt.nodes.new("ShaderNodeEmission")
    aov = nt.nodes.new("ShaderNodeOutputAOV")
    aov.aov_name = "rws_face_id"
    attr = nt.nodes.new("ShaderNodeAttribute")
    attr.attribute_type = "GEOMETRY"
    attr.attribute_name = "rws_face_id"
    nt.links.new(attr.outputs["Fac"], aov.inputs["Value"])
    nt.links.new(emit.outputs["Emission"], out.inputs["Surface"])
    emit.inputs["Color"].default_value = (0.4, 0.4, 0.4, 1.0)
    emit.inputs["Strength"].default_value = 1.0


def load_exr(path: str):
    img = bpy.data.images.load(path)
    img.colorspace_settings.name = "Non-Color"
    info = {"size": list(img.size), "channels": int(img.channels), "n": len(img.pixels)}
    if info["n"] == 0:
        bpy.data.images.remove(img)
        return info, None
    buf = np.empty(info["n"], dtype=np.float32)
    img.pixels.foreach_get(buf)
    arr = buf.reshape(img.size[1], img.size[0], int(img.channels))
    bpy.data.images.remove(img)
    return info, arr


def main() -> int:
    out: dict = {}
    tmp = tempfile.mkdtemp(prefix="rws_probe5_")
    out["tmp"] = tmp
    scene, cube, back, cam = build_scene()
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 16
    scene.cycles.filter_width = 1.5

    # per-face labels: 12 cube faces get ids 0..11, tags cycling 0/1/2, material per tag
    n_faces = len(cube.data.polygons)
    add_face_attributes(cube.data, np.arange(n_faces), np.arange(n_faces) % 3, 3)
    for poly in cube.data.polygons:
        poly.material_index = int(poly.index) % 3
    add_aov_material(cube.data)
    add_face_attributes(back.data, np.full(len(back.data.polygons), -1),
                        np.full(len(back.data.polygons), -1), 1)

    vl = bpy.context.view_layer
    for flag in ("use_pass_z", "use_pass_position", "use_pass_object_index",
                 "use_pass_material_index", "use_pass_ambient_occlusion"):
        setattr(vl, flag, True)
    aov = vl.aovs.add()
    aov.name = "rws_face_id"
    aov.type = "VALUE"

    # one File Output node per pass, item format overridden to single-layer EXR
    tree = bpy.data.node_groups.new(name="rws_probe5", type="CompositorNodeTree")
    rl = tree.nodes.new("CompositorNodeRLayers")
    out["rl_sockets"] = sorted(s.name for s in rl.outputs)
    for want in PASSES:
        src = next((s for s in rl.outputs if s.name == want), None)
        if src is None:
            out.setdefault("missing_sockets", []).append(want)
            continue
        fo = tree.nodes.new("CompositorNodeOutputFile")
        fo.directory = tmp
        fo.file_name = "pass_" + want.replace(" ", "_").lower()
        fo.save_as_render = False
        item = fo.file_output_items.new("FLOAT", "value")
        item.override_node_format = True
        item.save_as_render = False
        item.format.file_format = "OPEN_EXR"
        item.format.color_depth = "32"
        dst = next((s for s in fo.inputs if s.name == "value"), None)
        tree.links.new(src, dst)
    scene.compositing_node_group = tree

    t0 = time.time()
    bpy.ops.render.render(write_still=False)
    out["render_seconds_16spp"] = time.time() - t0
    time.sleep(0.4)
    out["files"] = sorted(os.listdir(tmp))

    for fn in out["files"]:
        info, arr = load_exr(os.path.join(tmp, fn))
        rec = {"info": info}
        if arr is not None:
            flat = arr.reshape(-1, arr.shape[2])
            rec.update({"min": float(np.nanmin(flat)), "max": float(np.nanmax(flat)),
                        "mean": float(np.nanmean(flat)),
                        "center": arr[arr.shape[0] // 2, arr.shape[1] // 2].tolist(),
                        "row_top_mean": arr[-1].reshape(-1, arr.shape[2]).mean(axis=0).tolist(),
                        "row_bottom_mean": arr[0].reshape(-1, arr.shape[2]).mean(axis=0).tolist(),
                        "unique_head": np.unique(np.round(flat[:, 0], 4))[:12].tolist()})
            finite = np.isfinite(flat)
            fr = np.abs(flat - np.rint(np.nan_to_num(flat)))
            rec["non_integral_fraction"] = float(np.mean(fr.max(axis=1) > 1e-4))
            rec["finite_fraction"] = float(np.mean(finite))
        out.setdefault("passes", {})[fn] = rec

    # denoiser availability
    den: dict = {"use_denoising": bool(scene.cycles.use_denoising)}
    try:
        scene.cycles.use_denoising = True
        scene.cycles.denoiser = "OPENIMAGEDENOISE"
        den["denoiser_set"] = scene.cycles.denoiser
        den["denoising_use_gpu"] = bool(getattr(scene.cycles, "denoising_use_gpu", False))
        t1 = time.time()
        bpy.ops.render.render(write_still=False)
        den["render_seconds_denoised"] = time.time() - t1
        den["ok"] = True
    except Exception as exc:  # noqa: BLE001
        den["ok"] = False
        den["error"] = f"{type(exc).__name__}: {exc}"
    out["denoise"] = den

    print("PROBE5_JSON_BEGIN")
    print(json.dumps(out, indent=2, default=str))
    print("PROBE5_JSON_END")
    return 0


if __name__ == "__main__":
    sys.exit(main())
