"""Stable randomness: explicit sub-streams that never depend on worker order (plan 5.1)."""

from __future__ import annotations

import hashlib
import json
from typing import Iterable

import numpy as np

#: Fixed module sub-stream names.  ``pattern.evaluate`` reads frozen coefficients only and
#: must never draw randomness at query points.
MODULES: tuple[str, ...] = (
    "shape", "material", "pattern", "cut", "damage",
    "camera", "light", "sensor", "geometry", "sampler",
)

#: Frozen bit generator, recorded in env_report so replay is verifiable.
BIT_GENERATOR = "PCG64"


def seed64(master_seed: int, *parts: object) -> int:
    """Derive a 64-bit unsigned seed from an explicit key path.

    Never depends on worker index, completion order or ``hash()``.
    """
    payload = json.dumps(
        [int(master_seed), *parts], ensure_ascii=False,
        separators=(",", ":"), sort_keys=True, allow_nan=False,
    ).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "little")


def make_rng(master_seed: int, *parts: object) -> np.random.Generator:
    return np.random.Generator(np.random.PCG64(seed64(master_seed, *parts)))


def derive_named_rngs(master_seed: int, lineage_id: str,
                      modules: Iterable[str] = MODULES) -> dict[str, np.random.Generator]:
    """One independent generator per module for a given lineage."""
    return {name: make_rng(master_seed, lineage_id, name) for name in modules}


def seed_ref(master_seed: int, *parts: object) -> str:
    """Human-readable, deterministic seed reference for logs and metrics."""
    return json.dumps([int(master_seed), *parts], ensure_ascii=False, separators=(",", ":"))


def basis_id(axis_id: str, master_seed: int, lineage_id: str, fragment_id: str) -> str:
    """All intensity levels of one axis share a single basis id (no per-level redraw)."""
    return hashlib.sha256(
        json.dumps([axis_id, int(master_seed), lineage_id, fragment_id],
                   separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()[:32]
