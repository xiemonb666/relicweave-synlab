"""Place a sourced blue-white pigment field on a sampled bowl meridian.

The input curve is the caller's sampled outer meridian ``[radius, z, s]`` chart payload.
The panel mapping and bleed are appearance controls; they do not recover pre-firing pigment
or change vessel geometry.  ``s`` is recomputed from the finite ``(r,z)`` polyline because
the current reference-generator chart payload stores a zero placeholder in column three.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np

from .underglaze import (
    MAX_ESTIMATED_WORKING_BYTES,
    MAX_GRID_CELLS,
    MAX_OPERATOR_NNZ,
    SurfaceOfRevolutionOperator,
    TwoFractionAppearanceResult,
    blue_white_appearance,
    build_surface_of_revolution_operator,
    diffuse_two_fraction_appearance,
    sample_periodic_field,
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
NORMALIZED_DENSITY_HASH_SCHEMA = \
    "synlab.patterns.bluewhite_panel.normalized_density_sha256.v1"
_NORMALIZED_DENSITY_CANONICAL_DTYPE = "<f8"
GRID_BILINEAR_SAMPLING = "grid_bilinear_v1"
SOURCE_RESOLVED_STATIONARY_SAMPLING = "source_resolved_stationary_v1"
_CONTINUOUS_SAMPLING_MODES = {
    GRID_BILINEAR_SAMPLING,
    SOURCE_RESOLVED_STATIONARY_SAMPLING,
}
_SOURCE_FIELDS = (
    "source_id",
    "title",
    "source_url",
    "source_mask_path",
    "source_mask_sha256",
    "normalized_density_sha256",
    "mask_semantics",
    "photo_state",
)


def normalized_density_sha256(normalized_density: np.ndarray) -> str:
    """Hash schema, shape, input dtype, and canonical little-endian float64 values."""
    input_values = np.asarray(normalized_density)
    if (input_values.ndim != 2 or not np.issubdtype(input_values.dtype, np.number)
            or np.issubdtype(input_values.dtype, np.complexfloating)
            or not np.all(np.isfinite(input_values))):
        raise ValueError("normalized_density must be a finite two-dimensional array")
    canonical = np.ascontiguousarray(input_values.astype(_NORMALIZED_DENSITY_CANONICAL_DTYPE,
                                                          copy=False))
    if not np.all(np.isfinite(canonical)):
        raise ValueError("normalized_density cannot be represented as finite float64 values")
    header = json.dumps({
        "schema": NORMALIZED_DENSITY_HASH_SCHEMA,
        "shape": list(input_values.shape),
        "input_dtype": input_values.dtype.str,
        "canonical_dtype": _NORMALIZED_DENSITY_CANONICAL_DTYPE,
        "memory_order": "C",
    }, sort_keys=True, separators=(",", ":")).encode("ascii")
    digest = hashlib.sha256()
    digest.update(header)
    digest.update(b"\0")
    digest.update(canonical.tobytes(order="C"))
    return digest.hexdigest()


def _source_record(source_metadata: Mapping[str, Any],
                   normalized_density: np.ndarray, *,
                   normalized_density_hash: str | None = None) -> dict[str, str]:
    if not isinstance(source_metadata, Mapping):
        raise ValueError("source_metadata must be an explicit mapping")
    missing = [name for name in _SOURCE_FIELDS if name not in source_metadata]
    if missing:
        raise ValueError("source_metadata is missing required fields: " + ", ".join(missing))
    record: dict[str, str] = {}
    for name in _SOURCE_FIELDS:
        value = source_metadata[name]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"source_metadata[{name!r}] must be a non-empty string")
        record[name] = value.strip()
    if not _SHA256_RE.fullmatch(record["source_mask_sha256"].lower()):
        raise ValueError("source_mask_sha256 must be a lowercase or uppercase SHA-256 digest")
    if not _SHA256_RE.fullmatch(record["normalized_density_sha256"].lower()):
        raise ValueError("normalized_density_sha256 must be a SHA-256 digest")
    record["source_mask_sha256"] = record["source_mask_sha256"].lower()
    record["normalized_density_sha256"] = record["normalized_density_sha256"].lower()
    observed_density_hash = (normalized_density_hash or
                              normalized_density_sha256(normalized_density))
    if record["normalized_density_sha256"] != observed_density_hash:
        raise ValueError("normalized_density_sha256 does not match the supplied source field")
    if record["photo_state"] != "already_fired_photo":
        raise ValueError("blue-white panel source must be identified as an already-fired photo")
    return record


def _profile_arclength(profile_rzs: np.ndarray) -> tuple[np.ndarray, np.ndarray, str]:
    profile = np.asarray(profile_rzs, dtype=np.float64)
    if profile.ndim != 2 or profile.shape[1] != 3 or profile.shape[0] < 3:
        raise ValueError("profile_rzs must have shape (n>=3, 3) as [r,z,s]")
    if not np.all(np.isfinite(profile)):
        raise ValueError("profile_rzs must contain only finite coordinates")
    radius = profile[:, 0]
    if np.any(radius <= 0.0):
        raise ValueError("outer meridian must remain at strictly positive radius")
    segment_length = np.linalg.norm(np.diff(profile[:, :2], axis=0), axis=1)
    if np.any(~np.isfinite(segment_length)) or np.any(segment_length <= 0.0):
        raise ValueError("outer meridian must have nonzero finite segment lengths")
    s = np.concatenate(([0.0], np.cumsum(segment_length, dtype=np.float64)))
    if not np.all(np.isfinite(s)) or s[-1] <= 0.0:
        raise ValueError("outer meridian arclength must be finite and positive")

    provided_s = profile[:, 2]
    if np.allclose(provided_s, 0.0, rtol=0.0, atol=1e-12):
        s_status = "chart_payload_zero_placeholder_recomputed_from_rz_polyline"
    elif (np.all(np.diff(provided_s) > 0.0)
          and np.allclose(np.diff(provided_s), segment_length,
                          rtol=2e-6, atol=2e-6)):
        s_status = "provided_s_validated_against_finite_rz_polyline"
    else:
        raise ValueError("profile_rzs third column must be zero placeholder or matching polyline arclength")
    return radius, s, s_status


def _integral_r_between(radius_profile: np.ndarray, s_profile: np.ndarray,
                        s_queries: np.ndarray) -> np.ndarray:
    """Exact integral of piecewise-linear radius over profile intervals."""
    cumulative = np.concatenate((
        [0.0], np.cumsum(0.5 * (radius_profile[:-1] + radius_profile[1:])
                         * np.diff(s_profile), dtype=np.float64)))
    sq = np.asarray(s_queries, dtype=np.float64)
    index = np.searchsorted(s_profile, sq, side="right") - 1
    index = np.clip(index, 0, len(s_profile) - 2)
    delta = sq - s_profile[index]
    segment = np.diff(s_profile)[index]
    slope = (radius_profile[index + 1] - radius_profile[index]) / segment
    return cumulative[index] + radius_profile[index] * delta + 0.5 * slope * delta ** 2


def _panel_radius_bounds_and_shear(
        radius_profile: np.ndarray, s_profile: np.ndarray,
        s_low: float, s_high: float, panel_width_mm: float) -> tuple[float, float]:
    """Return min radius and max |a| over the panel using the finite-polyline slopes.

    On each intersected profile segment, ``dr/ds`` is constant. Since radius is
    positive and linear there, ``|dr/ds| / r`` is largest at the lower-radius end;
    ``|X|`` is largest at the panel's declared physical half-width. Evaluating those
    segment endpoints gives the exact segmentwise bound, including both one-sided
    derivatives at polyline vertices.
    """
    min_radius = math.inf
    max_abs_shear = 0.0
    half_width = panel_width_mm / 2.0
    for i, (s0, s1) in enumerate(zip(s_profile[:-1], s_profile[1:])):
        left = max(float(s0), s_low)
        right = min(float(s1), s_high)
        if right < left:
            continue
        segment = float(s1 - s0)
        slope = float((radius_profile[i + 1] - radius_profile[i]) / segment)
        r_left = float(radius_profile[i] + slope * (left - s0))
        r_right = float(radius_profile[i] + slope * (right - s0))
        local_min = min(r_left, r_right)
        min_radius = min(min_radius, local_min)
        max_abs_shear = max(max_abs_shear, half_width * abs(slope) / local_min)
    if not np.isfinite(min_radius) or min_radius <= 0.0:
        raise ValueError("panel band did not intersect a positive-radius meridian")
    return min_radius, max_abs_shear


def _bilinear_source_sample(source: np.ndarray, x_index: np.ndarray,
                            row_index: np.ndarray,
                            within_panel: np.ndarray) -> np.ndarray:
    """Sample one unwrapped image panel, preserving its finite blank boundary."""
    height, width = source.shape
    x0 = np.floor(np.clip(x_index, 0.0, width - 1.0)).astype(np.int64)
    y0 = np.floor(np.clip(row_index, 0.0, height - 1.0)).astype(np.int64)
    x1 = np.minimum(x0 + 1, width - 1)
    y1 = np.minimum(y0 + 1, height - 1)
    fx = np.clip(x_index - x0, 0.0, 1.0)
    fy = np.clip(row_index - y0, 0.0, 1.0)
    v00 = source[y0, x0]
    v01 = source[y0, x1]
    v10 = source[y1, x0]
    v11 = source[y1, x1]
    top = v00 * (1.0 - fx) + v01 * fx
    bottom = v10 * (1.0 - fx) + v11 * fx
    sampled = top * (1.0 - fy) + bottom * fy
    return np.where(within_panel, sampled, 0.0)


def _sample_source_mapping(
        source_density: np.ndarray,
        profile_radius_mm: np.ndarray,
        profile_s_mm: np.ndarray,
        s_query_mm: np.ndarray | float,
        theta_query_rad: np.ndarray | float,
        *, panel_width_mm: float, panel_height_mm: float,
        center_s_mm: float, center_theta_rad: float,
        image_top_toward: Literal["lower_s", "higher_s"],
) -> np.ndarray:
    """Sample the immutable finite image through the panel's actual-profile map."""
    sq = np.asarray(s_query_mm, dtype=np.float64)
    tq = np.asarray(theta_query_rad, dtype=np.float64)
    if np.any(~np.isfinite(sq)) or np.any(~np.isfinite(tq)):
        raise ValueError("source-resolved query coordinates must be finite")
    sq, tq = np.broadcast_arrays(sq, tq)
    radius = np.interp(sq, profile_s_mm, profile_radius_mm)
    wrapped_delta = (tq - center_theta_rad + math.pi) % (2.0 * math.pi) - math.pi
    x_mm = radius * wrapped_delta
    s_low = center_s_mm - panel_height_mm / 2.0
    s_high = center_s_mm + panel_height_mm / 2.0
    height, width = source_density.shape
    x_index = (x_mm / panel_width_mm + 0.5) * width - 0.5
    if image_top_toward == "lower_s":
        row_index = (sq - s_low) / panel_height_mm * height - 0.5
    else:
        row_index = (s_high - sq) / panel_height_mm * height - 0.5
    within_panel = ((np.abs(x_mm) <= panel_width_mm / 2.0)
                    & (sq >= s_low) & (sq <= s_high))
    sampled = _bilinear_source_sample(
        np.asarray(source_density, dtype=np.float64), x_index, row_index, within_panel)
    if not np.all(np.isfinite(sampled)):
        raise ValueError("source-resolved sampling produced a non-finite density")
    return sampled


