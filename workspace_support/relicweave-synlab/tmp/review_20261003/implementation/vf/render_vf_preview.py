"""Render actual VF NPZ geometry with Blender; geometry is never synthesized here."""

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset", type=Path, required=True)
    parser.add_argument("--section", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--pattern-label", default="four_bands")
    parser.add_argument("--exterior-only", action="store_true")
    return parser.parse_args(argv)


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for collection in (bpy.data.materials, bpy.data.cameras, bpy.data.lights, bpy.data.meshes):
        for block in list(collection):
            if block.users == 0:
                collection.remove(block)


def make_material(name, color, roughness=0.78, metallic=0.0):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*[float(c) for c in color], 1.0)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*[float(c) for c in color], 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    return mat


def add_mesh(name, vertices, faces, materials, face_material_ids):
    mesh = bpy.data.meshes.new(name + "Mesh")
    mesh.from_pydata(vertices.tolist(), [], faces.tolist())
    mesh.materials.clear()
    for mat in materials:
        mesh.materials.append(mat)
    mesh.polygons.foreach_set("material_index", face_material_ids.astype(np.int32))
    for poly in mesh.polygons:
        poly.use_smooth = True
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    return obj


def make_continuous_band_material(recipe):
    """Build a Blender shader that evaluates the recipe from rest/material Z."""
    material = bpy.data.materials.new("VF continuous rest-coordinate painted bands")
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (1000, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (760, 0)
    bsdf.inputs["Roughness"].default_value = float(recipe["surface_finish"]["roughness"])
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

    rest = nodes.new("ShaderNodeAttribute")
    rest.attribute_name = "vf_rest_xyz_mm"
    rest.location = (-1000, 100)
    separate = nodes.new("ShaderNodeSeparateXYZ")
    separate.location = (-800, 100)
    links.new(rest.outputs["Vector"], separate.inputs["Vector"])

    palette = recipe["palette_linear_rgb"]
    current = None
    x = -550
    for index, band in enumerate(recipe["bands"]):
        lower = float(band["center_z_mm"]) - float(band["width_mm"]) / 2
        upper = float(band["center_z_mm"]) + float(band["width_mm"]) / 2
        above = nodes.new("ShaderNodeMath")
        above.operation = "GREATER_THAN"
        above.location = (x, 180 - index * 180)
        above.inputs[1].default_value = lower
        links.new(separate.outputs["Z"], above.inputs[0])
        below = nodes.new("ShaderNodeMath")
        below.operation = "LESS_THAN"
        below.location = (x, 40 - index * 180)
        below.inputs[1].default_value = upper
        links.new(separate.outputs["Z"], below.inputs[0])
        mask = nodes.new("ShaderNodeMath")
        mask.operation = "MULTIPLY"
        mask.location = (x + 170, 100 - index * 180)
        links.new(above.outputs[0], mask.inputs[0])
        links.new(below.outputs[0], mask.inputs[1])
        mix = nodes.new("ShaderNodeMixRGB")
        mix.blend_type = "MIX"
        mix.location = (x + 360, 100 - index * 180)
        mix.inputs["Color2"].default_value = (*[float(c) for c in palette[band["color"]]], 1.0)
        if current is None:
            mix.inputs["Color1"].default_value = (*[float(c) for c in palette["base"]], 1.0)
        else:
            links.new(current, mix.inputs["Color1"])
        links.new(mask.outputs[0], mix.inputs["Fac"])
        current = mix.outputs["Color"]
        x += 70
    links.new(current, bsdf.inputs["Base Color"])
    return material


def add_rest_coordinate_attribute(obj, vertices):
    attribute = obj.data.attributes.new(
        name="vf_rest_xyz_mm", type="FLOAT_VECTOR", domain="POINT"
    )
    attribute.data.foreach_set("vector", np.asarray(vertices, dtype=np.float32).reshape(-1).tolist())


def point_camera(camera, target):
    direction = Vector(target) - camera.location
    camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def add_camera(name, location, target, ortho_scale):
    data = bpy.data.cameras.new(name)
    data.type = "ORTHO"
    data.ortho_scale = ortho_scale
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    point_camera(obj, target)
    bpy.context.scene.camera = obj
    return obj


def add_lights():
    for name, location, power, size in (
        ("Key", (45, -70, 95), 35000, 65),
        ("Fill", (-55, -35, 50), 18000, 80),
        ("Rim", (5, 65, 75), 28000, 55),
    ):
        light = bpy.data.lights.new(name, "AREA")
        light.energy = power
        light.shape = "DISK"
        light.size = size
        obj = bpy.data.objects.new(name, light)
        bpy.context.collection.objects.link(obj)
        obj.location = location
        point_camera(obj, (4, 0, 27))


def setup_render(path, resolution=1100):
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = 96
    scene.render.resolution_x = resolution
    scene.render.resolution_y = resolution
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    scene.world.color = (0.78, 0.75, 0.70)
    scene.view_settings.view_transform = "AgX"
    scene.render.filepath = str(path)


def render_exterior(args):
    clear_scene()
    with np.load(args.asset / "geometry" / "surface.npz", allow_pickle=False) as geom:
        vertices = geom["vertices_mm"].astype(np.float64)
        faces = geom["faces"].astype(np.int32)
    with np.load(args.asset / "fields" / "surface.npz", allow_pickle=False) as fields:
        regions = fields["face_region"].astype(np.int32)
    manifest = json.loads((args.asset / "manifest.json").read_text(encoding="utf-8"))
    recipe = manifest["ornament"]["recipe"]
    rule_material = make_continuous_band_material(recipe)
    base_material = make_material(
        "Unpainted prototype clay",
        recipe["palette_linear_rgb"]["base"],
        float(recipe["surface_finish"]["roughness"]),
    )
    ids = (regions != 1).astype(np.int32)
    obj = add_mesh("VF canonical surface", vertices, faces, [rule_material, base_material], ids)
    add_rest_coordinate_attribute(obj, vertices)
    add_lights()
    add_camera("ExteriorCamera", (92, -142, 78), (5, 0, 28), 77)
    setup_render(args.out_dir / f"exterior_{args.pattern_label}.png")
    bpy.ops.render.render(write_still=True)


def render_section(args, closeup=None):
    clear_scene()
    with np.load(args.section, allow_pickle=False) as geom:
        vertices = geom["vertices_mm"].astype(np.float64)
        faces = geom["faces"].astype(np.int32)
    # New y=0 half-section CAD faces are separately shown as cut material.
    tri = vertices[faces]
    centers = tri.mean(axis=1)
    normals = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    normals /= np.maximum(np.linalg.norm(normals, axis=1), 1e-12)[:, None]
    cut = (np.abs(centers[:, 1]) < 1e-5) & (np.abs(normals[:, 1]) > 0.85)
    exterior = make_material("Original ceramic surface", (0.53, 0.34, 0.22), 0.8)
    cutmat = make_material("CAD section plane, visual only", (0.88, 0.64, 0.34), 0.86)
    ids = cut.astype(np.int32)
    obj = add_mesh("Half section from exported STEP solid", vertices, faces, [exterior, cutmat], ids)
    add_lights()
    if closeup == "lower":
        add_camera("LowerJointCamera", (42, -130, 30), (22, 0, 14), 32)
        file_name = "joint_lower_section.png"
    elif closeup == "upper":
        add_camera("UpperJointCamera", (42, -130, 55), (18, 0, 43), 80)
        file_name = "joint_upper_section.png"
    else:
        add_camera("SectionCamera", (42, -150, 70), (5, 0, 28), 82)
        file_name = "axial_half_section.png"
    setup_render(args.out_dir / file_name)
    bpy.ops.render.render(write_still=True)


def main():
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    render_exterior(args)
    if not args.exterior_only:
        render_section(args)
        render_section(args, "lower")
        render_section(args, "upper")


if __name__ == "__main__":
    main()

