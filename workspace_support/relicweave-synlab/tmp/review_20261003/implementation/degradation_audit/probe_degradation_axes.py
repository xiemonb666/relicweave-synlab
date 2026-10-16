from __future__ import annotations
import hashlib, json, math, traceback
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import trimesh
from PIL import Image, ImageDraw

from synlab.degrade.api import apply_axis
from synlab.degrade.axes import _FragmentView
from synlab.degrade.registry import AXIS_REGISTRY
from synlab.degrade.sources import KIND_IMAGE, KIND_PHYSICAL, SourceBundle, mesh_geometry_hash
from synlab.schemas.runtime import ORIGIN_INTERFACE, ORIGIN_MOTHER_SURFACE
from synlab.storage.mesh_io import with_face_attrs

OUT = Path("tmp/review_20261003/implementation/degradation_audit")
OUT.mkdir(parents=True, exist_ok=True)
SEED = 20261003
LINEAGE = "degradation_audit_small_probe_20261003"

def jsonable(v):
    if isinstance(v, dict): return {str(k): jsonable(x) for k,x in v.items()}
    if isinstance(v, (list,tuple)): return [jsonable(x) for x in v]
    if isinstance(v, np.ndarray): return v.tolist()
    if isinstance(v, (np.integer,)): return int(v)
    if isinstance(v, (np.floating,)): return float(v)
    if isinstance(v, (np.bool_,)): return bool(v)
    if isinstance(v, (str,int,float,bool)) or v is None: return v
    return repr(v)

def output_image(ref):
    if hasattr(ref, "payload"): return ref.payload
    if hasattr(ref, "get"): return ref.payload
    return {}

def small_box():
    base = trimesh.creation.box(extents=(8.0, 8.0, 2.4))
    vertices, faces = trimesh.remesh.subdivide_to_size(
        np.asarray(base.vertices, dtype=np.float64), np.asarray(base.faces, dtype=np.int64),
        max_edge=2.4)
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    mesh.merge_vertices()
    fc = np.asarray(mesh.triangles_center, dtype=np.float64)
    fn = np.asarray(mesh.face_normals, dtype=np.float64)
    top = (fn[:,2] > 0.9) & (fc[:,2] > 1.19)
    origin = np.full(len(mesh.faces), ORIGIN_MOTHER_SURFACE, dtype=np.uint8)
    interface_id = np.full(len(mesh.faces), -1, dtype=np.int32)
    origin[top] = ORIGIN_INTERFACE
    interface_id[top] = 1
    with_face_attrs(mesh, origin_kind=origin, interface_id=interface_id)
    area = np.asarray(mesh.area_faces, dtype=np.float64)
    layer = top & ((np.arange(len(mesh.faces)) % 3) != 1)
    painted = np.tile(np.array([0.78,0.20,0.11], dtype=np.float32), (len(mesh.faces),1))
    substrate = np.tile(np.array([0.57,0.50,0.40], dtype=np.float32), (len(mesh.faces),1))
    albedo = np.where(layer[:,None], painted, substrate).astype(np.float32)
    appearance = {
        "texel_albedo": albedo.copy(),
        "texel_substrate_albedo": substrate.copy(),
        "texel_area_mm2": area,
        "texel_layer": layer.astype(np.int32),
        "texel_roughness": np.full(len(mesh.faces),0.62,dtype=np.float32),
        "texel_positions": fc.copy(),
        "pattern_region": layer.copy(),
        "interface_region": top.copy(),
    }
    fragment = _FragmentView(mesh, "probe_fragment_small",
        meta={"material_id":"M03","appearance":appearance},
        face_attrs={"origin_kind":origin,"interface_id":interface_id})
    source = SourceBundle(source_kind=KIND_PHYSICAL,
        payload={"mesh":mesh,"fragment":fragment,"appearance":appearance},
        role="probe", schema="probe", unit="mm", frame="F_mm",
        lineage_id=LINEAGE, fragment_id="probe_fragment_small",
        meta={"material_id":"M03","master_seed":SEED,"provenance":"SYNTHETIC_SMALL_BOX_FIXTURE",
              "fixture_vertices":int(len(mesh.vertices)),"fixture_faces":int(len(mesh.faces)),
              "fixture_top_interface_faces":int(top.sum()),"appearance_texels":int(len(area))})
    return mesh, top, source