@dataclass(frozen=True)
class BlueWhitePanelResult:
    """A sourced loading field, two-fraction appearance result, and numeric receipt."""

    initial_density: np.ndarray
    bound_density: np.ndarray
    mobile_density: np.ndarray
    total_density: np.ndarray
    linear_rgb: np.ndarray
    s_centers_mm: np.ndarray
    radius_mm: np.ndarray
    theta_centers_rad: np.ndarray
    cell_area_mm2: np.ndarray
    operator: SurfaceOfRevolutionOperator
    spread_result: TwoFractionAppearanceResult
    receipt: dict[str, Any]
    glaze_white_linear_rgb: tuple[float, float, float]
    tau_rgb: tuple[float, float, float]
    # Appended fields preserve the original positional constructor contract.
    continuous_sampling_mode: str = GRID_BILINEAR_SAMPLING
    source_density: np.ndarray | None = None
    profile_radius_mm: np.ndarray | None = None
    profile_s_mm: np.ndarray | None = None
    panel_width_mm: float | None = None
    panel_height_mm: float | None = None
    center_s_mm: float | None = None
    center_theta_rad: float | None = None
    image_top_toward: Literal["lower_s", "higher_s"] | None = None
    mobile_fraction: float | None = None
    mobile_transport_is_zero: bool = False

    def sample_density(self, s_mm: np.ndarray | float,
                       theta_rad: np.ndarray | float,
                       *, component: Literal["initial", "bound", "mobile", "total"] = "total"
                       ) -> np.ndarray:
        """Sample a field at meridian ``s`` and periodic azimuth ``theta``.

        The default route bilinearly samples every stored finite-volume grid field. The
        opt-in source-resolved route samples the stationary fraction from the immutable
        source image and the mobile fraction from the recorded FV grid.
        """
        values = {
            "initial": self.initial_density,
            "bound": self.bound_density,
            "mobile": self.mobile_density,
            "total": self.total_density,
        }.get(component)
        if values is None:
            raise ValueError("component must be initial, bound, mobile, or total")
        sq = np.asarray(s_mm, dtype=np.float64)
        if np.any(~np.isfinite(sq)) or np.any(sq < 0.0) or np.any(sq > self.receipt["surface"]["meridian_length_mm"]):
            raise ValueError("s_mm query must lie within the outer-meridian band")
        if self.continuous_sampling_mode == GRID_BILINEAR_SAMPLING:
            return sample_periodic_field(values, self.s_centers_mm, self.operator.n_theta,
                                         s_mm, theta_rad)
        if self.continuous_sampling_mode != SOURCE_RESOLVED_STATIONARY_SAMPLING:
            raise ValueError("panel has an unsupported continuous sampling mode")
        required = (self.source_density, self.profile_radius_mm, self.profile_s_mm,
                    self.panel_width_mm, self.panel_height_mm, self.center_s_mm,
                    self.center_theta_rad, self.image_top_toward, self.mobile_fraction)
        if any(value is None for value in required):
            raise ValueError("source-resolved panel result is missing its immutable mapping")
        sq = np.asarray(s_mm, dtype=np.float64)
        if (np.any(~np.isfinite(sq)) or np.any(sq < 0.0)
                or np.any(sq > self.receipt["surface"]["meridian_length_mm"])):
            raise ValueError("s_mm query must lie within the outer-meridian band")
        source_sample = _sample_source_mapping(
            self.source_density, self.profile_radius_mm, self.profile_s_mm,
            s_mm, theta_rad, panel_width_mm=self.panel_width_mm,
            panel_height_mm=self.panel_height_mm, center_s_mm=self.center_s_mm,
            center_theta_rad=self.center_theta_rad,
            image_top_toward=self.image_top_toward)
        if component == "initial":
            return source_sample
        bound = (1.0 - self.mobile_fraction) * source_sample
        if component == "bound":
            return bound
        if self.mobile_transport_is_zero:
            mobile = self.mobile_fraction * source_sample
        else:
            mobile = sample_periodic_field(
                self.mobile_density, self.s_centers_mm, self.operator.n_theta,
                s_mm, theta_rad)
        if component == "mobile":
            return mobile
        if self.mobile_transport_is_zero:
            return source_sample
        return bound + mobile

    def sample_linear_rgb(self, s_mm: np.ndarray | float,
                          theta_rad: np.ndarray | float) -> np.ndarray:
        """Sample normalized total loading, then map it to dimensionless linear RGB."""
        density = self.sample_density(s_mm, theta_rad, component="total")
        return blue_white_appearance(
            density, glaze_white_linear_rgb=self.glaze_white_linear_rgb,
            tau_rgb=self.tau_rgb)


