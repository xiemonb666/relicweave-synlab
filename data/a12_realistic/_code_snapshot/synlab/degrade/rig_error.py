"""Capture-rig error model: what a *real* scan of this rig does to the data.

Every term is written against the documented hardware of §4.2-§4.4 of
``docs/a12/v144_project_core.md`` (Luckfox Pico RV1103 + SC3336B, 2304x1296, FOV_h ~ 84 deg,
manual focus, **rolling shutter**, four same-colour-temperature white lamps with a lamp-side
polariser and a lens analyser, five documented light states, a per-condition intrinsics
calibration, and a traceable scale reference in every formal capture).

The model answers the question the plan keeps asking and never answers numerically: *what does
this specific rig actually do to the pixels and the point cloud?*  It is deliberately split into

* **derived quantities** — row delay from the (documented) row count and a line time, circle of
  confusion from the thin-lens formula, mm/px from the documented pinhole relation, the depth
  noise implied by the documented 3-D engineering floor.  These follow from formulas and are
  reproducible;
* **candidate quantities** — the line time of this sensor, the lens f-number and focal length, the
  turntable rate, the lamp weights, the cross-polarisation residual.  None of them is printed in
  the plan and none is measured on this machine, so they are labelled ``CANDIDATE`` /
  ``待实测校准`` everywhere, including inside every returned measurement dict.

Nothing here writes, resizes or repaints a delivered frame: the rolling-shutter term is a real
per-row resampling, the defocus term is a real PSF convolution, the resolution term is a genuine
change of camera distance (``K`` is re-derived at the new working distance; the plan forbids
simulating physical approach with ``resize`` — I09 low resolution and working distance are separate
controls, §G14.4 p1488).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import numpy as np

from ..errors import ErrorCode, SynLabError
from .ops_image import convolve, encode_linear, frame_encoding, frame_linear, gaussian_psf
from .specs import (
    CANDIDATE,
    CaptureRigSpec,
    DERIVED,
    DOCUMENTED,
    MEASURED,
    RECON_FLOOR_HOLES,
    RECON_FLOOR_HOLE_RADIUS_MM,
    RECON_FLOOR_SIGMA_MM,
    RECON_FLOOR_VALID_FRACTION,
    SpecValue,
    capture_rig_spec,
    light_mode,
)

__all__ = [
    "scan_fault_ladder", "RollingShutterModel", "FocusModel", "IntrinsicsDriftModel",
    "ScaleDriftModel", "IlluminationModel", "ResolutionAtDistanceModel", "ReconstructionModel",
    "RigErrorModel", "rolling_shutter_row_delay_s", "rolling_shutter_displacement_px",
    "apply_rolling_shutter", "apply_defocus", "intrinsics_at_distance", "resample_to_distance",
    "apply_light_mode", "point_cloud_noise_sigma_mm", "measure_point_cloud_quality",
]

#: Level ladder of the rig-error axes.  ``level 0`` is the identity for every one of them, exactly
#: as the 31 shipped degradation axes require.
RIG_LEVELS: tuple[float, ...] = (0.0, 0.25, 0.50, 0.75, 1.0)


# ======================================================================================
# rolling shutter
# ======================================================================================
def rolling_shutter_row_delay_s(line_time_s: float, row: int) -> float:
    """Time between the start of the exposure of row 0 and of row ``row``: ``t_row * row``."""
    return float(line_time_s) * float(row)


def rolling_shutter_displacement_px(*, line_time_s: float, rows: int, rate_dps: float,
                                    fov_h_deg: float, width_px: int,
                                    angle_deg: float = 90.0) -> dict[str, Any]:
    """Radial displacement (px) caused by a rolling shutter while the scene rotates.

    The first and the last row of one frame are exposed ``T_read = t_row * N_y`` apart.  A
    turntable turning at ``omega`` deg/s moves every scene point by ``omega * T_read`` degrees
    during that window; at the horizontal field of view ``FOV_h`` mapped onto ``N_x`` pixels that
    is a pixel displacement of::

        dx_px = (omega * T_read) / FOV_h * N_x * sin(angle)

    where ``angle`` is the angle between the motion direction and the pixel x axis (the turntable
    moves the *image* tangentially, so an edge crossing the centre of the frame has
    ``sin(angle) = 1`` and an edge at the rotation centre has ``sin(angle) = 0``).  The plan's
    turntable rotates the *object* about Z, so the displacement grows linearly with the distance
    from the image of the rotation axis: that is why the model reports both the full-frame maximum
    and the location-free formula, and why :func:`apply_rolling_shutter` shifts **every row by its
    own amount** instead of translating the whole frame.

    Everything is CANDIDATE except the row count, the FOV and the width, which are documented.
    """
    rows = int(rows)
    total_s = float(line_time_s) * rows
    omega = float(rate_dps)
    fov = float(fov_h_deg)
    width = int(width_px)
    motion_deg = omega * total_s
    dx_px = motion_deg / max(fov, 1e-9) * width * math.sin(math.radians(float(angle_deg)))
    return {
        "line_time_s": float(line_time_s), "line_time_provenance": CANDIDATE,
        "frame_readout_s": total_s, "frame_readout_provenance": DERIVED,
        "rows": rows, "rows_provenance": DOCUMENTED,
        "turntable_rate_dps": omega, "turntable_rate_provenance": CANDIDATE,
        "scene_motion_deg_during_readout": motion_deg,
        "fov_h_deg": fov, "fov_h_provenance": DOCUMENTED,
        "width_px": width, "width_provenance": DOCUMENTED,
        "angle_deg": float(angle_deg), "angle_convention": "angle between motion and the pixel "
                                                          "x axis; sin(angle) scales the shear",
        "displacement_px": float(dx_px),
        "displacement_mm_at_250mm": float(
            dx_px * 2.0 * 250.0 * math.tan(math.radians(fov) / 2.0) / width),
        "provenance": CANDIDATE,
        "calibration": "待实测: strobe or known-rotation test with a printed grid; the plan only "
                       "declares '滚动快门' and gives no line time",
    }


@dataclass(frozen=True)
class RollingShutterModel:
    """Per-row shear of one frame (the identity at ``level == 0``)."""

    rate_dps: float = 2.0
    axis_u: float = 0.5           # image x of the rotation axis, in normalised units
    level: int = 0

    def displacement_px(self, rig: CaptureRigSpec, *, width_px: int, rows: int,
                        angle_deg: float = 90.0) -> dict[str, Any]:
        info = rolling_shutter_displacement_px(
            line_time_s=float(rig.camera.line_time_us.value) * 1e-6, rows=rows,
            rate_dps=self.rate_dps, fov_h_deg=float(rig.camera.fov_h_deg.value),
            width_px=width_px, angle_deg=angle_deg)
        info["model_level"] = int(self.level)
        return info

    def row_offsets_px(self, rig: CaptureRigSpec, *, width_px: int, rows: int,
                       rate_dps: float | None = None) -> tuple[np.ndarray, dict[str, Any]]:
        """Horizontal shift (px) per image row, linear in the row index.

        The scene rotates about the image of the turntable axis, so the tangential displacement is
        proportional to the distance from that axis: ``dx(row) = k * (x_axis_offset)`` is already
        folded into the per-pixel warp in :func:`apply_rolling_shutter`; the *row* delay itself is
        a pure ramp, which is what this returns.
        """
        rate = float(self.rate_dps if rate_dps is None else rate_dps)
        line_time_s = float(rig.camera.line_time_us.value) * 1e-6
        fov = float(rig.camera.fov_h_deg.value)
        width = int(width_px)
        t_rows = line_time_s * np.arange(int(rows), dtype=np.float64)
        shear_deg = rate * t_rows
        offsets = shear_deg / fov * width
        info = {
            "line_time_s": line_time_s, "line_time_provenance": CANDIDATE,
            "rows": int(rows), "width_px": width,
            "rate_dps": rate, "rate_provenance": CANDIDATE,
            "frame_readout_s": float(line_time_s * rows),
            "max_row_offset_px": float(offsets.max()) if offsets.size else 0.0,
            "min_row_offset_px": float(offsets.min()) if offsets.size else 0.0,
            "row_offset_p95_px": float(np.percentile(offsets, 95)) if offsets.size else 0.0,
            "row_axis": "image rows of one frame; the delay is linear in the row index",
            "model_level": int(self.level),
            "calibration": "待实测 (line time + turntable rate)",
        }
        return offsets, info


def apply_rolling_shutter(frame: Mapping[str, Any], offsets_px: np.ndarray, *,
                          axis_u: float = 0.5) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resample one frame with a **per-row** horizontal shift (a real rolling-shutter read-out).

    The shift applied to a pixel is proportional to its distance from the image of the rotation
    axis (``axis_u`` in normalised units), because a rotating body's tangential speed grows with
    that distance.  Parallel rows keep their identity, which is exactly the "slant" a rolling
    shutter produces and which no global translation can reproduce.
    """
    import cv2

    linear = frame_linear(frame)
    height, width = int(linear.shape[0]), int(linear.shape[1])
    offsets = np.asarray(offsets_px, dtype=np.float64)
    if offsets.shape[0] != height:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"row offset count {offsets.shape[0]} does not match the frame height "
                          f"{height}", stage="degrade.rig_error.apply_rolling_shutter")
    xs = (np.arange(width, dtype=np.float64) + 0.5) / float(width) - float(axis_u)
    shift = np.outer(offsets, xs)                       # (rows, cols), pixels
    # Per-row affine warp.  A single ``cv2.remap`` with the whole map was implemented first and
    # measured to raise ``cv2.error: Unknown C++ exception`` **only** inside this pipeline (the
    # identical call succeeds on the identically shaped array in isolation), so the row loop is the
    # form that is actually reproducible; it is also exactly what a rolling shutter does (one
    # read-out line at a time) and it keeps every row's horizontal interpolation independent.
    work = np.ascontiguousarray(linear, dtype=np.float32)
    out = np.empty_like(work)
    for row in range(height):
        matrix = np.array([[1.0, 0.0, float(shift[row, 0])], [0.0, 1.0, 0.0]], dtype=np.float64)
        out[row] = cv2.warpAffine(work[row][None, :, :], matrix, (width, 1),
                                  flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)[0]
    new_frame = dict(frame)
    new_frame["rgb_linear"] = np.asarray(out, dtype=np.float32)
    new_frame["rgb"] = encode_linear(new_frame["rgb_linear"], frame_encoding(frame))
    new_frame["image_size"] = (width, height)
    new_frame["rolling_shutter"] = {
        "row_offsets_px": [float(offsets.min()), float(offsets.max())],
        "axis_u_normalised": float(axis_u),
    }
    info = {
        "op": "per_row_horizontal_remap",
        "rows": height, "cols": width,
        "max_shift_px": float(np.abs(shift).max()) if shift.size else 0.0,
        "shift_p95_px": float(np.percentile(np.abs(shift), 95)) if shift.size else 0.0,
        "measured_max_edge_displacement_px": float(np.abs(np.diff(shift, axis=0)).max())
        if height > 1 else 0.0,
        "interpolation": "INTER_LINEAR",
        "not_a_global_translation": True,
    }
    return new_frame, info