def raster_top(mesh, face_rgb, top_mask, path, title):
    w=h=192
    image=Image.new("RGB",(w,h),(244,242,236))
    draw=ImageDraw.Draw(image)
    xy=np.asarray(mesh.vertices,dtype=np.float64)[:,:2]
    lo=xy.min(axis=0); span=np.maximum(xy.max(axis=0)-lo,1e-9)
    xy_px=np.column_stack([16+(xy[:,0]-lo[0])*(w-32)/span[0],
                           h-16-(xy[:,1]-lo[1])*(h-32)/span[1]])
    for i,face in enumerate(np.asarray(mesh.faces)):
        if not top_mask[i]: continue
        color=np.rint(np.clip(face_rgb[i],0,1)*255).astype(np.uint8)
        draw.polygon([tuple(np.rint(xy_px[int(k)]).astype(int)) for k in face],
                     fill=tuple(int(c) for c in color), outline=(80,75,68))
    draw.rectangle((0,h-24,w,h),fill=(255,255,255))
    draw.text((5,h-20),title,fill=(10,10,10))
    image.save(path)

def make_phys_outputs():
    mesh, top, source=small_box()
    report={"case":"P05 paint removal + P06 dirt appearance + P02 edge rounding",
            "source":source.describe(),"source_meta":jsonable(source.meta),
            "source_appearance_keys":sorted(source.get("appearance").keys()),
            "vertices":int(len(mesh.vertices)),"faces":int(len(mesh.faces)),
            "top_interface_faces":int(top.sum()),"geometry_source_hash":mesh_geometry_hash(mesh),
            "axes":{}}
    level1_refs={}
    p02_meshes={}
    for axis in ("P05","P06","P02"):
        rows=[]
        for level in (0,1,4):
            try:
                ref,m=apply_axis(axis,level,source,None,lineage_id=LINEAGE,commit=False)
                if level == 1:
                    level1_refs[axis]=ref
                payload=output_image(ref)
                if axis == "P02":
                    result_mesh=payload.get("mesh",mesh)
                    p02_meshes[level]=result_mesh
                    rows.append({"level":level,"status":"OK","axis":m.axis_id,"variant":m.variant,
                       "planned":jsonable(m.planned),"measured":jsonable(m.measured),
                       "units":jsonable(m.units),"identity":bool(m.identity),"realized":bool(m.realized),
                       "source_hash":m.source_hash,"result_hash":m.result_hash,
                       "basis_id":m.extra.get("basis_id"),
                       "label_invalidations":jsonable(m.extra.get("label_invalidations",[])),
                       "label_status":m.extra.get("label_status"),
                       "calibration_status":getattr(m,"calibration_status",None),
                       "extra":jsonable(m.extra),
                       "geometry_hash_before":mesh_geometry_hash(mesh),
                       "geometry_hash_after":mesh_geometry_hash(result_mesh),
                       "vertices_after":int(len(result_mesh.vertices)),"faces_after":int(len(result_mesh.faces)),
                       "volume_after_mm3":float(abs(result_mesh.volume)),
                       "watertight_after":bool(result_mesh.is_watertight)})
                    continue
                app=payload.get("appearance") or source.get("appearance")
                rgb=np.asarray(app["texel_albedo"],dtype=np.float64)
                source_app=source.get("appearance")
                app_keys=sorted(app.keys())
                missing_keys=sorted(set(source_app.keys())-set(app_keys)) if level>0 else []
                roughness=(np.asarray(app["texel_roughness"],dtype=np.float64)
                           if "texel_roughness" in app else None)
                q={
                    "level":level,"status":"OK","axis":m.axis_id,"variant":m.variant,
                    "planned":jsonable(m.planned),"measured":jsonable(m.measured),
                    "units":jsonable(m.units),"identity":bool(m.identity),"realized":bool(m.realized),
                    "source_hash":m.source_hash,"result_hash":m.result_hash,
                    "result_appearance_keys":app_keys,
                    "missing_source_appearance_keys":missing_keys,
                    "extra":jsonable(m.extra),"basis_id":m.extra.get("basis_id"),
                    "label_invalidations":jsonable(m.extra.get("label_invalidations",[])),
                    "label_status":m.extra.get("label_status"),
                    "calibration_status":getattr(m,"calibration_status",None),
                    "albedo_mean":rgb.mean(axis=0).tolist(),
                    "albedo_std":rgb.std(axis=0).tolist(),
                    "pattern_texel_count":int(np.asarray(app.get("pattern_region",[]),dtype=bool).sum()),
                    "paint_layer_count":int((np.asarray(app.get("texel_layer",[]))>0).sum()),
                    "roughness_mean":(float(roughness.mean()) if roughness is not None else None),
                    "image_png":None,
                }
                image_name=f"{axis.lower()}_L{level}_top_albedo.png"
                raster_top(mesh,rgb,top,OUT/image_name,f"{axis} L{level} top-face albedo projection")
                q["image_png"]=image_name
                rows.append(q)
            except Exception as e:
                rows.append({"level":level,"status":"ERROR","error":f"{type(e).__name__}: {e}",
                             "traceback":traceback.format_exc()})
        report["axes"][axis]=rows
    report["composition_checks"]={}
    for first_axis,next_axis in (("P05","P06"),("P06","P05")):
        try:
            first_bundle=level1_refs[first_axis].as_bundle()
            try:
                next_ref,next_measurement=apply_axis(next_axis,1,first_bundle,None,
                    lineage_id=LINEAGE,commit=False)
                report["composition_checks"][f"{first_axis}_L1_to_{next_axis}_L1"]={
                    "status":"PASS","result_hash":next_measurement.result_hash,
                    "measured":jsonable(next_measurement.measured)}
            except Exception as e:
                report["composition_checks"][f"{first_axis}_L1_to_{next_axis}_L1"]={
                    "status":"FAIL","error_type":type(e).__name__,
                    "error":str(e),"traceback":traceback.format_exc(),
                    "first_output_payload_keys":sorted(first_bundle.payload),
                    "first_output_appearance_keys":sorted((first_bundle.get("appearance") or {}).keys())}
        except Exception as e:
            report["composition_checks"][f"{first_axis}_L1_to_{next_axis}_L1"]={
                "status":"PROBE_ERROR","error":f"{type(e).__name__}: {e}"}
    # Independently traverse the production physical route (physical.apply_damage -> OPS.run_damage
    # -> selected_backend -> the declared P02 implementation) on the same 110-vertex fixture.
    try:
        op=AXIS_REGISTRY.get("P02")
        basis=op.sample_basis({"source":source,"lineage_id":LINEAGE,
            "fragment_id":source.fragment_id,"master_seed":SEED},
            np.random.default_rng(SEED),op.default_variant)
        recipe=op.recipe(level=4,variant=op.default_variant,
            params=op.params_for(4,op.default_variant),basis=basis,
            fragment=source.get("fragment"),source=source)
        from synlab.physical.operators import run_damage
        routed_outcome=run_damage(mesh,recipe,fragment=source.get("fragment"))
        from synlab.physical.api import apply_damage
        physical_result=apply_damage(source.get("clean_truth"),source.get("fragment"),recipe)
        details=dict((physical_result.meta or {}).get("details") or {})
        from synlab.physical.api import audit_physical
        physical_audit=audit_physical(physical_result,mesh)
        report["p02_production_route"]={
            "status":"OK","route":"synlab.physical.api.apply_damage",
            "backend":details.get("damage_backend"),
            "backend_selection":jsonable(details.get("backend_selection")),
            "routed_outcome_watertight":bool(routed_outcome.mesh.is_watertight),
            "routed_outcome_volume_mm3":float(abs(routed_outcome.mesh.volume)),
            "measured":jsonable((physical_result.meta or {}).get("measured") or {}),
            "physical_result_qa":jsonable(physical_result.qa),
            "physical_audit":jsonable(physical_audit),
            "component_stats":[{"component_id":c.component_id,"watertight":bool(c.mesh.is_watertight),
                "volume_mm3":float(abs(c.mesh.volume)),"faces":int(len(c.mesh.faces)),
                "vertices":int(len(c.mesh.vertices))} for c in physical_result.components],
            "watertight":physical_result.components[0].mesh.is_watertight if physical_result.components else None,
            "basis_id":basis.basis_id,"source_fixture_vertices":int(len(mesh.vertices)),
            "source_fixture_faces":int(len(mesh.faces))
        }
    except Exception as e:
        report["p02_production_route"]={"status":"ERROR","error":f"{type(e).__name__}: {e}",
            "traceback":traceback.format_exc()}
    # Actual mesh cross-sections for the small declared interface fixture; each panel uses the
    # source's same x/z bounds so visible edge recession is comparable across levels.
    try:
        levels=(0,1,4); panel_w=150; panel_h=150
        strip=Image.new("RGB",(panel_w*len(levels),panel_h+24),(255,255,255))
        draw=ImageDraw.Draw(strip)
        lo=np.asarray(mesh.bounds[0],dtype=float); hi=np.asarray(mesh.bounds[1],dtype=float)
        span=np.maximum(hi[[0,2]]-lo[[0,2]],1e-9)
        for idx,level in enumerate(levels):
            obj=p02_meshes[level]
            section=obj.section(plane_origin=np.array([0.,0.,0.]),plane_normal=np.array([0.,1.,0.]))
            xoff=idx*panel_w
            if section is not None:
                for path in section.discrete:
                    points=np.asarray(path,dtype=float)[:,[0,2]]
                    px=xoff+10+(points[:,0]-lo[0])*(panel_w-20)/span[0]
                    py=panel_h-10-(points[:,1]-lo[2])*(panel_h-20)/span[1]
                    xy=[(int(round(x)),int(round(y))) for x,y in zip(px,py)]
                    if len(xy)>1: draw.line(xy+[xy[0]],fill=(15,35,55),width=2)
            draw.text((xoff+6,panel_h+4),f"P02 L{level} section",fill=(10,10,10))
        strip.save(OUT/"p02_L0_L1_L4_geometry_sections.png")
        report["p02_section_png"]="p02_L0_L1_L4_geometry_sections.png"
    except Exception as e:
        report["p02_section_png_error"]=f"{type(e).__name__}: {e}"
    (OUT/"appearance_probe.json").write_text(json.dumps(jsonable(report),indent=2,ensure_ascii=False),encoding="utf-8")
    return report

