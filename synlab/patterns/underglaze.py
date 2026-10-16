"""Metric-aware blue-and-white underglaze pigment diffusion surrogates.

This module evolves a non-negative pigment-loading field on a surface of revolution.
The axial coordinate is true meridian arclength in millimetres and the azimuth is
periodic.  Diffusivities are explicit inputs in mm^2 per effective process unit;
``duration`` is a dimensionless effective process index.  They are not a fitted kiln
temperature law or a reconstruction of a historical firing.

The finite-volume graph defaults to midpoint cell areas ``r_i * ds * dtheta`` and uses
symmetric face conductances.  Its stiffness matrix is a weighted graph Laplacian, so the
conservative equation is ``A dc/dt = L c``.  A similarity transform makes the generator
symmetric: ``H = A^-1/2 L A^-1/2``.  SciPy's sparse ``expm_multiply`` advances that system
without a custom time-step solver.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy import sparse
from scipy.sparse.linalg import expm_multiply

TWO_PI = 2.0 * np.pi
MAX_GRID_CELLS = 256_000
MAX_OPERATOR_NNZ = 5 * MAX_GRID_CELLS
MAX_ESTIMATED_WORKING_BYTES = 512 * 1024 * 1024
MAX_SCALED_GENERATOR_INFINITY_NORM = 1_000.0


@dataclass(frozen=True)
class SurfaceOfRevolutionOperator:
    """Sparse conservative diffusion operator for cell-centered annular body bands."""

    s_centers_mm: np.ndarray
    radius_mm: np.ndarray
    n_theta: int
    ds_mm: float
    dtheta_rad: float
    cell_area_mm2: np.ndarray
    stiffness: sparse.csr_matrix
    generator: sparse.csr_matrix
    diffusivity_s_mm2_per_unit: np.ndarray
    diffusivity_theta_mm2_per_unit: np.ndarray
    budget: dict[str, int | float]

    @property
    def shape(self) -> tuple[int, int]:
        return (int(self.s_centers_mm.size), int(self.n_theta))

    @property
    def n_cells(self) -> int:
        return int(self.s_centers_mm.size * self.n_theta)

    def sample(self, field: np.ndarray, s_query_mm: np.ndarray | float,
               theta_query_rad: np.ndarray | float) -> np.ndarray:
        """Bilinearly sample cell centers, clamping only at the no-flux s end bands.

        Azimuth is wrapped modulo 2*pi.  The first center is an annular body band with
        positive radius; no pole value is represented by this grid.
        """
        return sample_periodic_field(field, self.s_centers_mm, self.n_theta,
                                     s_query_mm, theta_query_rad)


@dataclass(frozen=True)
class DiffusionResult:
    """Concentration field and auditable numerical receipt."""

    concentration: np.ndarray
    receipt: dict[str, Any]


@dataclass(frozen=True)
class TwoFractionAppearanceResult:
    """Bound and mobile normalized pigment fractions plus their visible sum."""

    total_density: np.ndarray
    bound_density: np.ndarray
    mobile_density: np.ndarray
    receipt: dict[str, Any]


def _finite_array(value: Any, name: str, *, ndim: int | None = None) -> np.ndarray:
    arr = np.asarray(value, dtype=np.float64)
    if ndim is not None and arr.ndim != ndim:
        raise ValueError(f"{name} must have {ndim} dimensions; got {arr.ndim}")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} must contain only finite values")
    return arr


def _cell_parameter(value: Any, name: str, shape: tuple[int, int]) -> np.ndarray:
    """Expand a scalar, radial profile, or cell-wise diffusivity onto the grid."""
    arr = _finite_array(value, name)
    if arr.ndim == 1 and arr.shape == (shape[0],):
        arr = arr[:, None]
    try:
        expanded = np.broadcast_to(arr, shape).astype(np.float64, copy=True)
    except ValueError as exc:
        raise ValueError(f"{name} must be scalar or broadcastable to grid {shape}") from exc
    if np.any(expanded < 0.0):
        raise ValueError(f"{name} must be non-negative")
    return expanded


def _harmonic_face(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Harmonic mean that leaves a zero-diffusivity face impermeable."""
    denom = a + b
    out = np.zeros(np.broadcast_shapes(a.shape, b.shape), dtype=np.float64)
    np.divide(2.0 * a * b, denom, out=out, where=denom > 0.0)
    return out


