"""Patch v6: split the facet metric into its two measured sources (shading normal vs albedo)."""
from pathlib import Path

p = Path("tests/a12/observe/_run_fracture_appearance.py")
s = p.read_text(encoding="utf-8")

old = '''    for mode, crease, label in (("FLAT", 35.0, "flat (frozen)"),
                                ("SMOOTH", 180.0, "smooth vertex normals"),
                                ("SMOOTH_CREASE", float(config.crease_angle_deg),
                                 f"smooth + crease {config.crease_angle_deg:g} deg")):
        res = render_and_image(target=target, frame=frame,
                               appearance=fa.AppearanceSpec(
                                   normal_mode=mode, crease_angle_deg=crease, relief=False,
                                   interpolation="PERSPECTIVE_CORRECT", label=label),
                               relief=None, obs_spec=spec_obs, imaging_seed=11,
                               supersample=int(config.supersample))
        out["variants"][mode] = {
            "label": label, "crease_angle_deg": crease,
            "geometry_hash": res["render"].meta["appearance"]["geometry_hash"],
            "measured": measure(res),
        }'''
new = '''    # The delivered scene carries a per-face procedural palette albedo (render.procedural_albedo),
    # so a triangle boundary shows TWO independent steps: the shading-normal step and the albedo
    # step.  Both are measured, because a per-pixel normal can only remove the first.
    params_specimen = fa.appearance_parameters_from_profile(
        material_profile(body["material_id"]), material_id=body["material_id"])
    flat_albedo = np.tile(np.asarray(params_specimen.albedo, dtype=np.float64),
                          (len(mesh.faces), 1))
    for mode, crease, label in (("FLAT", 35.0, "flat (frozen)"),
                                ("SMOOTH", 180.0, "smooth vertex normals"),
                                ("SMOOTH_CREASE", float(config.crease_angle_deg),
                                 f"smooth + crease {config.crease_angle_deg:g} deg")):
        entry: dict = {"label": label, "crease_angle_deg": crease}
        for key, albedo in (("per_face_palette", None), ("constant_material_albedo", flat_albedo)):
            res = render_and_image(target=target, frame=frame,
                                   appearance=fa.AppearanceSpec(
                                       normal_mode=mode, crease_angle_deg=crease, relief=False,
                                       interpolation="PERSPECTIVE_CORRECT", label=label),
                                   relief=None, obs_spec=spec_obs, imaging_seed=11,
                                   supersample=int(config.supersample), albedo=albedo)
            entry[key] = measure(res)
            entry["geometry_hash"] = res["render"].meta["appearance"]["geometry_hash"]
        out["variants"][mode] = entry
    out["albedo_sources"] = {
        "per_face_palette": ("render.procedural_albedo: the delivered scene's per-face speckle "
                             "(declared SENSOR_SIM); its steps sit on every triangle boundary"),
        "constant_material_albedo": ("the specimen material's own albedo, identical on every face: "
                                     "isolates the shading-normal facet step"),
        "material_albedo": [float(x) for x in params_specimen.albedo],
    }'''
assert old in s, "facets loop pattern missing"
s = s.replace(old, new, 1)
p.write_text(s, encoding="utf-8")
print("patched")