def build_bluewhite_panel(
        profile_rzs: np.ndarray,
        normalized_source_density: np.ndarray,
        *,
        source_metadata: Mapping[str, Any],
        panel_width_mm: float,
        panel_height_mm: float,
        center_s_mm: float,
        center_theta_rad: float,
        diffusivity_s_mm2_per_unit: float,
        diffusivity_theta_mm2_per_unit: float,
        duration: float,
        mobile_fraction: float,
        n_s: int,
        n_theta: int,
        boundary_halo_mm: float = 2.0,
        image_top_toward: Literal["lower_s", "higher_s"] = "lower_s",
        glaze_white_linear_rgb: tuple[float, float, float] = (0.94, 0.91, 0.84),
        tau_rgb: tuple[float, float, float] = (3.04, 2.56, 0.93),
        continuous_sampling_mode: str = GRID_BILINEAR_SAMPLING,
        max_grid_cells: int = MAX_GRID_CELLS,
        max_operator_nnz: int = MAX_OPERATOR_NNZ,
        max_memory_bytes: int = MAX_ESTIMATED_WORKING_BYTES,
) -> BlueWhitePanelResult:
    """Project one finite, unwrapped mask panel onto a variable-radius bowl chart.

    ``profile_rzs`` is the chart's sampled ``[r,z,s]`` array. The returned arclength is
    recomputed from the finite ``(r,z)`` polyline, matching the chart implementation. The
    source image is sampled once, with blank space outside the panel; it is never tiled.
    For each meridian row the map uses ``x_mm = r(s) * wrapped(theta-center_theta)`` so
    its declared physical arc width is constant while its angle adapts to bowl radius.

    The source hash must bind to both the original mask file and the canonical normalized
    density array passed here. A valid hash is provenance evidence, not proof of photo
    calibration or historical pigment placement.
    """
    profile_coordinates = np.asarray(profile_rzs, dtype=np.float64)
    profile_radius, s_profile, s_status = _profile_arclength(profile_coordinates)
    source_input = np.asarray(normalized_source_density)
    source_density_hash = normalized_density_sha256(source_input)
    source = np.asarray(normalized_source_density, dtype=np.float64)
    if source.ndim != 2 or min(source.shape) < 2 or not np.all(np.isfinite(source)):
        raise ValueError("normalized_source_density must be a finite 2-D image of at least 2x2")
    if np.any(source < 0.0) or np.any(source > 1.0):
        raise ValueError("normalized_source_density must lie in [0, 1]")
    if not np.any(source > 0.0):
        raise ValueError("normalized_source_density must contain visible source pigment")
    source_record = _source_record(source_metadata, source,
                                   normalized_density_hash=source_density_hash)

    def finite_positive(value: float, name: str) -> float:
        value = float(value)
        if not np.isfinite(value) or value <= 0.0:
            raise ValueError(f"{name} must be finite and strictly positive")
        return value

    panel_width_mm = finite_positive(panel_width_mm, "panel_width_mm")
    panel_height_mm = finite_positive(panel_height_mm, "panel_height_mm")
    boundary_halo_mm = float(boundary_halo_mm)
    if not np.isfinite(boundary_halo_mm) or boundary_halo_mm < 0.0:
        raise ValueError("boundary_halo_mm must be finite and non-negative")
    center_s_mm = float(center_s_mm)
    center_theta_rad = float(center_theta_rad)
    if not np.isfinite(center_s_mm) or not np.isfinite(center_theta_rad):
        raise ValueError("panel center coordinates must be finite")
    if image_top_toward not in ("lower_s", "higher_s"):
        raise ValueError("image_top_toward must be 'lower_s' or 'higher_s'")
    if (not isinstance(continuous_sampling_mode, str)
            or continuous_sampling_mode not in _CONTINUOUS_SAMPLING_MODES):
        raise ValueError("continuous_sampling_mode must be grid_bilinear_v1 or "
                         "source_resolved_stationary_v1")
    duration = float(duration)
    mobile_fraction = float(mobile_fraction)
    diffusivity_s_mm2_per_unit = float(diffusivity_s_mm2_per_unit)
    diffusivity_theta_mm2_per_unit = float(diffusivity_theta_mm2_per_unit)
    if not np.isfinite(duration) or duration < 0.0:
        raise ValueError("duration must be finite and non-negative")
    if not np.isfinite(mobile_fraction) or not 0.0 <= mobile_fraction <= 1.0:
        raise ValueError("mobile_fraction must be finite and in [0, 1]")
    if (not np.isfinite(diffusivity_s_mm2_per_unit)
            or diffusivity_s_mm2_per_unit < 0.0
            or not np.isfinite(diffusivity_theta_mm2_per_unit)
            or diffusivity_theta_mm2_per_unit < 0.0):
        raise ValueError("diffusivities must be finite and non-negative")
    effective_k_s_mm2 = duration * diffusivity_s_mm2_per_unit
    effective_k_theta_mm2 = duration * diffusivity_theta_mm2_per_unit
    if not np.isfinite(effective_k_s_mm2) or not np.isfinite(effective_k_theta_mm2):
        raise ValueError("duration times diffusivity must remain finite")

    def grid_dimension(value: int, name: str, minimum: int) -> int:
        if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)):
            raise ValueError(f"{name} must be an integer")
        value = int(value)
        if value < minimum:
            raise ValueError(f"{name} must be at least {minimum}")
        return value

    n_s = grid_dimension(n_s, "n_s", 2)
    n_theta = grid_dimension(n_theta, "n_theta", 3)
    n_cells = n_s * n_theta
    if n_cells > min(int(max_grid_cells), MAX_GRID_CELLS):
        raise ValueError(f"grid has {n_cells:,} cells; budget is {min(int(max_grid_cells), MAX_GRID_CELLS):,}")
    if max_grid_cells < 1 or max_grid_cells > MAX_GRID_CELLS:
        raise ValueError(f"max_grid_cells must be in [1, {MAX_GRID_CELLS}]")
    if max_operator_nnz < 1 or max_operator_nnz > MAX_OPERATOR_NNZ:
        raise ValueError(f"max_operator_nnz must be in [1, {MAX_OPERATOR_NNZ}]")
    if max_memory_bytes < 1 or max_memory_bytes > MAX_ESTIMATED_WORKING_BYTES:
        raise ValueError("max_memory_bytes must be within the 512 MiB safety ceiling")

    meridian_length_mm = float(s_profile[-1])
    s_low = center_s_mm - panel_height_mm / 2.0
    s_high = center_s_mm + panel_height_mm / 2.0
    if (s_low < boundary_halo_mm or s_high > meridian_length_mm - boundary_halo_mm):
        raise ValueError("panel placement is outside the outer-meridian band or its blank halo")
    s_edges = np.linspace(0.0, meridian_length_mm, n_s + 1, dtype=np.float64)
    ds_mm = meridian_length_mm / n_s
    s_centers_mm = (np.arange(n_s, dtype=np.float64) + 0.5) * ds_mm
    radius_mm = np.interp(s_centers_mm, s_profile, profile_radius)
    if np.any(radius_mm <= 0.0) or not np.all(np.isfinite(radius_mm)):
        raise ValueError("sampled annular meridian must keep every radius positive")
    radius_integral = _integral_r_between(profile_radius, s_profile, s_edges)
    area_s = np.diff(radius_integral) * (2.0 * math.pi / n_theta)
    if np.any(area_s <= 0.0) or not np.all(np.isfinite(area_s)):
        raise ValueError("piecewise-polyline annular cell areas must be finite and positive")

    # The source image occupies one finite, non-overlapping cylindrical unwrap branch.
    panel_radius_min, max_abs_shear = _panel_radius_bounds_and_shear(
        profile_radius, s_profile, s_low, s_high, panel_width_mm)
    finite_width_limit_mm = 2.0 * math.pi * panel_radius_min
    max_half_angle = panel_width_mm / (2.0 * panel_radius_min)
    if panel_width_mm >= finite_width_limit_mm:
        raise ValueError("panel width must be less than 2*pi*minimum panel radius")

    operator = build_surface_of_revolution_operator(
        s_centers_mm, radius_mm, n_theta,
        diffusivity_s_mm2_per_unit=diffusivity_s_mm2_per_unit,
        diffusivity_theta_mm2_per_unit=diffusivity_theta_mm2_per_unit,
        cell_area_mm2=area_s,
        max_grid_cells=max_grid_cells,
        max_operator_nnz=max_operator_nnz,
        max_memory_bytes=max_memory_bytes,
    )

    theta_centers = (np.arange(n_theta, dtype=np.float64) + 0.5) * (2.0 * math.pi / n_theta)
    initial_density = _sample_source_mapping(
        source, profile_radius, s_profile, s_centers_mm[:, None], theta_centers[None, :],
        panel_width_mm=panel_width_mm, panel_height_mm=panel_height_mm,
        center_s_mm=center_s_mm, center_theta_rad=center_theta_rad,
        image_top_toward=image_top_toward)
    if not np.any(initial_density > 0.0):
        raise ValueError("panel placement sampled no source pigment onto the surface grid")

    spread_result = diffuse_two_fraction_appearance(
        operator, initial_density, duration=duration, mobile_fraction=mobile_fraction)
    total_density = spread_result.total_density
    white = tuple(float(value) for value in glaze_white_linear_rgb)
    tau = tuple(float(value) for value in tau_rgb)
    linear_rgb = blue_white_appearance(
        total_density, glaze_white_linear_rgb=white, tau_rgb=tau)

    # Keep the caller's exact input dtype/shape/values in a defensive immutable copy.
    source_bytes = np.ascontiguousarray(source_input).tobytes(order="C")
    source_immutable = np.frombuffer(source_bytes, dtype=source_input.dtype).reshape(
        source_input.shape)
    image_height, image_width = source.shape
    profile_radius_immutable = np.array(profile_radius, dtype=np.float64, copy=True)
    profile_s_immutable = np.array(s_profile, dtype=np.float64, copy=True)
    profile_radius_immutable.setflags(write=False)
    profile_s_immutable.setflags(write=False)
    mobile_transport_is_zero = bool(
        mobile_fraction == 0.0
        or (effective_k_s_mm2 == 0.0 and effective_k_theta_mm2 == 0.0))

    theta_to_seam = min(float(np.mod(center_theta_rad, 2.0 * math.pi)),
                        float(2.0 * math.pi - np.mod(center_theta_rad, 2.0 * math.pi)))
    seam_clearance_angle = max(0.0, theta_to_seam - max_half_angle)
    receipt: dict[str, Any] = {
        "schema": "synlab.patterns.bluewhite_panel_receipt.v2",
        "model": "sourced_photo_proxy_on_actual_sampled_outer_meridian_with_two_fraction_bleed",
        "source": {**source_record,
                   "source_density_shape": [int(image_height), int(image_width)],
                   "normalized_density_hash_schema": NORMALIZED_DENSITY_HASH_SCHEMA,
                   "normalized_density_hash_input_dtype": source_input.dtype.str,
                   "normalized_density_hash_canonical_dtype": _NORMALIZED_DENSITY_CANONICAL_DTYPE,
                   "normalized_density_hash_binds_shape_and_dtype": True,
                   "source_density_value_range": [float(np.min(source)), float(np.max(source))],
                   "source_density_contains_tonal_variation": bool(np.ptp(source) > 0.0)},
        "interpretation_limits": {
            "source_state": "already_fired_photo_normalized_appearance_proxy",
            "recovered_prefire_pigment": False,
            "historical_vase_reproduction": False,
            "synthetic_new_design_on_bowl_candidate": True,
            "optical_or_firing_calibration": False,
            "unseen_surface_or_symbolic_meaning_inferred": False,
            "geometry_or_material_mechanics_changed": False,
        },
        "surface": {
            "coordinate_frame": "sampled outer-meridian polyline [radius_mm,z_mm,s_mm]",
            "s_definition": "cumulative Euclidean segment length over the supplied finite (r,z) polyline from its first row",
            "s_origin_rz_mm": [float(profile_coordinates[0, 0]),
                               float(profile_coordinates[0, 1])],
            "s_terminal_rz_mm": [float(profile_coordinates[-1, 0]),
                                 float(profile_coordinates[-1, 1])],
            "s_input_column_status": s_status,
            "arclength_is_exact_cad": False,
            "radius_min_mm": float(np.min(radius_mm)),
            "radius_max_mm": float(np.max(radius_mm)),
            "meridian_length_mm": meridian_length_mm,
            "positive_radius_annular_chart": True,
            "cell_area_method": "piecewise-linear exact integral of r(s) over each meridian cell times dtheta",
            "cell_area_min_mm2": float(np.min(area_s)),
            "cell_area_max_mm2": float(np.max(area_s)),
            "boundary_conditions": {"s": "no_flux_at_both_outer_meridian_ends",
                                    "theta": "periodic_exactly_n_theta_cells"},
        },
        "grid": {**operator.budget, "n_s": n_s, "n_theta": n_theta,
                 "ds_mm": ds_mm, "dtheta_rad": operator.dtheta_rad,
                 "max_grid_cells": int(max_grid_cells),
                 "max_operator_nnz": int(max_operator_nnz),
                 "max_memory_bytes": int(max_memory_bytes)},
        "panel": {
            "mapping": "single finite panel; x_mm = r(s) * wrapped(theta - center_theta)",
            "source_image_top_toward": image_top_toward,
            "width_mm": panel_width_mm,
            "height_mm": panel_height_mm,
            "center_s_mm": center_s_mm,
            "center_theta_rad": float(np.mod(center_theta_rad, 2.0 * math.pi)),
            "s_bounds_mm": [s_low, s_high],
            "boundary_halo_mm": boundary_halo_mm,
            "actual_s_halo_mm": [s_low, meridian_length_mm - s_high],
            "finite_width_guard": "panel_width_mm < 2*pi*minimum_piecewise_linear_radius_over_panel_band",
            "panel_band_minimum_radius_mm": panel_radius_min,
            "maximum_nonoverlapping_width_mm": finite_width_limit_mm,
            "theta_half_width_max_rad": max_half_angle,
            "periodic_seam_clearance_min_angle_rad": seam_clearance_angle,
            "periodic_seam_away_from_panel": bool(seam_clearance_angle > 0.0),
            "physical_arc_width_is_row_constant": True,
            "local_angle_changes_with_r_s": True,
            "panel_metric": "dell^2=(dX-a*dY)^2+dY^2; area-preserving but sheared",
            "piecewise_polyline_max_abs_shear_a_bound": max_abs_shear,
            "shear_bound_convention": (
                "finite piecewise-linear r(s); each intersected segment uses its "
                "one-sided constant dr/ds and the declared |X|=width/2; segmentwise "
                "bound occurs at its lower-radius endpoint; no smooth-CAD derivative "
                "or geometric error certificate is implied"),
            "curvature_mapping_distortion": "source x coordinate is local cylindrical arc distance; no perspective or photo-curvature correction is available",
            "tiling_or_repetition": False,
        },
        "appearance_controls": {
            "diffusivity_s_mm2_per_effective_unit": diffusivity_s_mm2_per_unit,
            "diffusivity_theta_mm2_per_effective_unit": diffusivity_theta_mm2_per_unit,
            "duration_dimensionless_effective_process_index": duration,
            "effective_K_s_mm2": effective_k_s_mm2,
            "effective_K_theta_mm2": effective_k_theta_mm2,
            "mobile_fraction": mobile_fraction,
            "bound_fraction": 1.0 - mobile_fraction,
            "mobile_fraction_is_measured_chemistry": False,
            "continuous_sampling_mode": continuous_sampling_mode,
            "source_resolved_stationary_sampling": (
                continuous_sampling_mode == SOURCE_RESOLVED_STATIONARY_SAMPLING),
            "mobile_transport_is_zero": mobile_transport_is_zero,
            "no_sharpening_or_post_pde_blur": True,
            "color_law": "glaze_white_linear_rgb * exp(-tau_rgb * normalized_density)",
            "glaze_white_linear_rgb": list(white),
            "dimensionless_tau_rgb": list(tau),
            "tau_is_optical_path_or_measured_coefficient": False,
        },
        "mass": spread_result.receipt["mass"],
        "mass_accounting": {
            "scope": "DISCRETE_GRID_MASS_ONLY",
            "continuous_source_quadrature_equality_claimed": False,
            "fine_grid_convergence_claimed": False,
            "description": ("mass values use the finite-volume source and result arrays with "
                            "the recorded discrete cell areas"),
        },
        "solver_receipt": spread_result.receipt,
    }
    return BlueWhitePanelResult(
        initial_density=initial_density,
        bound_density=spread_result.bound_density,
        mobile_density=spread_result.mobile_density,
        total_density=total_density,
        linear_rgb=linear_rgb,
        s_centers_mm=s_centers_mm,
        radius_mm=radius_mm,
        theta_centers_rad=theta_centers,
        cell_area_mm2=area_s,
        operator=operator,
        spread_result=spread_result,
        receipt=receipt,
        glaze_white_linear_rgb=white,
        tau_rgb=tau,
        continuous_sampling_mode=continuous_sampling_mode,
        source_density=source_immutable,
        profile_radius_mm=profile_radius_immutable,
        profile_s_mm=profile_s_immutable,
        panel_width_mm=panel_width_mm,
        panel_height_mm=panel_height_mm,
        center_s_mm=center_s_mm,
        center_theta_rad=center_theta_rad,
        image_top_toward=image_top_toward,
        mobile_fraction=mobile_fraction,
        mobile_transport_is_zero=mobile_transport_is_zero,
    )


__all__ = ["BlueWhitePanelResult", "build_bluewhite_panel",
           "GRID_BILINEAR_SAMPLING", "SOURCE_RESOLVED_STATIONARY_SAMPLING",
           "normalized_density_sha256", "NORMALIZED_DENSITY_HASH_SCHEMA"]