def _preflight(n_s: int, n_theta: int, *, max_grid_cells: int,
               max_operator_nnz: int, max_memory_bytes: int) -> dict[str, int | float]:
    n_cells = n_s * n_theta
    # One axial no-flux graph has (n_s-1)*n_theta faces and the periodic direction
    # contributes n_s*n_theta unique faces.  Each edge gives two off-diagonals and
    # one diagonal per cell, so this is the exact structural nonzero count.
    edge_count = (2 * n_s - 1) * n_theta
    nnz = n_cells + 2 * edge_count
    # Conservative peak estimate for cell/edge work arrays, COO assembly, both CSR
    # operators, and sparse expm_multiply work vectors.  It is intentionally checked
    # before any grid-sized allocation.
    estimated_bytes = 384 * n_cells + 64 * nnz
    if max_grid_cells < 1 or max_grid_cells > MAX_GRID_CELLS:
        raise ValueError(f"max_grid_cells must be in [1, {MAX_GRID_CELLS}]")
    if max_operator_nnz < 1 or max_operator_nnz > MAX_OPERATOR_NNZ:
        raise ValueError(f"max_operator_nnz must be in [1, {MAX_OPERATOR_NNZ}]")
    if max_memory_bytes < 1 or max_memory_bytes > MAX_ESTIMATED_WORKING_BYTES:
        raise ValueError("max_memory_bytes must be within the 512 MiB safety ceiling")
    if n_cells > max_grid_cells:
        raise ValueError(f"grid has {n_cells:,} cells; budget is {max_grid_cells:,}")
    if nnz > max_operator_nnz:
        raise ValueError(f"operator needs {nnz:,} structural entries; budget is "
                         f"{max_operator_nnz:,}")
    if estimated_bytes > max_memory_bytes:
        raise ValueError(f"estimated sparse working set is {estimated_bytes:,} bytes; "
                         f"budget is {max_memory_bytes:,}")
    return {
        "grid_cells": int(n_cells),
        "operator_nnz_upper_bound": int(nnz),
        "estimated_peak_working_bytes": int(estimated_bytes),
        "max_grid_cells": int(max_grid_cells),
        "max_operator_nnz": int(max_operator_nnz),
        "max_memory_bytes": int(max_memory_bytes),
    }


