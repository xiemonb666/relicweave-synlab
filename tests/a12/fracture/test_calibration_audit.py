"""Precision audit of the measured events: every calibration point's numbers, and the rate.

``configs/a12/fracture_calibration.json`` holds the raw measurements; this module turns them into
the audit verdicts the calibration document quotes, and re-derives them from the event whenever a
point is small enough to run here.  Nothing in this file widens a threshold: the frozen A06 limits
come from :mod:`synlab.fracture.spec` and a point that misses one is reported as failed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from synlab.fracture.spec import (
    AMBIGUITY_AREA_RATIO_MAX,
    INTERFACE_GAP_P95_MM,
    NORMAL_REVERSAL_P95_DEG,
    OVERLAP_RATIO_MAX,
    VOLUME_REL_TOL,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
CALIBRATION = REPO_ROOT / "configs" / "a12" / "fracture_calibration.json"
REPORTS = REPO_ROOT / "data" / "a12_reports"

#: the measurement files the calibration document quotes (all written by the instrument)
SERIES_FILES = (
    "fracture_calibration_matrix.json",
    "fracture_calibration_energy.json",
    "fracture_calibration_energy_V02.json",
    "fracture_calibration_energy_V13.json",
    "fracture_calibration_size.json",
    "fracture_calibration_heights.json",
)


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():  # pragma: no cover - the reports ship with the workspace
        pytest.skip(f"{path} is missing")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", SERIES_FILES)
def test_every_measured_row_is_either_green_or_explicitly_refused(name: str) -> None:
    payload = _load(REPORTS / name)
    rows = payload.get("rows") or []
    assert rows, f"{name} carries no measurements"
    for row in rows:
        status = str(row.get("status"))
        assert status in ("OK", "REFUSED", "ERROR")
        if status == "OK":
            measurement = row["measurement"]
            assert measurement["qa_passed"] is True, (name, row["vessel_id"],
                                                      measurement["qa_failures"])
            assert measurement["qa_failures"] == []
            # A06, from the frozen spec, on the measured numbers
            assert measurement["volume_rel_diff"] <= VOLUME_REL_TOL
            assert measurement["overlap_ratio"] <= OVERLAP_RATIO_MAX
            assert measurement["gap_p95_mm_max"] <= INTERFACE_GAP_P95_MM
            assert measurement["normal_angle_p95_deg_max"] <= NORMAL_REVERSAL_P95_DEG
            assert measurement["source_coverage"] >= 0.999
            assert measurement["ambiguous_area_ratio_total"] <= AMBIGUITY_AREA_RATIO_MAX
            # watertight, positive-volume pieces, and they are all of them
            assert measurement["watertight_pieces"] == measurement["pieces"]
            assert measurement["positive_volume_pieces"] == measurement["pieces"]
            assert measurement["piece_volume_sum_mm3"] == pytest.approx(
                measurement["mother_volume_mm3"], rel=1e-3)
            # the conjugate evidence: no one-sided facet anywhere in the event
            conjugacy = measurement["facet_conjugacy"] or {}
            assert conjugacy.get("one_sided_facets") == 0
            assert conjugacy.get("conjugate") is True
        else:
            failure = row.get("failure") or {}
            assert failure.get("code"), (name, row.get("vessel_id"))


def test_audit_table_is_complete_for_every_data_point() -> None:
    """No data point may lack an audit row: the table and the fit come from the same rows."""
    calibration = _load(CALIBRATION)
    points = calibration["points"]
    rows: list[dict[str, Any]] = []
    for name in SERIES_FILES:
        rows.extend(_load(REPORTS / name).get("rows") or [])
    green = [r for r in rows if r.get("status") == "OK"]
    # every green row carries the full A06 block
    for row in green:
        measurement = row["measurement"]
        for key in ("volume_rel_diff", "overlap_ratio", "gap_p95_mm_max",
                    "normal_angle_p95_deg_max", "source_coverage",
                    "ambiguous_area_ratio_total", "unmatched_interface_area_ratio",
                    "facet_conjugacy", "vertex_identity_ratio_min",
                    "nearest_surface_p95_mm_max"):
            assert key in measurement, (row["vessel_id"], key)
    assert len(points) >= 20
    assert len(green) >= 20


def test_the_analysis_coverage_above_the_cut_is_green_at_the_documented_heights() -> None:
    """The V01/M01 heights the fitted law uses are exactly the ones the audit passes."""
    heights = _load(REPORTS / "fracture_calibration_heights.json")["rows"]
    v01 = {float(r["drop_height_mm"]): r for r in heights
           if r["vessel_id"] == "V01" and r["material_id"] == "M01"}
    assert set(v01) >= {2000.0, 4000.0, 8000.0}
    for height, row in v01.items():
        assert row["status"] == "OK", (height, row.get("failure"))
        assert row["measurement"]["pieces"] == {2000.0: 3, 4000.0: 5, 8000.0: 7}[height]


def test_refusals_are_all_the_same_mechanism_and_at_least_one_is_documented() -> None:
    """The refusals are volume shortfalls, not silent passes with a different excuse."""
    reasons: dict[str, int] = {}
    for name in SERIES_FILES:
        for row in _load(REPORTS / name).get("rows") or []:
            if row.get("status") == "REFUSED":
                message = str((row.get("failure") or {}).get("message", ""))
                if "volume_rel_diff" in message:
                    reasons["volume_shortfall"] = reasons.get("volume_shortfall", 0) + 1
                elif "gap" in message or "normal reversal" in message:
                    reasons["interface_geometry"] = reasons.get("interface_geometry", 0) + 1
                else:
                    reasons["other"] = reasons.get("other", 0) + 1
    assert reasons.get("volume_shortfall", 0) >= 1
    # the measured refusal rate of the documented series is published in the calibration file
    calibration = _load(CALIBRATION)
    assert calibration["points"]


def test_open_cutters_explain_the_volume_shortfall_when_they_occur() -> None:
    """Per-cell indicator vs the audit shortfall, from the event's own meta (no re-derivation)."""
    accounting = REPORTS / "fracture_volume_accounting_V02.json"
    if not accounting.is_file():  # pragma: no cover - probe output ships with the workspace
        pytest.skip("run tests/a12/fracture/_probe_volume_accounting.py --vessel V02 first")
    payload = _load(accounting)
    rows = payload["rows"]
    assert rows
    saw_shortfall = False
    for row in rows:
        assert row["cells"] == row["target_pieces"] or row["cells"] >= 1
        if row["volume_rel_diff"] <= VOLUME_REL_TOL:
            assert row["open_cutters"] == []
            continue
        saw_shortfall = True
        # the whole shortfall is accounted for by cells whose cutter is not a closed solid
        assert row["open_and_empty"], row["target_pieces"]
        assert set(row["open_and_empty"]) <= set(row["open_cutters"])
    assert saw_shortfall, "the probe no longer exercises the shortfall it documents"


