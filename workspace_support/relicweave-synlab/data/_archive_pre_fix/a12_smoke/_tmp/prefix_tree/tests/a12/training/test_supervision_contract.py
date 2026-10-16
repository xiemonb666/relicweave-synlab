"""Supervision contract of the five A12 tasks, pinned on the **real** exported package.

The smoke report answers "did the loss run"; these tests answer the question the report could
not answer before: *why not*, per task.  The contract is

    every task is either supervised on the real batch (``n_allowed > 0``) **or** carries an
    explicit ``structural`` marker naming the measured blocker and the unlock condition

so a task can never be silently zero, and a task whose labels exist but are masked is never
reported as if it had no labels at all (``n_valid_labels > 0`` with ``n_allowed == 0`` is
*blocked*, which is a data fix, not a code fix).

Plan 30.12 semantics are re-measured here as well: ``UNKNOWN`` never enters supervision, an
unconfirmed label never enters supervision, and a slot whose validity mask is False never
carries a value that could be mistaken for a label.
"""

from __future__ import annotations

import numpy as np
import pytest

from _fixtures import REPO_ROOT
from synlab.qc.loader_probe import _batch_rows
from synlab.storage.export import TrainingPackage
from synlab.training.labels import PackageLabelSource
from synlab.training.smoke import run_smoke

PACKAGE = REPO_ROOT / "data" / "a12_exports" / "closed_loop" / "training_package"
TASKS = ("rank", "view", "correspondence", "quality", "contradiction")
pytestmark = pytest.mark.skipif(not (PACKAGE / "export_manifest.json").exists(),
                                reason="real exported training package not present")


@pytest.fixture(scope="module")
def smoke(tmp_path_factory) -> dict:
    out = tmp_path_factory.mktemp("supervision_contract")
    return run_smoke(PACKAGE, steps=1, out_dir=out, include_loader_probe=False)


@pytest.fixture(scope="module")
def package() -> TrainingPackage:
    return TrainingPackage(PACKAGE)


# ------------------------------------------------------------------------------------
# 1. every task: supervised, or structurally marked -- never silently zero
# ------------------------------------------------------------------------------------
def test_every_task_is_supervised_or_structurally_marked(smoke: dict) -> None:
    supervision = smoke["supervision"]
    assert set(supervision["tasks"]) == set(TASKS)
    assert supervision["tasks_without_explanation"] == [], (
        "a task with n_allowed == 0 must carry a measured structural marker and an unlock "
        "condition: " + repr(supervision["tasks_without_explanation"]))
    for name in TASKS:
        task = supervision["tasks"][name]
        if task["n_allowed"] > 0:
            assert task["structural"] is None, name
            continue
        marker = task["structural"]
        assert marker is not None, name
        assert marker["applicable"] is False, name
        assert marker["reason"], name
        assert marker["unlock_condition"], name
        assert marker["evidence"], name


def test_supervision_counts_are_measured_on_the_real_batch(smoke: dict) -> None:
    """The exact before/after numbers of ``docs/a12/training_run.md`` §7."""
    tasks = smoke["supervision"]["tasks"]
    # labels that exist and are valid, before any encodability mask
    assert tasks["view"]["n_valid_labels"] == 12
    assert tasks["rank"]["n_valid_labels"] == 3          # 3 R2 positives, 0 legal negatives
    assert tasks["contradiction"]["n_valid_labels"] == 3
    assert tasks["correspondence"]["n_valid_labels"] > 0  # exported from the truth arrays
    assert tasks["quality"]["n_valid_labels"] == 3        # label-side observability targets
    # rows that survive every mask the loss applies
    assert tasks["view"]["n_allowed"] == 12
    assert tasks["quality"]["n_allowed"] == 3
    assert tasks["rank"]["n_allowed"] == 0
    assert tasks["contradiction"]["n_allowed"] == 0
    assert tasks["correspondence"]["n_allowed"] == 0
    # a blocked task is blocked *with labels present*, not unlabelled
    assert smoke["honesty"]["tasks_blocked_with_labels_present"] == ["contradiction",
                                                                     "correspondence", "rank"]