def build_surface_of_revolution_operator(
        s_centers_mm: np.ndarray,
        radius_mm: np.ndarray,
        n_theta: int,
        *,
        diffusivity_s_mm2_per_unit: float | np.ndarray,
        diffusivity_theta_mm2_per_unit: float | np.ndarray,
        cell_area_mm2: np.ndarray | None = None,
        max_grid_cells: int = MAX_GRID_CELLS,
        max_operator_nnz: int = MAX_OPERATOR_NNZ,
        max_memory_bytes: int = MAX_ESTIMATED_WORKING_BYTES,
) -> SurfaceOfRevolutionOperator:
    """Build the metric-aware FV graph on an arclength/azimuth surface grid.

    ``s_centers_mm`` must be uniformly spaced meridian-arclength centers.  The caller
    supplies only positive-radius cell centers, so an axis pole is excluded explicitly.
    The first and last axial faces have no flux.  Azimuthal neighbors wrap periodically.
    Diffusivities may be scalar, an ``(n_s,)`` radial profile, or broadcastable to
    ``(n_s, n_theta)``.  Their local face value is the harmonic mean.  Cell areas use
    midpoint ``r_i*ds*dtheta`` quadrature by default; callers with profile-integrated
    areas may supply a positive ``(n_s,)`` or ``(n_s, n_theta)`` array of exact discrete
    cell measures.
    """
    s = _finite_array(s_centers_mm, "s_centers_mm", ndim=1)
    radius = _finite_array(radius_mm, "radius_mm", ndim=1)
    if s.size < 2:
        raise ValueError("at least two axial body bands are required")
    if radius.shape != s.shape:
        raise ValueError("radius_mm must have one radius per axial center")
    if np.any(radius <= 0.0):
        raise ValueError("radius_mm must be strictly positive; the pole is excluded")
    try:
        n_theta_int = int(n_theta)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("n_theta must be an integer of at least 3") from exc
    if (isinstance(n_theta, (bool, np.bool_)) or n_theta_int != n_theta
            or n_theta_int < 3):
        raise ValueError("n_theta must be an integer of at least 3")
    n_theta = n_theta_int
    shape = (int(s.size), n_theta)
    budget = _preflight(*shape, max_grid_cells=int(max_grid_cells),
                        max_operator_nnz=int(max_operator_nnz),
                        max_memory_bytes=int(max_memory_bytes))
    if np.any(np.diff(s) <= 0.0):
        raise ValueError("s_centers_mm must be strictly increasing")
    ds_values = np.diff(s)
    ds = float(np.mean(ds_values))
    if not np.allclose(ds_values, ds, rtol=1e-10, atol=max(1e-12, abs(ds) * 1e-12)):
        raise ValueError("s_centers_mm must be uniformly spaced in true arclength")
    ds_diff = _cell_parameter(diffusivity_s_mm2_per_unit,
                              "diffusivity_s_mm2_per_unit", shape)
    dt_diff = _cell_parameter(diffusivity_theta_mm2_per_unit,
                              "diffusivity_theta_mm2_per_unit", shape)
    dtheta = TWO_PI / n_theta
    if cell_area_mm2 is None:
        cell_area = np.broadcast_to(radius[:, None] * ds * dtheta, shape).copy()
        area_source = "midpoint_radius_times_true_arclength_step_times_azimuth_step"
    else:
        supplied_area = _finite_array(cell_area_mm2, "cell_area_mm2")
        if supplied_area.shape == (s.size,):
            supplied_area = supplied_area[:, None]
        try:
            cell_area = np.broadcast_to(supplied_area, shape).astype(np.float64, copy=True)
        except ValueError as exc:
            raise ValueError("cell_area_mm2 must have shape (n_s,) or broadcast to "
                             f"{shape}") from exc
        if np.any(cell_area <= 0.0) or not np.all(np.isfinite(cell_area)):
            raise ValueError("cell_area_mm2 must be strictly positive")
        area_source = "caller_supplied_profile_integrated_discrete_cell_measure"
    if not np.all(np.isfinite(cell_area)) or np.any(cell_area <= 0.0):
        raise ValueError("cell areas must be finite and strictly positive")

    # Axial faces lie halfway between adjacent cell centers; their metric radius is
    # the linear midpoint radius.  The boundary faces are intentionally omitted.
    axial_face_radius = 0.5 * (radius[:-1] + radius[1:])
    if not np.all(np.isfinite(axial_face_radius)) or np.any(axial_face_radius <= 0.0):
        raise ValueError("all interior axial face radii must be finite and positive")
    g_s = (_harmonic_face(ds_diff[:-1, :], ds_diff[1:, :])
           * axial_face_radius[:, None] * dtheta / ds)
    ax0 = (np.arange(s.size - 1, dtype=np.int64)[:, None] * n_theta
           + np.arange(n_theta, dtype=np.int64)[None, :]).ravel()
    ax1 = ax0 + n_theta

    # Each periodic edge is emitted exactly once from j to j+1 (including seam).
    theta_right = np.roll(dt_diff, -1, axis=1)
    g_theta = (_harmonic_face(dt_diff, theta_right)
               * (ds / (radius[:, None] * dtheta)))
    th0 = np.arange(s.size * n_theta, dtype=np.int64)
    th1 = (np.arange(s.size, dtype=np.int64)[:, None] * n_theta
           + (np.arange(n_theta, dtype=np.int64)[None, :] + 1) % n_theta).ravel()

    edge0 = np.concatenate((ax0, th0))
    edge1 = np.concatenate((ax1, th1))
    conductance = np.concatenate((g_s.ravel(), g_theta.ravel()))
    if not np.all(np.isfinite(conductance)):
        raise ValueError("conductances overflowed; check geometry and diffusivity scales")
    degree = np.bincount(np.concatenate((edge0, edge1)),
                         weights=np.concatenate((conductance, conductance)),
                         minlength=s.size * n_theta)
    if not np.all(np.isfinite(degree)):
        raise ValueError("conductance sums overflowed; check diffusivity scales")
    diagonal = -degree
    offdiag_values = np.concatenate((conductance, conductance))
    rows = np.concatenate((edge0, edge1, np.arange(s.size * n_theta, dtype=np.int64)))
    cols = np.concatenate((edge1, edge0, np.arange(s.size * n_theta, dtype=np.int64)))
    values = np.concatenate((offdiag_values, diagonal))
    stiffness = sparse.coo_matrix((values, (rows, cols)), shape=(s.size * n_theta,) * 2).tocsr()
    stiffness.sum_duplicates()
    stiffness.eliminate_zeros()

    # Similarity transform of the conservative mass system.  Build from the COO
    # representation so the numeric symmetry is retained without sparse products.
    coo = stiffness.tocoo(copy=True)
    area_flat = np.broadcast_to(cell_area, shape).ravel()
    inv_sqrt_area = 1.0 / np.sqrt(area_flat)
    if not np.all(np.isfinite(inv_sqrt_area)):
        raise ValueError("cell areas are too small for a finite similarity transform")
    coo.data *= inv_sqrt_area[coo.row] * inv_sqrt_area[coo.col]
    if not np.all(np.isfinite(coo.data)):
        raise ValueError("symmetric generator overflowed; check area/diffusivity scales")
    generator = coo.tocsr()
    generator.sum_duplicates()
    generator.eliminate_zeros()
    generator_abs_row_sum = np.bincount(
        coo.row, weights=np.abs(coo.data), minlength=s.size * n_theta)
    generator_max_abs_row_sum = float(np.max(generator_abs_row_sum))
    if not np.isfinite(generator_max_abs_row_sum):
        raise ValueError("symmetric generator row norm overflowed")

    # The graph is assembled in equal-and-opposite face pairs; this also guards future
    # edits from accidentally leaving a non-conservative row sum.
    row_sum_max_abs = float(np.max(np.abs(np.asarray(stiffness.sum(axis=1)).ravel())))
    return SurfaceOfRevolutionOperator(
        s_centers_mm=s.copy(), radius_mm=radius.copy(), n_theta=n_theta,
        ds_mm=ds, dtheta_rad=dtheta, cell_area_mm2=cell_area,
        stiffness=stiffness, generator=generator,
        diffusivity_s_mm2_per_unit=ds_diff,
        diffusivity_theta_mm2_per_unit=dt_diff,
        budget={**budget,
                "actual_stiffness_nnz": int(stiffness.nnz),
                "actual_generator_nnz": int(generator.nnz),
                "stiffness_max_abs_row_sum": row_sum_max_abs,
                "generator_max_abs_row_sum": generator_max_abs_row_sum,
                "first_band_radius_mm": float(radius[0]),
                "radius_min_mm": float(np.min(radius)),
                "radius_max_mm": float(np.max(radius)),
                "first_band_excludes_pole": True,
                "minimum_interior_axial_face_radius_mm": float(np.min(axial_face_radius)),
                "cell_area_source": area_source,
                "axial_boundary_condition": "no_flux_at_both_ends",
                "azimuth_boundary_condition": "periodic",
                "edge_diffusivity": "harmonic_mean",
                "axial_face_radius": "arithmetic_midpoint_between_true_arclength_centers"})


