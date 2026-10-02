"""Read-only audit tests for the mother-geometry findings (A12).

These tests **measure** the current mother geometry and assert that the measurements are on
record; they do not change any geometry, and they never write to the repository.

Assertions that state the geometry *should* be correct are marked
``pytest.mark.xfail(strict=True, ...)`` and name the defect they depend on, so that

* the suite stays green while the defect is open (the failure is the recorded expectation),
* and the moment the defect is fixed the strict xfail turns into XPASS -> a hard error that
  forces the assertion to be promoted to a normal test.

Defect references (all in ``docs/a12/mother_geometry_audit.md`` and
``data/a12/reports/mother_geometry_audit.json``):

* **A1** ``synlab/mothers/vessels/common.py`` ``wall_points`` (the final clamp at the end of
  the function, ``if out and rr > out[-1][0]: rr = out[-1][0]``) forces the returned radii to
  be non-increasing.  Every call site asks for a wall that runs from ``r_start`` up to a larger
  ``R_mm``, so the wall is returned flat at the radius of the first sample.
* **A2** ``monotone_radius_control_points`` (same file) drops every control point whose radius
  is below the running maximum, which deletes the shoulder/neck cone of a necked vessel and
  truncates the body at the shoulder.
* **A3** ``group_extrude.py`` V22 implements the bevel as a boolean *intersection* with a
  bevel-thick plate, so the slab is cut down to the bevel thickness.

State of the defects in this checkout (see the "修复落地与验证" section of the report):

* **A1 and A2 are fixed** - P1 removed the radius clamp from ``wall_points`` and P2 replaced
  the radius-monotone filter with ``advancing_control_points`` (z must advance).  The seven
  strict xfails that depended on A1/A2 turned into XPASS and are now **plain assertions**
  (``test_wall_widens_to_its_declared_radius``, ``test_neck_family_body_reaches_its_declared_rim``,
  ``test_v10_lid_seats_on_the_body_instead_of_floating``).
* **A3 (V22) and B1 (V23) are still open**, so their two xfails stay strict.

Because the pre-fix numbers in ``data/a12/reports/mother_geometry_audit.json`` are the *frozen
pre-fix snapshot*, the live build can no longer be compared against it.  The live cross-check
now uses the post-fix measurement file ``s15_audit_all.json`` and, separately, asserts that the
pre-fix snapshot still carries its own (historical) values.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:  # pragma: no cover - guard for direct execution
    sys.path.insert(0, str(REPO_ROOT))

from synlab.mothers.api import audit_mother, create_mother, default_params  # noqa: E402
from synlab.mothers.vessels import common as common_mod  # noqa: E402
from synlab.seeds import make_rng, seed64  # noqa: E402

#: The vessels whose profile ends in a decreasing shoulder/neck cone (defect A2).
NECK_FAMILY = ("V06", "V07", "V08", "V09", "V10", "V11", "V16")
#: The **pre-fix** audit report this module cross-checks (frozen snapshot, commit c311269).
AUDIT_JSON = REPO_ROOT / "data" / "a12" / "reports" / "mother_geometry_audit.json"
#: The **post-fix** re-measurement of all 24 vessels (P1+P2 landed).
POSTFIX_JSON = (REPO_ROOT / "data" / "a12" / "reports" / "geom_fix" / "s15_audit_all.json")
#: Seed policy of the audit (the same one the report was produced with).
SEED_TAG = "mother_geometry_audit"


def _rng(vessel_id: str):
    return make_rng(int(seed64(0xA12, vessel_id, SEED_TAG)), vessel_id, "audit")


@pytest.fixture(scope="module")
def neck_mothers() -> dict:
    """One real mother per neck-family vessel, built exactly as the audit built it."""
    out = {}
    for vessel_id in NECK_FAMILY:
        out[vessel_id] = create_mother(vessel_id, "M01", default_params(vessel_id),
                                       _rng(vessel_id), mother_id=f"{vessel_id}-audit")
    return out


# ---------------------------------------------------------------------------------------
# recordings: these assert that the measurement exists, not that it is good
# ---------------------------------------------------------------------------------------
def test_audit_report_exists_and_covers_every_vessel():
    if not AUDIT_JSON.exists():
        pytest.skip(f"{AUDIT_JSON.relative_to(REPO_ROOT)} is not present in this checkout")
    payload = json.loads(AUDIT_JSON.read_text(encoding="utf-8"))
    table = payload["symptom_table"]
    assert len(table) == 24, "the audit must cover all 24 registered vessels"
    assert {row["vessel_id"] for row in table} == {f"V{i:02d}" for i in range(1, 25)}
    for row in table:
        # the measured z and the declared z must both be on record for every vessel
        assert row["status"] == "OK", f"{row['vessel_id']}: {row['status']}"
        assert row["declared_source"], f"{row['vessel_id']}: no declared-z provenance"
        measured = row["measured_profile_z_rim_mm"]
        if measured is None:
            measured = row["measured_z_extent_mm"]
        assert measured is not None and np.isfinite(measured), row["vessel_id"]
        assert row["watertight"] is True, row["vessel_id"]
        assert isinstance(row["audit_ok"], bool), row["vessel_id"]
        assert isinstance(row["symptoms"], list), row["vessel_id"]
    # the report must pin the code state it was measured against
    hashes = payload["code_state"]["file_hashes"]
    assert "synlab/mothers/vessels/common.py" in hashes
    assert payload["code_state"]["synlab_mothers_worktree_clean"] is True


def test_measured_z_rim_is_recorded_next_to_the_declared_target(neck_mothers):
    """``z_rim`` (measured) and ``z_rim_target_mm`` (declared) must both be recorded.

    The live build is compared against the **post-fix** re-measurement
    (``geom_fix/s15_audit_all.json``).  The pre-fix snapshot is a different geometry by
    construction, so it is checked separately, below.
    """
    postfix = None
    if POSTFIX_JSON.exists():
        payload = json.loads(POSTFIX_JSON.read_text(encoding="utf-8"))
        postfix = payload["vessels"]
    for vessel_id, mother in neck_mothers.items():
        metrics = dict(mother.meta.get("profile_metrics") or {})
        assert "z_rim" in metrics, f"{vessel_id}: measured z_rim is not recorded"
        assert "z_rim_target_mm" in metrics, f"{vessel_id}: declared target is not recorded"
        assert np.isfinite(float(metrics["z_rim"]))
        assert np.isfinite(float(metrics["z_rim_target_mm"]))
        # the same explicit consistency column the builder writes (pure recording)
        assert metrics["z_rim_shortfall_mm"] == pytest.approx(
            float(metrics["z_rim_target_mm"]) - float(metrics["z_rim"]), abs=1e-9)
        if postfix is not None:
            # the live build must agree with the post-fix re-measurement (same seed, params)
            assert float(metrics["z_rim"]) == pytest.approx(
                float(postfix[vessel_id]["profile_z_rim_mm"]), abs=0.05)


def test_prefix_snapshot_still_records_the_prefix_numbers():
    """The pre-fix audit stays an honest historical record (it must not be rewritten)."""
    if not AUDIT_JSON.exists():
        pytest.skip(f"{AUDIT_JSON.relative_to(REPO_ROOT)} is not present in this checkout")
    payload = json.loads(AUDIT_JSON.read_text(encoding="utf-8"))
    reported = {row["vessel_id"]: row for row in payload["symptom_table"]}
    # the A2 family was truncated at the shoulder in that snapshot - the signature of A2
    assert reported["V10"]["measured_profile_z_rim_mm"] == pytest.approx(123.07, abs=0.05)
    assert reported["V16"]["measured_profile_z_rim_mm"] == pytest.approx(119.96, abs=0.05)
    assert payload["defects"]["A2_monotone_drops_neck"]["affected"] == list(NECK_FAMILY)


def test_wall_points_returns_rising_z_and_never_negative_radius():
    """Contract that holds before and after the fix: ordered z, non-negative radii."""
    pts = common_mod.wall_points(r_start_mm=30.0, R_mm=80.0, z_start=5.0, z_rim_mm=90.0,
                                 count=6, exponent=0.8)
    assert len(pts) == 6
    z = [float(p[1]) for p in pts]
    assert z == sorted(z) and len(set(z)) == len(z)
    assert all(float(p[0]) >= 0.0 for p in pts)


def test_mother_build_is_deterministic_for_a_fixed_seed():
    """The audit is reproducible: same seed and params -> same geometry hash."""
    first = create_mother("V10", "M01", default_params("V10"), _rng("V10"), mother_id="det")
    second = create_mother("V10", "M01", default_params("V10"), _rng("V10"), mother_id="det")
    assert first.meta["geometry_hash"] == second.meta["geometry_hash"]
    assert np.isclose(first.mesh.volume, second.mesh.volume, rtol=0, atol=1e-9)


def test_defects_are_documented_with_evidence():
    """The report must carry the three defect records with their measurements."""
    if not AUDIT_JSON.exists():
        pytest.skip(f"{AUDIT_JSON.relative_to(REPO_ROOT)} is not present in this checkout")
    payload = json.loads(AUDIT_JSON.read_text(encoding="utf-8"))
    defects = payload["defects"]
    assert defects["A1_wall_points_collapse"]["affected"] == [
        "V01", "V02", "V03", "V04", "V05", "V06", "V07", "V08", "V09", "V10", "V11", "V12",
        "V15", "V16", "V17"]
    assert defects["A2_monotone_drops_neck"]["affected"] == list(NECK_FAMILY)
    assert defects["A3_stele_bevel_intersection"]["affected"] == ["V22"]
    # the V22 evidence is a measured number, not a claim
    v22 = next(r for r in payload["symptom_table"] if r["vessel_id"] == "V22")
    assert v22["measured_z_extent_mm"] == pytest.approx(6.0, abs=0.01)
    assert v22["declared_z_mm"] == pytest.approx(38.0, abs=0.01)


# ---------------------------------------------------------------------------------------
# correctness assertions: these were ``xfail(strict=True)`` while A1/A2 were open; the fix
# turned all seven into XPASS, so they are real assertions now.
# ---------------------------------------------------------------------------------------
@pytest.mark.parametrize("vessel_id,declared_radius_mm", [("V17", 90.0), ("V01", 95.0)])
def test_wall_widens_to_its_declared_radius(vessel_id, declared_radius_mm):
    """A1 fixed: ``wall_points`` no longer clamps the rising wall to its first sample."""
    mother = create_mother(vessel_id, "M01", default_params(vessel_id), _rng(vessel_id),
                           mother_id=f"{vessel_id}-audit")
    measured = float(mother.meta["profile_metrics"]["r_max"])
    assert measured >= 0.97 * declared_radius_mm


@pytest.mark.parametrize("vessel_id", ["V06", "V07", "V10", "V11", "V16"])
def test_neck_family_body_reaches_its_declared_rim(vessel_id, neck_mothers):
    """A2 fixed: the shoulder/neck control points survive and the body reaches the rim."""
    metrics = dict(neck_mothers[vessel_id].meta["profile_metrics"])
    target = float(metrics["z_rim_target_mm"])
    assert abs(float(metrics["z_rim"]) - target) <= max(1.0, 0.02 * target)
    # the acceptance criterion the audit wrote down for the fix is tighter: +/- 2.5 mm
    assert abs(float(metrics["z_rim"]) - target) <= 2.5


def test_v10_lid_seats_on_the_body_instead_of_floating():
    """A2 fixed: the lid lands on the mouth instead of hanging above a truncated shoulder."""
    mother = create_mother("V10", "M01", default_params("V10"), _rng("V10"), mother_id="gap")
    parts = mother.mesh.split(only_watertight=False)
    spans = sorted((float(p.bounds[0][2]), float(p.bounds[1][2])) for p in parts)
    worst_gap = max((spans[i + 1][0] - spans[i][1] for i in range(len(spans) - 1)), default=0.0)
    assert worst_gap <= 1.0


def test_advancing_filter_enforces_rising_z_and_keeps_repeated_radii():
    """P2 as landed: the filter is named ``advancing_control_points`` and drops on ``z``.

    Two facts at once: (a) the old radius rule is gone - a shoulder that narrows after a wide
    belly survives - and (b) the filter's rule is ``z``, not the arclength parameter the shell
    kernel actually uses.
    """
    assert not hasattr(common_mod, "monotone_radius_control_points")
    shoulder = np.asarray([[0.0, 0.0], [40.0, 10.0], [80.0, 20.0], [60.0, 30.0], [30.0, 40.0]])
    kept = common_mod.advancing_control_points(shoulder)
    assert len(kept) == len(shoulder), "a narrowing shoulder must survive (defect A2)"
    assert np.all(np.diff(np.asarray(kept)[:, 1]) > 0)


@pytest.mark.xfail(strict=True, reason=(
    "P2 side effect (NOT sanctioned by the audit): the z-advance rule also drops the "
    "concave-base outline points of V01/V12/V15/V17, which are listed along the outline "
    "(z goes down before it goes up).  Measured: those four vessels dropped 0 points before "
    "the fix and 3-4 points after, and V01's lowest point moved from z=0.93 mm to z=8.04 mm "
    "- the bowl lost its recessed base.  The shell kernel parameterises the mid-line by "
    "arclength, so only a duplicated (zero-length) segment can degenerate it."))
def test_concave_base_outline_survives_the_advancing_filter():
    outline = np.asarray([[0.0, 8.0], [19.0, 7.9], [39.0, 4.4], [55.4, 3.25], [68.4, 4.9],
                          [80.0, 31.5]])
    kept = common_mod.advancing_control_points(outline)
    assert len(kept) == len(outline)


@pytest.mark.xfail(strict=True, reason=(
    "defect A3 (group_extrude.py V22): the bevel is a boolean intersection with a bevel-thick "
    "plate, so the 38 mm slab is cut down to bevel_mm (measured z extent 6.0 mm)"))
def test_v22_keeps_its_declared_slab_thickness():
    params = default_params("V22")
    mother = create_mother("V22", "M01", params, _rng("V22"), mother_id="slab")
    extent = float(mother.mesh.bounds[1][2] - mother.mesh.bounds[0][2])
    assert extent >= 0.95 * float(params["thickness_mm"])


@pytest.mark.xfail(strict=True, reason=(
    "defect B1 (group_composite.py V23): height_mm is not the realised total height - the "
    "figure starts 0.15*head_h above z=0 and its crown stops 0.05*head_h short"))
def test_figurine_realises_its_declared_total_height():
    params = default_params("V23")
    mother = create_mother("V23", "M01", params, _rng("V23"), mother_id="height")
    extent = float(mother.mesh.bounds[1][2] - mother.mesh.bounds[0][2])
    assert extent >= 0.99 * float(params["height_mm"])


def test_audit_mother_still_passes_for_the_affected_vessels(neck_mothers):
    """Honest scope note: the frozen QA gates do *not* see A1/A2, so they still pass.

    This test pins that fact rather than pretending QA catches the defect: if a future gate
    starts failing these mothers, this test will tell us the QA contract changed.
    """
    for vessel_id, mother in neck_mothers.items():
        report = audit_mother(mother, max_thickness_probes=48, run_self_intersection=False)
        assert report["ok"] is True, f"{vessel_id}: {report.get('failures')}"