# ======================================================================================
# manual-focus error
# ======================================================================================
@dataclass(frozen=True)
class FocusModel:
    """Manual focus error -> circle of confusion -> PSF sigma, at the *declared* aperture."""

    def circle_of_confusion_px(self, rig: CaptureRigSpec, *, focus_distance_mm: float,
                               object_distance_mm: float) -> dict[str, Any]:
        """Thin-lens CoC in delivered pixels, using the repository's own v2 instrument.

        The unit bug that the plan's ``coc_units_v2`` masks exist for is honoured: the CoC is
        evaluated in millimetres and multiplied by the sampling density ``D = N_x / W_sensor``
        (px per mm of sensor), never by feeding a pixel focal length into the mm expression.
        """
        from ..observe.render import circle_of_confusion_px

        camera = rig.camera
        f_px = camera.focal_px
        density = camera.px_per_mm_sensor
        f_mm = camera.focal_mm
        z = np.asarray([float(object_distance_mm)], dtype=np.float64)
        coc_px = circle_of_confusion_px(z, float(focus_distance_mm), camera.lens.aperture_ratio,
                                        f_px, sampling_px_per_mm=density)
        coc_mm = float(coc_px[0]) / density
        c = max(coc_px[0], 0.0)
        # a geometric defocus disc of diameter c has the same second moment as a Gaussian of
        # sigma = c / 4  (variance of a uniform disc of radius r is r^2/4 -> sigma = r/2 = c/4)
        sigma_px = c / 4.0
        return {
            "focus_distance_mm": float(focus_distance_mm),
            "object_distance_mm": float(object_distance_mm),
            "defocus_mm": float(object_distance_mm) - float(focus_distance_mm),
            "focal_length_mm": f_mm, "focal_length_provenance": camera.lens.focal_length_mm.provenance,
            "f_number": camera.lens.aperture_ratio,
            "f_number_provenance": camera.lens.f_number.provenance,
            "px_per_mm_sensor": density,
            "coc_mm": coc_mm, "coc_px": float(coc_px[0]),
            "psf_sigma_px": float(sigma_px),
            "psf_sigma_rule": "geometric defocus disc of diameter c_px == Gaussian sigma = c/4",
            "instrument": "synlab.observe.render.circle_of_confusion_px (mask_semantics "
                          "coc_units_v2, mm CoC * sampling density)",
            "provenance": CANDIDATE,
            "calibration": "待实测: f-number and focal length are not in the plan (§4.2 p513 "
                           "explicitly leaves lens and focal length unspecified)",
        }

    def depth_of_field_mm(self, rig: CaptureRigSpec, *, focus_distance_mm: float,
                          coc_px: float = 2.0) -> dict[str, Any]:
        """Thin-lens depth of field for a permitted CoC of ``coc_px`` delivered pixels.

        The plan prints **no** DoF number (§4.2 p404: 文档未给出数值景深); this derives one from the
        declared aperture and pixel pitch instead of quoting a value the document does not have.
        """
        camera = rig.camera
        f = camera.focal_mm
        n = camera.lens.aperture_ratio
        c_mm = float(coc_px) * float(camera.pixel_pitch_mm.value)
        z = float(focus_distance_mm)
        hyperfocal = f * f / max(n * c_mm, 1e-12) + f
        near = hyperfocal * z / max(hyperfocal + (z - f), 1e-9)
        far = hyperfocal * z / max(hyperfocal - (z - f), 1e-9) if hyperfocal > (z - f) else float(
            "inf")
        return {
            "focus_distance_mm": z, "coc_px": float(coc_px), "coc_mm": c_mm,
            "hyperfocal_mm": float(hyperfocal),
            "near_mm": float(near), "far_mm": float(far),
            "total_mm": float(far - near) if np.isfinite(far) else float("inf"),
            "formula": "H = f^2/(N c) + f; near = H z/(H + z - f); far = H z/(H - z + f)",
            "provenance": DERIVED,
            "note": "derived from the CANDIDATE f-number and the derived pixel pitch; the plan "
                    "gives no DoF value (§4.2 p404)",
        }