def diffuse_pigment(operator: SurfaceOfRevolutionOperator,
                    initial_density: np.ndarray,
                    *, duration: float) -> DiffusionResult:
    """Apply the sparse matrix exponential and return mass/roundoff evidence.

    Concentration is a caller-defined non-negative pigment-loading scalar.  ``duration``
    is a dimensionless effective process index; the supplied diffusivities carry
    ``mm^2 / process unit``.  Tiny negative solver roundoff (at most 128 eps times the
    input scale) is clipped and measured.  A larger negative value raises an error.
    """
    c0 = _finite_array(initial_density, "initial_density", ndim=2)
    if c0.shape != operator.shape:
        raise ValueError(f"initial_density shape {c0.shape} does not match {operator.shape}")
    if np.any(c0 < 0.0):
        raise ValueError("initial_density must be non-negative")
    duration = float(duration)
    if not np.isfinite(duration) or duration < 0.0:
        raise ValueError("duration must be finite and non-negative")

    area = np.broadcast_to(operator.cell_area_mm2, operator.shape)
    mass_before = float(np.sum(area * c0, dtype=np.float64))
    if not np.isfinite(mass_before):
        raise ValueError("initial weighted pigment mass overflowed")
    if duration == 0.0 or not np.any(c0):
        raw = c0.copy()
        scaled_generator_infinity_norm = 0.0
    else:
        scaled_generator_infinity_norm = float(
            duration * operator.budget["generator_max_abs_row_sum"])
        if (not np.isfinite(scaled_generator_infinity_norm)
                or scaled_generator_infinity_norm > MAX_SCALED_GENERATOR_INFINITY_NORM):
            raise ValueError(
                "duration-scaled generator infinity norm exceeds the resource budget "
                f"{MAX_SCALED_GENERATOR_INFINITY_NORM:g}")
        sqrt_area = np.sqrt(area.ravel())
        u0 = sqrt_area * c0.ravel()
        scaled_generator = operator.generator * duration
        trace_a = float(duration * np.sum(operator.generator.diagonal(), dtype=np.float64))
        if not np.all(np.isfinite(scaled_generator.data)) or not np.isfinite(trace_a):
            raise ValueError("duration-scaled generator overflowed")
        u1 = expm_multiply(scaled_generator, u0, traceA=trace_a)
        raw = (u1 / sqrt_area).reshape(operator.shape)
    if not np.all(np.isfinite(raw)):
        raise FloatingPointError("sparse exponential returned non-finite pigment density")

    scale = max(1.0, float(np.max(np.abs(c0))))
    roundoff_tolerance = float(128.0 * np.finfo(np.float64).eps * scale)
    min_solver_value = float(np.min(raw))
    negative = raw < 0.0
    clipped_count = int(np.count_nonzero(negative))
    if min_solver_value < -roundoff_tolerance:
        raise FloatingPointError(
            f"diffusion produced concentration {min_solver_value:.6g}, below the "
            f"roundoff clipping tolerance {-roundoff_tolerance:.6g}")
    clean = raw.copy()
    clean[negative] = 0.0
    mass_solver = float(np.sum(area * raw, dtype=np.float64))
    mass_after = float(np.sum(area * clean, dtype=np.float64))
    clipping_added_mass = float(-np.sum(area[negative] * raw[negative], dtype=np.float64))
    abs_drift = abs(mass_solver - mass_before)
    relative_drift = abs_drift / max(abs(mass_before), np.finfo(np.float64).tiny)
    final_abs_drift = abs(mass_after - mass_before)
    final_relative_drift = final_abs_drift / max(abs(mass_before), np.finfo(np.float64).tiny)
    receipt: dict[str, Any] = {
        "schema": "synlab.underglaze.diffusion_receipt.v1",
        "model": "metric_surface_of_revolution_finite_volume_sparse_exponential",
        "solver": "scipy.sparse.linalg.expm_multiply",
        "concentration_units": "caller_defined_pigment_loading_units",
        "diffusivity_units": "mm^2_per_effective_process_unit",
        "duration_units": "dimensionless_effective_process_index",
        "duration": duration,
        "integrated_diffusion_units": "mm^2",
        "exponential_work": {
            "scaled_generator_infinity_norm": scaled_generator_infinity_norm,
            "maximum_scaled_generator_infinity_norm": MAX_SCALED_GENERATOR_INFINITY_NORM,
        },
        "grid": {"n_s": operator.shape[0], "n_theta": operator.shape[1],
                 "ds_mm": operator.ds_mm, "dtheta_rad": operator.dtheta_rad,
                 "cell_area_min_mm2": float(np.min(area)),
                 "cell_area_max_mm2": float(np.max(area)),
                 "first_band_radius_mm": float(operator.radius_mm[0]),
                 "radius_min_mm": float(np.min(operator.radius_mm)),
                 "radius_max_mm": float(np.max(operator.radius_mm)),
                 "first_band_excludes_pole": True},
        "diffusivity": {
            "s_min_mm2_per_effective_unit": float(np.min(operator.diffusivity_s_mm2_per_unit)),
            "s_max_mm2_per_effective_unit": float(np.max(operator.diffusivity_s_mm2_per_unit)),
            "theta_min_mm2_per_effective_unit": float(np.min(operator.diffusivity_theta_mm2_per_unit)),
            "theta_max_mm2_per_effective_unit": float(np.max(operator.diffusivity_theta_mm2_per_unit)),
            "effective_s_diffusion_min_mm2": float(duration * np.min(operator.diffusivity_s_mm2_per_unit)),
            "effective_s_diffusion_max_mm2": float(duration * np.max(operator.diffusivity_s_mm2_per_unit)),
            "effective_theta_diffusion_min_mm2": float(duration * np.min(operator.diffusivity_theta_mm2_per_unit)),
            "effective_theta_diffusion_max_mm2": float(duration * np.max(operator.diffusivity_theta_mm2_per_unit)),
        },
        "boundary_conditions": {"s": "no_flux_at_both_ends", "theta": "periodic"},
        "operator": {**operator.budget,
                     "stiffness_symmetric_by_paired_face_assembly": True,
                     "generator_symmetric_by_area_similarity_transform": True,
                     "negative_semidefinite_by_nonnegative_graph_conductances": True,
                     "conductances_nonnegative": True},
        "mass": {"before": mass_before, "after_solver_before_roundoff_clip": mass_solver,
                 "after_roundoff_clip": mass_after,
                 "absolute_solver_drift": abs_drift,
                 "relative_solver_drift": relative_drift,
                 "absolute_final_drift_after_clip": final_abs_drift,
                 "relative_final_drift_after_clip": final_relative_drift,
                 "roundoff_clip_added_mass": clipping_added_mass},
        "roundoff": {"minimum_solver_concentration": min_solver_value,
                     "negative_cell_count": clipped_count,
                     "absolute_clip_tolerance": roundoff_tolerance,
                     "material_negative_values_clipped": False},
        "appearance_calibration": "not_applicable_to_diffusion_field",
        "claims": {"firing_reconstruction": False, "mechanical_geometry_change": False},
    }
    return DiffusionResult(concentration=clean, receipt=receipt)


