"""Render package meshes with a uniform emission shader and export float Z passes."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

import bpy
import numpy as np
from mathutils import Vector

argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
parser = argparse.ArgumentParser()
parser.add_argument('--canonical3', type=Path, required=True)
parser.add_argument('--candidate', type=Path, required=True)
parser.add_argument('--out-dir', type=Path, required=True)
args = parser.parse_args(argv)
args.out_dir.mkdir(parents=True, exist_ok=True)


def clear_objects():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    for datablocks in (bpy.data.meshes, bpy.data.cameras, bpy.data.materials):
        for block in list(datablocks):
            if block.users == 0:
                datablocks.remove(block)


def emission_material():
    material = bpy.data.materials.new('geometry-only neutral emission')
    material.use_nodes = True
    material.node_tree.nodes.clear()
    output = material.node_tree.nodes.new('ShaderNodeOutputMaterial')
    emission = material.node_tree.nodes.new('ShaderNodeEmission')
    emission.inputs['Color'].default_value = (0.72, 0.72, 0.72, 1.0)
    emission.inputs['Strength'].default_value = 1.0
    material.node_tree.links.new(emission.outputs['Emission'], output.inputs['Surface'])
    return material


def aim(obj, target):
    direction = Vector(target) - obj.location
    obj.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()


def new_camera(location, target, scale):
    data = bpy.data.cameras.new('shared orthographic camera')
    data.type = 'ORTHO'
    data.ortho_scale = scale
    camera = bpy.data.objects.new(data.name, data)
    bpy.context.collection.objects.link(camera)
    camera.location = location
    aim(camera, target)
    return camera


def add_mesh(asset: Path, name: str):
    with np.load(asset / 'geometry' / 'surface.npz', allow_pickle=False) as payload:
        vertices = payload['vertices_mm'].astype(np.float64)
        faces = payload['faces'].astype(np.int32)
    mesh = bpy.data.meshes.new(name + ' mesh')
    mesh.from_pydata(vertices.tolist(), [], faces.tolist())
    material = emission_material()
    mesh.materials.append(material)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    return obj


scene = bpy.context.scene
scene.render.engine = 'BLENDER_EEVEE'
scene.render.resolution_x = 1100
scene.render.resolution_y = 1100
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = 'PNG'
scene.render.film_transparent = True
scene.render.image_settings.color_mode = 'RGBA'
scene.view_settings.view_transform = 'Standard'
scene.render.use_compositing = True
scene.render.use_file_extension = True
scene.view_layers[0].use_pass_z = True
depth_tree = bpy.data.node_groups.new('VF geometry depth output', 'CompositorNodeTree')
scene.compositing_node_group = depth_tree
render_layers = depth_tree.nodes.new('CompositorNodeRLayers')
file_output = depth_tree.nodes.new('CompositorNodeOutputFile')
file_output.file_output_items.new('FLOAT', 'Depth')
depth_tree.links.new(render_layers.outputs['Depth'], file_output.inputs['Depth'])
file_output.format.file_format = 'OPEN_EXR_MULTILAYER'
file_output.format.color_mode = 'RGBA'
file_output.format.color_depth = '32'
file_output.directory = str(args.out_dir)

views = {
    'whole': ((92, -142, 78), (5, 0, 28), 77),
    'lower_root': ((42, -130, 30), (22, 0, 14), 32),
}
packages = [('canonical3', args.canonical3), ('brep_semantics1', args.candidate)]
for package_label, asset in packages:
    for view_label, (location, target, scale) in views.items():
        clear_objects()
        obj = add_mesh(asset, package_label + ' geometry only')
        camera = new_camera(location, target, scale)
        scene.camera = camera
        prefix = f'{package_label}_{view_label}'
        scene.render.filepath = str(args.out_dir / f'{prefix}.png')
        file_output.file_name = prefix + '_depth_' 
        bpy.ops.render.render(write_still=True)
        exr = args.out_dir / f'{prefix}_depth_0001.exr'
        if not exr.exists():
            # Blender may use four-digit frame suffixes in some builds.
            candidates = sorted(args.out_dir.glob(prefix + '_depth_*.exr'))
            if not candidates:
                raise RuntimeError(f'compositor did not write a depth EXR for {prefix}')
            exr = candidates[-1]
        print(f'{prefix}: depth_exr={exr}')
print(f'rendered {len(packages) * len(views)} geometry-only views at {scene.render.resolution_x}x{scene.render.resolution_y}; camera, projection and emission material are shared by label')