def small_image():
    h=w=64
    yy,xx=np.mgrid[0:h,0:w]
    edge=((xx//8+yy//8)%2).astype(np.float32)
    obj=((xx-31.5)**2/24**2+(yy-31.5)**2/22**2)<1
    lin=np.zeros((h,w,3),dtype=np.float32)
    lin[...,0]=0.08+0.28*obj+0.08*edge
    lin[...,1]=0.10+0.30*obj+0.06*edge
    lin[...,2]=0.12+0.20*obj+0.04*edge
    lin=np.clip(lin,0,1)
    rgb=np.rint(lin*255).astype(np.uint8)
    frame={"view_id":"fixture_view_0","rgb":rgb,"rgb_linear":lin,"encoding":"LINEAR",
           "K":np.array([[80.,0.,31.5],[0.,80.,31.5],[0.,0.,1.]],dtype=np.float64),
           "T_WC":np.eye(4,dtype=np.float64),"image_size":(w,h),"valid":True}
    return SourceBundle(source_kind=KIND_IMAGE,payload={"frames":[frame],"exposure_gain":1.0},
        role="probe",schema="probe",unit="px",frame="IMAGE",
        lineage_id=LINEAGE,fragment_id="phone_frame_small",
        meta={"master_seed":SEED,"provenance":"SYNTHETIC_64PX_SENSOR_FIXTURE"})

def make_noise_outputs():
    source=small_image()
    baseline=source.get("frames")[0]["rgb"]
    rows=[]
    for level in (0,1,4):
        try:
            ref,m=apply_axis("I03",level,source,None,lineage_id=LINEAGE,commit=False)
            frame=output_image(ref).get("frames",[{}])[0]
            rgb=np.asarray(frame["rgb"],dtype=np.uint8)
            name=f"i03_L{level}_rgb.png"
            Image.fromarray(rgb,"RGB").save(OUT/name)
            rows.append({"level":level,"status":"OK","planned":jsonable(m.planned),
                "measured":jsonable(m.measured),"units":jsonable(m.units),
                "identity":bool(m.identity),"realized":bool(m.realized),
                "calibration_status":getattr(m,"calibration_status",None),
                "source_hash":m.source_hash,"result_hash":m.result_hash,
                "basis_id":m.extra.get("basis_id"),
                "label_invalidations":jsonable(m.extra.get("label_invalidations",[])),
                "label_status":m.extra.get("label_status"),
                "mean_abs_rgb_delta_from_L0":float(np.mean(np.abs(rgb.astype(np.float32)-baseline.astype(np.float32)))),
                "rgb_changed_fraction":float(np.mean(np.any(rgb!=baseline,axis=2))),
                "image_png":name})
        except Exception as e:
            rows.append({"level":level,"status":"ERROR","error":f"{type(e).__name__}: {e}",
                         "traceback":traceback.format_exc()})
    report={"case":"I03 photon_scale low-cost camera sensor proxy","width":64,"height":64,
            "source":source.describe(),"levels":rows}
    (OUT/"phone_noise_probe.json").write_text(json.dumps(jsonable(report),indent=2,ensure_ascii=False),encoding="utf-8")
    return report

if __name__=="__main__":
    manifest={"seed":SEED,"lineage_id":LINEAGE,"output_dir":str(OUT),
              "fixture_limits":{"image_pixels":64*64,"physical_box_max_vertices":None},
              "runs":{}}
    p=make_phys_outputs()
    manifest["runs"]["appearance"]=p
    n=make_noise_outputs()
    manifest["runs"]["phone_noise"]=n
    fixture_info=p.get("source_meta",{})
    manifest["fixture_limits"]["physical_box_max_vertices"]=fixture_info.get("fixture_vertices")
    (OUT/"probe_manifest.json").write_text(json.dumps(jsonable(manifest),indent=2,ensure_ascii=False),encoding="utf-8")
    print(json.dumps(jsonable({
        "physical": {axis:[{k:r.get(k) for k in ("level","status","measured","identity","realized","basis_id","image_png")} for r in rows]
                    for axis,rows in p["axes"].items()},
        "noise":[{k:r.get(k) for k in ("level","status","measured","identity","realized","basis_id","image_png","mean_abs_rgb_delta_from_L0")} for r in n["levels"]],
        "fixture_vertices":fixture_info.get("fixture_vertices"),"fixture_faces":fixture_info.get("fixture_faces")
    }),indent=2,ensure_ascii=False))
