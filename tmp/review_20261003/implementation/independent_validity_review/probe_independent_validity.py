from __future__ import annotations
import json
import hashlib
import numpy as np
import trimesh
from synlab.physical.fields import interface_contact, roi_anchor_points, FourierField, rank_mask_for_area_fraction
from synlab.physical.operators import dirt_cover
from synlab.physical.recipe import DamageRecipe
from synlab.degrade.sources import SourceBundle, KIND_MESH
from synlab.degrade.api import apply_axis
from synlab.physical.api import audit_physical
from synlab.canonical import hash_json
from synlab.degrade.api import _apply_impl

out = {}

# Probe 1: closed 12-face source prism with unequal top ROI triangles (areas 1 and 9).
A=np.array([0.,0.,0.]); B=np.array([2.,0.,0.]); C=np.array([2.,1.,0.]); D=np.array([0.,9.,0.])
top=np.array([A,B,C,D]); bot=top.copy(); bot[:,2]=-1.
verts=np.vstack([top,bot])
faces=np.array([
    [0,1,2],[0,2,3],       # top ROI: signed areas 1 and 9
    [4,6,5],[4,7,6],       # bottom
    [0,4,5],[0,5,1],       # AB side
    [1,5,6],[1,6,2],       # BC side
    [2,6,7],[2,7,3],       # CD side
    [3,7,4],[3,4,0],       # DA side
],dtype=np.int64)
source=trimesh.Trimesh(vertices=verts,faces=faces,process=False)
source.metadata['face_attr_arrays']={'interface_id': np.array([0,0,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1],dtype=np.int32)}
small=trimesh.Trimesh(vertices=np.vstack([A,B,C,A+[0,0,-1],B+[0,0,-1],C+[0,0,-1]]),faces=np.array([
    [0,1,2],[3,5,4],[0,3,4],[0,4,1],[1,4,5],[1,5,2],[2,5,3],[2,3,0]
],dtype=np.int64),process=False)
area=float(source.area_faces[:2].sum())
contact=interface_contact(source,None,{'kind':'interface'},small,eps_mm=2e-3,density_mm=0.5)
out['interface_contact_area_bias']={
    'source_faces':len(source.faces),'source_watertight':bool(source.is_watertight),'source_winding_consistent':bool(source.is_winding_consistent),'source_signed_volume':float(source.volume),
    'roi_face_areas_mm2':[float(x) for x in source.area_faces[:2]],'roi_total_area_mm2':area,
    'body_watertight':bool(small.is_watertight),'body_signed_volume':float(small.volume),
    'anchors':contact['anchors'],'unweighted_residual_fraction':contact['residual_fraction'],
    'reported_lost_fraction':contact['lost_fraction'],'reported_lost_area_mm2':contact['lost_area_mm2'],
    'area_weighted_residual_fraction_if_small_face_only_survives':1.0/10.0,
    'area_weighted_lost_fraction_if_small_face_only_survives':9.0/10.0,
    'difference_in_lost_fraction':float(contact['lost_fraction']-0.9),
}

# Probe 2: equal-area tied rank boundary and nonuniform-area nearest-prefix behavior.
values=np.array([0.25,0.25,0.25,0.9])
weights=np.array([1.,1.,8.,2.])
rows=[]
previous=np.zeros(values.shape,dtype=bool)
for fraction in (0.0,0.1,0.2,0.5,1.0):
    mask,info=rank_mask_for_area_fraction(values,fraction,weights,tail='lower')
    rows.append({'fraction':fraction,'mask':mask.tolist(),'selected_area':info['selected_area'],'target_area':info['target_area'],'boundary_score':info['boundary_score'],'boundary_tie_split':info['boundary_tie_split'],'nested_with_previous':bool(np.all(previous <= mask))})
    previous=mask
out['rank_mask_ties_nonuniform_area']=rows

# Probe 3: direct P05-like current paint mask followed by P06. P06's current implementation
# measures against the preserved original pattern mask even though no paint remains visible.
field=FourierField.sample_frozen(np.random.default_rng(37),scale_mm=8.0,field_id='review_P06').payload()
appearance={
    'texel_albedo':np.tile(np.array([[0.65,0.3,0.2]],dtype=np.float32),(2,1)),
    'texel_substrate_albedo':np.tile(np.array([[0.4,0.4,0.4]],dtype=np.float32),(2,1)),
    'texel_area_mm2':np.array([1.,1.]),
    'texel_layer':np.array([1,1],dtype=np.int32),
    'texel_positions':np.array([[0.,0.,0.],[1.,0.,0.]],dtype=np.float64),
    'pattern_region':np.array([True,True]),
    'paint_mask_retained':np.array([False,False]),
    'paint_mask_removed':np.array([True,True]),
    'interface_region':np.array([True,True]),
    'texel_roughness':np.array([0.5,0.5],dtype=np.float32),
}
mesh=trimesh.creation.box(extents=(2,2,2))
recipe=DamageRecipe(axis_id='P06',variant='dirt_appearance',level=2,
                    params={'coverage':0.5},basis={'dirt_field':field,'seed':37},
                    meta={'appearance':appearance})
