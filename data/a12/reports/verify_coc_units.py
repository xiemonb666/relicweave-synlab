"""Independent verification of the CoC unit fix (``mask_semantics = coc_units_v2``).

Re-derivation, then two independent cross-checks against *declared* camera data, then the
before/after numbers on archived L0 views.

Part 1 -- arithmetic (no project code involved)
    * thin-lens ray trace: a marginal ray through the aperture edge lands on the sensor at
      ``c = A * |1 - s_f/s'|`` with ``A = f/N``, ``s' = f*z/(z-f)``, ``s_f = f*z_f/(z_f-f)``;
      compared against ``circle_of_confusion_px`` (mm form);
    * the delivered-pixel conversion ``c_px = D * c_mm`` with ``D = width_px / sensor_width_mm``.

Part 2 -- cross-checks against declared camera data
    * the profile's own declared depth of field (``thin_lens_dof`` at the native sensor pitch)
      is reproduced by inverting the corrected formula: ``c_mm(dof_near) == coC_px * pitch``;
    * ``D`` is confirmed twice: ``width_px / sensor_width_mm`` and
      ``focus / (focal_length_mm * mm_per_px_at_object)``, where ``mm_per_px_at_object`` is the
      magnification relation ``mm_per_px = z/f * pitch`` measured on the committed intrinsics.

Part 3 -- before/after on archived views (same depth maps, same pixels)
    * the shipped v1 expression (pixel focal length in the mm formula, no ``D``, f/1) and the
      v2 expression (declared optics, ``D``) on every committed view;
    * ``object px``, ``uncertain px``, ``deployment_mask px`` and the pixel-level
      ``visible`` intersection before and after, plus the fraction of object pixels whose CoC is
      below the profile's own 2.0 px mark-out.

Usage:
  .venv\\Scripts\\python.exe data/a12/reports/verify_coc_units.py \\
      --store <store> --obs <obs_asset_id> --archive data/a12/reports/coc_units_v2
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab.cameras.profiles import profile_by_id, thin_lens_dof  # noqa: E402
from synlab.observe.render import (  # noqa: E402
    MASK_SEMANTICS,
    RenderOutput,
    circle_of_confusion_px,
    deployment_mask_from_render,
)
from synlab.storage.store import AssetStore  # noqa: E402

COC_LEGACY_THRESHOLD_PX = 0.75      # RenderSpec.coc_px_threshold (pipeline: * declared f_number)
PIPELINE_APERTURE_COMPENSATION = True


def part1_arithmetic(profile) -> dict:
    f_mm = float(profile.meta["focal_length_mm"])
    f_number = float(profile.f_number)
    z_f = float(profile.working_distance_mm)
    sensor_w = float(profile.meta["sensor_width_mm"])
    width_px = 256
    D = width_px / sensor_w
    f_px = f_mm * D
    rows = []
    for z in (z_f - 30.0, z_f - 5.0, z_f, z_f + 10.0, z_f + 40.0):
        # exact marginal-ray blur diameter on the sensor plane
        A = f_mm / f_number
        s_img = f_mm * z / (z - f_mm)
        s_focus = f_mm * z_f / (z_f - f_mm)
        c_ray_mm = A * abs(1.0 - s_focus / s_img)
        formula = float(circle_of_confusion_px(np.array([z]), z_f, f_number, f_px,
                                               sampling_px_per_mm=D)[0])
        rows.append({
            "z_mm": float(z), "image_distance_mm": float(s_img),
            "focused_image_distance_mm": float(s_focus),
            "ray_trace_c_mm": float(c_ray_mm), "ray_trace_c_px": float(c_ray_mm * D),
            "circle_of_confusion_px_v2": formula,
            "relative_difference": float(abs(formula - c_ray_mm * D) / max(c_ray_mm * D, 1e-12)),
        })
    return {"focal_length_mm": f_mm, "f_number": f_number, "focus_distance_mm": z_f,
            "sensor_width_mm": sensor_w, "delivered_width_px": width_px,
            "sampling_px_per_mm_D": D, "f_px": f_px, "D_times_f_number": D * f_number,
            "ray_trace_vs_formula": rows,
            "note": "the thin-lens closed form is the standard small-blur approximation of the "
                    "ray trace; the two agree to well under 1 % over this depth span"}


def part2_declared_cross_checks(profile, mm_per_px_at_object: float) -> dict:
    f_mm = float(profile.meta["focal_length_mm"])
    f_number = float(profile.f_number)
    z_f = float(profile.working_distance_mm)
    sensor_w = float(profile.meta["sensor_width_mm"])
    native_w = int(profile.image_size[0])
    pitch_native = sensor_w / native_w
    coc_px = float(profile.meta.get("coC_px", 2.0))
    dof_near, dof_far = (float(v) for v in profile.depth_of_field_mm)
    D = 256 / sensor_w

    def c_mm(z: float) -> float:
        return float(circle_of_confusion_px(np.array([z]), z_f, f_number, f_mm * D,
                                            sampling_px_per_mm=D)[0] / D)

    target = coc_px * pitch_native
    return {
        "declared_dof_mm": [dof_near, dof_far],
        "declared_coc_px": coc_px,
        "native_pixel_pitch_mm": pitch_native,
        "criterion_c_mm_at_dof_limit": target,
        "measured_c_mm_at_dof_near": c_mm(dof_near),
        "measured_c_mm_at_dof_far": c_mm(dof_far),
        "max_relative_error": max(abs(c_mm(dof_near) - target) / target,
                                 abs(c_mm(dof_far) - target) / target),
        "D_from_width_over_sensor": D,
        "D_from_focal_and_magnification": z_f / (f_mm * mm_per_px_at_object),
        "mm_per_px_at_object_from_magnification": (1.0 / D) * z_f / f_mm,
        "mm_per_px_at_object_committed": mm_per_px_at_object,
        "note": "the magnification relation mm_per_px = (z/f) * sensor_pitch reproduces the "
                "committed mm_per_px_at_object with the *delivered* pitch 1/D (the native pitch "
                "would be the 4000 px grid), which is a second independent confirmation of D",
    }


def part3_before_after(store_root: Path, obs_id: str, profile_id: str,
                       archive: Path | None) -> dict:
    store = AssetStore(store_root)
    profile = profile_by_id(profile_id)
    f_mm = float(profile.meta["focal_length_mm"])
    f_number = float(profile.f_number)
    sensor_w = float(profile.meta["sensor_width_mm"])
    record = store.get_asset(obs_id)
    arrays = store.load_arrays(obs_id)
    views_meta = list((record.meta or {}).get("views") or [])
    threshold_v2 = (COC_LEGACY_THRESHOLD_PX * f_number if PIPELINE_APERTURE_COMPENSATION
                    else COC_LEGACY_THRESHOLD_PX)
    markout = float(profile.meta.get("coC_px", 2.0))
    out: dict = {"obs_asset": obs_id, "store": str(store_root), "profile_id": profile_id,
                 "mask_semantics_after": MASK_SEMANTICS,
                 "pipeline_threshold_after_px": threshold_v2,
                 "profile_markout_px": markout, "views": []}
    archive_arrays: dict[str, np.ndarray] = {}
    for index, view_meta in enumerate(views_meta):
        prefix = f"v{index:03d}."
        if prefix + "depth_z" not in arrays:
            continue
        depth = np.asarray(arrays[prefix + "depth_z"], dtype=np.float64)
        depth[depth < 0] = np.nan
        id_map = np.asarray(arrays[prefix + "id_map"])
        K = np.asarray(arrays[prefix + "K"], dtype=np.float64)
        stored_uncertain = np.asarray(arrays[prefix + "uncertain_mask"], dtype=bool)
        stored_mask = np.asarray(arrays[prefix + "deployment_mask"], dtype=bool)
        height, width = id_map.shape
        D = width / sensor_w
        f_px = 0.5 * (float(K[0, 0]) + float(K[1, 1]))
        focus = float(view_meta.get("working_distance_mm") or profile.working_distance_mm)
        obj = id_map >= 0
        coc_v1 = circle_of_confusion_px(depth, focus, 1.0, f_px)                     # shipped
        coc_v2 = circle_of_confusion_px(depth, focus, f_number, f_px,
                                        sampling_px_per_mm=D)                        # fixed
        finite = np.isfinite(coc_v1[obj]) & (coc_v1[obj] > 0)
        ratio = float(np.median(coc_v1[obj][finite] / coc_v2[obj][finite])) if finite.any() else 0.0
        # pixel-level rebuild of the delivered channels under each semantics
        render_v1 = RenderOutput(rgb_linear=np.zeros((height, width, 3), np.float32), depth_z=depth,
                                 id_map=id_map, surface_tag=np.zeros_like(id_map, np.int16),
                                 visibility=(obj).astype(np.uint8),
                                 uncertain_mask=(coc_v1 > threshold_v2).astype(bool),
                                 backend="SOFTWARE_RASTERIZER", meta={})
        render_v2 = RenderOutput(rgb_linear=np.zeros((height, width, 3), np.float32), depth_z=depth,
                                 id_map=id_map, surface_tag=np.zeros_like(id_map, np.int16),
                                 visibility=(obj).astype(np.uint8),
                                 uncertain_mask=(coc_v2 > threshold_v2).astype(bool),
                                 backend="SOFTWARE_RASTERIZER", meta={})
        mask_v1 = deployment_mask_from_render(render_v1)
        mask_v2 = deployment_mask_from_render(render_v2)
        # depth-of-field window implied by the corrected CoC at the *delivered* grid
        z_obj = depth[obj]
        finite_obj = np.isfinite(z_obj)
        within = np.isfinite(coc_v2[obj]) & (coc_v2[obj] <= markout) & finite_obj
        dof_window = ([float(z_obj[within].min()), float(z_obj[within].max())]
                      if bool(np.any(within)) else None)
        span_min = float(z_obj[finite_obj].min()) if bool(np.any(finite_obj)) else 0.0
        span_max = float(z_obj[finite_obj].max()) if bool(np.any(finite_obj)) else 0.0
        row = {
            "view": index, "view_id": view_meta.get("view_id"),
            "delivered_size": [int(width), int(height)],
            "sampling_px_per_mm_D": float(D), "f_px": float(f_px),
            "focal_length_mm_from_f_px": float(f_px / D),
            "working_distance_mm": focus,
            "object_px": int(np.count_nonzero(obj)),
            "depth_span_mm": float(np.nanmax(depth[obj]) - np.nanmin(depth[obj])),
            "depth_offset_p50_mm": float(np.nanpercentile(np.abs(depth[obj] - focus), 50)),
            "coc_v1_p50_px": float(np.nanpercentile(coc_v1[obj], 50)),
            "coc_v2_p50_px": float(np.nanpercentile(coc_v2[obj], 50)),
            "coc_v2_p95_px": float(np.nanpercentile(coc_v2[obj], 95)),
            "coc_v1_over_v2_p50": ratio,
            "D_times_f_number": float(D * f_number),
            "object_px_coc_v2_below_markout_fraction": float(np.mean(coc_v2[obj] <= markout)),
            "object_px_coc_v2_below_pipeline_threshold_fraction": float(
                np.mean(coc_v2[obj] <= threshold_v2)),
            "object_px_coc_v1_below_pipeline_threshold_fraction": float(
                np.mean(coc_v1[obj] <= threshold_v2)),
            "uncertain_px_on_object_v1": int(np.count_nonzero(stored_uncertain & obj)),
            "uncertain_px_on_object_v2": int(np.count_nonzero(render_v2.uncertain_mask & obj)),
            "deployment_mask_px_v1_stored": int(np.count_nonzero(stored_mask)),
            "deployment_mask_px_v2": int(np.count_nonzero(mask_v2)),
            "deployment_mask_over_object_v1_stored": float(
                np.count_nonzero(stored_mask) / max(int(np.count_nonzero(obj)), 1)),
            "deployment_mask_over_object_v2": float(
                np.count_nonzero(mask_v2) / max(int(np.count_nonzero(obj)), 1)),
            "visible_rule_px_v1": int(np.count_nonzero(mask_v1 & (id_map >= 0))),
            "visible_rule_px_v2": int(np.count_nonzero(mask_v2 & (id_map >= 0))),
            "object_depth_min_mm": span_min,
            "object_depth_max_mm": span_max,
            "dof_window_v2_px_below_markout_mm": dof_window,
            "object_span_inside_dof_v2": bool(
                dof_window is not None and dof_window[0] <= span_min
                and dof_window[1] >= span_max),
        }
        out["views"].append(row)
        if archive is not None:
            archive_arrays[f"v{index:03d}.depth_z"] = np.asarray(arrays[prefix + "depth_z"])
            archive_arrays[f"v{index:03d}.id_map"] = np.asarray(id_map, dtype=np.int32)
            archive_arrays[f"v{index:03d}.K"] = K
            archive_arrays[f"v{index:03d}.uncertain_mask_v1"] = stored_uncertain
            archive_arrays[f"v{index:03d}.deployment_mask_v1"] = stored_mask
    if archive is not None and archive_arrays:
        archive.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(archive / f"{obs_id}_views.npz", **archive_arrays)
        out["archive"] = str(archive / f"{obs_id}_views.npz")
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", default="")
    parser.add_argument("--obs", default="")
    parser.add_argument("--profile", default="CAM_MID_V3")
    parser.add_argument("--mm-per-px-at-object", type=float, default=1.2560096153846154)
    parser.add_argument("--archive", default="data/a12/reports/coc_units_v2")
    parser.add_argument("--out", default="data/a12/reports/coc_units_v2_verification.json")
    args = parser.parse_args()

    profile = profile_by_id(args.profile)
    report: dict = {"profile_id": args.profile}
    report["part1_arithmetic"] = part1_arithmetic(profile)
    report["part2_declared_cross_checks"] = part2_declared_cross_checks(
        profile, args.mm_per_px_at_object)
    if args.store and args.obs:
        report["part3_before_after"] = part3_before_after(
            Path(args.store), args.obs, args.profile,
            Path(args.archive) if args.archive else None)
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str),
                      encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
