"""Display <-> authority frame conversion (plan 20.14.1, interfaces.md section 1).

Authoritative geometry is **millimetres, right-handed, Z-up**.  glTF/GLB is **metres,
Y-up**.  ``T_display_authority`` is applied exactly once when deriving a display asset,
and its inverse exactly once when a display measurement is mapped back to authority
units.  Applying it twice is the classic 1000x scale bug; :func:`authority_to_display`
and :func:`display_to_authority` are the only sanctioned entry points, and
``tests/a12/api/test_display_transform.py`` checks both round trips with a 100 mm cube.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ..canonical import hash_json

MM_PER_M = 1000.0
DISPLAY_UNIT = "m"
AUTHORITY_UNIT = "mm"
DISPLAY_UP_AXIS = "Y"
AUTHORITY_UP_AXIS = "Z"

#: (x_d, y_d, z_d, 1) = T_display_authority @ (x_a, y_a, z_a, 1)
#:   x_d = 0.001 * x_a ; y_d = 0.001 * z_a ; z_d = -0.001 * y_a
T_DISPLAY_AUTHORITY: np.ndarray = np.array(
    [
        [0.001, 0.0, 0.0, 0.0],
        [0.0, 0.0, 0.001, 0.0],
        [0.0, -0.001, 0.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ],
    dtype=np.float64,
)

#: exact inverse of :data:`T_DISPLAY_AUTHORITY` (no floating point drift for the basis swap)
T_AUTHORITY_DISPLAY: np.ndarray = np.array(
    [
        [1000.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, -1000.0, 0.0],
        [0.0, 1000.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ],
    dtype=np.float64,
)

TRANSFORM_ID = hash_json({
    "display_to_authority": T_DISPLAY_AUTHORITY.tolist(),
    "authority_unit": AUTHORITY_UNIT,
    "display_unit": DISPLAY_UNIT,
    "authority_up": AUTHORITY_UP_AXIS,
    "display_up": DISPLAY_UP_AXIS,
    "applied": 1,
})


def _as_points(points: Any) -> np.ndarray:
    array = np.asarray(points, dtype=np.float64)
    if array.ndim != 2 or array.shape[1] != 3:
        raise ValueError(f"expected an (N,3) point array, got shape {array.shape}")
    return array


def authority_to_display(points_mm: Any, *, scale: float = 1.0) -> np.ndarray:
    """mm/Z-up -> m/Y-up **once** (returns a new array; the input is not modified)."""
    points = _as_points(points_mm)
    out = np.empty_like(points)
    out[:, 0] = points[:, 0] / MM_PER_M * scale
    out[:, 1] = points[:, 2] / MM_PER_M * scale
    out[:, 2] = -points[:, 1] / MM_PER_M * scale
    return out

def display_to_authority(points_m: Any, *, scale: float = 1.0) -> np.ndarray:
    """m/Y-up -> mm/Z-up **once** (inverse of :func:`authority_to_display`)."""
    points = _as_points(points_m)
    out = np.empty_like(points)
    out[:, 0] = points[:, 0] * MM_PER_M / scale
    out[:, 1] = -points[:, 2] * MM_PER_M / scale
    out[:, 2] = points[:, 1] * MM_PER_M / scale
    return out


def transform_vertices(vertices_mm: Any) -> np.ndarray:
    """Vectorised 4x4 application used for whole meshes (mm -> display m)."""
    points = _as_points(vertices_mm)
    homogeneous = np.concatenate([points, np.ones((points.shape[0], 1))], axis=1)
    return (T_DISPLAY_AUTHORITY @ homogeneous.T).T[:, :3]


def up_axis_swap_display_to_authority() -> np.ndarray:
    """The 3x3 rotation part of the authority transform (Y-up -> Z-up, metres -> mm)."""
    return T_AUTHORITY_DISPLAY[:3, :3]


def describe() -> dict[str, Any]:
    """Machine-readable record stored on every derived display asset."""
    return {
        "transform_id": TRANSFORM_ID,
        "authority_unit": AUTHORITY_UNIT,
        "authority_up_axis": AUTHORITY_UP_AXIS,
        "display_unit": DISPLAY_UNIT,
        "display_up_axis": DISPLAY_UP_AXIS,
        "display_to_authority": T_DISPLAY_AUTHORITY.tolist(),
        "authority_to_display": T_AUTHORITY_DISPLAY.tolist(),
        "applied_count": 1,
        "note": "GLB geometry is display-derived; authoritative geometry stays in mm/Z-up",
    }