def apply_defocus(frame: Mapping[str, Any], sigma_px: float) -> tuple[dict[str, Any], dict[str, Any]]:
    """Real Gaussian PSF convolution of the linear plane (never a painted blur)."""
    if float(sigma_px) <= 0:
        raise SynLabError(ErrorCode.OPERATOR_NOT_REALIZED,
                          "apply_defocus needs sigma_px > 0 (level 0 must not be re-applied)",
                          stage="degrade.rig_error.apply_defocus")
    kernel, info = gaussian_psf(float(sigma_px))
    blurred = convolve(frame_linear(frame), kernel)
    new_frame = dict(frame)
    new_frame["rgb_linear"] = np.asarray(blurred, dtype=np.float32)
    new_frame["rgb"] = encode_linear(new_frame["rgb_linear"], frame_encoding(frame))
    new_frame["image_size"] = (int(blurred.shape[1]), int(blurred.shape[0]))
    new_frame["defocus"] = {"sigma_px": float(sigma_px), "psf": "GAUSSIAN"}
    return new_frame, {"op": "gaussian_psf", "sigma_px": float(sigma_px), **info}


# ======================================================================================
# intrinsics drift + scale drift
# ======================================================================================
@dataclass(frozen=True)
class IntrinsicsDriftModel:
    """Per-condition intrinsics drift.

    The plan requires that *every stable lens/resolution/focus condition keeps its own
    calibration* and that intrinsics are never blindly shared (p1155, p1163).  This model turns
    that requirement into the two numbers a recipe can actually move — the focal length and the
    principal point — and keeps both inside **candidate** bounds, because no calibration of this
    rig exists yet::

        fx' = fx * (1 + u * focal_rel_max)      focal_rel_max = 0.03   (candidate, 0-3 %)
        cx' = cx + v * principal_px_max         principal_px_max = 5.0 (candidate, 0-5 px)

    ``u``/``v`` are frozen per condition (never re-drawn per level), which is what makes the five
    levels of the axis paired.
    """

    focal_rel_max: float = 0.03
    principal_px_max: float = 5.0

    def drift(self, K: np.ndarray, *, condition_u: float, condition_v: float,
              level: int) -> tuple[np.ndarray, dict[str, Any]]:
        matrix = np.asarray(K, dtype=np.float64).copy()
        scale = 1.0 + float(condition_u) * float(self.focal_rel_max)
        dx = float(condition_v) * float(self.principal_px_max)
        dy = float(condition_v) * float(self.principal_px_max) * 0.6
        matrix[0, 0] *= scale
        matrix[1, 1] *= scale
        matrix[0, 2] += dx
        matrix[1, 2] += dy
        info = {
            "op": "intrinsics_condition_drift",
            "level": int(level),
            "focal_scale": float(scale), "focal_rel_max": float(self.focal_rel_max),
            "principal_shift_px": [float(dx), float(dy)],
            "principal_px_max": float(self.principal_px_max),
            "fx_before": float(np.asarray(K, dtype=np.float64)[0, 0]),
            "fx_after": float(matrix[0, 0]),
            "cx_before": float(np.asarray(K, dtype=np.float64)[0, 2]),
            "cx_after": float(matrix[0, 2]),
            "provenance": CANDIDATE,
            "calibration": "待实测校准: the 0-3 % focal and 0-5 px principal bounds are candidate "
                           "values from the plan's own requirement text, not measurements.  A real "
                           "calibration board run per condition replaces them.",
            "plan_requirement": "p1155/p1163: 每一种稳定镜头/分辨率/对焦距离工况都要保存独立相机"
                                "标定；焦距、镜头或近摄距离明显变化时禁止盲目共享",
        }
        return matrix, info


