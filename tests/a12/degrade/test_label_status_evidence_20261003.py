"""Evidence-backed label status for degradation outputs (2026-10-03)."""

from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest
import trimesh

from synlab.degrade.api import (_apply_impl, _label_dependency_status, _label_status,
                                _rows_from_axis_report, apply_axis, operator_audit_table)
from synlab.degrade.registry import get_operator
from synlab.degrade.sources import KIND_IMAGE, KIND_PHYSICAL, SourceBundle
from synlab.schemas.runtime import CleanTruth


def _image_source(*, claimed_status: str = "") -> SourceBundle:
    # Constant linear input makes the sensor perturbation measurable with a 32 x 32 fixture.
    linear = np.full((32, 32, 3), 0.37, dtype=np.float32)
    frame = {"view_id": "fixture-view", "rgb_linear": linear,
             "encoding": "LINEAR", "K": np.eye(3, dtype=np.float64)}
    meta = {"master_seed": 41}
    if claimed_status:
        meta["label_status"] = claimed_status
    return SourceBundle(source_kind=KIND_IMAGE, payload={"frames": [frame]}, meta=meta)


def _physical_source() -> SourceBundle:
    mesh = trimesh.creation.box(extents=[20.0, 20.0, 10.0])
    coords = np.linspace(-8.0, 8.0, 8)
    positions = np.asarray([[x, y, 5.0] for x in coords for y in coords], dtype=np.float64)
    count = len(positions)
    appearance = {
        "texel_albedo": np.tile(np.asarray([[0.55, 0.45, 0.35]], dtype=np.float32),
                                (count, 1)),
        "texel_substrate_albedo": np.tile(
            np.asarray([[0.30, 0.25, 0.20]], dtype=np.float32), (count, 1)),
        "texel_layer": np.zeros(count, dtype=np.int32),
        "texel_area_mm2": np.ones(count, dtype=np.float64),
        "texel_positions": positions,
        "texel_roughness": np.full(count, 0.5, dtype=np.float32),
        "pattern_region": np.zeros(count, dtype=bool),
        "interface_region": np.zeros(count, dtype=bool),
    }
    clean_truth = CleanTruth(
        mother_id="fixture-mother", event_id="fixture-event", version=1,
        relations={}, interfaces=[], correspondence=[], event_tree={}, qa={"pass": True},
        meta={"truth_hash": "fixture-clean-truth-v1", "fragment_ids": ["fixture-fragment"]},
    )
    fragment = SimpleNamespace(mesh=mesh, fragment_id="fixture-fragment",
                               meta={"appearance": appearance})
    return SourceBundle(
        source_kind=KIND_PHYSICAL,
        payload={"mesh": mesh, "appearance": appearance, "fragment": fragment,
                 "clean_truth": clean_truth},
        meta={"fragment_id": "fixture-fragment", "master_seed": 41},
        unit="mm", frame="F_mm",
    )


def test_i03_nonzero_effect_does_not_accept_reported_recomputed() -> None:
    source = _image_source(claimed_status="RECOMPUTED")
    output, measurement = apply_axis("I03", 1, source, None, commit=False)

    before = source.get("frames")[0]["rgb_linear"]
    after = output.payload["frames"][0]["rgb_linear"]
    assert before.shape[:2] == (32, 32)
    assert np.count_nonzero(after != before) > 0
    assert measurement.realized is True
    assert measurement.extra["label_status"] == "PENDING_RECOMPUTE"
    assert measurement.extra["label_dependency_status"] == {
        "VisibleLabels": {
            "status": "PENDING_RECOMPUTE",
            "reason": "no matching recomputation artifact or receipt is recorded",
        },
        "FeatureAdapter": {
            "status": "PENDING_RECOMPUTE",
            "reason": "no matching recomputation artifact or receipt is recorded",
        },
    }
    assert measurement.extra["label_receipt_refs"] == {}

    report = {
        "axis_id": "I03", "label_invalidations": ["VisibleLabels", "FeatureAdapter"],
        "levels": {"1": {
            "level": 1, "label_status": measurement.extra["label_status"],
            "label_dependency_status": measurement.extra["label_dependency_status"],
            "label_receipt_refs": measurement.extra["label_receipt_refs"],
        }},
    }
    rows = _rows_from_axis_report(report)
    assert rows[0]["label_dependency_status"] == measurement.extra["label_dependency_status"]
    assert rows[0]["label_receipt_refs"] == {}
    pytest.importorskip("pyarrow")
    table = operator_audit_table(rows)
    assert json.loads(table.column("label_dependency_status")[0].as_py()) == \
        measurement.extra["label_dependency_status"]
    assert json.loads(table.column("label_receipt_refs")[0].as_py()) == {}