def diffuse_two_fraction_appearance(
        operator: SurfaceOfRevolutionOperator,
        initial_density: np.ndarray,
        *,
        duration: float,
        mobile_fraction: float,
) -> TwoFractionAppearanceResult:
    """Diffuse a fixed mobile fraction while retaining a bound brushwork core.

    This is an empirical normalized appearance model, not measured glaze chemistry.  The
    fixed initial field ``c0`` is split into ``(1-m)*c0`` (bound) and ``m*c0`` (mobile);
    only the mobile part is advanced by :func:`diffuse_pigment`, and the displayed field
    is their sum.  It does not sharpen, renormalize, or otherwise retouch the result.
    ``c0`` is dimensionless and bounded by one.  The exact limits are ``m=0`` -> no
    spread for any valid duration and ``m=1`` -> the existing full-field diffusion.
    """
    c0 = _finite_array(initial_density, "initial_density", ndim=2)
    if c0.shape != operator.shape:
        raise ValueError(f"initial_density shape {c0.shape} does not match {operator.shape}")
    if np.any(c0 < 0.0) or np.any(c0 > 1.0):
        raise ValueError("normalized initial_density must be in [0, 1]")
    duration = float(duration)
    if not np.isfinite(duration) or duration < 0.0:
        raise ValueError("duration must be finite and non-negative")
    mobile_fraction = float(mobile_fraction)
    if (not np.isfinite(mobile_fraction) or mobile_fraction < 0.0
            or mobile_fraction > 1.0):
        raise ValueError("mobile_fraction must be finite and in [0, 1]")

    bound = (1.0 - mobile_fraction) * c0
    mobile_initial = mobile_fraction * c0
    mobile_result = diffuse_pigment(operator, mobile_initial, duration=duration)
    mobile = mobile_result.concentration
    total = bound + mobile
    area = np.broadcast_to(operator.cell_area_mm2, operator.shape)
    mass_before = float(np.sum(area * c0, dtype=np.float64))
    mass_bound = float(np.sum(area * bound, dtype=np.float64))
    mass_mobile_before = float(np.sum(area * mobile_initial, dtype=np.float64))
    mass_mobile_after = float(np.sum(area * mobile, dtype=np.float64))
    mass_after = float(np.sum(area * total, dtype=np.float64))
    relative_drift = abs(mass_after - mass_before) / max(
        abs(mass_before), np.finfo(np.float64).tiny)
    receipt = {
        "schema": "synlab.underglaze.two_fraction_appearance_receipt.v1",
        "model": "empirical_normalized_bound_plus_mobile_phase",
        "interpretation": "appearance parameterization; not measured glaze chemistry",
        "duration": duration,
        "mobile_fraction": mobile_fraction,
        "bound_fraction": 1.0 - mobile_fraction,
        "mass": {
            "initial_total": mass_before,
            "initial_bound": mass_bound,
            "initial_mobile": mass_mobile_before,
            "final_bound": mass_bound,
            "final_mobile": mass_mobile_after,
            "final_total": mass_after,
            "relative_final_total_drift": relative_drift,
        },
        "no_sharpening_or_renormalization": True,
        "mobile_diffusion_receipt": mobile_result.receipt,
        "claims": {"measured_glaze_chemistry": False,
                   "firing_reconstruction": False,
                   "mechanical_geometry_change": False},
    }
    return TwoFractionAppearanceResult(total_density=total, bound_density=bound,
                                       mobile_density=mobile, receipt=receipt)