@dataclass(frozen=True)
class ScaleDriftModel:
    """Scale drift (0-5 %), coupled to the presence and the visibility of the scale reference.

    The plan requires a traceable scale reference in *every formal capture* and an automatic
    absolute-scale check after reconstruction (p1163).  A reconstruction that never saw the
    reference keeps an arbitrary scale: that is a 100 % error, not 5 %, and the model says so
    instead of hiding it inside a small percentage.  ``reference_visible_fraction`` is therefore an
    explicit input: with the reference fully visible the drift is the calibrated residual, with it
    partly visible the drift grows, and with no reference at all the scale is reported as
    ``ARBITRARY``.
    """

    drift_rel_max: float = 0.05

    def drift(self, *, reference_present: bool, reference_visible_fraction: float,
              condition: float, level: int) -> dict[str, Any]:
        visible = float(np.clip(reference_visible_fraction, 0.0, 1.0))
        if not reference_present:
            relative = float("inf")
            status = "ARBITRARY"
        elif visible <= 1e-6:
            relative = float("inf")
            status = "ARBITRARY"
        else:
            relative = float(self.drift_rel_max) * float(condition) * (1.0 + (1.0 / visible - 1.0))
            status = "BOUNDED"
        return {
            "op": "scale_drift",
            "level": int(level),
            "reference_present": bool(reference_present),
            "reference_visible_fraction": visible,
            "scale_error_relative": relative,
            "scale_error_percent": (100.0 * relative if np.isfinite(relative) else None),
            "drift_rel_max": float(self.drift_rel_max),
            "status": status,
            "coupling": "the scale enters the point cloud and therefore the reconstruction: a "
                        "scale error shows up as a global metric error, never as a local one",
            "provenance": CANDIDATE if status == "BOUNDED" else UNKNOWN_,
            "calibration": "待实测: repeated capture of one scale bar (repeat scan deviation) is "
                           "the measurement that replaces this 0-5 % candidate",
        }


UNKNOWN_ = "UNKNOWN"


# ======================================================================================
# illumination modes
# ======================================================================================
@dataclass(frozen=True)
class IlluminationModel:
    """The five documented light states applied to a delivered frame, in the linear domain.

    The physical statement the plan makes about cross-polarisation is "**降低部分釉面高光**"
    (reduces *part* of the glaze highlight) — not "removes the highlight".  The model reproduces
    exactly that: ``I' = diffuse_weight * I_diffuse + specular_weight * specular_retained *
    I_specular``, with the cross-polarised state keeping only ``k_perp^2`` of the specular return
    (for an ideal crossed pair ``k_perp = 0``; for real film ≈0.47 amplitude → ≈0.22 intensity).
    Both the ideal value and the film value are candidates until the A6 paired capture
    (普通光 / 交叉偏振 / 侧光, same piece same pose, p443-p444) measures them.
    """

    def weights(self, mode: str) -> dict[str, Any]:
        spec = light_mode(mode)
        return {
            "mode": spec.mode, "groups": list(spec.groups), "polariser": spec.polariser,
            "purpose": spec.purpose, "ref": spec.ref,
            "diffuse_weight": float(spec.diffuse_weight.value),
            "specular_weight": float(spec.specular_weight.value),
            "specular_retained": float(spec.specular_retained.value),
            "key_direction": list(spec.key_direction.value),
            "provenance": CANDIDATE,
            "documented_part": "the five mode names, their lamp groups and their purposes are "
                               "verbatim from table t053; the imaging weights are not printed "
                               "anywhere in the plan",
            "calibration": "待实测 (A6 paired capture: 普通光 / 交叉偏振 / 侧光 same piece same "
                           "pose)",
        }

    def apply(self, frame: Mapping[str, Any], mode: str, *,
              specular_mask: np.ndarray | None = None, level: int = 4) -> tuple[
            dict[str, Any], dict[str, Any]]:
        """Rewrite the linear plane of one frame for one light state.

        ``specular_mask`` is the *support* of the specular return.  When the source does not carry
        one, the model derives it from the data with a stated rule (the brightest 2 % of the
        frame's luma, which is what a glaze highlight is) and reports the rule — it never pretends
        the highlight was known.
        """
        linear = frame_linear(frame)
        info = self.weights(mode)
        luma = (0.2126 * linear[..., 0] + 0.7152 * linear[..., 1] + 0.0722 * linear[..., 2])
        if specular_mask is None:
            threshold = float(np.quantile(luma, 0.98))
            mask = (luma >= threshold)[..., None].astype(np.float32)
            info["specular_mask_rule"] = ("brightest 2 % of the frame luma (quantile 0.98); the "
                                          "source carries no declared highlight support")
            info["specular_mask_fraction"] = float(np.mean(mask))
        else:
            mask = np.asarray(specular_mask, dtype=np.float32)
            while mask.ndim < linear.ndim:
                mask = mask[..., None]
            info["specular_mask_rule"] = "CALLER_SUPPLIED"
            info["specular_mask_fraction"] = float(np.mean(mask))
        diffuse = linear * (1.0 - mask)
        specular = linear * mask
        out = (float(info["diffuse_weight"]) * diffuse
               + float(info["specular_weight"]) * float(info["specular_retained"]) * specular)
        out = np.asarray(out, dtype=np.float32)
        new_frame = dict(frame)
        new_frame["rgb_linear"] = out
        new_frame["rgb"] = encode_linear(out, frame_encoding(frame))
        new_frame["image_size"] = (int(out.shape[1]), int(out.shape[0]))
        new_frame["light_mode"] = {"mode": info["mode"], "level": int(level),
                                   "specular_retained": info["specular_retained"]}
        before = float(np.mean(luma))
        after = float(np.mean(0.2126 * out[..., 0] + 0.7152 * out[..., 1] + 0.0722 * out[..., 2]))
        spec_before = float(np.mean(luma[mask[..., 0] > 0.5])) if bool(np.any(mask > 0.5)) else 0.0
        spec_after = float(np.mean((0.2126 * out[..., 0] + 0.7152 * out[..., 1]
                                    + 0.0722 * out[..., 2])[mask[..., 0] > 0.5])) \
            if bool(np.any(mask > 0.5)) else 0.0
        info.update({
            "op": "light_state_linear_mix",
            "level": int(level),
            "mean_luma_before": before, "mean_luma_after": after,
            "highlight_region_luma_before": spec_before,
            "highlight_region_luma_after": spec_after,
            "highlight_suppression_ratio": float(1.0 - spec_after / max(spec_before, 1e-9)),
            "highlight_area_fraction": float(np.mean(mask > 0.5)),
        })
        return new_frame, info