def test_pair_mask_names_the_conjunct_that_rejected_each_pair(smoke: dict) -> None:
    """``allowed = z_valid[q] & z_valid[c] & pair_valid`` -- decomposed, not a bare zero."""
    pair = smoke["supervision"]["pair_mask"]
    assert pair["pair_valid"] == 3
    assert pair["z_valid_queries"] == 3
    assert pair["z_valid_candidates"] == 0
    assert pair["allowed"] == 0
    assert pair["rejected_by"] == {"pair_valid==False": 0, "z_valid[query]==False": 0,
                                   "z_valid[candidate]==False": 3}
    assert len(pair["unencodable_pairs"]) == 3
    for entry in pair["unencodable_pairs"]:
        assert entry["z_valid_query"] is True
        assert entry["z_valid_candidate"] is False
        assert entry["candidate"].endswith("-p")


# ------------------------------------------------------------------------------------
# 2. the two tasks that really start
# ------------------------------------------------------------------------------------
def test_view_and_quality_are_the_tasks_with_supervision(smoke: dict) -> None:
    assert smoke["supervision"]["tasks_with_supervision"] == ["quality", "view"]
    record = smoke["steps"]["records"][0]
    assert record["tasks"]["view"]["skipped"] is False
    assert record["tasks"]["view"]["n_valid"] == 12
    assert record["tasks"]["view"]["loss"] > 0.0
    assert record["tasks"]["quality"]["skipped"] is False
    assert record["tasks"]["quality"]["n_valid"] == 3
    assert record["tasks"]["quality"]["loss"] is not None
    assert smoke["steps"]["optimizer_steps_taken"] == 1


def test_quality_target_is_label_side_not_a_feature(package: TrainingPackage) -> None:
    """The D-task target is the visible/truth layer's observability, not the OBS_EST input."""
    rows = package.labels("quality")
    assert rows, "the package carries no label-side quality measurement"
    measured = [r for r in rows if r["valid"]]
    assert measured, "no fragment carries a measurable observability target"
    for row in measured:
        assert row["target_channel"] == "observability_visible_rate"
        assert row["source_kind"] == "GT_ORACLE"
        assert row["asset_id"]
        # the value is the real ratio of the two measured counts, never an invented number
        assert row["target_value"] == pytest.approx(row["visible"] / row["samples"])
        # the observability rule is the truth layer's own rule, quoted in the row
        assert row["samples"] > 0
    for row in rows:
        if row["samples"] == 0:
            assert row["valid"] is False
            assert row["reason"]


def test_quality_aggregation_marks_unmeasured_fragments_invalid(package: TrainingPackage
                                                                ) -> None:
    source = PackageLabelSource.from_package(package)
    ids = ["LIN0000_V01_M01_PAT01_E01-m", "LIN0000_V01_M01_PAT01_E01-p",
           "definitely-not-in-this-release"]
    target, valid, report = source.quality_target_for(ids)
    assert target.shape == (3, 1, 1) and valid.shape == (3, 1, 1)
    assert bool(valid[0, 0, 0]) is True
    # a modelled-but-unobserved fragment gets no target; the slot stays invalid, never a label
    assert bool(valid[1, 0, 0]) is False and float(target[1, 0, 0]) == 0.0
    assert bool(valid[2, 0, 0]) is False and float(target[2, 0, 0]) == 0.0
    assert report["missing_is_not_a_zero_label"] is True
    assert report["per_fragment"]["LIN0000_V01_M01_PAT01_E01-p"]["target"] is None
    assert report["per_fragment"]["LIN0000_V01_M01_PAT01_E01-p"]["reason"] == \
        "no_label_side_measurement"
    assert report["n_valid"] == 1


# ------------------------------------------------------------------------------------
# 3. correspondence: labels were exported, the pair cannot be scored
# ------------------------------------------------------------------------------------
def test_correspondence_labels_reach_the_package_but_cannot_be_scored(smoke: dict,
                                                                     package: TrainingPackage
                                                                     ) -> None:
    counts = package.manifest["counts"]
    samples = int(counts["correspondence_samples"])
    assert samples > 0, "the release's corr_* truth arrays were dropped again"
    assert int(counts["correspondence_pairs"]) == 3
    task = smoke["supervision"]["tasks"]["correspondence"]
    assert task["n_valid"] == samples
    assert task["n_allowed"] == 0
    blocked = task["blocked_by"]
    assert any("no_token_evidence" in reason for reason in blocked), blocked
    assert any("token" in reason for reason in blocked), blocked
    assert task["structural"]["unlock_condition"]
    diagnostics = smoke["steps"]["records"][0]["tasks"]["correspondence"]["diagnostics"]
    assert diagnostics["label_samples_in_package"] == samples
    assert diagnostics["pairs_with_both_sides_observable"] == 0
    assert diagnostics["pairs_in_batch_with_labels"] == 3