def test_level_zero_keeps_identity_label_status_and_no_dependency_is_explicit() -> None:
    output, measurement = apply_axis("I03", 0, _image_source(), None, commit=False)
    assert output.identity is True
    assert measurement.extra["label_status"] == "NOT_INVALIDATED_AT_LEVEL0"
    assert set(measurement.extra["label_dependency_status"]) == {"VisibleLabels", "FeatureAdapter"}
    assert all(row["status"] == "NOT_INVALIDATED_AT_LEVEL0"
               for row in measurement.extra["label_dependency_status"].values())

    no_dependency = SimpleNamespace(AXIS_ID="T00", LABEL_INVALIDATIONS=())
    bundle = _image_source()
    assert _label_status(no_dependency, bundle, bundle) == "NO_LABEL_DEPENDENCY"


def test_actual_physical_truth_update_is_retained_but_overall_status_stays_pending() -> None:
    source = _physical_source()
    result, _record, measurement = _apply_impl("P06", 1, source, None, commit=False)

    physical = result.get("physical_result")
    assert physical.meta["physical_truth_status"] == "UPDATED"
    assert physical.physical_truth is not None
    dependencies = measurement.extra["label_dependency_status"]
    assert dependencies["PhysicalTruth"]["status"] == "UPDATED"
    assert dependencies["PhysicalTruth"]["clean_truth_ref"] == "fixture-clean-truth-v1"
    assert dependencies["PhysicalTruth"]["physical_truth_version"] == 2
    assert dependencies["PhysicalTruth"]["axis_id"] == "P06"
    assert dependencies["PhysicalTruth"]["level"] == 1
    assert dependencies["PhysicalTruth"]["source_geometry_hash"]
    assert dependencies["PhysicalTruth"]["result_geometry_hash"]
    assert dependencies["PhysicalTruth"]["artifact_path"] == \
        "payload.physical_result.physical_truth"
    assert measurement.extra["label_receipt_refs"]["PhysicalTruth"].startswith(
        "PhysicalResult.physical_truth:P06:")
    assert dependencies["VisibleLabels"]["status"] == "PENDING_RECOMPUTE"
    assert dependencies["FeatureAdapter"]["status"] == "PENDING_RECOMPUTE"
    assert measurement.extra["label_status"] == "PENDING_RECOMPUTE"


@pytest.mark.parametrize("tamper", ["clean_ref", "version", "result_geometry"])
def test_mismatched_physical_truth_receipt_is_rejected(tamper: str) -> None:
    source = _physical_source()
    result, _record, _measurement = _apply_impl("P06", 1, source, None, commit=False)
    physical = result.get("physical_result")

    if tamper == "clean_ref":
        bad_truth = replace(physical.physical_truth, clean_truth_ref="unrelated-clean-truth")
        bad_physical = replace(physical, physical_truth=bad_truth)
        bad_meta = dict(result.meta)
    elif tamper == "version":
        bad_truth = replace(physical.physical_truth, version=physical.physical_truth.version + 1)
        bad_physical = replace(physical, physical_truth=bad_truth)
        bad_meta = dict(result.meta)
    else:
        bad_physical = physical
        bad_meta = {**dict(result.meta), "extra": {
            **dict(result.meta["extra"]), "result_geometry_hash": "sha256:stale"}}

    bad_payload = {**result.payload, "physical_result": bad_physical}
    bad_result = replace(result, payload=bad_payload, meta=bad_meta)
    evidence = _label_dependency_status(get_operator("P06"), source, bad_result)

    assert evidence["PhysicalTruth"]["status"] == "PENDING_RECOMPUTE"
    assert "PhysicalTruth" in evidence["PhysicalTruth"]["reason"]
    assert _label_status(get_operator("P06"), source, bad_result,
                         dependency_status=evidence) == "PENDING_RECOMPUTE"


def test_missing_artifact_cannot_be_replaced_by_recomputed_status_string() -> None:
    operator = SimpleNamespace(AXIS_ID="P01", LABEL_INVALIDATIONS=("PhysicalTruth",))
    source = SourceBundle(source_kind=KIND_PHYSICAL, payload={"clean_truth": SimpleNamespace(
        mother_id="M", event_id="E", version=1, meta={"truth_hash": "clean-hash"})})
    result = SourceBundle(source_kind=KIND_PHYSICAL, payload={},
                          meta={"axis_id": "P01", "level": 1,
                                "label_status": "RECOMPUTED"})

    evidence = _label_dependency_status(operator, source, result)
    assert evidence["PhysicalTruth"]["status"] == "PENDING_RECOMPUTE"
    assert _label_status(operator, source, result, dependency_status=evidence) == \
        "PENDING_RECOMPUTE"


def test_reported_physical_recompute_failure_stays_failed() -> None:
    operator = SimpleNamespace(AXIS_ID="P01", LABEL_INVALIDATIONS=("PhysicalTruth",))
    source = SourceBundle(source_kind=KIND_PHYSICAL, payload={})
    physical_result = SimpleNamespace(meta={"physical_truth_status": "FAILED"})
    result = SourceBundle(source_kind=KIND_PHYSICAL,
                          payload={"physical_result": physical_result}, meta={"axis_id": "P01"})

    evidence = _label_dependency_status(operator, source, result)
    assert evidence["PhysicalTruth"]["status"] == "FAILED"
    assert _label_status(operator, source, result, dependency_status=evidence) == "FAILED"