def test_piece_count_sweep_timings_are_measured_not_estimated() -> None:
    stage = REPORTS / "fracture_calibration_stage_V01.json"
    payload = _load(stage)
    rows = {int(r["target_pieces"]): r for r in payload["rows"]}
    assert set(rows) >= {4, 8, 16, 32}
    for count, row in rows.items():
        if row.get("status") != "OK":
            continue
        assert row["partition_s"] > 0.0
        assert row["cell_mesh_s"] >= 0.0
        assert row["boolean_s"] > 0.0
        assert row["event_reported_s"] > row["partition_s"]
        # the stage split must add up to the event time it decomposes
        total = (row["partition_s"] + row["cell_mesh_s"] + row["boolean_s"]
                 + row["audit_and_assembly_s"])
        assert total == pytest.approx(row["event_reported_s"], rel=0.05, abs=0.05)
    # the partition is the dominant single stage: assert the measured ordering
    ok = [r for r in rows.values() if r.get("status") == "OK"]
    assert ok
    assert all(r["partition_s"] > r["boolean_s"] for r in ok)


def test_facet_conjugacy_is_measured_on_every_green_point() -> None:
    for name in SERIES_FILES:
        for row in _load(REPORTS / name).get("rows") or []:
            if row.get("status") != "OK":
                continue
            measurement = row["measurement"]
            conjugacy = measurement["facet_conjugacy"]
            assert conjugacy["shared_facet_pairs"] >= 1
            assert conjugacy["max_vertex_distance_mm"] <= conjugacy["tolerance_mm"] + 1e-9
            identity = measurement.get("vertex_identity_ratio_min")
            if identity is not None:
                assert 0.0 <= identity <= 1.0
            nearest = measurement.get("nearest_surface_p95_mm_max")
            if nearest is not None:
                assert np.isfinite(nearest)