before_field=hash_json(field)
result=dirt_cover(mesh,recipe)
covered=np.asarray(result.appearance['dirt_mask'],dtype=bool)
out['p06_after_p05_all_paint_removed']={
    'pattern_region_count':int(appearance['pattern_region'].sum()),
    'current_paint_visible_count':int(appearance['paint_mask_retained'].sum()),
    'covered_texels':int(covered.sum()),
    'reported_pattern_visibility_reduction':result.measurements['pattern_visibility_reduction'],
    'current_visible_pattern_reduction':(float(appearance['paint_mask_retained'][covered].sum()/max(appearance['paint_mask_retained'].sum(),1)) if appearance['paint_mask_retained'].any() else 0.0),
    'reported_coverage':result.measurements['realized_coverage'],
    'geometry_hash_unchanged':result.measurements['geometry_hash_unchanged'],
    'source_rank_field_sha256_before':before_field,
    'source_rank_field_sha256_after':hash_json(field),
    'source_appearance_unchanged':bool(not appearance['paint_mask_retained'].any() and np.array_equal(appearance['pattern_region'],[True,True]) and np.allclose(appearance['texel_albedo'],0.65*np.ones_like(appearance['texel_albedo'])+np.array([[0,-0.0,-0.0]]))),
}

# Probe 4: actual public P02 degradation route uses run_narrowband_damage directly.
# 3x3 subdivision of a closed 10 mm cube gives 60 faces (<100); top triangles are the interface ROI.
n=3; zlevels=(5.,-5.)
xyz=[]
for z in zlevels:
    for i in range(n+1):
        for j in range(n+1):
            xyz.append([-5.+10.*i/n,-5.+10.*j/n,z])
def ix(side,i,j): return side*(n+1)*(n+1)+i*(n+1)+j
ff=[]; ids=[]
# top
for i in range(n):
  for j in range(n):
    a,b,c,d=ix(0,i,j),ix(0,i+1,j),ix(0,i+1,j+1),ix(0,i,j+1)
    ff.extend([[a,b,c],[a,c,d]]); ids.extend([0,0])
# bottom reverse
for i in range(n):
  for j in range(n):
    a,b,c,d=ix(1,i,j),ix(1,i+1,j),ix(1,i+1,j+1),ix(1,i,j+1)
    ff.extend([[a,c,b],[a,d,c]]); ids.extend([-1,-1])
# perimeter edges in top cyclic order; bottom indices paired, quads oriented outward
perimeter=[]
for i in range(n): perimeter.append((ix(0,i,0),ix(0,i+1,0)))
for j in range(n): perimeter.append((ix(0,n,j),ix(0,n,j+1)))
for i in range(n,0,-1): perimeter.append((ix(0,i,n),ix(0,i-1,n)))
for j in range(n,0,-1): perimeter.append((ix(0,0,j),ix(0,0,j-1)))
for a,b in perimeter:
    a2,b2=a+(n+1)*(n+1),b+(n+1)*(n+1)
    ff.extend([[a,a2,b2],[a,b2,b]]); ids.extend([-1,-1])
p02mesh=trimesh.Trimesh(vertices=np.asarray(xyz),faces=np.asarray(ff,dtype=np.int64),process=False)
p02mesh.metadata['face_attr_arrays']={'interface_id':np.asarray(ids,dtype=np.int32)}
p02source=SourceBundle(source_kind=KIND_MESH,payload={'mesh':p02mesh},fragment_id='review-fragment',meta={'fragment_id':'review-fragment','material_id':'M01'})
p02_result=None
try:
    output_bundle,record,measurement=_apply_impl('P02',1,p02source,None,commit=False,lineage_id='independent-validity-review')
    p02_result=output_bundle.get('physical_result')
    p02_audit=audit_physical(p02_result,clean=p02mesh)
    p02_component=p02_result.components[0]
    out['public_p02_route']={'status':'returned','measurement_valid':bool(measurement.valid),'measurement_realized':bool(measurement.realized),'measurement_label_status':measurement.extra.get('label_status'),'measurement_label_dependencies':measurement.extra.get('label_dependency_status'),'physical_result_qa_status':p02_result.qa.get('status'),'component_count':len(p02_result.components),'component_watertight':[bool(c.mesh.is_watertight) for c in p02_result.components],'component_signed_volumes':[float(c.mesh.volume) for c in p02_result.components],'audit_physical_status':p02_audit.get('status'),'audit_physical_failures':p02_audit.get('failure_codes'),'postassembly_failure_codes':(p02_audit.get('checks',{}).get('postassembly',{}).get('failure_codes')),'source_faces':len(p02mesh.faces),'source_watertight':bool(p02mesh.is_watertight),'source_signed_volume':float(p02mesh.volume)}
except Exception as exc:
    out['public_p02_route']={'status':'raised','type':type(exc).__name__,'message':str(exc),'source_faces':len(p02mesh.faces),'source_watertight':bool(p02mesh.is_watertight),'source_signed_volume':float(p02mesh.volume)}

print(json.dumps(out,indent=2,sort_keys=True,default=lambda x: str(x)))


