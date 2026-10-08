"""Patch v4: run the appearance study on a LIT fracture, and measure the unlit control."""
from pathlib import Path

p = Path("tests/a12/observe/_run_fracture_appearance.py")
s = p.read_text(encoding="utf-8")

pairs = [
    ("""SPECIMEN = STUDY[0]                    # V10/M11 (plane cut: the fracture fills the ROI frame)""",
     """#: The appearance study runs on the fracture with the largest measured lit score
#: ``-(n_roi . light)`` among the four study bodies.  This is a measurement, not a preference:
#: the frozen model has one directional light and its Lambert term is clipped, so a fracture that
#: faces away from that light renders as ``albedo * ambient`` and NO normal perturbation can
#: change a code value there (measured: V10/M11 scores -0.79 on every ROI and its relief dDN is
#: exactly 0).  ``UNLIT_CONTROL`` keeps that body in the run as the control.
SPECIMEN = STUDY[3]                    # V02/M01 (a12_iface lineage: real sub-mm relief)
UNLIT_CONTROL = STUDY[0]               # V10/M11 (plane cut, faces away from the frozen light)"""),
    ("""    report: dict = {"schema": fa.APPEARANCE_SCHEMA + ".run", "config": config.as_dict(),
                    "master_seed": MASTER_SEED, "specimen_entry": SPECIMEN,
                    "started_at_s": 0.0, "stages": {}, "timing": {}}
    target, body = load_target(SPECIMEN)
    mesh = target.mesh
    rng = make_rng(MASTER_SEED, "appearance", "run")
    roi_config = fr.load_fracture_roi_config()
    from synlab.cameras.profiles import camera_profiles

    profiles = {p.tier: p for p in camera_profiles()}
    base = profiles[config.base_tier]
    closeup = fr.closeup_profile(roi_config, base=base, delivered_long_edge_px=1024)
    footprint = fr.mm_per_px(working_distance_mm=config.working_distance_mm,
                             f_px=float(closeup.K[0, 0])) * 512.0
    rois = fr.fracture_rois(target, roi_config, footprint_radius_mm=footprint)
    roi = pick_roi(rois)
    report["roi_frame"] = {"footprint_radius_mm": footprint,
                           "n_rois": len(rois), "roi_id": roi.roi_id,
                           "roi": roi.as_dict()}""",
     """    report: dict = {"schema": fa.APPEARANCE_SCHEMA + ".run", "config": config.as_dict(),
                    "master_seed": MASTER_SEED, "specimen_entry": SPECIMEN,
                    "started_at_s": 0.0, "stages": {}, "timing": {}}
    target, body = load_target(SPECIMEN)
    mesh = target.mesh
    rng = make_rng(MASTER_SEED, "appearance", "run")
    roi_config = fr.load_fracture_roi_config()
    from synlab.cameras.profiles import camera_profiles

    light = fa.frozen_light()
    profiles = {p.tier: p for p in camera_profiles()}
    base = profiles[config.base_tier]
    closeup = fr.closeup_profile(roi_config, base=base, delivered_long_edge_px=1024)
    footprint = fr.mm_per_px(working_distance_mm=config.working_distance_mm,
                             f_px=float(closeup.K[0, 0])) * 512.0
    rois = fr.fracture_rois(target, roi_config, footprint_radius_mm=footprint)
    roi = max(rois, key=lambda r: lit_score(r, light))
    report["lit_ranking_specimen"] = sorted(
        [{"roi_id": r.roi_id, "lit_score": lit_score(r, light), "n_faces": int(r.n_faces),
          "area_mm2": float(r.area_mm2)} for r in rois], key=lambda r: -r["lit_score"])
    report["roi_frame"] = {"footprint_radius_mm": footprint,
                           "n_rois": len(rois), "roi_id": roi.roi_id,
                           "lit_score": lit_score(roi, light),
                           "roi": roi.as_dict()}"""),
]
for old, new in pairs:
    if old not in s:
        raise SystemExit("PATTERN NOT FOUND:\n" + old[:200])
    s = s.replace(old, new, 1)

# unlit control inside stage_sweep: one relief pair on the darkest body, measured
old_tail = """    return {"specimen": body, "roi": roi.as_dict(), "material_parameters": params.as_dict(),
            "relief_field": field.as_dict(), "spectrum": spectrum, "rows": rows,
            "noise_control": control,
            "images_raw": images}"""
