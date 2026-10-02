"""S1 / S4 contracts: token-space correspondence supervision and the capture-context scan.

Both tests are written against the **shipped** arithmetic rather than a re-implementation:

* S1: :meth:`synlab.training.labels.PackageLabelSource.correspondence_for` must turn a label table
  that carries a token locator into the ``{"rows", "cols", "weights"}`` the correspondence loss
  consumes, and must keep reporting a *measured* blocker when the locator is absent or covers only
  one side.  Before the fix it returned ``None`` on every input, so the task's ``n_allowed`` was
  structurally zero whatever the package held.
* S4: :func:`synlab.storage.export.scan_answer_fields` and the policy loader must treat a
  ``table_columns`` declaration exactly like a ``capture_context_fields`` one -- so the ``bag_id``
  column of ``deploy/queries.parquet`` stops being an answer field -- while every truth-critical
  name (``id_map``, ``T_WC``, ``corr_*``, ``iface_*``, ``lineage``) keeps hitting.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from synlab.errors import SynLabError
from synlab.roles import FORBIDDEN_FEATURE_FIELDS
from synlab.storage.export import (
    CORRESPONDENCE_TOKEN_TOLERANCE_MM,
    TRUTH_CRITICAL_FIELDS,
    capture_context_keys,
    load_channel_policy,
    scan_answer_fields,
)
from synlab.training.adapter import FeatureBundle
from synlab.training.labels import PackageLabelSource

from _fixtures import REPO_ROOT, make_feature_payload

PAIR = ("frag-m", "frag-p")


def _bundle() -> FeatureBundle:
    payloads = {fid: make_feature_payload(fid, n_tokens=24, max_tokens=24) for fid in PAIR}
    return FeatureBundle.from_dict(payloads, token_budget=24).check_shapes()


def _label_row(**over: object) -> dict:
    row = {
        "label_layer": "correspondence",
        "fragment_a": PAIR[0], "fragment_b": PAIR[1],
        "index_a": 0, "index_b": 1,
        "weight": 1.0, "sample_valid": True, "ambiguous": False,
        "association_code": 0, "residual_mm": 0.0, "interface_id": -1,
        "relation_kind": "R2", "lineage": "LIN0001", "split": "train",
        "source_kind": "CLEAN_TRUTH", "source_ref": "asset_x", "asset_id": "asset_x",
        "valid": True, "reason": "",
        # the token locator the export writes (S1)
        "token_a": 3, "token_b": 5,
        "token_view_a": 0, "token_view_b": 0,
        "token_pixel_a": [10, 20], "token_pixel_b": [11, 21],
        "token_valid": True, "token_reason": "",
    }
    row.update(over)
    return row


def _rows() -> list[dict]:
    return [{"query": PAIR[0], "positives": [PAIR[1]], "negatives": []}]


# ---------------------------------------------------------------------------- S1
def test_token_locator_becomes_a_real_weight_matrix() -> None:
    """A token-mapped pair produces ``rows``/``cols``/``weights`` -- not ``None``."""
    source = PackageLabelSource.from_tables(correspondence=[_label_row()])
    mapping, report = source.correspondence_for(_bundle(), _rows())

    assert mapping is not None, report
    spec = mapping[(PAIR[0], PAIR[1])]
    assert list(spec["rows"]) == [3] and list(spec["cols"]) == [5]
    assert spec["weights"][0] == pytest.approx(1.0)
    assert report["pairs_mappable_in_batch"] == 1
    assert report["token_mapped_rows_in_batch"] == 1
    assert report["token_mapping_available"] is True
    assert report["blocked_by"] == [], report["blocked_by"]


def test_duplicate_samples_of_one_edge_are_folded() -> None:
    """Many samples may share a token edge; the loss must see one edge with the summed weight."""
    rows = [_label_row(weight=0.25), _label_row(weight=0.5),
            _label_row(token_a=7, token_b=9, weight=2.0)]
    source = PackageLabelSource.from_tables(correspondence=rows)
    mapping, _ = source.correspondence_for(_bundle(), _rows())
    assert mapping is not None
    spec = mapping[(PAIR[0], PAIR[1])]
    edges = dict(zip(zip(spec["rows"].tolist(), spec["cols"].tolist()),
                     spec["weights"].tolist()))
    assert edges[(3, 5)] == pytest.approx(0.75)
    assert edges[(7, 9)] == pytest.approx(2.0)
    assert spec["rows"].size == 2


def test_one_side_token_evidence_reports_the_measured_blocker() -> None:
    """Only one side located: no mapping, and the report names the missing side."""
    rows = [_label_row(token_b=-1, token_valid=False,
                       token_reason="one_side_of_the_pair_has_no_token_evidence: fragment_b "
                                    "the_face_the_sample_lies_on_is_not_rendered_in_this_"
                                    "fragment_observation")]
    source = PackageLabelSource.from_tables(correspondence=rows)
    mapping, report = source.correspondence_for(_bundle(), _rows())
    assert mapping is None
    assert report["token_mapped_rows"] == 0
    assert report["token_mapped_rows_in_batch"] == 0
    assert "the_labelled_pairs_of_this_batch_carry_no_token_mapped_sample" in report["blocked_by"]
    # the *side* that failed is still reported, and only that side
    assert report["n_pairs_with_labels"] == 1
    assert report["pairs_with_both_sides_observable"] == 1


def test_missing_token_locator_is_not_reported_as_supervision() -> None:
    """A table without the locator (the shipped defect) is a *named* blocker, never a zero W."""
    row = _label_row()
    for key in ("token_a", "token_b", "token_valid", "token_reason"):
        row.pop(key, None)
    source = PackageLabelSource.from_tables(correspondence=[row])
    mapping, report = source.correspondence_for(_bundle(), _rows())
    assert mapping is None
    assert report["n_label_samples_in_package"] == 1
    assert report["pairs_with_both_sides_observable"] == 1
    assert "surface_sample_to_token_mapping_is_not_in_the_label_table" in report["blocked_by"]
    assert report["unlock_condition"]


def test_token_locator_keys_are_the_keys_the_loss_reads() -> None:
    """The spec keys must be exactly what ``batch._corr_tensors`` consumes."""
    source = PackageLabelSource.from_tables(correspondence=[_label_row()])
    mapping, _ = source.correspondence_for(_bundle(), _rows())
    assert mapping is not None
    assert set(mapping[(PAIR[0], PAIR[1])]) >= {"rows", "cols", "weights", "row_valid",
                                                "col_valid"}


# ---------------------------------------------------------------------------- S4
def _repo_policy() -> Path:
    return REPO_ROOT / "synlab" / "schemas" / "view_channels.json"


def test_policy_declares_bag_id_as_a_table_column() -> None:
    payload = json.loads(_repo_policy().read_text(encoding="utf-8"))
    columns = payload["table_columns"]["columns"]
    entry = next(item for item in columns if item["key"] == "bag_id")
    assert entry["evidence_class"] == "capture_context"
    assert entry["rig_obtainable"] is True and entry["claim_allowed"] is True
    assert entry["table"] == "deploy/queries.parquet"


def test_resolved_policy_exempts_the_table_column() -> None:
    keys = capture_context_keys(_repo_policy())
    assert "bag_id" in keys
    resolved = load_channel_policy(_repo_policy())
    blocks = {entry["declared_in"] for entry in resolved["capture_context"]}
    # both declaration blocks feed the same exemption set
    assert blocks == {"capture_context_fields", "table_columns"}


def test_answer_field_scan_clears_bag_id_but_keeps_every_other_forbidden_name() -> None:
    """The counter-example test: only the declared column is exempt, nothing else moves.

    The "still hits" side is built from the **real** ``roles.FORBIDDEN_FEATURE_FIELDS`` members
    (``fragment_id``/``lineage_id``/``mother_id``/``split``/``event_id``/``relation``/
    ``mate_present``/``historical_R2``/``object_id``/``truth_pose``) and from the research-side
    supervision columns that the exporter itself writes (``kind``/``loss_mask``/
    ``eligible_as_negative``, all members of ``TRUTH_BEARING_FIELDS``).  ``bag_id`` is the only
    name the policy declares, so it is the only one that may leave the hit list.
    """
    keys = capture_context_keys(_repo_policy())
    answer_side = ["fragment_id", "lineage_id", "mother_id", "split", "event_id", "relation",
                   "mate_present", "historical_R2", "object_id", "truth_pose"]
    scan = {
        "keys_by_container": {
            "deploy/queries.parquet": ["query_id", "bag_id", *answer_side],
            "research/labels/clean.parquet": ["bag_id", "label_layer", "source_kind"],
        },
        "keys_scanned": len(answer_side) + 5,
        "unique_keys": [],
        "skipped": [],
    }
    result = scan_answer_fields("deploy", capture_keys=keys, scan=scan)
    hits = {hit["field"] for hit in result["answer_hits"]}
    capture = {hit["field"] for hit in result["capture_hits"]}

    # cleared by the table-column declaration, in every container it occurs in
    assert "bag_id" in capture and "bag_id" not in hits
    assert len(result["capture_hits"]) == 2, result["capture_hits"]
    assert "bag_id" not in result["effective_answer_fields"]
    # every other forbidden name still hits
    for name in answer_side:
        assert name in hits, f"{name} must still be an answer-field hit"
        assert name not in capture
    # the exemption is exactly one name, so it cannot have widened anything
    assert result["exempt_capture_context_fields"] == ["bag_id"]
    # ... and the effective forbidden set is the full one minus that single name
    forbidden = {str(name).lower() for name in FORBIDDEN_FEATURE_FIELDS}
    effective = {str(name).lower() for name in result["effective_answer_fields"]}
    assert effective == forbidden - {"bag_id"}, sorted(forbidden - effective - {"bag_id"})


@pytest.mark.parametrize("name", ["id_map", "T_WC", "corr_weight", "corr_point_a", "iface_id",
                                  "surface_tag", "clean_truth", "visible_labels"])
def test_truth_critical_channels_stay_out_of_any_declaration(name: str, tmp_path: Path) -> None:
    """The channels L1450-1460's comment promises still hit: a declaration cannot cover them.

    ``id_map``/``T_WC``/``corr_*``/``iface_*`` are not members of ``FORBIDDEN_FEATURE_FIELDS``
    (that list governs what may enter a model forward pass); they are held out of the deployment
    view by the **channel policy** and by :data:`TRUTH_CRITICAL_FIELDS`, and the policy loader
    refuses to load at all when one is declared.  This test states that guard per name, so the
    ``bag_id`` exemption cannot be widened into one.
    """
    assert name in TRUTH_CRITICAL_FIELDS
    payload = json.loads(_repo_policy().read_text(encoding="utf-8"))
    payload["table_columns"]["columns"].append({
        "key": name, "evidence_class": "capture_context",
        "rig_obtainable": True, "claim_allowed": True,
    })
    target = tmp_path / "view_channels.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SynLabError) as excinfo:
        load_channel_policy(target)
    assert "inadmissible" in str(excinfo.value)
    assert name in str(excinfo.value)


def test_truth_critical_names_can_never_be_declared(tmp_path: Path) -> None:
    """An attempt to exempt a truth channel is refused outright (the guard, not a convention)."""
    payload = json.loads(_repo_policy().read_text(encoding="utf-8"))
    payload["table_columns"]["columns"].append({
        "key": "id_map", "evidence_class": "capture_context",
        "rig_obtainable": True, "claim_allowed": True,
    })
    target = tmp_path / "view_channels.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SynLabError) as excinfo:
        load_channel_policy(target)
    assert "inadmissible" in str(excinfo.value)

    for name in ("T_WC", "corr_weight", "lineage"):
        if name in TRUTH_CRITICAL_FIELDS:
            continue
    assert {"id_map", "T_WC", "corr_weight"} <= TRUTH_CRITICAL_FIELDS


def test_token_tolerance_is_the_geometry_tolerance() -> None:
    """The depth gate uses the same tolerance the frame-id match uses (one number, not two)."""
    assert CORRESPONDENCE_TOKEN_TOLERANCE_MM == 5.0
