"""Shared fixtures for the A12 material / layer tests (plan 8)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:  # pragma: no cover - import guard for direct execution
    sys.path.insert(0, str(REPO_ROOT))

from synlab.materials.api import build_material_profile, material_ids  # noqa: E402
from synlab.seeds import make_rng  # noqa: E402

SEED_A = 4242
SEED_B = 77


@pytest.fixture(scope="session")
def all_materials() -> list[str]:
    ids = material_ids()
    assert len(ids) == 12, f"expected the twelve plan materials, got {ids}"
    return ids


@pytest.fixture(scope="session")
def profiles(all_materials):
    """``{material_id: profile}`` frozen from one documented seed per material."""
    return {mid: build_material_profile(mid, {}, make_rng(SEED_A, "material", mid))
            for mid in all_materials}


@pytest.fixture(scope="session")
def outer_points() -> np.ndarray:
    """A deterministic sample of mother millimetres inside a reference 80 mm shell."""
    rng = np.random.default_rng(11)
    radius = rng.uniform(30.0, 80.0, size=48)
    height = rng.uniform(0.0, 130.0, size=48)
    angle = rng.uniform(0.0, 2.0 * np.pi, size=48)
    return np.column_stack([radius * np.cos(angle), radius * np.sin(angle), height])


def reference_profile(material_id: str, *, r_outer_mm: float = 80.0,
                      z_rim_mm: float = 130.0) -> dict:
    profile = build_material_profile(material_id, {}, make_rng(SEED_A, "material", material_id))
    profile["outer_reference"].update({"r_outer_mm": float(r_outer_mm),
                                       "r_inner_mm": 0.0, "z_floor_mm": 0.0,
                                       "z_rim_mm": float(z_rim_mm)})
    return profile


__all__ = ["SEED_A", "SEED_B", "reference_profile"]