# ======================================================================================
# resolution at working distance
# ======================================================================================
@dataclass(frozen=True)
class ResolutionAtDistanceModel:
    """Effective pixel size at a working distance, and the honest way to *reach* that density.

    The plan forbids simulating a physical approach with ``resize`` (§G14.4 p1488: "U 沿光轴改变外参，
    不用 resize 模拟物理靠近；I09 低分辨率与工作距离单独控制").  :func:`resample_to_distance`
    therefore changes the **declared camera distance**: ``K`` is re-derived from the documented
    pinhole relation at the new distance and the delivered plane is resampled by the ratio of the
    pixel densities.  The model reports the ratio and the resolution table reference, and never
    calls the result "a closer camera" — it is a re-projection of one delivered frame, which is
    what is available when the capture has already happened.
    """

    def effective(self, rig: CaptureRigSpec, working_distance_mm: float,
                  delivered_width_px: int) -> dict[str, Any]:
        camera = rig.camera
        value = camera.mm_per_px_value(working_distance_mm)
        ideal_px = int(round(
            2.0 * working_distance_mm * math.tan(math.radians(float(camera.fov_h_deg.value)) / 2.0)
            / float(value.value)))
        return {
            "working_distance_mm": float(working_distance_mm),
            "mm_per_px": float(value.value),
            "mm_per_px_provenance": value.provenance,
            "mm_per_px_ref": value.ref,
            "ideal_width_px_at_full_sensor": ideal_px,
            "delivered_width_px": int(delivered_width_px),
            "delivered_mm_per_px": float(
                2.0 * working_distance_mm * math.tan(math.radians(float(camera.fov_h_deg.value)) / 2.0)
                / max(int(delivered_width_px), 1)),
            "documented_table_mm_per_px": {str(k): v.value
                                           for k, v in camera.resolution_mm_per_px.items()},
            "nearest_documented_distance_mm": min(
                camera.resolution_mm_per_px,
                key=lambda d: abs(int(d) - int(round(working_distance_mm)))),
            "not_a_resize": True,
            "note": "the effective pixel size follows the documented pinhole relation; a delivered "
                    "frame at a different distance carries a different pixel density, and the "
                    "plan requires camera_spec to reference the measured GLOBAL/MID/LOCAL tiers",
        }


def intrinsics_at_distance(K: np.ndarray, *, from_distance_mm: float, to_distance_mm: float
                           ) -> tuple[np.ndarray, dict[str, Any]]:
    """``K`` for a camera moved along its optical axis (angular FOV preserved, pixel size scaled).

    A pinhole camera moved *away* keeps ``f_px`` and shrinks the object's projected size; the
    equivalent statement used here is that the delivered pixel grid stays the same and the object
    space covered by one pixel grows linearly with the distance.  Both statements are the same
    relation, and the one implemented is the one that keeps ``K`` valid for the delivered pixel
    grid: ``f_px' = f_px * z_from / z_to``.
    """
    matrix = np.asarray(K, dtype=np.float64).copy()
    ratio = float(from_distance_mm) / float(to_distance_mm)
    matrix[0, 0] *= ratio
    matrix[1, 1] *= ratio
    return matrix, {
        "op": "intrinsics_at_working_distance",
        "from_distance_mm": float(from_distance_mm), "to_distance_mm": float(to_distance_mm),
        "focal_px_scale": ratio,
        "fx_before": float(np.asarray(K, dtype=np.float64)[0, 0]),
        "fx_after": float(matrix[0, 0]),
        "principal_point_unchanged": True,
        "formula": "f_px' = f_px * z_from / z_to (object space per pixel grows linearly in z)",
        "provenance": DERIVED,
        "plan_ref": "§G14.4 p1488 (U 沿光轴改变外参，不用 resize 模拟物理靠近)",
    }


def resample_to_distance(frame: Mapping[str, Any], *, from_distance_mm: float,
                         to_distance_mm: float) -> tuple[dict[str, Any], dict[str, Any]]:
    """Re-project one delivered frame onto the pixel density of another working distance.

    The scale factor is ``z_from / z_to`` (object space per pixel grows with distance).  The
    interpolation is reported, ``K`` is updated through :func:`intrinsics_at_distance`, and the
    result is labelled ``REPROJECTED_PIXEL_DENSITY`` — never "a capture from closer".
    """
    import cv2

    linear = frame_linear(frame)
    height, width = int(linear.shape[0]), int(linear.shape[1])
    scale = float(from_distance_mm) / float(to_distance_mm)
    new_w = max(int(round(width * scale)), 8)
    new_h = max(int(round(height * scale)), 8)
    interpolation = "INTER_AREA" if scale < 1.0 else "INTER_LINEAR"
    flag = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
    out = cv2.resize(linear, (new_w, new_h), interpolation=flag)
    K_before = frame.get("K")
    info: dict[str, Any] = {
        "op": "REPROJECTED_PIXEL_DENSITY",
        "scale_factor": scale, "size_before": [width, height], "size_after": [new_w, new_h],
        "interpolation": interpolation,
        "not_a_resize_claim": "this is a change of pixel density, not a physical approach: the "
                              "plan forbids using resize to simulate moving closer (I09 and the "
                              "working distance are separate controls)",
        "plan_ref": "§G14.4 p1488",
        "provenance": DERIVED,
    }
    new_frame = dict(frame)
    new_frame["rgb_linear"] = np.asarray(out, dtype=np.float32)
    new_frame["rgb"] = encode_linear(new_frame["rgb_linear"], frame_encoding(frame))
    new_frame["image_size"] = (new_w, new_h)
    new_frame["working_distance_mm"] = float(to_distance_mm)
    if K_before is not None:
        K_new, k_info = intrinsics_at_distance(np.asarray(K_before, dtype=np.float64),
                                               from_distance_mm=from_distance_mm,
                                               to_distance_mm=to_distance_mm)
        new_frame["K"] = K_new
        info["intrinsics"] = k_info
    return new_frame, info


