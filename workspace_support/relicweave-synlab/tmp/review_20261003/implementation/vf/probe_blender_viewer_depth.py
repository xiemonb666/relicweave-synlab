import bpy
bpy.context.scene.render.engine='BLENDER_EEVEE'
s=bpy.context.scene
s.render.resolution_x=32; s.render.resolution_y=24; s.render.resolution_percentage=100
s.view_layers[0].use_pass_z=True
node_tree=bpy.data.node_groups.new('depth test','CompositorNodeTree')
s.compositing_node_group=node_tree
rl=node_tree.nodes.new('CompositorNodeRLayers')
v=node_tree.nodes.new('CompositorNodeViewer')
node_tree.links.new(rl.outputs['Depth'],v.inputs['Image'])
bpy.ops.render.render(write_still=False)
print('IMAGES',[(im.name,tuple(im.size),im.channels,len(im.pixels)) for im in bpy.data.images])
for im in bpy.data.images:
 if 'Viewer' in im.name: print('VIEWER_MINMAX',min(im.pixels[:]),max(im.pixels[:]))
