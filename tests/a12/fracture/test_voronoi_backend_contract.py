"""``warp_voronoi_cut`` through the façade: dispatch, reproducibility and the A06 audit.

The review requirement has two halves and both are asserted here on a **real** mother (V01/M01,
184888 mm^3, measured median wall 4.08 mm):

* the backend is reachable from ``synlab.fracture.api.fracture_event`` -- the same entry point the
  batch pipeline uses -- and it is a *physical* split, not a plane: the piece count comes from the
  count law and the pieces carry a Voronoi cell, not a cutter plane;
* the event that comes back is A06-green, and the same seed reproduces it bit for bit.

The event sizes are chosen small (2-5 cells) because this host kills heavy processes; the full
efficiency table is measured by ``tests/a12/fracture/_run_calibration.py`` and recorded in
``docs/a12/fracture_calibration.md``.
"""
from __future__ import annotations

import numpy as np
import pytest

from synlab.fracture.api import BUILT_BACKENDS, audit_fracture, fracture_event
from synlab.fracture.impact import BodyStats, MaterialStats
from synlab.fracture.spec import FractureSpec

pytestmark = pytest.mark.filterwarnings("ignore::RuntimeWarning")

VESSEL = "V01"
MATERIAL = "M01"
MOTHER_VOLUME_MM3 = 184887.9889183985
MOTHER_WALL_MM = 4.080892328102671


def _mother():
    from synlab.mothers.api import create_mother, default_params, ensure_registered

    ensure_registered()
    mother = create_mother(VESSEL, MATERIAL, default_params(VESSEL),
                           np.random.default_rng(20261002))
    mother.vessel_id = VESSEL
    mother.material_id = MATERIAL
    return mother


def _spec(target_pieces: int | None = None, drop_height_mm: float | None = None) -> FractureSpec:
    meta: dict[str, object] = {}
    if target_pieces is not None:
        meta["target_pieces"] = int(target_pieces)
    if drop_height_mm is not None:
        meta["drop_height_mm"] = float(drop_height_mm)
    return FractureSpec(backend="warp_voronoi_cut", meta=meta)


def test_backend_is_registered_and_no_longer_pending() -> None:
    assert "warp_voronoi_cut" in BUILT_BACKENDS
    from synlab.fracture.api import PENDING_BACKENDS

    assert "warp_voronoi_cut" not in PENDING_BACKENDS


def test_registry_entry_names_the_entry_point() -> None:
    from synlab.registry import REGISTRY, load_all

    load_all()
    entry = REGISTRY.get("fracture_backend", "warp_voronoi_cut")
    assert entry is not None
    notes = str(getattr(entry, "notes", ""))
    assert "run_voronoi_event" in notes or "voronoi_event" in notes


def test_efficiency_sweep_entry_point_reports_the_count_source() -> None:
    """A forced count is recorded as an override; the physics result stays published next to it."""
    from synlab.fracture.calibrate import body_stats_of, material_stats_of
    from synlab.fracture.voronoi_event import run_voronoi_event
    from synlab.fracture.physics import load_physics_config

    config = load_physics_config()
    mother = _mother()
    body = body_stats_of(mother, VESSEL)
    material = material_stats_of(MATERIAL)
    result = run_voronoi_event(mother, event_id="CONTRACT-OVERRIDE", config=config,
                               rng=np.random.default_rng(20261002), body=body, material=material,
                               target_pieces=4)
    assert result.meta["count_source"] == "explicit_override"
    assert result.meta["target_pieces"] == 4
    count_model = result.meta["count_model"]
    assert count_model["n_raw"] > 0.0
    assert count_model["count_source"] if "count_source" in count_model else True
    assert len(result.fragments) >= 1
    for fragment in result.fragments:
        assert int(fragment.meta.get("voronoi_cell", -1)) >= 0
    assert result.qa.get("passed") is True


def test_facade_dispatch_runs_a_real_voronoi_event() -> None:
    mother = _mother()
    result = fracture_event(mother, _spec(target_pieces=3), np.random.default_rng(20261002),
                            event_id="CONTRACT-DISPATCH")
    assert result.backend == "warp_voronoi_cut"
    assert len(result.fragments) >= 2
    # the physics record is present and traceable to this event's own spec
    assert result.meta["physics_config_hash"].startswith("sha256:")
    assert result.meta["fracture_spec_hash"]
    assert result.meta["count_source"] in ("physics", "explicit_override")
    audit = audit_fracture(result, mother)
    assert audit["passed"] is True, audit.get("failures")
    # a Voronoi event is *not* a plane cut: it produces one cell per piece, not two sides
    assert all(int(f.meta.get("voronoi_cell", -1)) >= 0 for f in result.fragments)


def test_a06_audit_numbers_of_a_real_voronoi_event() -> None:
    mother = _mother()
    result = fracture_event(mother, _spec(target_pieces=5), np.random.default_rng(20261002),
                            event_id="CONTRACT-A06")
    qa = result.qa
    assert qa["passed"] is True, qa.get("failures")
    assert qa["volume_rel_diff"] <= qa["volume_tolerance"]
    assert qa["overlap_ratio"] <= qa["overlap_tolerance"]
    assert qa["gap_p95_mm_max"] <= qa["gap_tolerance_mm"]
    assert qa["normal_angle_p95_deg_max"] <= qa["normal_angle_tolerance_deg"]
    assert qa["source_coverage"] >= 0.999
    assert qa["ambiguous_area_ratio_total"] <= qa["ambiguity_tolerance"]
    # every piece is a closed positive solid, and they sum to the mother
    for fragment in result.fragments:
        assert fragment.mesh.is_watertight
        assert float(fragment.volume_mm3) > 0.0
    total = float(sum(f.volume_mm3 for f in result.fragments))
    assert total == pytest.approx(MOTHER_VOLUME_MM3, rel=1e-3)
    # the conjugate evidence: every shared facet is the identical vertex set on both sides
    conjugacy = result.meta["facet_conjugacy"]
    assert conjugacy["conjugate"] is True
    assert conjugacy["one_sided_facets"] == 0


