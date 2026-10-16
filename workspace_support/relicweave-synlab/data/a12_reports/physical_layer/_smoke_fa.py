import sys, json, time
sys.path.insert(0, '.')
import numpy as np
from synlab.observe import fracture_appearance as fa
from synlab.materials import build_material_profile, default_material_params
from synlab.seeds import make_rng

print("import ok")
light = fa.frozen_light()
print("light", light.direction, light.color, light.ambient)
prof = build_material_profile("M01", default_material_params("M01"), make_rng(20261001, "appearance", "M01"))
ap = fa.appearance_parameters_from_profile(prof, material_id="M01")
print("M01", json.dumps({k: ap.as_dict()[k] for k in ("material_name","sigma_r0_mm","lambda_min_mm","lambda_max_mm","porosity","grain_scale_mm","glaze_thickness_mm","transmission")}, ensure_ascii=False))
print("bands", ap.band_wavelengths_mm, [round(x,4) for x in ap.band_amplitudes_mm])

# geometry parity test setup: 200 mm plate
import trimesh
from synlab.observe.render import MaterialSpec
m = trimesh.creation.box(extents=(60.0, 60.0, 10.0))
sc = fa.Scene(name="t", vertices=np.asarray(m.vertices), faces=np.asarray(m.faces),
              surface_tag=np.full(np.asarray(m.faces).shape[0], 2, dtype=np.int16),
              material=MaterialSpec(np.tile(np.array([0.6,0.55,0.5], dtype=np.float32), (np.asarray(m.faces).shape[0],1)),
                                       np.full(np.asarray(m.faces).shape[0], 0.5, dtype=np.float32)))
from synlab.observe.render import render_view, RenderSpec, BACKEND_SOFTWARE, MaterialSpec
from synlab.schemas.runtime import ViewFrame
K = np.array([[800.0,0,256.0],[0,800.0,192.0],[0,0,1.0]])
T = np.eye(4); T[:3,3] = np.array([0.0,0.0,-200.0])
fr = ViewFrame(view_id="v", K=K, T_WC=T, image_size=(512,384), profile_id="test", tier="LOCAL",
               u_position_mm=200.0, working_distance_mm=200.0, focus_setting=0.0,
               source_kind="SENSOR_SIM", camera_model="PINHOLE", dist=np.zeros(0),
               meta={"focal_length_mm": 6.1, "f_number": 4.0, "near_mm":1.0})
myspec = RenderSpec(supersample=1, max_pixels=4_000_000)
a = render_view(sc, fr, light=light, spec=myspec, backend=BACKEND_SOFTWARE)
b = fa.render_appearance_view(sc, fr, light=light, spec=myspec, appearance=fa.AppearanceSpec(normal_mode="FLAT", relief=False, interpolation="FROZEN"))
print("rgb equal:", bool(np.array_equal(a.rgb_linear, b.rgb_linear)), "maxdiff", float(np.abs(a.rgb_linear-b.rgb_linear).max()))
print("id equal:", bool(np.array_equal(a.id_map, b.id_map)), "tag equal:", bool(np.array_equal(a.surface_tag, b.surface_tag)))
print("depth equal:", bool(np.array_equal(np.nan_to_num(a.depth_z, nan=-1), np.nan_to_num(b.depth_z, nan=-1))))
t0=time.perf_counter()
c = fa.render_appearance_view(sc, fr, light=light, spec=myspec, appearance=fa.AppearanceSpec(normal_mode="SMOOTH_CREASE", relief=True, amplitude_scale=1.0), relief_field=None)
print("smooth+relief(none) seconds", round(time.perf_counter()-t0,2))