def sample_periodic_field(field: np.ndarray, s_centers_mm: np.ndarray, n_theta: int,
                          s_query_mm: np.ndarray | float,
                          theta_query_rad: np.ndarray | float) -> np.ndarray:
    """Bilinearly interpolate ``(n_s, n_theta)`` cell values with periodic azimuth."""
    values = _finite_array(field, "field", ndim=2)
    s = _finite_array(s_centers_mm, "s_centers_mm", ndim=1)
    if s.size != values.shape[0] or values.shape[1] != int(n_theta) or int(n_theta) < 3:
        raise ValueError("field shape must be (len(s_centers_mm), n_theta>=3)")
    if s.size < 2 or np.any(np.diff(s) <= 0.0):
        raise ValueError("s_centers_mm must be strictly increasing with at least two centers")
    ds = np.diff(s)
    if not np.allclose(ds, ds[0], rtol=1e-10, atol=max(1e-12, abs(float(ds[0])) * 1e-12)):
        raise ValueError("s_centers_mm must be uniformly spaced")
    sq = _finite_array(s_query_mm, "s_query_mm")
    tq = _finite_array(theta_query_rad, "theta_query_rad")
    sq, tq = np.broadcast_arrays(sq, tq)
    # No-flux ghost half-cells are represented by constant extension to edge centers.
    s_clamped = np.clip(sq, s[0], s[-1])
    sf = np.clip((s_clamped - s[0]) / float(ds[0]), 0.0, s.size - 1)
    s0 = np.floor(sf).astype(np.int64)
    s1 = np.minimum(s0 + 1, s.size - 1)
    fs = sf - s0
    dtheta = TWO_PI / int(n_theta)
    tf = np.mod(tq, TWO_PI) / dtheta - 0.5
    t0_unwrapped = np.floor(tf).astype(np.int64)
    ft = tf - t0_unwrapped
    t0 = np.mod(t0_unwrapped, int(n_theta))
    t1 = np.mod(t0 + 1, int(n_theta))
    c00 = values[s0, t0]
    c01 = values[s0, t1]
    c10 = values[s1, t0]
    c11 = values[s1, t1]
    low = c00 * (1.0 - ft) + c01 * ft
    high = c10 * (1.0 - ft) + c11 * ft
    return low * (1.0 - fs) + high * fs


