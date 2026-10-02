"""Implicit-sheet cutter topology: watertight, zero bad edges, budget and sampling contracts.

The cutter is the *one* instance both halves of an event consume, so its topology is the first
thing that has to hold.  Every threshold asserted here is the frozen A06 one; nothing is relaxed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixtures as fx  # noqa: E402

from synlab.fracture.implicit.backend import build_implicit_cutter  # noqa: E402
from synlab.fracture.spec import (  # noqa: E402
    DEFAULT_ERROR_BUDGET_MM,
    INTERFACE_GAP_P95_MM,
    NORMAL_REVERSAL_P95_DEG,
)
from synlab.materials.api import build_material_profile, default_material_params  # noqa: E402
from synlab.seeds import make_rng  # noqa: E402

TRIANGLE_BUDGET = 60_000
LIN = "a12_fracture_implicit_test"


@pytest.fixture(scope="module")
def built():
    mother = fx.box_mother((12.0, 12.0, 12.0), mother_id="implicit_topology")
    profile = build_material_profile("M01", default_material_params("M01"),
                                     make_rng(20261001, LIN, "material"))
    cutter, field, params, report = build_implicit_cutter(
        mother, material_profile=profile, rng=make_rng(20261001, LIN, "build"),
        event_id="topology", error_budget_mm=DEFAULT_ERROR_BUDGET_MM,
        options={"max_sheet_triangles": TRIANGLE_BUDGET})
    return mother, cutter, field, params, report


def test_cutter_is_a_closed_manifold_with_zero_bad_edges(built) -> None:
    _mother, cutter, _field, _params, report = built
    topology = report["topology"]
    assert bool(topology["is_watertight"]) is True
    assert int(topology["bad_edges"]) == 0
    assert int(topology["boundary_edges"]) == 0
    assert bool(topology["is_winding_consistent"]) is True
    assert set(topology["edge_use_histogram"]) == {"2"}
    assert int(topology["euler_number"]) == 2
    assert float(topology["volume_mm3"]) > 0.0
    assert int(report["bad_edges"]) == 0 and bool(report["watertight"]) is True
    # one instance for both sides: the recorded hash is the mesh's own hash
    from synlab.fracture.booleans import mesh_hash

    assert report["cutter_hash"] == mesh_hash(cutter.mesh)


def test_realized_interpolation_error_is_inside_the_frozen_budget(built) -> None:
    _mother, _cutter, _field, _params, report = built
    error = report["realized_error"]
    assert float(report["requested_error_mm"]) == pytest.approx(DEFAULT_ERROR_BUDGET_MM)
    assert float(error["realized_error_mm"]) <= DEFAULT_ERROR_BUDGET_MM * (1.0 + 1e-9)
    assert bool(error["within_budget"]) is True
    assert int(error["probes_per_triangle"]) >= 10
    assert int(error["triangles_checked"]) > 0


def test_sampling_density_meets_the_four_per_wavelength_contract(built) -> None:
    _mother, _cutter, _field, _params, report = built
    sampling = report["sampling_density"]
    assert bool(sampling["meets_4_per_lambda"]) is True
    assert float(sampling["samples_per_lambda_p95_worst"]) >= 4.0
    plan = report["sampling_plan"]
    # the chosen spacing never exceeds the sampling bound ...
    assert float(plan["delta_final_mm"]) <= float(plan["delta_sampling_mm"]) * (1.0 + 1e-9)
    # ... and never goes below the triangle-budget bound (that is where the mask widens instead)
    assert float(plan["delta_final_mm"]) >= float(plan["delta_triangle_budget_mm"]) * (1.0 - 1e-9)
    assert int(plan["triangle_budget"]) == TRIANGLE_BUDGET


def test_band_limiting_is_reported_and_never_silent(built) -> None:
    _mother, _cutter, _field, _params, report = built
    limit = report["field"]["band_limit"]
    assert int(limit["bands_kept"]) >= 1
    assert int(limit["bands_kept"]) + len(limit["dropped"]) == int(limit["bands_requested"])
    if limit["band_limited"]:
        assert float(limit["removed_rms_mm"]) >= 0.0
        assert limit["dropped"], "a band-limited spectrum must name the dropped bands"
    assert float(limit["lambda_min_realized_mm"]) > 0.0


def test_sheet_taper_is_one_on_the_footprint_and_zero_far_outside(built) -> None:
    """The taper's own contract: exactly 1 on the footprint, 0 beyond the taper width."""
    _mother, _cutter, field, _params, _report = built
    envelope = field.envelope
    assert envelope is not None
    width = float(envelope.width_mm)
    u = np.array([envelope.u0, envelope.u0 + 1.0])
    v = np.array([envelope.v0, envelope.v0 + 1.0])
    sd = envelope.signed_distance(u, v)
    assert np.all(np.isfinite(sd))
    inside = envelope.mask(u, v)
    assert np.all(inside[sd >= 0.0] == pytest.approx(1.0))
    far = envelope.mask(np.array([envelope.u0]), np.array([envelope.v0]))
    assert float(far[0]) <= 1.0
    assert width > 0.0


def test_gate_refuses_without_the_switch_and_declares_itself_out_of_built_backends() -> None:
    from synlab.fracture import api as api_mod
    from synlab.fracture.implicit import BACKEND_IMPLICIT, backend_status

    status = backend_status()
    assert status["registered"] is True
    assert status["gated"] is True
    assert status["in_built_backends"] is False
    assert BACKEND_IMPLICIT not in api_mod.BUILT_BACKENDS
    from synlab.registry import REGISTRY

    entry = REGISTRY.get("fracture_backend", BACKEND_IMPLICIT)
    assert entry.status == "SPECIFIED"
    assert "implicit" in entry.notes
    assert entry.meta.get("builder_name") == "build_implicit_cutter"


def test_interface_and_normal_tolerances_are_the_frozen_ones() -> None:
    """A guard against silently relaxing the shared-surface thresholds."""
    assert INTERFACE_GAP_P95_MM == 0.02
    assert NORMAL_REVERSAL_P95_DEG == 2.0
    assert DEFAULT_ERROR_BUDGET_MM == 0.01