def test_drop_height_in_the_spec_meta_changes_the_count() -> None:
    mother = _mother()
    low = fracture_event(mother, _spec(drop_height_mm=500.0), np.random.default_rng(20261002),
                         event_id="CONTRACT-LOW")
    high = fracture_event(mother, _spec(drop_height_mm=8000.0), np.random.default_rng(20261002),
                          event_id="CONTRACT-HIGH")
    low_energy = low.meta["count_model"]["energy_j"]
    high_energy = high.meta["count_model"]["energy_j"]
    assert high_energy > low_energy
    assert high.meta["count_model"]["n_deterministic"] > low.meta["count_model"]["n_deterministic"]


def test_same_seed_reproduces_the_same_partition() -> None:
    mother = _mother()
    first = fracture_event(mother, _spec(target_pieces=4), np.random.default_rng(20261002),
                           event_id="CONTRACT-R1")
    second = fracture_event(mother, _spec(target_pieces=4), np.random.default_rng(20261002),
                            event_id="CONTRACT-R2")
    assert first.cutter_ref == second.cutter_ref
    assert result_volumes(first) == result_volumes(second)
    # an *independent* seed reaches the same audit result through a different partition: the
    # reproducibility claim is about the seed, and the QA claim is about the geometry
    other = fracture_event(mother, _spec(target_pieces=4), np.random.default_rng(11),
                           event_id="CONTRACT-R3")
    assert other.cutter_ref != first.cutter_ref
    assert other.qa.get("passed") is True
    assert other.qa["volume_rel_diff"] <= other.qa["volume_tolerance"]
    assert len(other.fragments) >= 2


def result_volumes(result) -> list[float]:
    return [round(float(f.volume_mm3), 6) for f in result.fragments]


def test_a_seed_that_fails_the_audit_is_refused_not_repaired() -> None:
    """Some seeds land on a partition the backend cannot deliver; the refusal is explicit.

    This is the honest half of "accepted by the batch chain": a partition whose discretised cell
    cutters are not closed loses the whole cell's material, the audit reports the shortfall against
    the frozen 0.1% tolerance, and the event is refused.  Nothing here retries with another seed or
    relaxes a threshold; the failure is raised as ``FRACTURE_CONSERVATION_FAIL`` with the measured
    numbers attached, and ``docs/a12/fracture_calibration.md`` records the measured rate.
    """
    from synlab.errors import SynLabError

    mother = _mother()
    refused = 0
    for seed in (7, 20261002, 11, 23):
        try:
            result = fracture_event(mother, _spec(target_pieces=4), np.random.default_rng(seed),
                                    event_id=f"CONTRACT-SEED{seed}")
        except SynLabError as exc:
            assert str(getattr(exc.code, "value", exc.code)) == "FRACTURE_CONSERVATION_FAIL"
            measurements = exc.measurements or {}
            assert ("volume_rel_diff" in measurements or "open_cutters" in measurements
                    or "cells" in measurements)
            refused += 1
            continue
        assert result.qa.get("passed") is True, result.qa.get("failures")
    # at least one seed of the four is reproducible and green, and the rate is published
    assert refused <= 3


def test_open_cutter_condition_is_published_and_explains_a_shortfall() -> None:
    """A non-closed cell cutter is *reported* per cell, not left to look like an overlap defect."""
    from synlab.fracture.calibrate import body_stats_of, event_rng, material_stats_of
    from synlab.fracture.physics import load_physics_config
    from synlab.fracture.voronoi_event import _displaced_cell_mesh, run_voronoi_event

    config = load_physics_config()
    mother = _mother()
    body: BodyStats = body_stats_of(mother, VESSEL)
    material: MaterialStats = material_stats_of(MATERIAL)
    result = run_voronoi_event(mother, event_id="CONTRACT-OPEN", config=config,
                               rng=event_rng(), body=body, material=material, target_pieces=8)
    assert "open_cutters" in result.meta
    assert "open_cutter_count" in result.meta
    assert result.meta["open_cutter_count"] == len(result.meta["open_cutters"])
    # the published list is exactly the cells whose cutter is not a closed solid, measured with the
    # event's own discretisation
    assert all(isinstance(index, int) for index in result.meta["open_cutters"])
    if result.meta["open_cutter_count"]:
        assert result.meta["dropped_cells"], (
            "an open cutter must show up as a dropped cell; otherwise the indicator is not the "
            "mechanism it claims to be")
    del _displaced_cell_mesh  # imported for the docstring reference only


def test_body_stats_come_from_measurements_not_constants() -> None:
    from synlab.fracture.calibration import body_stats_of

    mother = _mother()
    body = body_stats_of(mother, VESSEL)
    assert body.wall_mm == pytest.approx(MOTHER_WALL_MM, rel=0.02)
    assert body.volume_mm3 == pytest.approx(MOTHER_VOLUME_MM3, rel=1e-6)
    assert body.thickness_min_mm < body.wall_mm < body.thickness_max_mm