new_tail = """    unlit = _unlit_control(config=config, light=light)
    return {"specimen": body, "roi": roi.as_dict(), "material_parameters": params.as_dict(),
            "relief_field": field.as_dict(), "spectrum": spectrum, "rows": rows,
            "noise_control": control, "unlit_control": unlit,
            "images_raw": images}


def _unlit_control(*, config, light) -> dict:
    \"\"\"The same relief pair on a fracture that faces AWAY from the frozen light.

    The frozen model clips the Lambert term at 0, so on such a view the shading is
    ``albedo * ambient`` everywhere and the normal channel cannot change one code value.  Running
    the control makes "the relief is invisible" a measurement instead of a claim.
    \"\"\"
    from synlab.cameras.profiles import camera_profiles

    rois = None
    try:
        target, body = load_target(UNLIT_CONTROL)
        mesh = target.mesh
        roi_config = fr.load_fracture_roi_config()
        profiles = {p.tier: p for p in camera_profiles()}
        base = profiles[config.base_tier]
        long_edge = 1024
        closeup = fr.closeup_profile(roi_config, base=base, delivered_long_edge_px=long_edge)
        footprint = fr.mm_per_px(working_distance_mm=config.working_distance_mm,
                                 f_px=float(closeup.K[0, 0])) * 512.0
        rois = fr.fracture_rois(target, roi_config, footprint_radius_mm=footprint)
        roi = min(rois, key=lambda r: lit_score(r, light))
        faces = patch_faces(mesh, roi.interface_id)
        tris = np.asarray(mesh.faces)[faces]
        spec = rt.ObsSpec(view_count=1, delivered_size=(long_edge, 768),
                          max_render_pixels=long_edge * long_edge, master_seed=MASTER_SEED,
                          lineage_id="fracture_appearance", frame_id="S_mm",
                          renderer=rt.RENDERER_AUTO,
                          distortion_policy=rt.DISTORTION_POLICY_IGNORE)
        frame = fr.make_fracture_roi_frames(
            rois=[roi], profile=closeup, spec=spec, config=roi_config, long_edge_px=long_edge,
            rng=make_rng(MASTER_SEED, "appearance_frame", roi.roi_id), run_id="appearance",
            mesh=mesh)[0]
        profile = material_profile(body["material_id"])
        amp = sorted(float(x) for x in config.amplitudes_mm)[-1]
        field = fa.build_relief_field(
            profile=profile, roi=roi, patch_vertices=mesh.vertices, patch_triangles=tris,
            mesh=mesh, rng=make_rng(MASTER_SEED, "appearance_field", body["material_id"]),
            amplitude_mm=amp, glaze_strip=False)
        off = render_and_image(target=target, frame=frame,
                               appearance=fa.AppearanceSpec(
                                   normal_mode="FLAT", relief=False,
                                   interpolation="PERSPECTIVE_CORRECT", label="unlit off"),
                               relief=None, obs_spec=spec, imaging_seed=11, supersample=1)
        on = render_and_image(target=target, frame=frame,
                              appearance=fa.AppearanceSpec(
                                  normal_mode="FLAT", relief=True,
                                  interpolation="PERSPECTIVE_CORRECT", label="unlit on"),
                              relief=field, obs_spec=spec, imaging_seed=11, supersample=1)
        return {
            "vessel_id": body["vessel_id"], "material_id": body["material_id"],
            "roi_id": roi.roi_id, "lit_score": lit_score(roi, light), "ra_mm": amp,
            "realized_ra_mm": field.realized_ra_mm,
            "lambert": off["render"].meta["appearance"]["lambert"],
            "difference": fa.difference_dn_statistics(on["dn_float"], off["dn_float"], on["mask"]),
            "prediction": field.predicted_shading_ddn(
                albedo=field.parameters.albedo, light=light, T_WC=frame.T_WC,
                ra_scale=field.amplitude_scale),
            "conclusion": ("clipped Lambert term: the normal channel is measured to be unable to "
                           "change the image on a fracture that faces away from the frozen light"),
        }
    except Exception as exc:  # noqa: BLE001
        return {"status": "FAILED", "error": f"{type(exc).__name__}: {exc}",
                "n_rois": 0 if rois is None else len(rois)}"""
if old_tail not in s:
    raise SystemExit("TAIL PATTERN NOT FOUND")
s = s.replace(old_tail, new_tail, 1)
p.write_text(s, encoding="utf-8")
print("patched")
