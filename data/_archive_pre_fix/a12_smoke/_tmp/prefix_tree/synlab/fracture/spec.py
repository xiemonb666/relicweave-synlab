"""Shared parameter objects and QA thresholds for the fracture package.

Every threshold in this module is *frozen*: tests and docs reference these constants
instead of re-deriving numbers, so a change is visible as an interface change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..registry import STATUS_IMPLEMENTED, STATUS_MISSING, STATUS_PENDING

# ---------------------------------------------------------------------------- backends
BACKEND_PLANE = "plane_shared_cut"
BACKEND_ROUGH = "rough_shared_cut"
BACKEND_WARPED = "warped_partition"
BACKEND_SECONDARY = "secondary_fracture"
BACKEND_MODES = "fracture_modes"

REQUIRED_BACKENDS: tuple[str, ...] = (
    BACKEND_PLANE, BACKEND_ROUGH, BACKEND_WARPED, BACKEND_SECONDARY,
)

BACKEND_STATUS: dict[str, str] = {
    BACKEND_PLANE: STATUS_IMPLEMENTED,
    BACKEND_ROUGH: STATUS_IMPLEMENTED,
    BACKEND_WARPED: STATUS_IMPLEMENTED,
    BACKEND_SECONDARY: STATUS_IMPLEMENTED,
    # Optional backend: no licence/permission obtained for a kinetic fracture-mode solver,
    # and no solver dependency is installed.  Registered as a placeholder, never faked.
    BACKEND_MODES: STATUS_MISSING,
}

# ---------------------------------------------------------------------------- thresholds
#: Absolute contact-area threshold (plan 11.3: development candidate 0.1 mm^2).
R2_AREA_ABS_MM2 = 0.1
#: Relative threshold against the mother *material surface* area (plan 30.5); both must pass.
R2_AREA_REL = 1.0e-4
#: Numerical grey zone below which a real contact is TINY_CONTACT rather than R2.
TINY_AREA_ABS_MM2 = 1.0e-3
TINY_AREA_REL = 1.0e-6

#: Barycentric / coordinate reconstruction residual budget for correspondence samples.
CORRESPONDENCE_RESIDUAL_MM = 1.0e-4
#: Normal reversal budget for clean shared normals (plan 11.1).
NORMAL_REVERSAL_P95_DEG = 2.0
#: Shared-surface sampled distance budget (plan task contract).
INTERFACE_GAP_P95_MM = 0.02
#: Fraction of interface area that may be ambiguous before an event is refused.
AMBIGUITY_AREA_RATIO_MAX = 0.02
#: Volume conservation relative difference.
VOLUME_REL_TOL = 1.0e-3
#: Overlap volume ratio between M_- and M_+.
OVERLAP_RATIO_MAX = 1.0e-4

#: Interpolation-error budget for the shared height field (plan 10.1 step 4).
DEFAULT_ERROR_BUDGET_MM = 0.01
#: Amplitude / wavelength guards (plan 10.1 step 3).
AMP_MIN_MM = 0.02
AMP_MAX_MM = 0.3
WAVELENGTH_MIN_MM = 0.2
WAVELENGTH_MAX_MM = 3.0
#: Resources per cutter (hard guard: never silently coarsen the shortest wavelength).
DEFAULT_MAX_CUTTER_CELLS = 400_000
DEFAULT_MAX_CUTTER_TRIANGLES = 3_000_000

#: Tiny-fragment archive threshold (plan 10.3): debris stays in the conservation ledger.
TINY_VOLUME_MM3 = 1.0
TINY_DIAMETER_MM = 1.0


@dataclass
class FractureSpec:
    """Frozen parameters of one fracture event (mutable only through a new spec hash)."""

    backend: str = BACKEND_PLANE
    #: plane / rough only: explicit world-space plane point+normal (hand-computed fixtures).
    plane_point: np.ndarray | None = None
    plane_normal: np.ndarray | None = None
    #: rough only
    target_rms_mm: float = 0.05
    n_bands: int | None = None
    error_budget_mm: float = DEFAULT_ERROR_BUDGET_MM
    #: warped_partition only
    n_seeds: int = 4
    power_weights_mm2: np.ndarray | None = None
    seed_points: np.ndarray | None = None
    #: secondary_fracture only
    parent_event_id: str | None = None
    target_fragment_ids: tuple[str, ...] = ()
    child_planes: list[tuple[np.ndarray, np.ndarray]] = field(default_factory=list)
    #: resources
    max_cutter_cells: int = DEFAULT_MAX_CUTTER_CELLS
    max_cutter_triangles: int = DEFAULT_MAX_CUTTER_TRIANGLES
    seed_max_mm: float = 4.0
    meta: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        def conv(value: Any) -> Any:
            if isinstance(value, np.ndarray):
                return np.asarray(value, dtype=np.float64).tolist()
            if isinstance(value, (list, tuple)):
                return [conv(v) for v in value]
            if isinstance(value, dict):
                return {str(k): conv(v) for k, v in sorted(value.items())}
            if isinstance(value, (np.integer,)):
                return int(value)
            if isinstance(value, (np.floating,)):
                return float(value)
            return value

        return conv({
            "backend": self.backend,
            "plane_point": self.plane_point,
            "plane_normal": self.plane_normal,
            "target_rms_mm": self.target_rms_mm,
            "n_bands": self.n_bands,
            "error_budget_mm": self.error_budget_mm,
            "n_seeds": self.n_seeds,
            "power_weights_mm2": self.power_weights_mm2,
            "seed_points": self.seed_points,
            "parent_event_id": self.parent_event_id,
            "target_fragment_ids": list(self.target_fragment_ids),
            "child_planes": list(self.child_planes),
            "max_cutter_cells": self.max_cutter_cells,
            "max_cutter_triangles": self.max_cutter_triangles,
            "seed_max_mm": self.seed_max_mm,
            "meta": self.meta,
        })