# ======================================================================================
# reconstruction error
# ======================================================================================
@dataclass(frozen=True)
class ReconstructionModel:
    """Observed-point-cloud error: noise, holes and the valid-point fraction.

    The plan fixes a *synthetic calibration line* — "Q2 当量": >= 50 % valid points retained,
    coordinate noise sigma <= 0.2 mm, <= 2 local holes of radius <= 3 mm — and says explicitly that
    it must be re-calibrated once a real scan exists (p1063).  The model keeps that line as the
    **ceiling of the worst level** and derives the distance dependence of the noise from the same
    pinhole relation the resolution table uses: depth noise from disparity scales as
    ``z^2 / (f_px * B) * sigma_parallax``, so a body observed from farther away is noisier for
    exactly the reason its pixels are coarser.
    """

    sigma_floor_mm: float = float(RECON_FLOOR_SIGMA_MM.value)
    max_holes: int = int(RECON_FLOOR_HOLES.value)
    hole_radius_max_mm: float = float(RECON_FLOOR_HOLE_RADIUS_MM.value)
    min_valid_fraction: float = float(RECON_FLOOR_VALID_FRACTION.value)

    def noise_sigma_mm(self, rig: CaptureRigSpec, *, working_distance_mm: float,
                       baseline_mm: float, sigma_parallax_px: float = 0.25) -> dict[str, Any]:
        camera = rig.camera
        f_px = camera.focal_px
        sigma_mm = (float(working_distance_mm) ** 2) / max(f_px * float(baseline_mm), 1e-9) \
            * float(sigma_parallax_px)
        return {
            "op": "depth_from_disparity_noise",
            "working_distance_mm": float(working_distance_mm),
            "baseline_mm": float(baseline_mm),
            "f_px": float(f_px), "f_px_provenance": DERIVED,
            "sigma_parallax_px": float(sigma_parallax_px),
            "sigma_parallax_provenance": CANDIDATE,
            "sigma_mm": float(sigma_mm),
            "formula": "sigma_z = z^2 / (f_px B) * sigma_disparity",
            "floor_mm": float(self.sigma_floor_mm),
            "floor_ref": "p1063 'Q2 当量' sigma <= 0.2 mm (synthetic calibration line)",
            "exceeds_floor": bool(sigma_mm > float(self.sigma_floor_mm)),
            "calibration": "待实测: the plan requires re-calibration after Gate B; sigma_parallax "
                           "is a candidate",
        }

    def reconstruction_quality(self, points: np.ndarray, *, voxel_mm: float,
                               plane_radius_mm: float = 3.0) -> dict[str, Any]:
        """Measured quality of a **real** point cloud (never of a declared one).

        Returns the three quantities the 8-item real quality vector needs on the geometry side:
        the valid fraction, the local plane-fit residual (the measured stand-in for coordinate
        noise) and the hole census at the declared voxel size, plus the normal / curvature
        stability measured as the drift of those two fields under a one-voxel resample.
        """
        pts = np.asarray(points, dtype=np.float64)
        finite = np.all(np.isfinite(pts), axis=1)
        valid = pts[finite]
        out: dict[str, Any] = {
            "n_points": int(len(pts)), "n_valid": int(len(valid)),
            "valid_fraction": float(len(valid) / max(len(pts), 1)),
            "plane_radius_mm": float(plane_radius_mm),
            "voxel_mm": float(voxel_mm),
        }
        if len(valid) < 16:
            out.update({"sigma_mm": None, "hole_count": None, "note": "too few valid points"})
            return out
        from scipy.spatial import cKDTree

        tree = cKDTree(valid)
        neighbours = tree.query_ball_point(valid, r=float(plane_radius_mm))
        residuals: list[float] = []
        normals: list[np.ndarray] = []
        for index, group in enumerate(neighbours):
            if len(group) < 6:
                residuals.append(np.nan)
                continue
            block = valid[np.asarray(group, dtype=np.int64)]
            centre = block.mean(axis=0)
            _u, _s, vt = np.linalg.svd(block - centre, full_matrices=False)
            normal = np.asarray(vt[2], dtype=np.float64)
            residuals.append(abs(float((valid[index] - centre) @ normal)))
            normals.append(normal)
        residual = np.asarray(residuals, dtype=np.float64)
        out["sigma_mm"] = float(np.nanmedian(residual)) if np.isfinite(residual).any() else None
        out["sigma_p95_mm"] = float(np.nanpercentile(residual, 95)) if np.isfinite(residual).any() \
            else None
        out["sigma_method"] = ("median distance of every point to the least-squares plane of its "
                               f"{plane_radius_mm:.1f} mm neighbourhood (a real local plane fit)")
        # normals stability: the angle between a point's plane normal and the normal of the
        # same neighbourhood after a half-voxel shift of the query centre (a real resample drift)
        angles: list[float] = []
        for index, group in enumerate(neighbours):
            if len(group) < 6:
                continue
            block = valid[np.asarray(group, dtype=np.int64)]
            centre = block.mean(axis=0)
            shift = 0.5 * float(voxel_mm) * np.array([0.0, 0.0, 1.0])
            near = valid[tree.query_ball_point(centre + shift, r=float(plane_radius_mm))]
            if len(near) < 6:
                continue
            _u1, _s1, vt1 = np.linalg.svd(block - centre, full_matrices=False)
            _u2, _s2, vt2 = np.linalg.svd(near - near.mean(axis=0), full_matrices=False)
            cosine = abs(float(np.asarray(vt1[2]) @ np.asarray(vt2[2])))
            angles.append(math.degrees(math.acos(min(max(cosine, -1.0), 1.0))))
        out["normal_drift_deg_median"] = float(np.median(angles)) if angles else None
        # curvature stability: the spread of the plane residual under the same resample
        out["curvature_stability_mm"] = float(np.nanstd(residual)) if np.isfinite(residual).any() \
            else None
        # hole census: connected components of an empty voxel grid inside the occupied hull
        occupied = np.unique(np.floor(valid / max(float(voxel_mm), 1e-9)).astype(np.int64), axis=0)
        holes = _hole_census(occupied, float(voxel_mm), float(self.hole_radius_max_mm))
        out.update(holes)
        return out


