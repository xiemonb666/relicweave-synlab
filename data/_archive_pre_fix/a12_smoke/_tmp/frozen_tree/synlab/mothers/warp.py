"""Low-amplitude non-axisymmetric deformation shared by both walls (plan 7.1 step 6).

The warp is a *common* vertex map: radial scaling multiplies the inner and the outer
surface by the same factor and an eccentric shift translates both, so the wall thickness
is not silently manufactured or destroyed.  Every warped mother is re-measured by
``audit_mother`` and rejected with ``MOTHER_INVALID`` when the realised thickness drops
below the gate, so this module never has to be trusted on its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import trimesh

from ..errors import ErrorCode, SynLabError

#: candidate reuse: ``manifold3d.Manifold.warp`` applies a topology-preserving vertex map
#: inside the Manifold kernel, but its Python round-trip does not guarantee that the
#: triangle order (and therefore our ``face_surface_tag`` / ``source_triangle`` arrays)
#: survives.  The PoC in ``_poc_reuse`` records that evidence; the project therefore
#: applies the identical map to the trimesh vertex array.
WARP_MODE = "numpy_vertex_map"


@dataclass
class WarpSpec:
    """Parameters of one non-axisymmetric deformation (recorded with the mother)."""

    amplitude: float = 0.0          # radial modulation fraction (0 .. 0.08)
    lobes: int = 2                  # circumferential mode count (2, 3, 4, ...)
    phase_rad: float = 0.0
    eccentricity_mm: float = 0.0    # lateral offset growing with height
    ecc_phase_rad: float = 0.0
    envelope_top: float = 1.0       # radial warp weight at the rim
    envelope_bottom: float = 0.0    # radial warp weight at the base
    z_min: float = 0.0
    z_max: float = 1.0
    tilt_rad: float = 0.0           # optional lean of the upper part
    meta: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": WARP_MODE,
            "amplitude": float(self.amplitude),
            "lobes": int(self.lobes),
            "phase_rad": float(self.phase_rad),
            "eccentricity_mm": float(self.eccentricity_mm),
            "ecc_phase_rad": float(self.ecc_phase_rad),
            "envelope_top": float(self.envelope_top),
            "envelope_bottom": float(self.envelope_bottom),
            "z_min_mm": float(self.z_min),
            "z_max_mm": float(self.z_max),
            "tilt_rad": float(self.tilt_rad),
            **{k: v for k, v in self.meta.items()},
        }

    @property
    def is_identity(self) -> bool:
        return (abs(self.amplitude) < 1e-12 and abs(self.eccentricity_mm) < 1e-12
                and abs(self.tilt_rad) < 1e-12)


def warp_spec_from_rng(rng: np.random.Generator, *, z_min: float, z_max: float,
                       amplitude_max: float, eccentricity_max_mm: float,
                       allowed_lobes: tuple[int, ...] = (2, 3, 4)) -> WarpSpec:
    """Draw one frozen warp (RNG is used once, at build time - never at query time)."""
    if amplitude_max < 0 or eccentricity_max_mm < 0:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "warp amplitudes must be non-negative",
                          stage="mothers.warp")
    u = rng.random(4)
    amp = float(amplitude_max) * float(np.sqrt(u[0]))          # area-weighted draw
    lobes = int(allowed_lobes[int(rng.integers(0, len(allowed_lobes)))])
    ecc = float(eccentricity_max_mm) * float(np.sqrt(u[1]))
    return WarpSpec(
        amplitude=amp,
        lobes=lobes,
        phase_rad=float(u[2] * 2.0 * np.pi),
        eccentricity_mm=ecc,
        ecc_phase_rad=float(u[3] * 2.0 * np.pi),
        z_min=float(z_min),
        z_max=float(z_max),
    )


def apply_warp(mesh: trimesh.Trimesh, spec: WarpSpec) -> dict[str, Any]:
    """Apply ``spec`` to the vertices in place; returns a realised-deformation report."""
    if spec.is_identity:
        return {"applied": False, "max_displacement_mm": 0.0, "mode": WARP_MODE}
    verts = np.asarray(mesh.vertices, dtype=np.float64)
    v = verts.copy()
    x, y, z = v[:, 0], v[:, 1], v[:, 2]
    r = np.hypot(x, y)
    theta = np.arctan2(y, x)
    span = max(spec.z_max - spec.z_min, 1e-9)
    t = np.clip((z - spec.z_min) / span, 0.0, 1.0)
    env = spec.envelope_bottom + (spec.envelope_top - spec.envelope_bottom) * t
    safety = np.where(r > 1e-6, 1.0, 0.0)
    mod = 1.0 + spec.amplitude * env * np.cos(spec.lobes * theta + spec.phase_rad)
    r_new = r * mod * safety + r * (1.0 - safety)
    scale = np.where(r > 1e-6, r_new / np.maximum(r, 1e-9), 1.0)
    v[:, 0] = x * scale
    v[:, 1] = y * scale
    if abs(spec.eccentricity_mm) > 1e-12 or abs(spec.tilt_rad) > 1e-12:
        shift = (spec.eccentricity_mm * env + np.tan(spec.tilt_rad) * (z - spec.z_min))
        v[:, 0] += shift * np.cos(spec.ecc_phase_rad)
        v[:, 1] += shift * np.sin(spec.ecc_phase_rad)
    disp = np.linalg.norm(v - verts, axis=1)
    mesh.vertices = v
    mesh.metadata = dict(mesh.metadata or {})
    return {
        "applied": True,
        "mode": WARP_MODE,
        "max_displacement_mm": float(disp.max()),
        "mean_displacement_mm": float(disp.mean()),
        "spec": spec.as_dict(),
    }
