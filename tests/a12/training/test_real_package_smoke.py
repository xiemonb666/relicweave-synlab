"""Real exported training package smoke: real batch, real forward/backward, real checkpoint.

Runs :func:`synlab.training.smoke.run_smoke` against
``data/a12_exports/closed_loop/training_package`` when that package exists in the checkout
(it is generated data and may legitimately be absent).  Every number asserted here comes from
the run that just happened; the assertions pin the *facts* of the package -- including the
facts that make full training impossible today (no legal negative, no encodable positive
pair), which must be reported rather than worked around.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from _fixtures import REPO_ROOT
from synlab.training.smoke import run_smoke

PACKAGE = REPO_ROOT / "data" / "a12_exports" / "closed_loop" / "training_package"
pytestmark = pytest.mark.skipif(not (PACKAGE / "export_manifest.json").exists(),
                                reason="real exported training package not present")


@pytest.fixture(scope="module")
def smoke(tmp_path_factory) -> dict:
    out = tmp_path_factory.mktemp("real_smoke")
    return run_smoke(PACKAGE, steps=2, out_dir=out, include_loader_probe=False)


def test_package_is_read_and_verified_from_real_bytes(smoke: dict) -> None:
    package = smoke["package"]
    assert package["files_verified"] is True
    assert package["files_checked"] == len(
        __import__("json").loads((PACKAGE / "export_manifest.json").read_text(encoding="utf-8"))[
            "files"])
    assert package["relation_rows"] == 3
    assert package["relation_kind_histogram"] == {"R2": 3}
    assert package["queries_with_observation"] == 3
    assert smoke["batch"]["source"]["rows_read"] == 3


def test_batch_composition_is_the_real_exported_one(smoke: dict) -> None:
    batch = smoke["batch"]
    assert batch["n_queries"] == 3 and batch["n_candidates"] == 1
    assert batch["positives"] == 3 and batch["negatives"] == 0
    assert batch["shapes"]["pair_index"] == [3, 1, 2]
    assert batch["shapes"]["neg_mask"] == [3, 1]
    # the -p mate of every R2 pair is modelled but unobserved: it can never be encoded
    source = batch["source"]
    assert source["fragments_without_observation"] == 3
    assert source["fragments_with_observation"] == 3
    assert source["tokens_total"] == 576 and source["points_valid"] == 6049
    assert batch["exposure"]["r2_edges_exposed"] == 3
    assert batch["exposure"]["legal_negatives"] == 0


def test_only_tasks_with_real_supervision_run(smoke: dict) -> None:
    first = smoke["steps"]["records"][0]
    assert first["skipped"] is False
    assert first["tasks"]["view"]["skipped"] is False
    assert first["tasks"]["view"]["n_valid"] == 12            # 3 observed fragments x 4 views
    assert first["tasks"]["view"]["loss"] is not None
    # the package carries the label side of the D task (one observability target per observed
    # fragment), so quality really runs; measured, not asserted from a constant
    assert first["tasks"]["quality"]["skipped"] is False
    assert first["tasks"]["quality"]["n_valid"] == 3
    assert first["tasks"]["quality"]["n_valid_labels"] == 3
    assert first["tasks"]["quality"]["loss"] is not None
    # the three tasks that cannot start name the *measured* blocker, not a catch-all string
    assert first["tasks"]["rank"]["reason"] == "no_legal_negative_in_exported_relations"
    assert first["tasks"]["correspondence"]["reason"] == \
        "correspondence_labels_never_reached_token_space"
    assert first["tasks"]["contradiction"]["reason"] == \
        "no_encodable_contradiction_pair_candidate_side_unobserved"
    assert all(r["loss"] is None or r["loss"] == r["loss"] for r in smoke["steps"]["records"])
    assert smoke["steps"]["optimizer_steps_taken"] == 2


def test_trainer_fit_refuses_a_window_without_effective_queries(smoke: dict) -> None:
    """``fit()`` must refuse, not silently optimise on nothing."""
    refusal = smoke["trainer_fit_refusal"]
    assert refusal["raised"] == "SynLabError"
    assert refusal["error_code"] == "SCHEMA_INVALID"
    assert "no effective query" in refusal["message"]
    assert smoke["supervision_availability"]["queries_eligible_for_rank_loss"] == 0


def test_checkpoint_round_trip_is_numerically_identical(smoke: dict) -> None:
    ck = smoke["checkpoint"]
    assert ck["saved"] is True
    assert ck["model_state_vs_checkpoint"]["ok"] is True
    assert ck["load_is_bitwise_identical"] is True
    assert ck["extra_step_loss_equal"] is True
    assert ck["extra_step_loss_delta"] == 0.0
    assert ck["extra_step_digest_equal"] is True
    assert ck["extra_step_loss_live"] == ck["extra_step_loss_resumed"]
    # a different data release must be refused instead of silently resumed
    assert ck["release_mismatch_refused"]["raised"] == "SynLabError"
    assert ck["release_mismatch_refused"]["error_code"] == "REPLAY_MISMATCH"


def test_report_is_honest_about_what_was_not_trained(smoke: dict) -> None:
    honesty = smoke["honesty"]
    assert honesty["synthesised_negatives"] == 0
    assert honesty["synthesised_labels"] == 0
    assert set(honesty["tasks_skipped"]) == {"rank", "correspondence", "contradiction"}
    # the two tasks that really ran, and the three that are blocked *with labels present*
    assert honesty["tasks_with_real_supervision"] == ["quality", "view"]
    assert honesty["tasks_blocked_with_labels_present"] == ["contradiction", "correspondence",
                                                            "rank"]
    assert smoke["status"] == "PIPELINE_OK_DATA_INSUFFICIENT"
    assert smoke["model"]["parameters"]["total"] == 72710


def test_checkpoint_file_lands_next_to_the_report(smoke: dict) -> None:
    path = Path(smoke["checkpoint"]["path"])
    assert path.exists() and path.stat().st_size == smoke["checkpoint"]["bytes"]
