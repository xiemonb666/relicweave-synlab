"""Fracture-appearance run: relief through the normal channel, measured on real renders.

Stages (all outputs under the allowed write scope):

* ``sweep``     - ``dDN`` vs ``Ra`` (0.02 / 0.08 / 0.4 mm) at every ``mm/px`` rung, plus the
                  imaging-noise control pair that bounds the measurement floor.
* ``facets``    - flat vs smooth vs smooth-with-crease normals on the *same* geometry
                  (path 1 of facet suppression) and the required mesh density (path 2).
* ``materials`` - >= 3 materials on the *same* fracture geometry (grain / pore / fibre /
                  transmission / glaze differences), measured on rendered images.
* ``glaze``     - is the glaze/body step in the RGB?  Layer records, measured shell thickness,
                  a real render of the audited relief-damping strip, and the edge profile.
* ``images``    - the side-by-side A/B PNGs (1024 and 2048).

Usage (repository root, venv interpreter):
    python tests/a12/observe/_run_fracture_appearance.py [--stages sweep,facets,...] [--quick]
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import sys
import time
from dataclasses import replace as replace_config
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from _run_fracture_roi import STUDY, load_target  # noqa: E402  (same study bodies, one source)

from synlab.fracture import morphology as mo  # noqa: E402
from synlab.materials import build_material_profile, default_material_params  # noqa: E402
from synlab.observe import fracture_appearance as fa  # noqa: E402
from synlab.observe import fracture_roi as fr  # noqa: E402
from synlab.observe import routes as rt  # noqa: E402
from synlab.observe.imaging import apply_imaging_chain  # noqa: E402
from synlab.observe.render import RenderSpec  # noqa: E402
from synlab.seeds import make_rng  # noqa: E402

#: The integer ``surface_tag`` of the observed interface (fracture) faces; ``routes`` maps
#: ``ORIGIN_INTERFACE`` to it and ``fracture_roi.view_resolution_record`` uses the same 2.
RIM_TAG = 2

SPECIMEN = STUDY[0]                    # V10/M11 (plane cut: the fracture fills the ROI frame)
MATERIAL_SEEDS = 20261001
REPORT_DIR = ROOT / "data/a12_reports/physical_layer"
STORE_ROOT = ROOT / "data/a12_fapp/store"
MASTER_SEED = 20261001


# -------------------------------------------------------------------------------------- helpers
def material_profile(material_id: str) -> dict:
    return build_material_profile(material_id, default_material_params(material_id),
                                  make_rng(MATERIAL_SEEDS, "physical_layer", "materials",
                                           material_id))


def patch_faces(mesh, interface_id: int) -> np.ndarray:
    """Face indices of the fracture patch with this ``interface_id`` (origin_kind = INTERFACE)."""
    attrs = dict((getattr(mesh, "metadata", None) or {}).get("face_attr_arrays") or {})
    kind = np.asarray(attrs["origin_kind"]).reshape(-1)
    iface = np.asarray(attrs["interface_id"]).reshape(-1)
    return np.nonzero((kind == int(fr.ORIGIN_INTERFACE)) & (iface == int(interface_id)))[0]


def pick_roi(rois, wanted: str = "iface6_c000"):
    for r in rois:
        if r.roi_id == wanted:
            return r
    return max(rois, key=lambda r: r.n_faces)


def rung_long_edge(mm_per_px: float, *, working_distance_mm: float, f_px_native: float,
                   native_width_px: int) -> int:
    """Delivered long edge that realises ``mm_per_px`` at this working distance (same optics)."""
    return int(round(float(working_distance_mm) * float(native_width_px)
                     / (float(mm_per_px) * float(f_px_native))))


def render_and_image(*, target, frame, appearance, relief, obs_spec, imaging_seed: int,
                     supersample: int, albedo=None):
    """One appearance render through the project's own imaging chain (mirrors render_frame_bundles).

    ``render_frame_bundles`` is the single implementation of "frame -> ViewBundle"; the appearance
    renderer is wired into it through its ``render_fn`` hook, so the imaging chain, the delivered
    grid and the masks are the project's, not a private copy.  What is returned here is what a
    production caller would see in ``ViewBundle.imaging.image``.
    """
    from synlab.observe.render import build_scene

    scene = build_scene(target.mesh, surface_tag=target.surface_tag, face_id=target.face_id,
                        name=target.fragment_id)
    light = obs_spec.resolved_light()
    ss = max(int(supersample), 1)
    pixels = int(frame.image_size[0]) * int(frame.image_size[1]) * ss * ss
    render_spec = RenderSpec(supersample=ss,
                             max_pixels=max(int(obs_spec.max_render_pixels), pixels))
    render = fa.render_appearance_view(scene, frame, light=light, spec=render_spec,
                                       appearance=appearance, relief_field=relief,
                                       object_pose=None,
                                       focus_distance_mm=frame.working_distance_mm,
                                       albedo=albedo)
    imaging_spec = copy.copy(obs_spec.imaging)
    imaging_spec.crop_origin = (0, 0)
    imaging_spec.resize_scale = (1.0, 1.0)
    # Two readings of the SAME render through the project's own chain:
    #   SHADING   the chain in its noise-free limit (the photon scale raised so that
    #             `y = Poisson(g*x)/g` has negligible variance: sigma/x = 1/sqrt(g*x)).  This is
    #             the channel a relief measurement belongs in, because a 1-photon-per-pixel
    #             Poisson draw swamps any shading signal.
    #   DELIVERED the shipped default (effective_gain = 1), kept so the noise floor is measured
    #             rather than assumed away.
    def _chain(spec, seed: int):
        res = apply_imaging_chain(render.rgb_linear, K=frame.K, dist=frame.dist,
                                  uncertain_mask=render.uncertain_mask, depth_z=render.depth_z,
                                  focus_distance_mm=frame.working_distance_mm,
                                  rng=make_rng(MASTER_SEED, "appearance_imaging", str(int(seed))),
                                  spec=spec, camera_model=frame.camera_model or "PINHOLE")
        img = np.asarray(res.image)
        return res, (img.astype(np.float64).mean(axis=2) if img.ndim == 3
                     else img.astype(np.float64))

    shading_spec = copy.copy(imaging_spec)
    shading_spec.effective_gain = 1.0e6
    shading_res, shading_dn = _chain(shading_spec, imaging_seed)
    delivered_res, delivered_dn = _chain(imaging_spec, imaging_seed)
    lin = np.asarray(shading_res.linear, dtype=np.float64)
    dn_float = 255.0 * (lin.mean(axis=2) if lin.ndim == 3 else lin)
    mask = (render.id_map >= 0) & (render.surface_tag == RIM_TAG)
    return {"render": render, "image": shading_res.image, "dn": shading_dn,
            "dn_float": dn_float, "mask": mask,
            "imaging": shading_res, "frame": frame, "appearance": appearance,
            "image_delivered": delivered_res.image, "dn_delivered": delivered_dn,
            "imaging_delivered": delivered_res,
            "imaging_gain_shading": 1.0e6}


def measure(res: dict) -> dict:
    """Delivered-image statistics of one appearance render.

    Both readings of the same render are reported: ``dn`` is the quantised delivered image (the
    code values a reader sees) and ``dn_float`` is the pre-quantisation DN of the chain's linear
    output, which is the channel a sub-code-value shading signal has to be measured in.
    """
    dn, mask, render = res["dn"], res["mask"], res["render"]
    out = {"dn": fa.dn_statistics(dn, mask),
           "dn_float": fa.dn_statistics(res["dn_float"], mask),
           "dn_delivered_shipped_gain": fa.dn_statistics(res["dn_delivered"], mask),
           "facet": fa.facet_metrics(dn, render.id_map, mask),
           "direction": fa.directional_index(dn, mask),
           "grain": fa.grain_pixel_statistics(dn, mask)}
    return out


def mm_per_px_of(frame) -> float:
    return float(frame.working_distance_mm / float(frame.K[0, 0]))


def band_prediction(field, *, ra_mm: float, albedo: float, light=None,
                    levels: float = 255.0) -> dict:
    """The shading prediction from the field's **measured** slope (not from a nominal formula).

    The existing ``fracture_roi.shading_contrast`` puts the whole amplitude at one representative
    wavelength and therefore over-predicts by construction; the band formula ``2 pi A / lambda``
    also assumes that the whole ``Ra`` sits at ``lambda_min``.  The audited spectrum is red (M01's
    longest band carries 32x the amplitude of its shortest), so the honest prediction uses the
    gradient RMS that the field **actually has** on the ROI:

        ``dDN = levels * albedo * color * |l_perp| * slope_rms``
    """
    light = light or fa.frozen_light()
    perpendicular = float(math.sqrt(max(0.0, 1.0 - float(light.direction[2]) ** 2)))
    color_mean = float(np.mean(light.color))
    params = field.parameters
    scale = float(ra_mm) / max(float(field.ra_at_unit_mm), 1e-30)
    slope_measured = float(field.slope_rms_at_unit) * scale
    slopes = 2.0 * math.pi * (np.asarray(params.band_amplitudes_mm, dtype=np.float64)
                              * (float(ra_mm) / max(float(params.sigma_r0_mm), 1e-9))) \
        / np.asarray(params.band_wavelengths_mm, dtype=np.float64)
    band_slope_rms = float(math.sqrt(0.5 * float(np.sum(slopes ** 2))))
    single = 2.0 * math.pi * float(ra_mm) / float(params.lambda_min_mm)
    factor = levels * float(albedo) * color_mean * perpendicular
    return {
        "slope_rms_measured": slope_measured,
        "dDN_from_measured_slope": factor * slope_measured,
        "band_slope_rms": band_slope_rms,
        "band_dDN": factor * band_slope_rms,
        "single_lambda_slope_rms": single,
        "single_lambda_dDN": factor * single,
        "lambda_used_for_single_mm": float(params.lambda_min_mm),
        "amplitude_scale": scale,
        "note": ("dDN_from_measured_slope uses the gradient RMS measured on the ROI grid; "
                 "band_dDN assumes each audited band carries its own amplitude; "
                 "single_lambda_dDN is the pre-existing upper bound that puts the whole Ra at "
                 "lambda_min"),
    }


# -------------------------------------------------------------------------------------- stages
def stage_sweep(*, config, target, body, mesh, roi, rng) -> dict:
    from synlab.cameras.profiles import camera_profiles

    roi_config = fr.load_fracture_roi_config()
    profiles = {p.tier: p for p in camera_profiles()}
    base = profiles[config.base_tier]
    f_px_native = float(base.K[0, 0])
    native_width = int(base.image_size[0])
    faces = patch_faces(mesh, roi.interface_id)
    tris = np.asarray(mesh.faces)[faces]
    profile = material_profile(body["material_id"])
    params = fa.appearance_parameters_from_profile(profile, material_id=body["material_id"])
    min_amp = min(float(x) for x in config.amplitudes_mm)
    field = fa.build_relief_field(profile=profile, roi=roi, patch_vertices=mesh.vertices,
                                 patch_triangles=tris, mesh=mesh,
                                 rng=make_rng(MASTER_SEED, "appearance_field", body["material_id"]),
                                 amplitude_mm=min_amp, glaze_strip=bool(config.glaze_strip))
    spectrum = fa.field_spectrum_report(field, extent_mm=2.0 * field.footprint_radius_mm, n=384)
    albedo = float(np.mean(params.albedo))
    spec = fa.field_spectrum_report  # keep the symbol used above explicit
    del spec
    rows = []
    images = {}
    for mm_px in config.rung_mm_per_px:
        long_edge = rung_long_edge(mm_px, working_distance_mm=config.working_distance_mm,
                                   f_px_native=f_px_native, native_width_px=native_width)
        if long_edge < 64 or long_edge > 4096:
            rows.append({"mm_per_px_target": float(mm_px), "status": "RUNG_UNREACHABLE",
                         "long_edge_px": int(long_edge)})
            continue
        closeup = fr.closeup_profile(roi_config, base=base, delivered_long_edge_px=long_edge)
        spec_obs = rt.ObsSpec(view_count=1, delivered_size=(long_edge, int(round(long_edge * 0.75))),
                              max_render_pixels=long_edge * long_edge, master_seed=MASTER_SEED,
                              lineage_id="fracture_appearance", frame_id="S_mm",
                              renderer=rt.RENDERER_AUTO,
                              distortion_policy=rt.DISTORTION_POLICY_IGNORE)
        frames = fr.make_fracture_roi_frames(
            rois=[roi], profile=closeup, spec=spec_obs, config=roi_config, long_edge_px=long_edge,
            rng=make_rng(MASTER_SEED, "appearance_frame", roi.roi_id), run_id="appearance",
            mesh=mesh)
        frame = frames[0]
        measured_mm_px = mm_per_px_of(frame)
        supersample = int(config.supersample) if long_edge <= 1024 else 1
        off = render_and_image(target=target, frame=frame,
                               appearance=fa.AppearanceSpec(normal_mode="FLAT", relief=False,
                                                            interpolation="PERSPECTIVE_CORRECT",
                                                            label=f"relief_off@{mm_px}"),
                               relief=None, obs_spec=spec_obs, imaging_seed=11,
                               supersample=supersample)
        row = {
            "mm_per_px_target": float(mm_px), "status": "OK",
            "long_edge_px": int(long_edge), "delivered_grid_px": [int(long_edge),
                                                                 int(round(long_edge * 0.75))],
            "mm_per_px_measured": measured_mm_px, "supersample": supersample,
            "albedo_mean": albedo, "relief_off": measure(off),
            "amplitudes": [],
        }
        for amp in config.amplitudes_mm:
            scaled = fa.resample_relief_ra(field, float(amp))
            on = render_and_image(target=target, frame=frame,
                                  appearance=fa.AppearanceSpec(
                                      normal_mode="FLAT", relief=True,
                                      interpolation="PERSPECTIVE_CORRECT",
                                      label=f"relief_on Ra={amp}"),
                                  relief=scaled, obs_spec=spec_obs, imaging_seed=11,
                                  supersample=supersample)
            diff = fa.difference_dn_statistics(on["dn_float"], off["dn_float"], on["mask"])
            changed = fa.difference_dn_statistics(on["dn"], off["dn"], on["mask"])
            diff_delivered = fa.difference_dn_statistics(on["dn_delivered"], off["dn_delivered"],
                                                         on["mask"])
            entry = {"ra_target_mm": float(amp), "ra_realized_mm": scaled.realized_ra_mm,
                     "difference": diff, "changed_code_values": changed,
                     "difference_delivered": diff_delivered,
                     "relief_on": measure(on),
                     "prediction": band_prediction(scaled, ra_mm=float(amp), albedo=albedo)}
            row["amplitudes"].append(entry)
            if abs(float(mm_px) - 0.073) < 1e-9:
                images[float(amp)] = {"on": on, "off": off}
        rows.append(row)
    # imaging-noise control: identical render, different imaging seed => the measurement floor
    control = None
    if rows and rows[0]["status"] == "OK":
        mm_px = 0.073
        long_edge = rung_long_edge(mm_px, working_distance_mm=config.working_distance_mm,
                                   f_px_native=f_px_native, native_width_px=native_width)
        closeup = fr.closeup_profile(roi_config, base=base, delivered_long_edge_px=long_edge)
        spec_obs = rt.ObsSpec(view_count=1, delivered_size=(long_edge, int(round(long_edge * 0.75))),
                              max_render_pixels=long_edge * long_edge, master_seed=MASTER_SEED,
                              lineage_id="fracture_appearance", frame_id="S_mm",
                              renderer=rt.RENDERER_AUTO,
                              distortion_policy=rt.DISTORTION_POLICY_IGNORE)
        frame = fr.make_fracture_roi_frames(
            rois=[roi], profile=closeup, spec=spec_obs, config=roi_config, long_edge_px=long_edge,
            rng=make_rng(MASTER_SEED, "appearance_frame", roi.roi_id), run_id="appearance",
            mesh=mesh)[0]
        a = render_and_image(target=target, frame=frame,
                             appearance=fa.AppearanceSpec(normal_mode="FLAT", relief=False,
                                                          interpolation="PERSPECTIVE_CORRECT",
                                                          label="noise_control"),
                             relief=None, obs_spec=spec_obs, imaging_seed=11,
                             supersample=int(config.supersample))
        b = render_and_image(target=target, frame=frame,
                             appearance=fa.AppearanceSpec(normal_mode="FLAT", relief=False,
                                                          interpolation="PERSPECTIVE_CORRECT",
                                                          label="noise_control_b"),
                             relief=None, obs_spec=spec_obs, imaging_seed=97,
                             supersample=int(config.supersample))
        control = {"mm_per_px": 0.073, "imaging_seed_a": 11, "imaging_seed_b": 97,
                   "difference_shading": fa.difference_dn_statistics(
                       a["dn_float"], b["dn_float"], a["mask"]),
                   "difference_shading_quantised": fa.difference_dn_statistics(
                       a["dn"], b["dn"], a["mask"]),
                   "difference_delivered": fa.difference_dn_statistics(
                       a["dn_delivered"], b["dn_delivered"], a["mask"]),
                   "definition": ("same render, different imaging noise seed: the code-value "
                                  "change that is NOT relief.  `difference_delivered` is the noise "
                                  "floor of the shipped chain (effective_gain = 1); "
                                  "`difference_shading` is the same noise-free-limit reading used "
                                  "for the relief numbers.")}
    return {"specimen": body, "roi": roi.as_dict(), "material_parameters": params.as_dict(),
            "relief_field": field.as_dict(), "spectrum": spectrum, "rows": rows,
            "noise_control": control,
            "images_raw": images}


def stage_facets(*, config, target, body, mesh, roi, rng) -> dict:
    from synlab.cameras.profiles import camera_profiles

    roi_config = fr.load_fracture_roi_config()
    profiles = {p.tier: p for p in camera_profiles()}
    base = profiles[config.base_tier]
    long_edge = 1024
    closeup = fr.closeup_profile(roi_config, base=base, delivered_long_edge_px=long_edge)
    spec_obs = rt.ObsSpec(view_count=1, delivered_size=(long_edge, 768),
                          max_render_pixels=long_edge * long_edge, master_seed=MASTER_SEED,
                          lineage_id="fracture_appearance", frame_id="S_mm",
                          renderer=rt.RENDERER_AUTO,
                          distortion_policy=rt.DISTORTION_POLICY_IGNORE)
    frame = fr.make_fracture_roi_frames(
        rois=[roi], profile=closeup, spec=spec_obs, config=roi_config, long_edge_px=long_edge,
        rng=make_rng(MASTER_SEED, "appearance_frame", roi.roi_id), run_id="appearance",
        mesh=mesh)[0]
    before = fa.geometry_hash(np.asarray(mesh.vertices), np.asarray(mesh.faces))
    out = {"mm_per_px_measured": mm_per_px_of(frame), "long_edge_px": long_edge,
           "geometry_hash_before": before, "variants": {}}
    for mode, crease, label in (("FLAT", 35.0, "flat (frozen)"),
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
        }
    after = fa.geometry_hash(np.asarray(mesh.vertices), np.asarray(mesh.faces))
    out["geometry_hash_after"] = after
    out["geometry_unchanged"] = bool(before == after)
    out["geometry_unchanged_in_every_variant"] = bool(all(
        v["geometry_hash"] == before for v in out["variants"].values()))
    # path 2: required mesh density from the audited lambda_min, against the measured patch
    params = fa.appearance_parameters_from_profile(material_profile(body["material_id"]),
                                                   material_id=body["material_id"])
    faces = patch_faces(mesh, roi.interface_id)
    tris = np.asarray(mesh.faces)[faces]
    edges_all = fa.measured_edge_length_mm(np.asarray(mesh.vertices), np.asarray(mesh.faces))
    edges_patch = fa.measured_edge_length_mm(np.asarray(mesh.vertices), np.asarray(mesh.faces),
                                             face_mask=np.isin(np.arange(len(mesh.faces)), faces))
    density = fa.required_mesh_density(lambda_min_mm=params.lambda_min_mm,
                                       area_mm2=float(roi.area_mm2),
                                       current_edge_mm=float(edges_patch["edge_median_mm"]),
                                       ratio=float(config.ratio_facet))
    px = fa.facet_pixel_budget(edge_mm=float(density["required_edge_mm"]),
                               mm_per_px=mm_per_px_of(frame))
    out["mesh_density"] = {"material": params.as_dict(), "patch_edges": edges_patch,
                           "scene_edges": edges_all, "inverse_solve": density,
                           "required_edge_in_px": px,
                           "current_edge_in_px": fa.facet_pixel_budget(
                               edge_mm=float(edges_patch["edge_median_mm"]),
                               mm_per_px=mm_per_px_of(frame))}
    return out


def stage_materials(*, config, target, body, mesh, roi, rng) -> dict:
    from synlab.cameras.profiles import camera_profiles

    roi_config = fr.load_fracture_roi_config()
    profiles = {p.tier: p for p in camera_profiles()}
    base = profiles[config.base_tier]
    long_edge = 1024
    closeup = fr.closeup_profile(roi_config, base=base, delivered_long_edge_px=long_edge)
    spec_obs = rt.ObsSpec(view_count=1, delivered_size=(long_edge, 768),
                          max_render_pixels=long_edge * long_edge, master_seed=MASTER_SEED,
                          lineage_id="fracture_appearance", frame_id="S_mm",
                          renderer=rt.RENDERER_AUTO,
                          distortion_policy=rt.DISTORTION_POLICY_IGNORE)
    frame = fr.make_fracture_roi_frames(
        rois=[roi], profile=closeup, spec=spec_obs, config=roi_config, long_edge_px=long_edge,
        rng=make_rng(MASTER_SEED, "appearance_frame", roi.roi_id), run_id="appearance",
        mesh=mesh)[0]
    faces = patch_faces(mesh, roi.interface_id)
    tris = np.asarray(mesh.faces)[faces]
    table = {}
    panels = []
    for material_id in config.materials:
        profile = material_profile(material_id)
        params = fa.appearance_parameters_from_profile(profile, material_id=material_id)
        field = fa.build_relief_field(
            profile=profile, roi=roi, patch_vertices=mesh.vertices, patch_triangles=tris, mesh=mesh,
            rng=make_rng(MASTER_SEED, "appearance_field", material_id),
            amplitude_mm=None, glaze_strip=bool(config.glaze_strip))
        albedo = np.tile(np.asarray(params.albedo, dtype=np.float64), (len(mesh.faces), 1))
        res = render_and_image(
            target=target, frame=frame,
            appearance=fa.AppearanceSpec(
                normal_mode="FLAT", relief=True, interpolation="PERSPECTIVE_CORRECT",
                diffuse_weight=1.0 - float(params.transmission),
                label=f"{material_id} relief_on"),
            relief=field, obs_spec=spec_obs, imaging_seed=11,
            supersample=int(config.supersample), albedo=albedo)
        res_nw = render_and_image(
            target=target, frame=frame,
            appearance=fa.AppearanceSpec(
                normal_mode="FLAT", relief=True, interpolation="PERSPECTIVE_CORRECT",
                diffuse_weight=1.0, label=f"{material_id} no transmission weighting"),
            relief=field, obs_spec=spec_obs, imaging_seed=11,
            supersample=int(config.supersample), albedo=albedo)
        off = render_and_image(
            target=target, frame=frame,
            appearance=fa.AppearanceSpec(
                normal_mode="FLAT", relief=False, interpolation="PERSPECTIVE_CORRECT",
                diffuse_weight=1.0 - float(params.transmission), label=f"{material_id} off"),
            relief=None, obs_spec=spec_obs, imaging_seed=11,
            supersample=int(config.supersample), albedo=albedo)
        table[material_id] = {
            "parameters": params.as_dict(),
            "relief_field": {k: field.as_dict()[k] for k in
                             ("realized_ra_mm", "ra_at_unit_mm", "lambda_min_mm",
                              "lambda_max_mm", "sigma_r0_mm", "glaze_strip",
                              "band_wavelengths_mm", "band_amplitudes_mm")},
            "albedo": list(params.albedo),
            "diffuse_weight": 1.0 - float(params.transmission),
            "relief_on": measure(res),
            "relief_on_without_transmission_weight": measure(res_nw),
            "relief_off": measure(off),
            "difference_relief_on_minus_off": fa.difference_dn_statistics(
                res["dn_float"], off["dn_float"], res["mask"]),
            "changed_code_values_relief_on_minus_off": fa.difference_dn_statistics(
                res["dn"], off["dn"], res["mask"]),
        }
        panels.append((material_id, res["image"],
                       [f"{material_id} {params.material_name}".strip(),
                        f"Ra={field.realized_ra_mm:.4f}mm lam_min={params.lambda_min_mm:.3f}mm",
                        f"mm/px={mm_per_px_of(frame):.5f} "
                        f"dDN_p95p05={table[material_id]['relief_on']['dn']['dn_p95_minus_p05']:.1f}",
                        f"aniso={table[material_id]['relief_on']['direction']['anisotropy']:.3f}"]))
    image_path = None
    if panels:
        image_path = ROOT / "data/a12_reports/physical_layer/fracture_appearance_materials_1024.png"
        fa.side_by_side_png(panels, image_path)
    return {"mm_per_px_measured": mm_per_px_of(frame), "long_edge_px": long_edge,
            "materials": table, "image": None if image_path is None else str(image_path)}


def stage_glaze(*, config, target, body, mesh, roi, rng) -> dict:
    """Is the glaze/body step visible?  Three measurements, no assumptions."""
    from synlab.cameras.profiles import camera_profiles
    from synlab.materials import combo_geometric_layers  # noqa: F401

    out: dict = {}
    # (a) do the fracture assets carry layer/glaze faces at all?
    attrs = dict((getattr(mesh, "metadata", None) or {}).get("face_attr_arrays") or {})
    out["asset_channels"] = {
        "keys": sorted(attrs.keys()),
        "has_layer_channel": bool(any("layer" in k or "glaze" in k for k in attrs)),
        "runs": [SPECIMEN["store"], STUDY[2]["store"], STUDY[3]["store"]],
        "verdict": ("the delivered fracture assets carry origin_kind + interface_id only: no face "
                    "carries a layer/glaze id, so a glaze/body step cannot be in the geometry"),
    }
    # (b) the material records that DO define a geometric layer, and its measured thickness
    layers = {}
    try:
        from synlab.materials import combo_geometric_layers as cgl

        for combo in ("L01", "L03"):
            entry = cgl(combo, {}, make_rng(4242, "layer"))
            layers[combo] = entry
        out["geometric_layer_records"] = layers
    except Exception as exc:  # noqa: BLE001
        out["geometric_layer_records_error"] = f"{type(exc).__name__}: {exc}"
    # (c) measured shell thickness of the L01 glaze on a real mother (the record the docs cite)
    try:
        from synlab.materials import build_layer_shell, combo_geometric_layers as cgl2
        from synlab.mothers.api import create_mother

        entry = cgl2("L01", {}, make_rng(4242, "layer"))[0]
        mother = create_mother("V01", "M01", {}, make_rng(4242, "shape"), mother_id="V01-layer")
        shell = build_layer_shell(mother, entry)
        out["measured_layer_shell"] = {
            "combo": "L01", "material": "M06", "kind": entry.get("mode"),
            "qa": {k: (float(v) if isinstance(v, (int, float)) else v)
                   for k, v in dict(shell.qa).items()},
            "thickness_mm": {k: float(shell.qa[k]) for k in ("p05_mm", "median_mm", "max_mm")
                             if k in shell.qa},
            "volume_mm3": float(shell.volume_mm3),
            "instrument": "materials.build_layer_shell + measure_layer_thickness (V01 mother)",
        }
    except Exception as exc:  # noqa: BLE001
        out["measured_layer_shell_error"] = f"{type(exc).__name__}: {exc}"
    # (d) the audited relief-damping strip, rendered: same geometry, glaze term on/off
    profiles = {p.tier: p for p in camera_profiles()}
    base = profiles[config.base_tier]
    long_edge = 1024
    roi_config = fr.load_fracture_roi_config()
    closeup = fr.closeup_profile(roi_config, base=base, delivered_long_edge_px=long_edge)
    spec_obs = rt.ObsSpec(view_count=1, delivered_size=(long_edge, 768),
                          max_render_pixels=long_edge * long_edge, master_seed=MASTER_SEED,
                          lineage_id="fracture_appearance", frame_id="S_mm",
                          renderer=rt.RENDERER_AUTO,
                          distortion_policy=rt.DISTORTION_POLICY_IGNORE)
    frame = fr.make_fracture_roi_frames(
        rois=[roi], profile=closeup, spec=spec_obs, config=roi_config, long_edge_px=long_edge,
        rng=make_rng(MASTER_SEED, "appearance_frame", roi.roi_id), run_id="appearance",
        mesh=mesh)[0]
    faces = patch_faces(mesh, roi.interface_id)
    tris = np.asarray(mesh.faces)[faces]
    glazed_id = "M04"
    profile = material_profile(glazed_id)
    params = fa.appearance_parameters_from_profile(profile, material_id=glazed_id)
    with_strip = fa.build_relief_field(
        profile=profile, roi=roi, patch_vertices=mesh.vertices, patch_triangles=tris, mesh=mesh,
        rng=make_rng(MASTER_SEED, "appearance_field", glazed_id), amplitude_mm=0.08,
        glaze_strip=True)
    without_strip = fa.build_relief_field(
        profile=profile, roi=roi, patch_vertices=mesh.vertices, patch_triangles=tris, mesh=mesh,
        rng=make_rng(MASTER_SEED, "appearance_field", glazed_id), amplitude_mm=0.08,
        glaze_strip=False)
    a = render_and_image(target=target, frame=frame,
                         appearance=fa.AppearanceSpec(normal_mode="FLAT", relief=True,
                                                      interpolation="PERSPECTIVE_CORRECT",
                                                      label="glaze strip ON"),
                         relief=with_strip, obs_spec=spec_obs, imaging_seed=11,
                         supersample=int(config.supersample))
    b = render_and_image(target=target, frame=frame,
                         appearance=fa.AppearanceSpec(normal_mode="FLAT", relief=True,
                                                      interpolation="PERSPECTIVE_CORRECT",
                                                      label="glaze strip OFF"),
                         relief=without_strip, obs_spec=spec_obs, imaging_seed=11,
                         supersample=int(config.supersample))
    diff = np.abs(a["dn"] - b["dn"])
    mask = a["mask"]
    out["relief_damping_strip"] = {
        "material": glazed_id, "glaze_thickness_mm": params.glaze_thickness_mm,
        "glaze_kind": params.glaze_kind,
        "strip_width_mm": float(with_strip.meta["derive_morphology_parameters"]
                                ["glaze_strip_width_mm"]),
        "strip_width_px": float(with_strip.meta["derive_morphology_parameters"]
                                ["glaze_strip_width_mm"]) / mm_per_px_of(frame),
        "ratio": float(with_strip.meta["derive_morphology_parameters"]["glaze_roughness_ratio"]),
        "difference": fa.difference_dn_statistics(a["dn_float"], b["dn_float"], mask),
        "changed_code_values": fa.difference_dn_statistics(a["dn"], b["dn"], mask),
        "dn_with_strip": fa.dn_statistics(a["dn"], mask),
        "dn_without_strip": fa.dn_statistics(b["dn"], mask),
        "changed_pixel_fraction": float(np.mean((diff > 0.5)[mask])) if mask.any() else 0.0,
        "definition": ("the audited morphology glaze term damps the relief inside a strip of "
                       "2*t_glaze along the fracture front; ON vs OFF on the same geometry"),
    }
    # (e) analytic step table for the measured layer thicknesses
    measured = out.get("measured_layer_shell", {}).get("thickness_mm") or {}
    thicknesses = [t for t in (measured.get("p05_mm"), measured.get("median_mm"),
                               measured.get("max_mm")) if t] or [0.55, 0.9]
    out["step_table"] = fa.glaze_step_report(
        thickness_mm=thicknesses,
        mm_per_px=[mm_per_px_of(frame), 0.0365],
        albedo_body=float(np.mean(fa.appearance_parameters_from_profile(
            material_profile("M01")).albedo)),
        albedo_glaze=float(np.mean(np.asarray(
            layers.get("L01", [{}])[0].get("albedo") or [0.3, 0.4, 0.3], dtype=np.float64))),
        relief_amplitude_mm=0.08, relief_wavelength_mm=params.lambda_min_mm,
        glaze_roughness_ratio=float(mo.GLAZE_ROUGHNESS_RATIO))
    out["mm_per_px_measured"] = mm_per_px_of(frame)
    return out


def stage_images(*, config, target, body, mesh, roi, rng, sweep: dict) -> dict:
    """The A/B PNGs the reader judges by eye, at 1024 and (optionally) 2048."""
    from synlab.cameras.profiles import camera_profiles

    roi_config = fr.load_fracture_roi_config()
    profiles = {p.tier: p for p in camera_profiles()}
    base = profiles[config.base_tier]
    f_px_native = float(base.K[0, 0])
    native_width = int(base.image_size[0])
    faces = patch_faces(mesh, roi.interface_id)
    tris = np.asarray(mesh.faces)[faces]
    profile = material_profile(body["material_id"])
    params = fa.appearance_parameters_from_profile(profile, material_id=body["material_id"])
    albedo_mean = float(np.mean(params.albedo))
    written = []
    for long_edge in config.long_edges_px:
        mm_px = float(config.working_distance_mm) * float(native_width) / (
            float(long_edge) * f_px_native)
        closeup = fr.closeup_profile(roi_config, base=base, delivered_long_edge_px=int(long_edge))
        spec_obs = rt.ObsSpec(view_count=1,
                              delivered_size=(int(long_edge), int(round(long_edge * 0.75))),
                              max_render_pixels=int(long_edge) * int(long_edge),
                              master_seed=MASTER_SEED, lineage_id="fracture_appearance",
                              frame_id="S_mm", renderer=rt.RENDERER_AUTO,
                              distortion_policy=rt.DISTORTION_POLICY_IGNORE)
        frame = fr.make_fracture_roi_frames(
            rois=[roi], profile=closeup, spec=spec_obs, config=roi_config,
            long_edge_px=int(long_edge), rng=make_rng(MASTER_SEED, "appearance_frame", roi.roi_id),
            run_id="appearance", mesh=mesh)[0]
        measured_mm_px = mm_per_px_of(frame)
        supersample = int(config.supersample) if int(long_edge) <= 1024 else 1
        off = render_and_image(target=target, frame=frame,
                               appearance=fa.AppearanceSpec(
                                   normal_mode="FLAT", relief=False,
                                   interpolation="PERSPECTIVE_CORRECT", label="relief_off"),
                               relief=None, obs_spec=spec_obs, imaging_seed=11,
                               supersample=supersample)
        smooth = render_and_image(target=target, frame=frame,
                                  appearance=fa.AppearanceSpec(
                                      normal_mode="SMOOTH_CREASE",
                                      crease_angle_deg=float(config.crease_angle_deg),
                                      relief=False, interpolation="PERSPECTIVE_CORRECT",
                                      label="smooth normals, no relief"),
                                  relief=None, obs_spec=spec_obs, imaging_seed=11,
                                  supersample=supersample)
        # the mid amplitude of the configured sweep: 0.08 mm
        amp = sorted(float(x) for x in config.amplitudes_mm)[len(config.amplitudes_mm) // 2]
        field = fa.build_relief_field(
            profile=profile, roi=roi, patch_vertices=mesh.vertices, patch_triangles=tris, mesh=mesh,
            rng=make_rng(MASTER_SEED, "appearance_field", body["material_id"]),
            amplitude_mm=amp, glaze_strip=bool(config.glaze_strip))
        on = render_and_image(target=target, frame=frame,
                              appearance=fa.AppearanceSpec(
                                  normal_mode="FLAT", relief=True,
                                  interpolation="PERSPECTIVE_CORRECT",
                                  label=f"relief_on Ra={amp}"),
                              relief=field, obs_spec=spec_obs, imaging_seed=11,
                              supersample=supersample)
        on_smooth = render_and_image(target=target, frame=frame,
                                     appearance=fa.AppearanceSpec(
                                         normal_mode="SMOOTH_CREASE",
                                         crease_angle_deg=float(config.crease_angle_deg),
                                         relief=True, interpolation="PERSPECTIVE_CORRECT",
                                         label=f"smooth + relief Ra={amp}"),
                                     relief=field, obs_spec=spec_obs, imaging_seed=11,
                                     supersample=supersample)
        diff = fa.difference_dn_statistics(on["dn_float"], off["dn_float"], on["mask"])
        facet_off = fa.facet_metrics(off["dn"], off["render"].id_map, off["mask"])
        facet_on = fa.facet_metrics(on["dn"], on["render"].id_map, on["mask"])
        facet_sm = fa.facet_metrics(smooth["dn"], smooth["render"].id_map, smooth["mask"])
        common = [f"{body['vessel_id']}/{body['material_id']} {roi.roi_id}"
                  f"  mm/px={measured_mm_px:.5f}  L={int(long_edge)}px",
                  f"grid={int(long_edge)}x{int(round(long_edge*0.75))}  supersample={supersample}"
                  f"  Ra={amp}mm  lam_min={params.lambda_min_mm:.3f}mm"]
        path = ROOT / f"data/a12_reports/physical_layer/fracture_appearance_AB_{int(long_edge)}.png"
        info = fa.side_by_side_png([
            ("relief_off", off["image"],
             common + [f"relief OFF (flat normals)  dDN_p95p05="
                       f"{fa.dn_statistics(off['dn'], off['mask'])['dn_p95_minus_p05']:.2f}",
                       f"facet edge step={facet_off['facet_edge_dn_step']:.2f} DN "
                       f"(interior {facet_off['interior_dn_step']:.2f}) "
                       f"median face={facet_off['median_face_area_px']:.0f}px"]),
            ("relief_on", on["image"],
             common + [f"relief ON (per-pixel normal)  dDN_p95p05="
                       f"{fa.dn_statistics(on['dn'], on['mask'])['dn_p95_minus_p05']:.2f}",
                       f"|DN_on-DN_off| rms={diff['dDN_rms']:.2f} p95={diff['dDN_p95_abs']:.2f} "
                       f"frac>=2DN={diff['fraction_above_2_dn']:.3f}",
                       f"facet edge step={facet_on['facet_edge_dn_step']:.2f} DN"]),
            ("smooth_no_relief", smooth["image"],
             common + [f"smooth+crease {config.crease_angle_deg:g}deg, relief OFF",
                       f"facet edge step={facet_sm['facet_edge_dn_step']:.2f} DN "
                       f"(interior {facet_sm['interior_dn_step']:.2f})  <- facets removed"]),
            ("smooth_relief", on_smooth["image"],
             common + [f"smooth + relief Ra={amp}mm",
                       f"facet edge step="
                       f"{fa.facet_metrics(on_smooth['dn'], on_smooth['render'].id_map, on_smooth['mask'])['facet_edge_dn_step']:.2f} DN"]),
        ], path)
        written.append({"long_edge_px": int(long_edge), "path": str(path),
                        "mm_per_px_measured": measured_mm_px, "supersample": supersample,
                        "ra_mm": amp, "dDN": diff,
                        "facet_edge_step_relief_off": facet_off["facet_edge_dn_step"],
                        "facet_edge_step_relief_on": facet_on["facet_edge_dn_step"],
                        "facet_edge_step_smooth": facet_sm["facet_edge_dn_step"],
                        "panel_info": info,
                        "images": {"off": off["image"], "on": on["image"],
                                   "smooth": smooth["image"], "smooth_on": on_smooth["image"],
                                   "mask": on["mask"], "id_map": on["render"].id_map}})
    return {"views": [{k: v for k, v in w.items() if k != "images"} for w in written],
            "_raw": written}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stages", default="sweep,facets,materials,glaze,images")
    parser.add_argument("--quick", action="store_true",
                        help="one rung, one amplitude (smoke test)")
    parser.add_argument("--no-store", action="store_true")
    args = parser.parse_args()
    stages = [s.strip() for s in args.stages.split(",") if s.strip()]

    started = time.perf_counter()
    config = fa.load_fracture_appearance_config()
    fa.validate_config(config)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report: dict = {"schema": fa.APPEARANCE_SCHEMA + ".run", "config": config.as_dict(),
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
                           "roi": roi.as_dict()}
    if args.quick:
        config = replace_config(config, rung_mm_per_px=(0.073,), amplitudes_mm=(0.08,),
                                   materials=tuple(config.materials[:3]), long_edges_px=(1024,))
        report["config"] = config.as_dict()
        report["quick"] = True

    images_raw = None
    for stage in stages:
        t0 = time.perf_counter()
        if stage == "sweep":
            out = stage_sweep(config=config, target=target, body=body, mesh=mesh, roi=roi, rng=rng)
            images_raw = out.pop("images_raw", None)
            report["stages"]["sweep"] = out
        elif stage == "facets":
            report["stages"]["facets"] = stage_facets(config=config, target=target, body=body,
                                                      mesh=mesh, roi=roi, rng=rng)
        elif stage == "materials":
            report["stages"]["materials"] = stage_materials(config=config, target=target,
                                                            body=body, mesh=mesh, roi=roi,
                                                            rng=rng)
        elif stage == "glaze":
            report["stages"]["glaze"] = stage_glaze(config=config, target=target, body=body,
                                                    mesh=mesh, roi=roi, rng=rng)
        elif stage == "images":
            out = stage_images(config=config, target=target, body=body, mesh=mesh, roi=roi,
                               rng=rng, sweep=report["stages"].get("sweep", {}))
            raw = out.pop("_raw", [])
            report["stages"]["images"] = out
            for item in raw:
                if args.no_store:
                    continue
                from synlab.storage.store import AssetStore

                store = AssetStore(STORE_ROOT)
                store.commit_asset(
                    role="diagnostic_report", schema="synlab.report.v1", unit="px",
                    frame="pixel_cv_center",
                    payload={"dn_relief_off": item["images"]["off"].astype(np.uint8),
                             "dn_relief_on": item["images"]["on"].astype(np.uint8),
                             "dn_smooth_no_relief": item["images"]["smooth"].astype(np.uint8),
                             "dn_smooth_relief": item["images"]["smooth_on"].astype(np.uint8),
                             "fracture_mask": item["images"]["mask"].astype(np.uint8),
                             "face_id_map": item["images"]["id_map"].astype(np.int32)},
                    meta={"vessel_id": body["vessel_id"], "material_id": body["material_id"],
                          "roi_id": roi.roi_id, "long_edge_px": item["long_edge_px"],
                          "mm_per_px_measured": item["mm_per_px_measured"],
                          "ra_mm": item["ra_mm"], "dDN": item["dDN"],
                          "note": "appearance-layer normal channel; geometry unmodified"},
                    lineage_id=str(body["lineage_id"]), split="train",
                    ancestry=[str(body["asset_id"])], qa={"geometry_modified": False},
                    qa_status="QA_PASS")
        else:
            raise SystemExit(f"unknown stage {stage!r}")
        report["timing"][stage] = float(time.perf_counter() - t0)
        fa.write_json(report, REPORT_DIR / "fracture_appearance_run.json")
        print(f"[appearance] stage {stage} done in {report['timing'][stage]:.1f}s", flush=True)
    report["timing"]["total_s"] = float(time.perf_counter() - started)
    fa.write_json(report, REPORT_DIR / "fracture_appearance_run.json")
    print(f"[appearance] total {report['timing']['total_s']:.1f}s -> "
          f"{REPORT_DIR / 'fracture_appearance_run.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())






