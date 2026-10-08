from __future__ import annotations

import math
from pathlib import Path

import bpy
import bmesh
import numpy as np
from mathutils import Vector

ROOT = Path(__file__).resolve().parent
GEOMETRY = ROOT / "geometry"
OUT = ROOT / "renders"
OUT.mkdir(parents=True, exist_ok=True)


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for block in list(bpy.data.materials):
        if block.users == 0:
            bpy.data.materials.remove(block)


def make_material(name, color, roughness=0.35, metallic=0.0):
    material = bpy.data.materials.new(name)
    material.diffuse_color = (*color, 1.0)
    material.use_nodes = True
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Specular IOR Level"].default_value = 0.28
    return material


def add_mesh(name, vertices, faces, material):
    mesh = bpy.data.meshes.new(name + "Mesh")
    mesh.from_pydata(vertices.tolist(), [], faces.tolist())
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(material)
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    return obj


def aim_camera(camera, target):
    camera.rotation_euler = (Vector(target) - camera.location).to_track_quat("-Z", "Y").to_euler()


def setup_scene(path, camera_location, target, ortho_scale=82.0, resolution=1600):
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = 96
    scene.render.resolution_x = resolution
    scene.render.resolution_y = resolution
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.filepath = str(path)
    scene.render.film_transparent = False
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Base Contrast"
    scene.view_settings.exposure = 0.8
    scene.world.use_nodes = True
    background = scene.world.node_tree.nodes.get("Background")
    background.inputs["Color"].default_value = (0.28, 0.30, 0.34, 1.0)
    background.inputs["Strength"].default_value = 0.8
    camera_data = bpy.data.cameras.new("Camera")
    camera = bpy.data.objects.new("Camera", camera_data)
    bpy.context.collection.objects.link(camera)
    camera.location = camera_location
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = ortho_scale
    aim_camera(camera, target)
    scene.camera = camera
    return scene


def add_lighting():
    def area(name, location, energy, size, color):
        data = bpy.data.lights.new(name, "AREA")
        data.energy = energy
        data.shape = "DISK"
        data.size = size
        data.color = color
        obj = bpy.data.objects.new(name, data)
        bpy.context.collection.objects.link(obj)
        obj.location = location
        obj.rotation_euler = (Vector((0.0, 0.0, 27.0)) - obj.location).to_track_quat("-Z", "Y").to_euler()
        return obj
    area("Key softbox", (48.0, -68.0, 92.0), 26000.0, 70.0, (1.0, 0.86, 0.66))
    area("Fill softbox", (-65.0, -22.0, 50.0), 17000.0, 82.0, (0.68, 0.78, 1.0))
    area("Rim softbox", (10.0, 70.0, 76.0), 30000.0, 55.0, (1.0, 0.94, 0.82))


def add_floor(material):
    bpy.ops.mesh.primitive_plane_add(size=300.0, location=(0.0, 0.0, -0.18))
    floor = bpy.context.object
    floor.name = "Neutral ground"
    floor.data.materials.append(material)


def non_manifold_edge_count(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    count = sum(not edge.is_manifold for edge in bm.edges)
    bm.free()
    return count


def main():
    clear_scene()
    failed_mesh_cut = OUT / "mesh_boolean_cut_visualization.png"
    if failed_mesh_cut.exists():
        failed_mesh_cut.unlink()
    body_npz = np.load(GEOMETRY / "surface.npz")
    vertices = body_npz["vertices_mm"]
    faces = body_npz["faces"]
    clay = make_material("Unpatterned porcelain", (0.86, 0.81, 0.70), roughness=0.31)
    floor_material = make_material("Neutral matte backdrop", (0.10, 0.12, 0.15), roughness=0.72)
    body = add_mesh("Canonical STEP body mesh", vertices, faces, clay)
    add_floor(floor_material)
    add_lighting()
    scene = setup_scene(OUT / "whole_porcelain.png", (78.0, -118.0, 96.0), (0.0, 0.0, 27.0), ortho_scale=78.0)
    bpy.ops.render.render(write_still=True)

    # The following is a visualization cut on the delivered STEP-tessellation
    # mesh, not native CAD section evidence. Its result is recorded in the log.
    clear_scene()
    body = add_mesh("Canonical STEP body mesh", vertices, faces, clay)
    body.rotation_euler[2] = math.radians(17.0)
    bpy.context.view_layer.objects.active = body
    body.select_set(True)
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(-55.0, 0.0, 28.0))
    cutter = bpy.context.object
    cutter.name = "Half-space cutter for mesh preview only"
    cutter.dimensions = (110.0, 120.0, 120.0)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    modifier = body.modifiers.new("Mesh-only axial visualization cut", "BOOLEAN")
    modifier.operation = "DIFFERENCE"
    modifier.solver = "EXACT"
    modifier.object = cutter
    bpy.context.view_layer.objects.active = body
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    bpy.data.objects.remove(cutter, do_unlink=True)
    for polygon in body.data.polygons:
        polygon.use_smooth = True
    cut_mesh_metrics = {
        "vertices": len(body.data.vertices),
        "faces": len(body.data.polygons),
        "non_manifold_edges": non_manifold_edge_count(body),
    }
    if cut_mesh_metrics["vertices"] > 0 and cut_mesh_metrics["faces"] > 0 and cut_mesh_metrics["non_manifold_edges"] == 0:
        add_floor(floor_material)
        add_lighting()
        setup_scene(OUT / "mesh_boolean_cut_visualization.png", (-125.0, -190.0, 105.0), (0.0, 0.0, 27.0), ortho_scale=82.0)
        bpy.ops.render.render(write_still=True)

    # Render exact native STEP intersection curves separately, with no filled
    # face, because OCC reported the planar fill face invalid.
    clear_scene()
    section_npz = np.load(GEOMETRY / "axial_section.npz")
    points = section_npz["edge_points_mm"]
    offsets = section_npz["edge_offsets"]
    line_material = make_material("Section line", (0.045, 0.035, 0.025), roughness=0.6)
    curve_data = bpy.data.curves.new("Canonical STEP section edges", type="CURVE")
    curve_data.dimensions = "3D"
    curve_data.resolution_u = 16
    curve_data.bevel_depth = 0.035
    curve_data.bevel_resolution = 2
    for edge_index in range(len(offsets) - 1):
        start, end = int(offsets[edge_index]), int(offsets[edge_index + 1])
        edge_points = points[start:end]
        spline = curve_data.splines.new("POLY")
        spline.points.add(len(edge_points) - 1)
        for i, point in enumerate(edge_points):
            spline.points[i].co = (float(point[0]), float(point[1]), float(point[2]), 1.0)
    section_obj = bpy.data.objects.new("Exact B-rep section wire linework", curve_data)
    bpy.context.collection.objects.link(section_obj)
    section_obj.data.materials.append(line_material)
    scene = setup_scene(OUT / "native_section_wire.png", (0.0, -145.0, 29.0), (0.0, 0.0, 28.0), ortho_scale=62.0, resolution=1800)
    scene.render.resolution_y = 1800
    bpy.ops.render.render(write_still=True)

    print({"mesh_boolean_visualization": cut_mesh_metrics, "native_section_face": "not filled; OCC face invalid", "renders": [str(p) for p in sorted(OUT.glob("*.png"))]})


if __name__ == "__main__":
    main()
