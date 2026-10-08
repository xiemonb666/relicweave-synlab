"""Real capture-rig error ladder measured on real delivered frames.

Run (from ``relicweave-synlab``)::

    .venv\\Scripts\\python.exe ..\\data\\a12_reports\\measure_rig_ladder.py

Writes ``data/a12_reports/a12_rig_error.json``.  Nothing else is written.

Per rig-error term, on **real** frames / **real** point clouds:

* rolling shutter —per-row displacement actually applied (px) and the radial displacement of the
  sharpest delivered edge measured before/after;
* focus —CoC (mm and px) and PSF sigma from the thin-lens model, and the *measured* blur drop;
* intrinsics drift —focal scale and principal shift (candidate bounds, tagged);
* scale drift —relative scale error and the ARBITRARY case;
* light states —per-mode highlight suppression measured on the frame;
* resolution at distance —the documented mm/px table, the delivered mm/px, and the re-projected
  pixel density (never called "moving closer");
* reconstruction —measured local plane residual sigma, hole census and valid fraction of a real
  observed point cloud, against the plan's "Q2 褰撻噺" line.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2] / "relicweave-synlab"
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from synlab.degrade import rig_error as RE  # noqa: E402
from synlab.degrade.api import observe_probe, probe_sources  # noqa: E402
from synlab.degrade.ops_image import frame_linear, gradient_energy, sharpness  # noqa: E402
from synlab.degrade.specs import capture_rig_spec  # noqa: E402

OUT = Path(__file__).resolve().parent
LIGHT_MODES = ("WHITE_DIFFUSE", "LEFT_GRAZE", "RIGHT_GRAZE", "CROSS_POL", "NORMAL_REFLECT")


def edge_displacement_px(before: np.ndarray, after: np.ndarray, *, axis: int = 1) -> float:
    """Horizontal displacement of the strongest edge, by 1-D cross-correlation of a row profile."""
    a = np.asarray(before, dtype=np.float64).mean(axis=2).mean(axis=0)
    b = np.asarray(after, dtype=np.float64).mean(axis=2).mean(axis=0)
    a = a - a.mean()
    b = b - b.mean()
    denom = max(float(np.linalg.norm(a) * np.linalg.norm(b)), 1e-12)
    correlation = np.correlate(b, a, mode="full") / denom
    lags = np.arange(-len(a) + 1, len(a))
    return float(lags[int(np.argmax(correlation))])


def real_frames(report: dict) -> tuple[list[dict], object | None, str]:
    """A real delivered frame list plus (when available) the real observation behind it.

    ``probe_sources`` is the shipped audit source.  On this checkout its proxy-scan observation
    raises inside OpenCV (``cv2.GaussianBlur`` on the small probe depth map) —an upstream
    failure, not one of ours —and the shipped helper only catches ``SynLabError``, so the failure
    escapes.  The fallback renders one frame with the same software rasteriser the observation
    routes use, at a resolution that does not trip that OpenCV path, and labels the provenance so
    the report never presents a fallback as the audit probe.
    """
    try:
        bundles = probe_sources()
        frames = list(bundles["I"].get("frames") or [])
        if frames:
            report["frames_provenance"] = str(bundles["I"].meta.get("provenance", "probe_sources"))
            return frames, None, "probe_sources"
        report["probe_sources_note"] = "probe_sources returned no frames"
    except Exception as exc:  # noqa: BLE001 - the upstream OpenCV failure is reported, not hidden
        report["probe_sources_error"] = f"{type(exc).__name__}: {exc}"
    import trimesh

    from synlab.observe.render import LightSpec, RenderSpec, build_scene, render_view
    from synlab.schemas.runtime import ViewFrame

    mesh = trimesh.creation.box(extents=(60.0, 45.0, 25.0))
    scene = build_scene(mesh, surface_tag=np.zeros(len(mesh.faces), dtype=np.int16),
                        face_id=np.arange(len(mesh.faces), dtype=np.int32), name="rig_ladder")
    T = np.eye(4)
    # The delivered frame must be at a **documented** size, otherwise the rolling-shutter numbers
    # are meaningless: the row delay is t_row * rows, so a 96-row debug frame produces a 0.001 px
    # shear at 2 deg/s (measured) while the real 1296-row sensor covers the documented 84 deg FOV
    # over 2304 columns.
    width_px, height_px = int(rig.camera.sensor_width_px.value), int(
        rig.camera.sensor_height_px.value)
    T[:3, 3] = np.array([0.0, -150.0, 70.0])
    focal_px = float(rig.camera.focal_px) * width_px / float(rig.camera.sensor_width_mm.value)
    view = ViewFrame(view_id="rig0",
                     K=np.array([[focal_px, 0.0, width_px / 2.0],
                                 [0.0, focal_px, height_px / 2.0], [0.0, 0.0, 1.0]]),
                     T_WC=T, image_size=(width_px, height_px), profile_id="LOCAL_V1", tier="LOCAL",
                     u_position_mm=0.0, working_distance_mm=150.0, focus_setting="fixed_near",
                     source_kind="SENSOR_SIM", camera_model="PINHOLE", dist=None)
    render = render_view(scene, view,
                         light=LightSpec(direction=np.array([-0.35, -0.62, -0.70]),
                                         color=np.array([2.35, 2.25, 2.10]),
                                         ambient=np.array([0.30, 0.30, 0.33])),
                         spec=RenderSpec(supersample=1, max_pixels=width_px * height_px))
    linear = np.asarray(render.rgb_linear, dtype=np.float32)
    from synlab.degrade.ops_image import encode_linear

    frame = {"view_id": "rig0", "rgb_linear": linear,
             "rgb": encode_linear(linear, "LINEAR"), "encoding": "LINEAR",
             "K": np.asarray(view.K, dtype=np.float64),
             "T_WC": np.asarray(view.T_WC, dtype=np.float64), "dist": None,
             "depth_z": np.asarray(render.depth_z, dtype=np.float32),
             "valid_mask": (np.asarray(render.id_map, dtype=np.int32) >= 0),
             "focus_distance_mm": 150.0, "valid": True,
             "renderer": "synlab.observe.render.render_view (software rasteriser)"}
    return [frame], None, "REAL_RENDER_FALLBACK_SOFTWARE_RASTERISER"


def main() -> int:
    started = time.time()
    rig = capture_rig_spec()
    report: dict = {
        "schema": "a12.rig_error.v1",
        "generated_by": "data/a12_reports/measure_rig_ladder.py",
        "hardware": {
            "board": rig.camera.board.value, "module": rig.camera.module.value,
            "sensor_px": [int(rig.camera.sensor_width_px.value),
                          int(rig.camera.sensor_height_px.value)],
            "sensor_mm": [float(rig.camera.sensor_width_mm.value),
                          float(rig.camera.sensor_height_mm.value)],
            "pixel_pitch_mm": float(rig.camera.pixel_pitch_mm.value),
            "focal_mm_derived": float(rig.camera.focal_mm),
            "focal_px": float(rig.camera.focal_px),
            "fov_h_deg": float(rig.camera.fov_h_deg.value),
            "shutter": rig.camera.shutter.value, "focus": rig.camera.focus_mode.value,
            "light_modes": list(LIGHT_MODES),
        },
        "levels": list(RE.RIG_LEVELS),
        "ladder": [],
        "light_states": {},
        "resolution": {},
        "reconstruction": {},
        "candidates": rig.candidates(),
    }

    # ---------------------------------------------------------------- real frames
    frames, _obs, provenance = real_frames(report)
    report["frames_provenance"] = provenance
    observation = None
    try:
        observation = observe_probe()
    except Exception as exc:  # noqa: BLE001 - the point-cloud half is reported as unavailable
        report["observation_error"] = f"{type(exc).__name__}: {exc}"
    if not frames:
        report["error"] = "no delivered frames available"
        (OUT / "a12_rig_error.json").write_text(json.dumps(report, indent=1, default=str),
                                               encoding="utf-8")
        return 1
    frame = frames[0]
    linear0 = frame_linear(frame)
    height, width = int(linear0.shape[0]), int(linear0.shape[1])
    report["frames"] = {"count": len(frames), "delivered_size_px": [width, height],
                        "provenance": str(str(report.get("frames_provenance", "")))}
    K0 = np.asarray(frame.get("K"), dtype=np.float64)
    focal_px_delivered = float(K0[0, 0])
    report["frames"]["focal_px_delivered"] = focal_px_delivered
    report["frames"]["mm_per_px_delivered_at_150mm"] = float(
        2.0 * 150.0 * np.tan(np.radians(float(rig.camera.fov_h_deg.value)) / 2.0) / width)

    # ---------------------------------------------------------------- ladder
    for level in range(5):
        intensity = RE.RIG_LEVELS[level]
        row: dict = {"level": level, "intensity": intensity}
        if level == 0:
            row["identity"] = {
                "rolling_shutter_applied": False, "defocus_applied": False,
                "intrinsics_changed": False, "scale_changed": False,
                "light_mode_changed": False, "pixel_density_changed": False,
                "note": "level 0 is the identity: the delivered frame is returned untouched",
            }
            report["ladder"].append(row)
            continue
        # rolling shutter: measured on the frame re-sampled to the **documented sensor grid**
        # (nearest-neighbour, so no detail is invented), because the shipped probe delivers
        # 128x96 and a 96-row frame cannot show the 1296-row sensor's shear at all.
        import cv2

        sensor_w, sensor_h = (int(rig.camera.sensor_width_px.value),
                              int(rig.camera.sensor_height_px.value))
        base = cv2.resize(np.asarray(linear0, dtype=np.float32), (sensor_w, sensor_h),
                          interpolation=cv2.INTER_NEAREST)
        base_frame = dict(frame)
        base_frame["rgb_linear"] = base
        base_frame["rgb"] = np.rint(np.clip(base, 0, 1) * 255).astype(np.uint8)
        K_sensor = np.asarray(K0, dtype=np.float64).copy()
        K_sensor[0, :] *= sensor_w / width
        K_sensor[1, :] *= sensor_h / height
        base_frame["K"] = K_sensor
        rate = float(rig.motion.turntable_rate_dps.value) * intensity
        offsets, rs_info = RE.RollingShutterModel(rate_dps=rate, level=level).row_offsets_px(
            rig, width_px=sensor_w, rows=sensor_h)
        rs_frame, rs_apply = RE.apply_rolling_shutter(base_frame, offsets, axis_u=0.25)
        radius_info = RE.rolling_shutter_displacement_px(
            line_time_s=float(rig.camera.line_time_us.value) * 1e-6, rows=sensor_h, rate_dps=rate,
            fov_h_deg=float(rig.camera.fov_h_deg.value), width_px=sensor_w)
        before_lin, after_lin = frame_linear(base_frame), frame_linear(rs_frame)
        row_delta = np.abs(after_lin - before_lin).mean(axis=(1, 2))
        rows_axis = np.arange(sensor_h, dtype=np.float64)
        slope = float(np.polyfit(rows_axis, row_delta, 1)[0]) if sensor_h > 1 else 0.0
        row["rolling_shutter"] = {
            **rs_info, **rs_apply,
            "sensor_grid_px": [sensor_w, sensor_h],
            "grid_note": ("the shipped probe delivers 128x96; the term is measured on the frame "
                          "re-sampled to the documented 2304x1296 grid with INTER_NEAREST, so the "
                          "row count and therefore the read-out window are the real ones"),
            "full_frame_displacement_px": radius_info["displacement_px"],
            "full_frame_displacement_mm_at_150mm": float(
                radius_info["displacement_px"] * 2.0 * 150.0
                * np.tan(np.radians(float(rig.camera.fov_h_deg.value)) / 2.0) / sensor_w),
            "measured_row_delta_mean": float(row_delta.mean()),
            "measured_row_delta_gradient_per_row": slope,
            "measured_row_delta_ratio_first_last": float(
                row_delta[-1] / max(row_delta[0], 1e-12)) if sensor_h > 1 else 0.0,
            "focal_px_delivered_note": "focal_px_delivered is the probe frame; the sensor-grid "
                                       "frame carries fx = focal_px * 2304 / sensor_width_mm",
        }
        # defocus (on the sensor-grid frame, so the CoC in pixels is at the documented density)
        focus_distance = 150.0
        object_distance = focus_distance * (1.0 + 0.08 * intensity)
        coc = RE.FocusModel().circle_of_confusion_px(rig, focus_distance_mm=focus_distance,
                                                     object_distance_mm=object_distance)
        d_frame, d_apply = RE.apply_defocus(rs_frame, coc["psf_sigma_px"])
        sharp_before = sharpness(frame_linear(rs_frame))
        sharp_after = sharpness(frame_linear(d_frame))
        grad_before = gradient_energy(frame_linear(rs_frame))
        grad_after = gradient_energy(frame_linear(d_frame))
        row["defocus"] = {
            **coc, **d_apply,
            "grid": "documented sensor grid",
            "sharpness_before": sharp_before,
            "sharpness_after": sharp_after,
            "sharpness_drop_ratio": float(1.0 - sharp_after / max(sharp_before, 1e-12)),
            "gradient_energy_before": grad_before,
            "gradient_energy_after": grad_after,
            "gradient_energy_drop_ratio": float(1.0 - grad_after / max(grad_before, 1e-12)),
            "depth_of_field_at_2px": RE.FocusModel().depth_of_field_mm(
                rig, focus_distance_mm=focus_distance, coc_px=2.0),
        }
        # intrinsics
        drift_K, k_info = RE.IntrinsicsDriftModel().drift(K0, condition_u=intensity,
                                                          condition_v=intensity, level=level)
        row["intrinsics_drift"] = {
            **k_info,
            "relative_focal_change": float(drift_K[0, 0] / K0[0, 0] - 1.0),
            "principal_shift_px": [float(drift_K[0, 2] - K0[0, 2]),
                                   float(drift_K[1, 2] - K0[1, 2])],
        }
        # scale
        row["scale_drift"] = RE.ScaleDriftModel().drift(
            reference_present=True, reference_visible_fraction=1.0 - 0.4 * intensity,
            condition=intensity, level=level)
        row["scale_drift_arbitrary_case"] = RE.ScaleDriftModel().drift(
            reference_present=False, reference_visible_fraction=0.0, condition=intensity,
            level=level)
        # resolution at distance
        row["resolution"] = RE.ResolutionAtDistanceModel().effective(
            rig, 150.0, width)
        reprojected, reproject_info = RE.resample_to_distance(
            d_frame, from_distance_mm=150.0, to_distance_mm=50.0)
        row["resolution"]["reprojected_to_50mm"] = {
            **reproject_info,
            "size_after": list(reprojected["image_size"]),
            "gradient_energy_before": gradient_energy(frame_linear(d_frame)),
            "gradient_energy_after": gradient_energy(frame_linear(reprojected)),
        }
        # light states on this level's frame
        row["light_states"] = {}
        for mode in LIGHT_MODES:
            lit, info = RE.IlluminationModel().apply(d_frame, mode, level=level)
            row["light_states"][mode] = {
                "mean_luma_before": info["mean_luma_before"],
                "mean_luma_after": info["mean_luma_after"],
                "highlight_region_luma_before": info["highlight_region_luma_before"],
                "highlight_region_luma_after": info["highlight_region_luma_after"],
                "highlight_suppression_ratio": info["highlight_suppression_ratio"],
                "highlight_area_fraction": info["highlight_area_fraction"],
                "specular_retained": info["specular_retained"],
                "provenance": info["provenance"],
            }
        row["reconstruction_noise_model"] = RE.ReconstructionModel().noise_sigma_mm(
            rig, working_distance_mm=150.0, baseline_mm=40.0)
        report["ladder"].append(row)

    # ---------------------------------------------------------------- light states table
    for mode in LIGHT_MODES:
        lit, info = RE.IlluminationModel().apply(frame, mode, level=4)
        report["light_states"][mode] = {k: v for k, v in info.items()
                                        if isinstance(v, (int, float, str, list, bool, type(None)))}

    # ---------------------------------------------------------------- resolution table
    report["resolution"] = {
        "documented_table": {str(k): v.as_dict() for k, v in
                             rig.camera.resolution_mm_per_px.items()},
        "documented_coverage": {str(k): v.as_dict() for k, v in
                                rig.camera.ideal_coverage_mm.items()},
        "per_distance": {str(d): RE.ResolutionAtDistanceModel().effective(rig, float(d), width)
                         for d in (50, 100, 150, 200, 250)},
        "no_resize_rule": "G14.4 p1488: U moves the camera along the optical axis; resize must not be used to simulate a physical approach",
    }

    # ---------------------------------------------------------------- reconstruction on a real cloud
    if observation is None:
        report["reconstruction"] = {"status": "UNAVAILABLE",
                                    "reason": report.get("observation_error", "unknown")}
        points = np.zeros((0, 3))
        real_points = points
    else:
        points = np.asarray(observation.points, dtype=np.float64)
        valid = (np.asarray(observation.point_valid, dtype=bool)
                 if getattr(observation, "point_valid", None) is not None
                 else np.ones(len(points), dtype=bool))
        real_points = points[valid]
    diag = float(np.linalg.norm(np.ptp(real_points, axis=0))) if len(real_points) else 1.0
    voxel = max(diag / 24.0, 0.2)
    if observation is not None:
        report["reconstruction"] = {
            "route": str(getattr(observation, "route", "")),
            "provenance": str(str(report.get("frames_provenance", ""))),
            "n_points_declared": int(len(points)), "n_points_valid": int(len(real_points)),
            "valid_fraction": float(len(real_points) / max(len(points), 1)),
            "voxel_mm": float(voxel),
            "measured": RE.measure_point_cloud_quality(real_points, voxel_mm=voxel,
                                                       plane_radius_mm=max(diag / 30.0, 0.5)),
            "floor": {
                "valid_point_fraction_min": float(RE.RECON_FLOOR_VALID_FRACTION.value),
                "coordinate_sigma_mm_max": float(RE.RECON_FLOOR_SIGMA_MM.value),
                "hole_count_max": int(RE.RECON_FLOOR_HOLES.value),
                "hole_radius_mm_max": float(RE.RECON_FLOOR_HOLE_RADIUS_MM.value),
                "provenance": RE.RECON_FLOOR_SIGMA_MM.provenance,
                "ref": "5.6 p1063 (a synthetic calibration line; it must be re-calibrated once a real scan exists)",
            },
            "observation_quality_keys": sorted((getattr(observation, "quality", {}) or {}).keys()),
        }
    if observation is not None:
        report["reconstruction"]["noise_model"] = RE.ReconstructionModel().noise_sigma_mm(
            rig, working_distance_mm=150.0, baseline_mm=40.0)

    # ------------------------------------------------------- manual-focus error sweep
    # The level ladder keeps the *declared* focus error small (8 % of the distance), which at
    # f/2.0 and 150 mm is a ~1 px CoC: sub-pixel and therefore nearly invisible (measured
    # gradient-energy drop 0.0007 at level 4).  A manual focus error on a real rig is however
    # frequently tens of millimetres, so the sweep below states what each error would cost.
    base_sensor = dict(frame)
    import cv2 as _cv2

    sensor_w, sensor_h = (int(rig.camera.sensor_width_px.value),
                          int(rig.camera.sensor_height_px.value))
    sensor_linear = _cv2.resize(np.asarray(linear0, dtype=np.float32), (sensor_w, sensor_h),
                                interpolation=_cv2.INTER_NEAREST)
    base_sensor["rgb_linear"] = sensor_linear
    base_sensor["rgb"] = np.rint(np.clip(sensor_linear, 0, 1) * 255).astype(np.uint8)
    grad0 = gradient_energy(sensor_linear)
    sweep = []
    for error_mm in (-50.0, -25.0, -10.0, -5.0, 0.0, 5.0, 10.0, 25.0, 50.0):
        info = RE.FocusModel().circle_of_confusion_px(
            rig, focus_distance_mm=150.0, object_distance_mm=150.0 + error_mm)
        if abs(error_mm) < 1e-9:
            sweep.append({**info, "error_mm": 0.0, "gradient_energy_drop_ratio": 0.0})
            continue
        blurred, _ = RE.apply_defocus(base_sensor, info["psf_sigma_px"])
        grad1 = gradient_energy(frame_linear(blurred))
        sweep.append({**info, "error_mm": float(error_mm),
                      "gradient_energy_before": grad0, "gradient_energy_after": grad1,
                      "gradient_energy_drop_ratio": float(1.0 - grad1 / max(grad0, 1e-12))})
        del blurred
    report["focus_error_sweep"] = {
        "focus_distance_mm": 150.0, "grid": "documented sensor grid",
        "note": "a real manual-focus error is often tens of mm; the ladder's own 8 % error is a "
                "1 px CoC and therefore nearly invisible",
        "rows": sweep,
    }

    report["seconds_total"] = round(time.time() - started, 2)
    (OUT / "a12_rig_error.json").write_text(json.dumps(report, indent=1, default=str),
                                            encoding="utf-8")
    print("wrote", OUT / "a12_rig_error.json", "in", report["seconds_total"], "s")
    for row in report["ladder"]:
        level = row["level"]
        if level == 0:
            print("L0 identity (nothing applied)")
            continue
        rs, df = row["rolling_shutter"], row["defocus"]
        print("L%d  row offset max=%.4f px (row-delta gradient %.3g/row, first:last %.3f)  "
              "CoC=%.3f px sigma=%.3f px  grad-energy drop %.4f  focal %+.2f%%  scale %s"
              % (level, rs["max_row_offset_px"], rs["measured_row_delta_gradient_per_row"],
                 rs["measured_row_delta_ratio_first_last"],
                 df["coc_px"], df["psf_sigma_px"], df["gradient_energy_drop_ratio"],
                 100 * row["intrinsics_drift"]["relative_focal_change"],
                 row["scale_drift"]["status"]))
    print("reconstruction:", {k: report["reconstruction"]["measured"].get(k)
                              for k in ("valid_fraction", "sigma_mm", "hole_count",
                                        "normal_drift_deg_median")})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