def blue_white_appearance(
        normalized_pigment_density: np.ndarray,
        *,
        glaze_white_linear_rgb: tuple[float, float, float] = (0.94, 0.91, 0.84),
        tau_rgb: tuple[float, float, float] = (3.04, 2.56, 0.93),
) -> np.ndarray:
    """Map normalized density to a blue-on-white linear-RGB appearance surrogate.

    The illustrative law is ``white_rgb * exp(-tau_rgb * normalized_density)`` where
    ``tau_rgb`` and density are dimensionless.  Red absorption exceeds green and blue,
    producing a cobalt-blue impression.  Defaults roughly align full density with this
    project's cobalt-white palette; they are an art-direction anchor, not measured
    optical coefficients.  The appearance proxy makes no claim about a specific glaze,
    cobalt chemistry, or fired color.
    """
    density = _finite_array(normalized_pigment_density, "normalized_pigment_density")
    if np.any(density < 0.0) or np.any(density > 1.0):
        raise ValueError("normalized_pigment_density must be in [0, 1]")
    white = _finite_array(glaze_white_linear_rgb, "glaze_white_linear_rgb", ndim=1)
    tau = _finite_array(tau_rgb, "tau_rgb", ndim=1)
    if white.shape != (3,) or np.any(white < 0.0) or np.any(white > 1.0):
        raise ValueError("glaze_white_linear_rgb must be three values in [0, 1]")
    if tau.shape != (3,) or np.any(tau < 0.0):
        raise ValueError("tau_rgb must be three non-negative dimensionless values")
    if not (tau[0] > tau[1] > tau[2]):
        raise ValueError("blue-white proxy expects red > green > blue absorption")
    return white * np.exp(-density[..., None] * tau)