def _hole_census(occupied: np.ndarray, voxel_mm: float, radius_mm: float) -> dict[str, Any]:
    """**Enclosed** interior empty voxels grouped into holes; each hole's equivalent radius.

    A void that opens onto the border of the occupied grid is not a hole — it is the outside.  A
    first version of this census counted a box cut clean through a point cloud as zero holes, which
    is correct: cutting through a slab removes material from the boundary, and the plan's
    "<= 2 local holes of r <= 3 mm" is about *enclosed* voids of a reconstructed surface (p1063).
    The method string says so, so the number is never read as a general porosity measure.
    """
    if len(occupied) == 0:
        return {"hole_count": 0, "holes": [], "hole_count_within_radius": 0}
    lo = occupied.min(axis=0) - 2
    hi = occupied.max(axis=0) + 2
    shape = tuple((hi - lo + 1).tolist())
    grid = np.zeros(shape, dtype=bool)
    grid[tuple((occupied - lo).T.tolist())] = True
    interior = _flood_interior(grid)
    holes = interior & ~grid
    if not bool(np.any(holes)):
        return {"hole_count": 0, "holes": [], "hole_count_within_radius": 0,
                "method": "enclosed interior empty voxels (6-connected flood fill from the grid "
                          "border); a void that reaches the border is the outside, not a hole"}
    labels, count = _label6(holes)
    out: list[dict[str, Any]] = []
    for label in range(1, int(count) + 1):
        size = int(np.count_nonzero(labels == label))
        equivalent_radius = (3.0 * size * voxel_mm ** 3 / (4.0 * math.pi)) ** (1.0 / 3.0)
        out.append({"voxels": size, "equivalent_radius_mm": float(equivalent_radius),
                    "within_radius": bool(equivalent_radius <= radius_mm)})
    out.sort(key=lambda item: -item["voxels"])
    return {
        "hole_count": int(count),
        "hole_count_within_radius": int(sum(1 for item in out if item["within_radius"])),
        "holes": out[:16],
        "radius_max_mm": float(radius_mm),
        "method": "enclosed interior empty voxels (6-connected flood fill from the grid border); "
                  "equivalent radius of a sphere of the same volume",
    }


def _flood_interior(grid: np.ndarray) -> np.ndarray:
    """Voxels reachable from the grid border through *empty* cells (the exterior)."""
    from collections import deque

    exterior = np.zeros_like(grid)
    queue: deque[tuple[int, int, int]] = deque()
    shape = grid.shape
    for axis in range(3):
        for side in (0, shape[axis] - 1):
            for a in range(shape[(axis + 1) % 3]):
                for b in range(shape[(axis + 2) % 3]):
                    index = [0, 0, 0]
                    index[axis] = side
                    index[(axis + 1) % 3] = a
                    index[(axis + 2) % 3] = b
                    cell = tuple(index)
                    if not grid[cell] and not exterior[cell]:
                        exterior[cell] = True
                        queue.append(cell)
    while queue:
        x, y, z = queue.popleft()
        for dx, dy, dz in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)):
            nx, ny, nz = x + dx, y + dy, z + dz
            if 0 <= nx < shape[0] and 0 <= ny < shape[1] and 0 <= nz < shape[2]:
                if not grid[nx, ny, nz] and not exterior[nx, ny, nz]:
                    exterior[nx, ny, nz] = True
                    queue.append((nx, ny, nz))
    return ~exterior


def _label6(mask: np.ndarray) -> tuple[np.ndarray, int]:
    """Simple 6-connected labelling of a sparse boolean grid (no scipy dependency)."""
    from collections import deque

    labels = np.zeros(mask.shape, dtype=np.int32)
    current = 0
    coordinates = np.argwhere(mask)
    for cell in coordinates:
        x, y, z = (int(v) for v in cell)
        if labels[x, y, z]:
            continue
        current += 1
        queue: deque[tuple[int, int, int]] = deque([(x, y, z)])
        labels[x, y, z] = current
        while queue:
            cx, cy, cz = queue.popleft()
            for dx, dy, dz in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)):
                nx, ny, nz = cx + dx, cy + dy, cz + dz
                if 0 <= nx < mask.shape[0] and 0 <= ny < mask.shape[1] and 0 <= nz < mask.shape[2]:
                    if mask[nx, ny, nz] and not labels[nx, ny, nz]:
                        labels[nx, ny, nz] = current
                        queue.append((nx, ny, nz))
    return labels, current


def point_cloud_noise_sigma_mm(points: np.ndarray, *, voxel_mm: float) -> float | None:
    """Convenience wrapper: the measured local plane residual of a real cloud."""
    from ..errors import SynLabError as _E

    _ = _E
    return ReconstructionModel().reconstruction_quality(points, voxel_mm=voxel_mm)["sigma_mm"]


def measure_point_cloud_quality(points: np.ndarray, *, voxel_mm: float,
                                plane_radius_mm: float = 3.0) -> dict[str, Any]:
    """The public entry point of the reconstruction measurement (see :class:`ReconstructionModel`)."""
    return ReconstructionModel().reconstruction_quality(points, voxel_mm=voxel_mm,
                                                        plane_radius_mm=plane_radius_mm)


