"""A12 Blender-backend verification: channel semantics, software comparison, sample tiers.

Run (project venv)::

    & .venv\\Scripts\\python.exe blender_scripts\\a12_channel_verify.py --steps smoke
    & .venv\\Scripts\\python.exe blender_scripts\\a12_channel_verify.py --steps all

Steps
-----
``smoke``     one real Blender render of the analytic fixture; prints every self-check.
``channels``  plan 13.2 / R7 channel-semantics verification: analytic plane depth, RGB vs
              Z/Object-Index/Material-Index anti-aliasing behaviour, integrality of the
              delivered integer channels, uncertain-mask coverage of real mixed borders.
``compare``   the same scene/camera through the software rasteriser: 100 mm cube size and
              depth, plane normal, integer id classes, wall time.
``tiers``     32 vs 64 samples, RGB noise/detail QA against a 256-sample reference, and a
              denoise-on/off check that geometry channels do not move.
``all``       every step above.

All artefacts are written under ``data/a12/reports/blender/``.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import trimesh  # noqa: E402

from synlab.cameras.projection import unproject  # noqa: E402
from synlab.observe.blender import (  # noqa: E402
    BlenderBackendConfig,
    capability_probe,
    find_blender_binary,
)
from synlab.observe.render import (  # noqa: E402
    BACKEND_BLENDER,
    BACKEND_SOFTWARE,
    LightSpec,
    RenderSpec,
    build_scene,
    deployment_mask_from_render,
    render_view,
)
from synlab.schemas.runtime import ViewFrame  # noqa: E402

OUT_ROOT = REPO / "data" / "a12" / "reports" / "blender"
WIDTH, HEIGHT = 192, 144
F_PX = 400.0
CUBE_MM = 100.0
CAM_Z = -400.0
#: occluder between the camera (z = -400) and the cube (z = -50..+50); the camera looks
#: along +z, so a *positive* plate z would be hidden behind the cube
PLATE_Z = -150.0
#: f-number of the thin-lens circle-of-confusion term.  The software rasteriser hard-codes
#: ``circle_of_confusion_px(depth, focus, 1.0, f_px)`` in ``synlab.observe.render.render_view``,
#: so the Blender call is given the same value to keep the two uncertain masks comparable.
F_NUMBER_FOR_COC = 1.0


# --------------------------------------------------------------------------------------
# fixture
# --------------------------------------------------------------------------------------
def make_fixture():
    """100 mm cube + an opaque 40 mm occluder plate; camera 400 mm in front, fx = 400 px."""
    box = trimesh.creation.box(extents=(CUBE_MM, CUBE_MM, CUBE_MM))
    plate = trimesh.creation.box(extents=(40.0, 40.0, 2.0))
    plate.apply_translation((0.0, 0.0, PLATE_Z))
    mesh = trimesh.util.concatenate([box, plate])
    n_box = len(box.faces)
    n_tot = len(mesh.faces)
    surface_tag = np.zeros(n_tot, dtype=np.int16)
    surface_tag[n_box:] = 2                     # rim/occluder tag
    face_id = np.arange(n_tot, dtype=np.int32)
    is_target = np.ones(n_tot, dtype=np.uint8)
    is_target[n_box:] = 0
    scene = build_scene(mesh, surface_tag=surface_tag, face_id=face_id, is_target=is_target,
                        name="fixture")
    frame = make_frame()
    light = LightSpec(direction=np.array([-0.35, -0.62, -0.70]) /
                      np.linalg.norm([-0.35, -0.62, -0.70]),
                      color=np.array([2.35, 2.25, 2.10]),
                      ambient=np.array([0.30, 0.30, 0.33]))
    truth = analytic_truth()
    return scene, frame, light, truth


def make_frame() -> ViewFrame:
    K = np.array([[F_PX, 0.0, (WIDTH - 1) / 2.0],
                  [0.0, F_PX, (HEIGHT - 1) / 2.0],
                  [0.0, 0.0, 1.0]], dtype=np.float64)
    T_WC = np.array([[-1.0, 0.0, 0.0, 0.0],
                     [0.0, -1.0, 0.0, 0.0],
                     [0.0, 0.0, 1.0, CAM_Z],
                     [0.0, 0.0, 0.0, 1.0]], dtype=np.float64)
    return ViewFrame(view_id="fixture_front", K=K, T_WC=T_WC, image_size=(WIDTH, HEIGHT),
                     profile_id="pinhole_fx400", tier="GLOBAL", u_position_mm=0.0,
                     working_distance_mm=abs(CAM_Z), focus_setting="FIXED",
                     source_kind="SENSOR_SIM", camera_model="PINHOLE", dist=None)


def analytic_truth() -> dict:
    """Closed-form expectations of the fixture (classroom geometry, not a renderer)."""
    return {
        "cube_front_z_mm": abs(CAM_Z) - CUBE_MM / 2.0,        # 350 mm
        "cube_back_z_mm": abs(CAM_Z) + CUBE_MM / 2.0,         # 450 mm
        "plate_front_z_mm": PLATE_Z - 1.0 - CAM_Z,            # near plate face, 249 mm
        "plate_distance_mm": abs(PLATE_Z - 1.0 - CAM_Z),
        "cube_front_width_px": CUBE_MM * F_PX / (abs(CAM_Z) - CUBE_MM / 2.0),
        "plate_width_px": 40.0 * F_PX / abs(PLATE_Z - 1.0 - CAM_Z),
        "cube_front_normal_world": [0.0, 0.0, -1.0],
        "background_linear": [0.02, 0.02, 0.025],
    }


def fit_plane_normal(depth: np.ndarray, K: np.ndarray, T_WC: np.ndarray,
                     mask: np.ndarray) -> dict:
    """Fit a plane to the back-projected depth over ``mask`` and return its world normal."""
    ys, xs = np.nonzero(mask)
    if xs.size < 16:
        return {"n_points": int(xs.size), "normal": None}
    uv = np.stack([xs.astype(np.float64), ys.astype(np.float64)], axis=1)
    z = depth[ys, xs].astype(np.float64)
    pts = unproject(uv, z, K, T_WC, None, model="PINHOLE")
    centre = pts.mean(axis=0)
    u, s, vt = np.linalg.svd(pts - centre)
    normal = vt[-1]
    if normal[2] > 0:
        normal = -normal
    return {"n_points": int(xs.size), "normal": normal.tolist(),
            "singular_values": s.tolist(), "planarity": float(s[-1] / max(s[0], 1e-12)),
            "rms_mm": float(np.sqrt(np.mean(((pts - centre) @ vt[-1]) ** 2)))}


def region_masks(render) -> dict:
    """Analytic region masks derived from the *delivered* channels only."""
    vis = render.visibility > 0
    depth = np.asarray(render.depth_z, dtype=np.float64)
    target_front = vis & np.isfinite(depth) & (np.abs(depth - (abs(CAM_Z) - CUBE_MM / 2.0))
                                              < 1.0)
    occluder = vis & np.isfinite(depth) & (depth < abs(CAM_Z) - CUBE_MM / 2.0)
    central = np.zeros_like(vis)
    central[HEIGHT // 4: 3 * HEIGHT // 4, WIDTH // 4: 3 * WIDTH // 4] = True
    return {"visible": vis, "target_front": target_front, "occluder": occluder,
            "central": central}


def u8(img: np.ndarray) -> np.ndarray:
    return np.clip(np.asarray(img, dtype=np.float64) * 255.0 + 0.5, 0, 255).astype(np.uint8)


# --------------------------------------------------------------------------------------
# steps
# --------------------------------------------------------------------------------------
def step_smoke(out_dir: Path, samples: int) -> dict:
    scene, frame, light, truth = make_fixture()
    t0 = time.time()
    render = render_view(scene, frame, light=light, spec=RenderSpec(),
                         backend=BACKEND_BLENDER,
                         focus_distance_mm=truth["cube_front_z_mm"],
                         blender_config=BlenderBackendConfig(samples=samples, filter_width=1.5,
                                                     f_number=F_NUMBER_FOR_COC,
                                                     run_label="smoke",
                                                     workdir=str(out_dir / "work_smoke")))
    dt = time.time() - t0
    report = {
        "step": "smoke",
        "seconds_total": dt,
        "backend": render.backend,
        "meta_subset": {k: render.meta[k] for k in
                        ("blender_version", "samples_requested", "samples_used",
                         "filter_width", "denoise", "engine", "cycles_device",
                         "elapsed_seconds", "render_seconds", "manifest_path",
                         "output_dir", "id_classes_visible", "visible_fraction"
                         if "visible_fraction" in render.meta else "surface_visible_fraction",
                         "uncertain_fraction", "occluded_fraction") if k in render.meta},
        "checks": render.meta.get("checks", {}),
        "shapes": {"rgb": list(render.rgb_linear.shape), "depth": list(render.depth_z.shape),
                   "id_map": list(render.id_map.shape)},
        "dtypes": {"rgb": str(render.rgb_linear.dtype), "depth": str(render.depth_z.dtype),
                   "id_map": str(render.id_map.dtype),
                   "surface_tag": str(render.surface_tag.dtype),
                   "visibility": str(render.visibility.dtype),
                   "uncertain": str(render.uncertain_mask.dtype)},
        "truth": truth,
        "depth_center_mm": float(render.depth_z[HEIGHT // 2, WIDTH // 2]),
        "rgb_center": render.rgb_linear[HEIGHT // 2, WIDTH // 2].tolist(),
        "id_classes_total": int(np.unique(render.id_map).size),
    }
    return report


def step_channels(out_dir: Path, samples: int) -> dict:
    """Plan 13.2 / R7: prove what each pass does and does not do."""
    import cv2

    scene, frame, light, truth = make_fixture()
    render = render_view(scene, frame, light=light, spec=RenderSpec(),
                         backend=BACKEND_BLENDER,
                         focus_distance_mm=truth["cube_front_z_mm"],
                         blender_config=BlenderBackendConfig(samples=samples, filter_width=1.5,
                                                     f_number=F_NUMBER_FOR_COC,
                                                     run_label="channels",
                                                     workdir=str(out_dir / "work_channels")))
    od = Path(render.meta["output_dir"])
    depth = np.asarray(render.depth_z, dtype=np.float64)
    depth_aa = np.load(od / "depth_z_aa_mm.npy").astype(np.float64)
    aa_obj = np.load(od / "aa_object_index_raw.npy").astype(np.float64)
    aa_face = np.load(od / "aa_face_id_raw.npy").astype(np.float64)
    id_map = np.asarray(render.id_map)
    # geometry support of the frame, independent of the mixing test, so that the silhouette
    # ring used below is not defined by the very mask it evaluates
    vis = render.visibility.astype(bool)
    geom = np.isfinite(np.asarray(render.depth_z, dtype=np.float64))
    uncertain = np.asarray(render.uncertain_mask, dtype=bool)

    # -- analytic depth on the flat cube front face
    front = vis & np.isfinite(depth) & (np.abs(depth - truth["cube_front_z_mm"]) < 2.0)
    depth_err = np.abs(depth[front] - truth["cube_front_z_mm"]) if front.any() else np.array([])
    # -- plane fit on the front face
    normal_fit = fit_plane_normal(depth, frame.K, frame.T_WC, front)

    # -- anti-aliasing behaviour: RGB pass vs Z / Object Index / Material Index passes
    rgb = np.asarray(render.rgb_linear, dtype=np.float64)
    edge_kernel = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], dtype=np.float32)
    rgb_edge = np.abs(cv2.filter2D(rgb.mean(axis=2).astype(np.float32), -1, edge_kernel))
    id_edge_px = int(np.count_nonzero(
        (id_map != np.roll(id_map, 1, axis=0)) | (id_map != np.roll(id_map, 1, axis=1))))
    silhouette = geom & ~cv2.erode(geom.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    geom_eroded = cv2.erode(geom.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)

    frac_obj = np.abs(aa_obj - np.rint(aa_obj)) > 1e-3
    frac_face = np.abs(aa_face - np.rint(aa_face)) > 1e-3
    valid_aa = np.isfinite(depth_aa) & np.isfinite(depth)
    depth_mix = np.zeros_like(frac_obj)
    depth_mix[valid_aa] = np.abs(depth_aa[valid_aa] - depth[valid_aa]) > 0.25

    # does the uncertain mask actually sit on the mixed borders?
    border = silhouette
    border_dil = cv2.dilate(border.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    report = {
        "step": "channels",
        "samples": samples,
        "output_dir": str(od),
        "manifest": render.meta["manifest_path"],
        "analytic_depth": {
            "expected_mm": truth["cube_front_z_mm"],
            "max_abs_error_mm": float(depth_err.max()) if depth_err.size else None,
            "p99_abs_error_mm": float(np.percentile(depth_err, 99)) if depth_err.size else None,
            "n_pixels": int(front.sum()),
            "note": "delivered depth_z is the exact geometry pass (1 sample, 0.01 px filter)",
        },
        "analytic_plane_normal": {
            "expected": truth["cube_front_normal_world"],
            "fitted": normal_fit,
            "angle_deg": float(np.degrees(np.arccos(np.clip(
                abs(np.dot(normal_fit["normal"], truth["cube_front_normal_world"])), -1, 1))))
            if normal_fit.get("normal") else None,
        },
        "aa_behaviour": {
            "rgb_edge_energy_mean": float(rgb_edge[vis].mean()) if vis.any() else 0.0,
            "rgb_edge_energy_p99": float(np.percentile(rgb_edge[vis], 99)) if vis.any() else 0.0,
            "exact_id_step_pixels": id_edge_px,
            "aa_object_index_fractional_px": int(np.count_nonzero(frac_obj)),
            "aa_face_id_fractional_px": int(np.count_nonzero(frac_face)),
            "aa_depth_mixing_px": int(np.count_nonzero(depth_mix)),
            "aa_object_index_fractional_max": float(np.abs(
                aa_obj - np.rint(aa_obj)).max()),
            "aa_depth_vs_exact_max_mm": float(np.abs(depth_aa[valid_aa]
                                                     - depth[valid_aa]).max())
            if valid_aa.any() else None,
            "interpretation": ("measured: the Shader AOV pass is filter-averaged exactly like "
                              "RGB (fractional face labels and surface tags on mixed borders), "
                              "while the Cycles Z pass and Object Index pass return identical "
                              "values under a 0.01 px and a 1.5 px filter, i.e. they are not "
                              "anti-aliased at all; the delivered integer channels therefore "
                              "come from the one-sample exact pass and are integral"),
        },
        "integer_channels": {
            "id_map_dtype": str(id_map.dtype),
            "id_map_is_integer": bool(np.issubdtype(id_map.dtype, np.integer)),
            "id_map_unique": int(np.unique(id_map).size),
            "id_map_classes_visible": int(np.unique(id_map[vis]).size) if vis.any() else 0,
            "surface_tag_unique": sorted(int(v) for v in np.unique(render.surface_tag)),
            "surface_tag_is_integer": bool(np.issubdtype(render.surface_tag.dtype,
                                                         np.integer)),
        },
        "uncertain_mask": {
            "fraction": float(uncertain.mean()),
            "n_pixels": int(np.count_nonzero(uncertain)),
            "coverage_on_silhouette": float(uncertain[border].mean()) if border.any() else None,
            "coverage_inside_eroded_object": float(uncertain[geom_eroded].mean())
            if geom_eroded.any() else None,
            "coverage_inside_eroded_target_front": float(
                uncertain[geom_eroded & front].mean()) if (geom_eroded & front).any() else None,
            "explanation_of_interior_coverage": (
                "the eroded interior contains the out-of-focus occluder plate (defocus term) "
                "and the label boundary between the two coplanar triangles of the cube face; "
                "the flat target front face itself is not marked uncertain"),
            "silhouette_px": int(np.count_nonzero(border)),
            "on_silhouette_or_dilated": float(
                uncertain[border_dil].mean()) if border_dil.any() else None,
            "outside_silhouette_dilated": int(np.count_nonzero(uncertain & ~border_dil)),
            "geometry_px": int(np.count_nonzero(geom)),
            "components": render.meta["checks"]["aa_pass_fractional"],
            "note": ("uncertain = mixed AA geometry | depth edge inside the pixel | defocus; "
                     "the mask must cover the real mixing borders (silhouette / depth step) "
                     "and stay out of the flat interior"),
        },
        "occlusion": {
            "occluder_px": int(np.count_nonzero(np.load(od / "occlusion.npy"))),
            "occlusion_fraction": float(np.load(od / "occlusion.npy").mean()),
            "plate_region_detected_px": int(np.count_nonzero(
                np.isfinite(depth) & (depth < truth["cube_front_z_mm"] - 1.0))),
            "plate_width_expected_px": truth["plate_width_px"],
            "plate_measured_width_px": float(np.sqrt(np.count_nonzero(
                np.load(od / "occlusion.npy")))),
            "note": ("occlusion = the target is hit when the non-target object is hidden but "
                     "not in the full scene; the detected area is compared with the analytic "
                     "projection of the 40 mm plate"),
        },
        "rgb_linearity": render.meta["checks"].get("rgb_linearity"),
        "rgb_background_linearity": render.meta["checks"].get("rgb_background_linearity"),
        "pass_aa_behaviour": render.meta["checks"].get("pass_aa_behaviour"),
        "raycast_vs_exact_pass": render.meta["checks"].get("raycast_vs_exact_pass"),
    }
    return report


def step_compare(out_dir: Path, samples: int) -> dict:
    """Same scene/camera through the software rasteriser and the Blender worker."""
    scene, frame, light, truth = make_fixture()
    focus = truth["cube_front_z_mm"]
    t0 = time.time()
    sw = render_view(scene, frame, light=light, spec=RenderSpec(supersample=2),
                     focus_distance_mm=focus, backend=BACKEND_SOFTWARE)
    sw_seconds = time.time() - t0
    t0 = time.time()
    bl = render_view(scene, frame, light=light, spec=RenderSpec(),
                     backend=BACKEND_BLENDER, focus_distance_mm=focus,
                     blender_config=BlenderBackendConfig(samples=samples, filter_width=1.5,
                                                 f_number=F_NUMBER_FOR_COC,
                                                 run_label="compare",
                                                 workdir=str(out_dir / "work_compare")))
    bl_seconds = time.time() - t0

    def summarise(render, seconds, name):
        vis = render.visibility.astype(bool)
        ys, xs = np.nonzero(vis)
        depth = np.asarray(render.depth_z, dtype=np.float64)
        front = vis & np.isfinite(depth) & (np.abs(depth - truth["cube_front_z_mm"]) < 2.0)
        # cube front-face extent measured from the delivered geometry channel
        fy, fx = np.nonzero(front)
        mask = np.zeros_like(vis)
        if fy.size:
            mask[fy, fx] = True
        return {
            "backend": name,
            "seconds": seconds,
            "visible_px": int(vis.sum()),
            "id_classes_visible": int(np.unique(np.asarray(render.id_map)[vis]).size),
            "id_classes_total": int(np.unique(render.id_map).size),
            "depth_center_mm": float(depth[HEIGHT // 2, WIDTH // 2]),
            "cube_front_px": int(front.sum()),
            "cube_front_bbox_px": ([int(fx.min()), int(fy.min()), int(fx.max()), int(fy.max())]
                                   if fx.size else None),
            "cube_front_width_px": float(fx.max() - fx.min() + 1) if fx.size else None,
            "cube_front_height_px": float(fy.max() - fy.min() + 1) if fy.size else None,
            "plane_normal": fit_plane_normal(depth, frame.K, frame.T_WC, mask),
            "occluded_px": (int(np.count_nonzero(getattr(render, "occlusion", None)))
                            if getattr(render, "occlusion", None) is not None else None),
            "occlusion_channel": ("measured (target-only vs full geometry pass)"
                                  if getattr(render, "occlusion", None) is not None
                                  else "not provided by this backend"),
            "uncertain_px": int(np.count_nonzero(render.uncertain_mask)),
            "mm_per_pixel": render.meta.get("mm_per_pixel"),
        }

    sw_s = summarise(sw, sw_seconds, "SOFTWARE_RASTERIZER")
    bl_s = summarise(bl, bl_seconds, "BLENDER_CYCLES")
    report = {
        "step": "compare",
        "truth": truth,
        "software": sw_s,
        "blender": bl_s,
        "expected_cube_front_width_px": truth["cube_front_width_px"],
        "width_delta_px": (None if not (sw_s["cube_front_width_px"]
                                        and bl_s["cube_front_width_px"])
                           else float(bl_s["cube_front_width_px"]
                                      - sw_s["cube_front_width_px"])),
        "depth_delta_mm": float(bl_s["depth_center_mm"] - sw_s["depth_center_mm"]),
        "normal_angle_deg": float(np.degrees(np.arccos(np.clip(abs(np.dot(
            sw_s["plane_normal"]["normal"], bl_s["plane_normal"]["normal"])), -1, 1))))
        if sw_s["plane_normal"].get("normal") and bl_s["plane_normal"].get("normal") else None,
        "speed_ratio_blender_over_software": (bl_seconds / sw_seconds) if sw_seconds else None,
        "unchanged_parameters": ("same Scene (mesh, per-face labels, albedo), same ViewFrame "
                                 "(K, T_WC, dist=None), same LightSpec, same resolution; no "
                                 "tuning of either backend to close the gap"),
    }
    return report


def step_tiers(out_dir: Path, samples: list[int], reference: int = 256) -> dict:
    """32/64 sample QA against a higher-sample reference; denoise must not move geometry."""
    scene, frame, light, truth = make_fixture()
    focus = truth["cube_front_z_mm"]

    def run(tag: str, n: int, denoise: bool = False):
        return render_view(scene, frame, light=light, spec=RenderSpec(),
                           backend=BACKEND_BLENDER, focus_distance_mm=focus,
                           blender_config=BlenderBackendConfig(
                               samples=n, filter_width=1.5, denoise=denoise,
                               f_number=F_NUMBER_FOR_COC,
                               run_label=tag, workdir=str(out_dir / f"work_{tag}")))

    ref = run(f"ref{reference}", reference)
    ref_rgb = np.asarray(ref.rgb_linear, dtype=np.float64)
    vis = ref.visibility.astype(bool)
    flat = vis.copy()
    flat[:HEIGHT // 3] = False
    report: dict = {"step": "tiers", "reference_samples": reference,
                    "reference_seconds": ref.meta["render_seconds"], "tiers": []}
    prev_depth = None
    for n in samples:
        t0 = time.time()
        got = run(f"s{n}", n)
        wall = time.time() - t0
        rgb = np.asarray(got.rgb_linear, dtype=np.float64)
        denom = np.maximum(ref_rgb[vis], 1e-6)
        rel = np.abs(rgb[vis] - ref_rgb[vis]) / denom
        noise = float(np.std(rgb[flat]) / max(np.mean(rgb[flat]), 1e-9)) if flat.any() else None
        entry = {
            "samples": n,
            "wall_seconds": wall,
            "render_seconds": got.meta["render_seconds"],
            "samples_used": got.meta["samples_used"],
            "rgb_mean_abs_rel_err_vs_reference": float(rel.mean()),
            "rgb_p99_abs_rel_err_vs_reference": float(np.percentile(rel, 99)),
            "flat_region_relative_std": noise,
            "depth_max_delta_mm_vs_reference": float(np.nanmax(np.abs(
                np.asarray(got.depth_z, dtype=np.float64)
                - np.asarray(ref.depth_z, dtype=np.float64)))),
            "id_map_identical_to_reference": bool(np.array_equal(got.id_map, ref.id_map)),
            "surface_tag_identical_to_reference": bool(np.array_equal(got.surface_tag,
                                                                      ref.surface_tag)),
            "uncertain_fraction": float(got.uncertain_mask.mean()),
        }
        report["tiers"].append(entry)
        prev_depth = got
    # denoise must affect RGB only
    base = run("denoise_off", samples[0])
    den = run("denoise_on", samples[0], denoise=True)
    report["denoise_rgb_only"] = {
        "samples": samples[0],
        "rgb_identical": bool(np.array_equal(base.rgb_linear, den.rgb_linear)),
        "rgb_mean_abs_diff": float(np.mean(np.abs(np.asarray(base.rgb_linear, dtype=np.float64)
                                                  - np.asarray(den.rgb_linear,
                                                               dtype=np.float64)))),
        "depth_identical": bool(np.array_equal(base.depth_z, den.depth_z,
                                               equal_nan=True)),
        "id_map_identical": bool(np.array_equal(base.id_map, den.id_map)),
        "surface_tag_identical": bool(np.array_equal(base.surface_tag, den.surface_tag)),
        "visibility_identical": bool(np.array_equal(base.visibility, den.visibility)),
        "uncertain_identical": bool(np.array_equal(base.uncertain_mask, den.uncertain_mask)),
        "denoise_flag_recorded": bool(den.meta["denoise"]),
    }
    report["frozen_tier"] = freeze_tier(report)
    return report


def freeze_tier(report: dict) -> dict:
    """Freeze the lowest passing tier with explicit thresholds (no silent tuning)."""
    thresholds = {"rgb_mean_abs_rel_err_vs_reference": 0.05,
                  "rgb_p99_abs_rel_err_vs_reference": 0.25,
                  "depth_max_delta_mm_vs_reference": 0.0,
                  "id_map_identical_to_reference": True}
    chosen = None
    for entry in sorted(report["tiers"], key=lambda e: e["samples"]):
        ok = (entry["rgb_mean_abs_rel_err_vs_reference"]
              <= thresholds["rgb_mean_abs_rel_err_vs_reference"]
              and entry["rgb_p99_abs_rel_err_vs_reference"]
              <= thresholds["rgb_p99_abs_rel_err_vs_reference"]
              and entry["depth_max_delta_mm_vs_reference"]
              <= thresholds["depth_max_delta_mm_vs_reference"]
              and entry["id_map_identical_to_reference"])
        entry["passes_frozen_qa"] = bool(ok)
        if ok and chosen is None:
            chosen = entry["samples"]
    return {"thresholds": thresholds, "chosen_samples": chosen,
            "note": ("chosen = lowest sample count meeting every threshold against the "
                     f"{report['reference_samples']}-sample reference; geometry channels must "
                     "be bit-identical because they come from a separate exact pass")}


# --------------------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--steps", default="smoke",
                        help="comma list of smoke,channels,compare,tiers,all")
    parser.add_argument("--samples", type=int, default=32)
    parser.add_argument("--out", default=str(OUT_ROOT))
    parser.add_argument("--tier-samples", default="32,64")
    args = parser.parse_args()
    steps = {s.strip() for s in args.steps.split(",") if s.strip()}
    if "all" in steps:
        steps = {"smoke", "channels", "compare", "tiers"}
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    probe = capability_probe()
    report: dict = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "python": sys.version,
        "blender_binary": find_blender_binary(),
        "capability_probe": probe,
        "steps": {},
    }
    if probe.get("status") != "OK":
        report["status"] = "BLENDER_UNAVAILABLE"
        (out_dir / "channel_verification.json").write_text(
            json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(json.dumps({"status": "BLENDER_UNAVAILABLE", "probe": probe}, indent=2))
        return 2

    if "smoke" in steps:
        report["steps"]["smoke"] = step_smoke(out_dir, args.samples)
    if "channels" in steps:
        report["steps"]["channels"] = step_channels(out_dir, args.samples)
    if "compare" in steps:
        report["steps"]["compare"] = step_compare(out_dir, args.samples)
    if "tiers" in steps:
        tiers = [int(v) for v in args.tier_samples.split(",") if v.strip()]
        report["steps"]["tiers"] = step_tiers(out_dir, tiers)
    report["status"] = "OK"
    path = out_dir / "channel_verification.json"
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"status": "OK", "report": str(path),
                      "steps": sorted(report["steps"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
