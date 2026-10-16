"""Shared-cutter contract tests (plan 10.1 steps 3-5, A06/A07).

Everything here is measured on *real* cutter bodies built by ``synlab.fracture.cut``: the closed
solid must be watertight (every edge exactly two faces), outward oriented with positive volume,
free of T-junctions/duplicate vertices, and the analytic height field must be reproduced within
the frozen interpolation budget — otherwise the build must return a structured precision error
instead of silently coarsening the shortest wavelength.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
TESTS_A12 = Path(__file__).resolve().parents[2]
for _path in (str(REPO_ROOT), str(TESTS_A12)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from synlab.errors import ErrorCode, SynLabError  # noqa: E402
from synlab.fracture import cut as cut_mod  # noqa: E402
from synlab.fracture.api import make_closed_cutter  # noqa: E402
from synlab.fracture.booleans import mesh_hash  # noqa: E402
from synlab.fracture.spec import (  # noqa: E402
    BACKEND_PLANE,
    BACKEND_ROUGH,
    DEFAULT_ERROR_BUDGET_MM,
    FractureSpec,
)
from synlab.seeds import make_rng  # noqa: E402

import fixtures as fx  # noqa: E402  (tests/a12/fracture is on sys.path)

MASTER_SEED = 20261001


def _edge_use(mesh) -> dict[int, int]:
    faces = np.asarray(mesh.faces, dtype=np.int64)
    counts: dict[tuple[int, int], int] = {}
    for tri in faces:
        for k in range(3):
            a, b = int(tri[k]), int(tri[(k + 1) % 3])
            key = (a, b) if a < b else (b, a)
            counts[key] = counts.get(key, 0) + 1
    out: dict[int, int] = {}
    for value in counts.values():
        out[value] = out.get(value, 0) + 1
    return out


@pytest.fixture(scope="module")
def bowl():
    return fx.thin_bowl_mother()


@pytest.fixture(scope="module")
def box():
    return fx.box_mother((20.0, 20.0, 20.0))


def _cutter(mother, backend: str, seed: int = MASTER_SEED, **kwargs):
    rng = make_rng(seed, "fracture_test", backend)
    spec = FractureSpec(backend=backend, **kwargs)
    return make_closed_cutter(mother, spec, rng)


def test_plane_cutter_is_a_closed_positive_solid(box) -> None:
    cutter = _cutter(box, BACKEND_PLANE)
    mesh = cutter.mesh
    assert bool(mesh.is_watertight)
    assert bool(mesh.is_winding_consistent)
    assert float(mesh.volume) > 0.0
    histogram = _edge_use(mesh)
    assert set(histogram) == {2}, f"edges with != 2 incident faces: {histogram}"
    assert float(cutter.realized_error_mm) == 0.0
    assert cutter.meta["watertight"] is True
    # no duplicated vertex positions: a T-junction would leave coincident copies behind
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    assert len(np.unique(np.round(vertices, 9), axis=0)) == vertices.shape[0]


def test_plane_cutter_keeps_its_sides_and_bottom_away_from_the_material(box) -> None:
    cutter = _cutter(box, BACKEND_PLANE)
    basis = cutter.basis
    local = basis.to_local(np.asarray(box.mesh.vertices, dtype=np.float64))
    depth_margin = float(basis.meta["depth_margin_mm"])
    assert depth_margin > 0.0
    local_cutter = basis.to_local(np.asarray(cutter.mesh.vertices, dtype=np.float64))
    # every vertex of the solid is at or below the shared surface, and the bottom sits a whole
    # depth margin below the deepest material point
    assert float(local_cutter[:, 2].max()) <= 1.0e-9
    assert float(local_cutter[:, 2].min()) <= float(local[:, 2].min()) - depth_margin + 1e-9
    # the (u, v) frame strictly contains the material rectangle
    mu0, mu1 = (float(x) for x in basis.meta["material_u_range"])
    mv0, mv1 = (float(x) for x in basis.meta["material_v_range"])
    assert basis.u_range[0] < mu0 and basis.u_range[1] > mu1
    assert basis.v_range[0] < mv0 and basis.v_range[1] > mv1
    assert float(local_cutter[:, 0].min()) <= basis.u_range[0] + 1e-9
    assert float(local_cutter[:, 0].max()) >= basis.u_range[1] - 1e-9


def test_rough_cutter_is_closed_and_within_budget(bowl) -> None:
    cutter = _cutter(bowl, BACKEND_ROUGH, target_rms_mm=0.05)
    mesh = cutter.mesh
    histogram = _edge_use(mesh)
    assert set(histogram) == {2}, f"edges with != 2 incident faces: {histogram}"
    assert bool(mesh.is_watertight) and bool(mesh.is_winding_consistent)
    assert float(mesh.volume) > 0.0
    assert float(cutter.realized_error_mm) <= float(cutter.requested_error_mm) + 1e-12
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    assert len(np.unique(np.round(vertices, 9), axis=0)) == vertices.shape[0]
    height = cutter.meta["height_field"]
    if not height["flat"]:
        assert height["wavelength_min_mm"] is not None
        window = height["meta"]["admitted_wavelength_window_mm"]
        assert window[0] >= 0.2 - 1e-12
        assert float(height["wavelength_min_mm"]) >= window[0] - 1e-12
        assert 0.02 - 1e-12 <= float(height["realized_rms_mm"]) <= 0.3 + 1e-12


def test_zero_amplitude_rough_regresses_to_the_plane(box) -> None:
    """A zero-amplitude rough surface must be *the* plane cutter, hash included."""
    plane = _cutter(box, BACKEND_PLANE)
    rough_zero = _cutter(box, BACKEND_ROUGH, target_rms_mm=0.0)
    assert mesh_hash(rough_zero.mesh) == mesh_hash(plane.mesh)
    assert np.allclose(np.asarray(rough_zero.mesh.vertices, dtype=np.float64),
                       np.asarray(plane.mesh.vertices, dtype=np.float64), atol=0.0, rtol=0.0)
    assert np.array_equal(np.asarray(rough_zero.mesh.faces), np.asarray(plane.mesh.faces))
    assert rough_zero.meta["height_field"]["flat"] is True
    assert float(rough_zero.realized_error_mm) == 0.0


def test_cutter_build_is_reproducible(box) -> None:
    first = _cutter(box, BACKEND_ROUGH, target_rms_mm=0.05)
    second = _cutter(box, BACKEND_ROUGH, target_rms_mm=0.05)
    assert mesh_hash(first.mesh) == mesh_hash(second.mesh)
    third = _cutter(box, BACKEND_ROUGH, seed=MASTER_SEED + 1, target_rms_mm=0.05)
    assert mesh_hash(third.mesh) != mesh_hash(first.mesh)


def test_unreachable_budget_is_refused_not_relaxed(box) -> None:
    """1e-6 mm cannot be realized: the build must say so instead of coarsening the field."""
    rng = make_rng(MASTER_SEED, "fracture_test", "strictness")
    spec = FractureSpec(backend=BACKEND_ROUGH, target_rms_mm=0.2, error_budget_mm=1.0e-6)
    with pytest.raises(SynLabError) as info:
        make_closed_cutter(box, spec, rng)
    assert info.value.code in (ErrorCode.PRECISION_NOT_REALIZED,
                               ErrorCode.PRECISION_BUDGET_EXCEEDED)
    measurements = dict(info.value.measurements or {})
    assert measurements, "a precision refusal must carry its measured numbers"
    assert any(key in measurements for key in
               ("realized_error_mm", "budget_mm", "cells", "max_cells", "wavelength_min_mm"))


def test_height_field_never_shortens_the_admitted_wavelength(box) -> None:
    basis = cut_mod.build_basis(np.asarray(box.mesh.vertices, dtype=np.float64),
                                np.array([1.0, 0.0, 0.0]))
    rng = make_rng(MASTER_SEED, "fracture_test", "wavelength")
    height = cut_mod.make_height_field(basis, rng, target_rms_mm=0.05,
                                       wavelength_min_mm=1.0, wavelength_max_mm=2.5)
    assert float(height.wavelength_min_mm) >= 1.0 - 1e-12
    assert float(height.meta["wavelength_max_mm"]) <= 2.5 + 1e-12
    assert float(height.realized_rms_mm) <= 0.3 + 1e-9
    # the realized shortest wavelength is reported so a resource failure is attributable
    assert float(height.meta["wavelength_min_mm"]) == pytest.approx(float(height.wavelength_min_mm))


def test_default_cutter_reports_its_measured_error(bowl) -> None:
    cutter = _cutter(bowl, BACKEND_ROUGH, target_rms_mm=0.05)
    assert float(cutter.requested_error_mm) == pytest.approx(DEFAULT_ERROR_BUDGET_MM)
    assert cutter.meta["error_samples"] > 0
    assert cutter.meta["realized_error_mm"] <= DEFAULT_ERROR_BUDGET_MM + 1e-12
    assert cutter.meta["cells"] > 0