def test_correspondence_rows_carry_the_real_measured_quantities(package: TrainingPackage) -> None:
    rows = package.labels("correspondence")
    assert rows
    weights = np.asarray([r["weight"] for r in rows], dtype=np.float64)
    assert weights.sum() > 0.0
    assert set(rows[0]) >= {"fragment_a", "fragment_b", "index_a", "index_b", "weight",
                            "sample_valid", "ambiguous", "association_code", "residual_mm",
                            "source_kind", "asset_id"}
    for row in rows[:50]:
        assert row["source_kind"] in ("CLEAN_TRUTH", "PHYSICAL_TRUTH")
        assert row["fragment_a"] != row["fragment_b"]
        assert row["valid"] == row["sample_valid"]
    # only pairs whose relation row is supervised (valid and loss_mask) may be exported
    supervised = {(str(r["query"]), str(r["candidate"])) for r in package.relations()
                  if r["valid"] and r["loss_mask"]}
    exported = {(r["fragment_a"], r["fragment_b"]) for r in rows}
    assert exported <= supervised | {(b, a) for a, b in supervised}


# ------------------------------------------------------------------------------------
# 4. plan 30.12: what must never become supervision
# ------------------------------------------------------------------------------------
def test_plan_30_12_invariants_hold_on_the_real_batch(smoke: dict) -> None:
    evidence = smoke["supervision"]["plan_30_12"]
    for key in ("unknown_rows_inside_supervision", "unconfirmed_rows_inside_supervision",
                "non_r2_relation_inside_pos_mask", "r2_rows_inside_neg_mask",
                "unknown_rows_with_a_contradiction_label",
                "missing_contradiction_rows_marked_valid",
                "invalid_quality_slots_with_a_nonzero_value"):
        assert evidence[key] == 0, (key, evidence[key])
    assert evidence["relation_codes_supervised"] == [2]      # only confirmed R2 positives


def test_loss_mask_false_rows_never_become_negatives(package: TrainingPackage) -> None:
    relations = package.relations()
    assert relations
    for row in relations:
        assert row["eligible_as_negative"] == bool(
            row["kind"] in ("R1", "R0") and row["valid"] and row["loss_mask"]), row
        if row["kind"] == "UNKNOWN":
            # plan 30.12: an UNKNOWN pair is never supervised, therefore never a negative
            assert row["loss_mask"] is False
            assert row["eligible_as_negative"] is False
    fragment_ids = sorted({str(r["query"]) for r in relations}
                          | {str(r["candidate"]) for r in relations})
    rows = _batch_rows(relations, fragment_ids, None)
    for row in rows:
        for candidate in row["negatives"]:
            kind = next(str(r["kind"]) for r in relations
                        if str(r["candidate"]) == candidate and str(r["query"]) == row["query"])
            assert kind in ("R1", "R0")
    # nothing in this package qualifies, which is exactly what rank reports
    assert sum(len(r["negatives"]) for r in rows) == 0


def test_contradiction_labels_are_class_degenerate_and_masked(smoke: dict) -> None:
    """The plan derives compatible/contradicting from the relation kind: honest limits."""
    task = smoke["supervision"]["tasks"]["contradiction"]
    assert task["n_valid"] == 3
    assert task["evidence"]["label_histogram"] == {"1": 3}    # 1 = compatible (R2)
    assert task["evidence"]["classes_present"] == 1
    assert task["n_allowed"] == 0
    diagnostics = smoke["steps"]["records"][0]["tasks"]["contradiction"]["diagnostics"]
    assert diagnostics["n_labels_valid_before_encodability"] == 3
    assert diagnostics["n_labels_after_encodability"] == 0
    assert any("cannot be scored" in c or "observe both" in c
               for c in task["structural"]["unlock_condition"])


def test_rank_reports_a_measured_negative_shortage(smoke: dict) -> None:
    task = smoke["supervision"]["tasks"]["rank"]
    assert task["n_valid_positives"] == 3
    assert task["n_valid_negatives"] == 0
    assert task["n_allowed_positives"] == 0
    assert "no_legal_negative" in task["structural"]["reason"]
    assert task["structural"]["evidence"]["positives_rejected_by"] == \
        {"z_valid[candidate]==False": 3}
    assert any("R1/R0" in c for c in task["structural"]["unlock_condition"])
