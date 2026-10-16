"""Deterministic continuous fields for the material model (plan 8.1).

``material_at(profile, points_mm, surface_tag)`` must be a *pure function of the mother
coordinates*: two fragments that were adjacent before the break have to see exactly the same
grain, pores and colour along their shared boundary.  Nothing here draws random numbers at
query time - every field is a closed-form function of ``(x, y, z)`` and the frozen profile
parameters, so the same point always evaluates to the same material sample.

The three primitives are:

* :func:`value_noise` - smooth deterministic scalar noise with a real correlation length in
  millimetres (trilinear value noise, not a white-noise texture);
* :func:`fiber_field` - a directional field (``cos`` of the projection onto a direction plus
  a slow cross-grain term) used for wood grain, stone bedding and bone lamellae;
* :func:`aggregate_spots` - isolated rounded inclusions for coarse grog and mineral grains.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

import numpy as np

from ..errors import ErrorCode, SynLabError

#: Frozen field kernels; the name/version is recorded in a profile so a change is visible.
FIELD_KERNELS = ("value_noise", "fiber_field", "aggregate_spots")
FIELD_KERNEL_VERSION_LEGACY = 1
FIELD_KERNEL_VERSION_LOGICAL_U64 = 2


def _i64(value: int) -> np.int64:
    """Interpret a 64-bit literal as a signed int64 without numpy overflow."""
    value &= 0xFFFFFFFFFFFFFFFF
    if value >= (1 << 63):
        value -= 1 << 64
    return np.int64(value)


def _hash_ids(points: np.ndarray, salt: int) -> np.ndarray:
    """Deterministic 64-bit hash of each integer lattice point (splitmix64)."""
    x = np.asarray(points, dtype=np.int64)
    # The salt comes from 64-bit seed derivation and can exceed the signed int64 range;
    # fold it deterministically instead of letting ``np.int64`` overflow.
    salt_i = _i64(int(salt))
    # 64-bit wrapping arithmetic is intended here; numpy's overflow warning is not useful.
    with np.errstate(over="ignore"):
        h = (x[:, 0] * _i64(0x9E3779B97F4A7C15)
             + x[:, 1] * _i64(0xBF58476D1CE4E5B9)
             + x[:, 2] * _i64(0x94D049BB133111EB)
             + salt_i * _i64(0xD6E8FEB86659FD93))
        h = (h ^ (h >> _i64(30))) * _i64(0xBF58476D1CE4E5B9)
        h = (h ^ (h >> _i64(27))) * _i64(0x94D049BB133111EB)
        h = h ^ (h >> _i64(31))
    return h.astype(np.uint64)


def _hash_ids_v2(points: np.ndarray, salt: int) -> np.ndarray:
    """SplitMix64 lattice hash using the specified *logical* unsigned right shifts.

    Version 1 stored intermediate state as signed int64 and therefore used arithmetic right
    shifts. Its top output bit was always zero, so ``_lattice_values`` was restricted to
    ``[0, .5)`` and the pore threshold at .62 could never be crossed. Keep that kernel intact
    for existing profiles and use this corrected unsigned implementation only when a profile
    explicitly records kernel version 2.
    """
    signed = np.asarray(points, dtype=np.int64)
    # Viewing preserves the two's-complement bit pattern for negative lattice coordinates.
    x = np.ascontiguousarray(signed).view(np.uint64).reshape(signed.shape)
    salt_u = np.uint64(int(salt) & 0xFFFFFFFFFFFFFFFF)
    c1 = np.uint64(0x9E3779B97F4A7C15)
    c2 = np.uint64(0xBF58476D1CE4E5B9)
    c3 = np.uint64(0x94D049BB133111EB)
    c4 = np.uint64(0xD6E8FEB86659FD93)
    with np.errstate(over="ignore"):
        h = x[:, 0] * c1 + x[:, 1] * c2 + x[:, 2] * c3 + salt_u * c4
        h = (h ^ (h >> np.uint64(30))) * c2
        h = (h ^ (h >> np.uint64(27))) * c3
        h = h ^ (h >> np.uint64(31))
    return h


def _hash_ids_for_version(points: np.ndarray, salt: int, kernel_version: int) -> np.ndarray:
    if int(kernel_version) == FIELD_KERNEL_VERSION_LEGACY:
        return _hash_ids(points, salt)
    if int(kernel_version) == FIELD_KERNEL_VERSION_LOGICAL_U64:
        return _hash_ids_v2(points, salt)
    raise SynLabError(ErrorCode.SCHEMA_INVALID,
                      f"unsupported material field kernel version {kernel_version!r}",
                      stage="materials.fields",
                      measurements={"supported": [FIELD_KERNEL_VERSION_LEGACY,
                                                    FIELD_KERNEL_VERSION_LOGICAL_U64]})


def _lattice_values(ids: np.ndarray) -> np.ndarray:
    """Map hashed lattice ids into ``[0, 1)``."""
    return (ids >> np.uint64(11)).astype(np.float64) / float(1 << 53)


def value_noise(points: np.ndarray, *, cell_mm: float, salt: int = 0,
                kernel_version: int = FIELD_KERNEL_VERSION_LEGACY) -> np.ndarray:
    """Trilinear value noise in ``[0, 1]`` with correlation length ``cell_mm``.

    ``cell_mm`` is a real millimetre length: two query points closer than ``cell_mm`` share
    most of their lattice corners, which is what makes a fracture boundary continuous.
    """
    pts = np.atleast_2d(np.asarray(points, dtype=np.float64))
    cell = float(cell_mm)
    if not np.isfinite(cell) or cell <= 0:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"value_noise needs a positive cell_mm, got {cell_mm!r}",
                          stage="materials.fields")
    local = pts / cell
    base = np.floor(local).astype(np.int64)
    frac = local - base
    smooth = frac * frac * (3.0 - 2.0 * frac)
    out = np.zeros(pts.shape[0], dtype=np.float64)
    for dx in (0, 1):
        for dy in (0, 1):
            for dz in (0, 1):
                corner = base + np.array([dx, dy, dz], dtype=np.int64)[None, :]
                value = _lattice_values(_hash_ids_for_version(
                    corner, int(salt), kernel_version))
                weight = ((smooth[:, 0] if dx else 1.0 - smooth[:, 0])
                          * (smooth[:, 1] if dy else 1.0 - smooth[:, 1])
                          * (smooth[:, 2] if dz else 1.0 - smooth[:, 2]))
                out += weight * value
    return np.clip(out, 0.0, 1.0)


def fractal_noise(points: np.ndarray, *, cell_mm: float, octaves: int = 3,
                  lacunarity: float = 2.0, gain: float = 0.5, salt: int = 0,
                  kernel_version: int = FIELD_KERNEL_VERSION_LEGACY) -> np.ndarray:
    """Sum of ``octaves`` value-noise bands; the first band fixes the correlation length."""
    total = np.zeros(np.atleast_2d(np.asarray(points, dtype=np.float64)).shape[0], dtype=np.float64)
    amplitude = 1.0
    weight = 0.0
    cell = float(cell_mm)
    for octave in range(int(max(octaves, 1))):
        total += amplitude * value_noise(points, cell_mm=cell, salt=salt + octave,
                                         kernel_version=kernel_version)
        weight += amplitude
        amplitude *= float(gain)
        cell /= float(lacunarity)
    return np.clip(total / max(weight, 1e-9), 0.0, 1.0)


def fiber_field(points: np.ndarray, *, direction: Iterable[float], period_mm: float,
                cross_period_mm: float, salt: int = 0, detail: float = 0.35,
                kernel_version: int = FIELD_KERNEL_VERSION_LEGACY) -> np.ndarray:
    """Directional fibre / bedding field in ``[0, 1]`` (1 = fibre, 0 = between fibres)."""
    pts = np.atleast_2d(np.asarray(points, dtype=np.float64))
    axis = np.asarray(list(direction), dtype=np.float64).reshape(-1)
    if axis.size != 3:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "fiber direction needs 3 components",
                          stage="materials.fields")
    norm = float(np.linalg.norm(axis))
    if norm <= 1e-12:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "fiber direction must be non-zero",
                          stage="materials.fields")
    axis = axis / norm
    along = pts @ axis
    across = pts - np.outer(along, axis)
    across_radius = np.linalg.norm(across, axis=1)
    period = max(float(period_mm), 1e-6)
    cross = max(float(cross_period_mm), 1e-6)
    rings = 0.5 + 0.5 * np.cos(2.0 * np.pi * across_radius / period)
    slow = 0.5 + 0.5 * np.sin(2.0 * np.pi * along / cross + 0.7)
    jitter = fractal_noise(pts, cell_mm=0.25 * period, octaves=2, salt=salt + 977,
                           kernel_version=kernel_version)
    return np.clip((1.0 - float(detail)) * rings * (0.65 + 0.35 * slow)
                   + float(detail) * jitter, 0.0, 1.0)


def aggregate_spots(points: np.ndarray, *, count_per_mm3: float, radius_mm: float,
                    salt: int = 0,
                    kernel_version: int = FIELD_KERNEL_VERSION_LEGACY) -> np.ndarray:
    """Isolated rounded inclusions in ``[0, 1]`` (coarse grog, mineral grains).

    The decision is deterministic per lattice cell of size ``2 * radius_mm``: a cell holds a
    grain when its hash falls below the requested density, and the grain centre is placed
    from the same hash.  That produces isolated clumps that never depend on query order.
    """
    pts = np.atleast_2d(np.asarray(points, dtype=np.float64))
    radius = float(radius_mm)
    if radius <= 0:
        return np.zeros(pts.shape[0], dtype=np.float64)
    cell = 2.0 * radius
    local = pts / cell
    base = np.floor(local).astype(np.int64)
    probability = float(np.clip(count_per_mm3 * cell ** 3, 0.0, 0.9))
    out = np.zeros(pts.shape[0], dtype=np.float64)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dz in (-1, 0, 1):
                corner = base + np.array([dx, dy, dz], dtype=np.int64)[None, :]
                ids = _hash_ids_for_version(corner, int(salt) + 5501, kernel_version)
                present = _lattice_values(ids) < probability
                if not np.any(present):
                    continue
                offset = np.column_stack([
                    _lattice_values(_hash_ids_for_version(corner, int(salt) + 7717,
                                                          kernel_version)),
                    _lattice_values(_hash_ids_for_version(corner, int(salt) + 9923,
                                                          kernel_version)),
                    _lattice_values(_hash_ids_for_version(corner, int(salt) + 1231,
                                                          kernel_version)),
                ])
                centre = (corner.astype(np.float64) + offset) * cell
                distance = np.linalg.norm(pts - centre, axis=1)
                inside = np.where(present, 1.0 - np.clip(distance / radius, 0.0, 1.0), 0.0)
                out = np.maximum(out, np.clip(inside, 0.0, 1.0))
    return out


def field_stack(points: np.ndarray, *, seed_salt: int, grain_scale_mm: float,
                pore_scale_mm: float, aggregate_radius_mm: float = 0.0,
                aggregate_density: float = 0.0, fiber_direction: Sequence[float] | None = None,
                fiber_period_mm: float = 0.0, octaves: int = 3,
                spots_are_aggregate: bool = True,
                kernel_version: int = FIELD_KERNEL_VERSION_LEGACY) -> dict[str, np.ndarray]:
    """Evaluate the geometric-statistics stack of one material at ``points``.

    Returns ``grain`` (0..1), ``porosity`` (0..1) and ``spots`` (0..1).  All three are pure
    functions of the coordinates, which is the plan's requirement for fracture continuity.
    """
    pts = np.atleast_2d(np.asarray(points, dtype=np.float64))
    # Fail before evaluating partial fields when a serialized profile names an unknown kernel.
    if int(kernel_version) not in (FIELD_KERNEL_VERSION_LEGACY,
                                   FIELD_KERNEL_VERSION_LOGICAL_U64):
        _hash_ids_for_version(np.zeros((0, 3), dtype=np.int64), seed_salt, kernel_version)
    grain = fractal_noise(pts, cell_mm=max(float(grain_scale_mm), 1e-3), octaves=octaves,
                          salt=seed_salt, kernel_version=kernel_version)
    pores = fractal_noise(pts, cell_mm=max(float(pore_scale_mm), 1e-3), octaves=2,
                          salt=seed_salt + 101, kernel_version=kernel_version)
    # a pore is a *hole*: darken the smooth field into a sparse high-contrast mask
    porosity = np.clip((pores - 0.62) / 0.38, 0.0, 1.0)
    if aggregate_radius_mm > 0 and aggregate_density > 0:
        spots = aggregate_spots(pts, count_per_mm3=float(aggregate_density),
                                radius_mm=float(aggregate_radius_mm), salt=seed_salt + 313,
                                kernel_version=kernel_version)
    else:
        spots = np.zeros(pts.shape[0], dtype=np.float64)
    if fiber_direction is not None and float(fiber_period_mm) > 0:
        fibers = fiber_field(pts, direction=fiber_direction, period_mm=float(fiber_period_mm),
                             cross_period_mm=max(8.0 * float(fiber_period_mm), 1e-3),
                             salt=seed_salt + 71, kernel_version=kernel_version)
        grain = np.clip(0.45 * grain + 0.55 * fibers, 0.0, 1.0)
    direction = _direction_field(fiber_direction, pts.shape[0])
    return {"grain": grain, "porosity": porosity, "spots": spots, "direction": direction}


def _direction_field(fiber_direction: Sequence[float] | None, count: int) -> np.ndarray:
    """Per-point grain / bedding direction (unit vectors), constant for isotropic bodies."""
    if fiber_direction is None:
        axis = np.array([0.0, 0.0, 1.0], dtype=np.float64)
    else:
        axis = np.asarray(list(fiber_direction), dtype=np.float64).reshape(-1)[:3]
        norm = float(np.linalg.norm(axis))
        axis = axis / norm if norm > 1e-12 else np.array([0.0, 0.0, 1.0])
    return np.tile(axis[None, :], (int(count), 1))


__all__ = ["FIELD_KERNELS", "FIELD_KERNEL_VERSION_LEGACY",
           "FIELD_KERNEL_VERSION_LOGICAL_U64", "value_noise", "fractal_noise", "fiber_field",
           "aggregate_spots", "field_stack"]