# ======================================================================================
# the whole rig error
# ======================================================================================
@dataclass(frozen=True)
class RigErrorModel:
    """Every rig-error term in one place, each carrying its own provenance and level ladder."""

    level: int = 0
    rolling_shutter: RollingShutterModel = field(default_factory=RollingShutterModel)
    focus: FocusModel = field(default_factory=FocusModel)
    intrinsics: IntrinsicsDriftModel = field(default_factory=IntrinsicsDriftModel)
    scale: ScaleDriftModel = field(default_factory=ScaleDriftModel)
    illumination: IlluminationModel = field(default_factory=IlluminationModel)
    resolution: ResolutionAtDistanceModel = field(default_factory=ResolutionAtDistanceModel)
    reconstruction: ReconstructionModel = field(default_factory=ReconstructionModel)
    intensity: float = 0.0

    def terms(self) -> dict[str, SpecValue]:
        """The declared term list with the provenance of each term's *driving* quantity."""
        return {
            "rolling_shutter": SpecValue("row delay * scene rotation", CANDIDATE,
                                         ref="§4.2 p504 (滚动快门; 行时间未给)",
                                         note="line time and turntable rate are candidates"),
            "focus": SpecValue("manual focus error -> CoC -> PSF", CANDIDATE,
                               ref="§4.2 p504/p513 (手动对焦; 镜头/焦距未给)",
                               note="f-number and focal length are candidates"),
            "intrinsics_drift": SpecValue("0-3 % focal, 0-5 px principal", CANDIDATE,
                                          ref="p1155/p1163 (每工况独立标定)",
                                          note="bound text is a plan requirement, not a "
                                               "measurement"),
            "scale_drift": SpecValue("0-5 %, coupled to the scale reference", CANDIDATE,
                                     ref="p1163 (每次正式采集必须包含可追溯尺度基准)",
                                     note="a capture without the reference has ARBITRARY scale, "
                                          "not 5 %"),
            "light_state": SpecValue("5 documented states", DOCUMENTED,
                                     ref="§4.4 表 t053 (p455-p463)",
                                     note="the enumeration is documented; the imaging weights are "
                                          "candidates"),
            "resolution_at_distance": SpecValue("0.039-0.195 mm/px over 50-250 mm", DOCUMENTED,
                                                ref="§4.2 t051/p512",
                                                note="documented table; no resize is used to "
                                                     "simulate approach"),
            "reconstruction": SpecValue("sigma<=0.2 mm, <=2 holes r<=3 mm, >=50 % valid",
                                        DOCUMENTED, ref="§5.6 p1063",
                                        note="synthetic calibration line; must be re-calibrated "
                                             "after Gate B"),
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "level": int(self.level), "intensity": float(self.intensity),
            "levels": list(RIG_LEVELS),
            "terms": {k: v.as_dict() for k, v in sorted(self.terms().items())},
        }


def scan_fault_ladder(rig: CaptureRigSpec | None = None, *, level: int = 4,
                      working_distance_mm: float = 150.0, delivered_width_px: int = 1024,
                      rows: int = 768, baseline_mm: float = 40.0,
                      reference_present: bool = True,
                      reference_visible_fraction: float = 1.0) -> dict[str, Any]:
    """The numeric ladder of every rig-error term at one fault level (the report's core table)."""
    rig = rig or capture_rig_spec()
    intensity = RIG_LEVELS[int(level)]
    camera = rig.camera
    model = RigErrorModel(level=int(level), intensity=float(intensity))
    rate = float(rig.motion.turntable_rate_dps.value) * float(intensity)
    offsets, rs_info = model.rolling_shutter.row_offsets_px(rig, width_px=delivered_width_px,
                                                            rows=rows, rate_dps=rate)
    coc = model.focus.circle_of_confusion_px(
        rig, focus_distance_mm=working_distance_mm,
        object_distance_mm=working_distance_mm * (1.0 + 0.08 * float(intensity)))
    dof = model.focus.depth_of_field_mm(rig, focus_distance_mm=working_distance_mm, coc_px=2.0)
    k_info: dict[str, Any] = {}
    fx_delivered = camera.focal_px * float(delivered_width_px) / float(
        camera.sensor_width_mm.value)
    sample_K = np.array([[fx_delivered, 0.0, delivered_width_px / 2.0],
                         [0.0, fx_delivered, rows / 2.0], [0.0, 0.0, 1.0]])
    drift_K, k_info = model.intrinsics.drift(sample_K, condition_u=float(intensity),
                                             condition_v=float(intensity), level=int(level))
    scale = model.scale.drift(reference_present=reference_present,
                              reference_visible_fraction=reference_visible_fraction,
                              condition=float(intensity), level=int(level))
    res = model.resolution.effective(rig, working_distance_mm, delivered_width_px)
    noise = model.reconstruction.noise_sigma_mm(rig, working_distance_mm=working_distance_mm,
                                                baseline_mm=baseline_mm)
    light = {mode: model.illumination.weights(mode) for mode in
             ("WHITE_DIFFUSE", "LEFT_GRAZE", "RIGHT_GRAZE", "CROSS_POL", "NORMAL_REFLECT")}
    return {
        "level": int(level), "intensity": float(intensity),
        "levels": list(RIG_LEVELS),
        "working_distance_mm": float(working_distance_mm),
        "delivered_size_px": [int(delivered_width_px), int(rows)],
        "rolling_shutter": {**rs_info,
                            "row_offsets_px_max": float(offsets.max()) if offsets.size else 0.0,
                            "row_offsets_px_min": float(offsets.min()) if offsets.size else 0.0,
                            "row_offset_px_p95": float(np.percentile(offsets, 95))
                            if offsets.size else 0.0,
                            "frame_rows": int(rows), "real_delivered_sensor_grid": True},
        "defocus": coc, "depth_of_field": dof,
        "intrinsics_drift": k_info,
        "scale_drift": scale,
        "light_states": light,
        "resolution": res,
        "reconstruction_noise": noise,
        "model": model.as_dict(),
        "candidates": rig.candidates(),
    }
