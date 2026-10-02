"""N9: the versioned QA policy that turns a recorded drift check into a failure code.

``synlab/physical/api.py::audit_physical`` records ``checks["roi_external_drift"] = {"max_mm":
..., "pass": bool(drift <= 1e-3)}`` and never appends a failure code, so a body whose extracted
geometry drifted **0.354 mm** outside the ROI shipped as ``status = PASS`` with
``failure_codes = []`` (``docs/a12/smallfixes_report.md`` §S11).  ``synlab/physical/**`` is
outside this task's write scope, so the tightening lives in ``synlab.qc.qa_policy`` as an explicit
versioned policy: it reads the recorded verdict and only ever **adds** failure codes.

These tests pin the policy's arithmetic and its two invariants -- it can flip a PASS to FAIL, and
it can never turn a FAIL into a PASS or drop a code (engineering policy R5: tighten, never relax).
"""

from __future__ import annotations

import json

import pytest

from _fixtures import REPO_ROOT
from synlab.qc.qa_policy import (
    DRIFT_FAILURE_CODE,
    QA_POLICY_HISTORY,
    QA_POLICY_VERSION,
    apply_qa_policy,
    audit_verdict,
    drift_reading,
    qa_policy_version,
    tighten_audits,
)

GLOBAL_AUDIT = REPO_ROOT / "data" / "a12_reports" / "s11_p03_drift.json"
NARROWBAND_AUDIT = REPO_ROOT / "data" / "a12_reports" / "s11_p03_narrowband_routed.json"


def _audit(drift: float, *, passed: bool | None = None, status: str = "PASS",
           codes: list[str] | None = None) -> dict:
    check: dict = {"max_mm": float(drift), "threshold_mm": 1e-3}
    if passed is not None:
        check["pass"] = bool(passed)
    return {"status": status, "axis_id": "P03", "level": 1, "failure_codes": list(codes or []),
            "checks": {"roi_external_drift": check, "damaged_subset_clean": {"pass": True}}}


def test_the_policy_is_versioned_with_a_recorded_change_and_reason() -> None:
    assert QA_POLICY_VERSION == "a12.qa.v2"
    versions = [str(item["version"]) for item in QA_POLICY_HISTORY]
    assert versions == ["a12.qa.v1", "a12.qa.v2"]
    current = next(item for item in QA_POLICY_HISTORY if item["status"] == "current")
    assert current["version"] == QA_POLICY_VERSION
    assert DRIFT_FAILURE_CODE in current["change"]
    assert current["reason"]
    assert "R5" in str(current.get("policy", ""))


def test_a_failed_drift_check_becomes_a_failure_code() -> None:
    before = _audit(0.35424330830574036, passed=False)
    after = apply_qa_policy(before)
    assert before["failure_codes"] == []                    # the input is never mutated
    assert after["status"] == "FAIL"
    assert after["failure_codes"] == [DRIFT_FAILURE_CODE]
    assert after["qa_policy"]["version"] == QA_POLICY_VERSION
    assert after["qa_policy"]["previous_version"] == "a12.qa.v1"
    applied = after["qa_policy"]["applied"]
    assert len(applied) == 1 and applied[0]["measured_mm"] == 0.35424330830574036


def test_a_passing_drift_check_is_left_alone() -> None:
    before = _audit(0.00034815253457054496, passed=True)
    after = apply_qa_policy(before)
    assert after["status"] == "PASS"
    assert after["failure_codes"] == []
    assert after["qa_policy"]["applied"] == []


def test_the_producer_rule_is_used_when_it_recorded_no_verdict() -> None:
    """No recorded ``pass`` flag: the policy re-derives it with the producer's own rule."""
    assert drift_reading(_audit(0.5))["pass"] is False
    assert apply_qa_policy(_audit(0.5))["status"] == "FAIL"
    assert apply_qa_policy(_audit(0.0005))["status"] == "PASS"


def test_the_policy_only_ever_adds_failure_codes() -> None:
    audit = _audit(0.3, passed=False, status="FAIL", codes=["NOT_WATERTIGHT"])
    after = apply_qa_policy(audit)
    assert after["failure_codes"] == ["NOT_WATERTIGHT", DRIFT_FAILURE_CODE]
    assert after["status"] == "FAIL"


def test_the_policy_never_upgrades_a_fail() -> None:
    audit = _audit(0.0, passed=True, status="FAIL", codes=["NOT_WATERTIGHT"])
    after = apply_qa_policy(audit)
    assert after["status"] == "FAIL"
    assert after["failure_codes"] == ["NOT_WATERTIGHT"]


def test_the_policy_is_idempotent() -> None:
    once = apply_qa_policy(_audit(0.3, passed=False))
    twice = apply_qa_policy(once)
    assert twice["failure_codes"] == once["failure_codes"]
    assert twice["status"] == once["status"]
    assert twice["qa_policy"]["applied"] == []              # nothing left to add
    assert twice["qa_policy"]["previous_version"] == QA_POLICY_VERSION


def test_an_audit_without_the_policy_block_is_labelled_v1() -> None:
    """That is how the already-produced artifacts are recognised -- they are never rewritten."""
    assert qa_policy_version(_audit(0.354, passed=False)) == "a12.qa.v1"
    assert qa_policy_version(apply_qa_policy(_audit(0.354, passed=False))) == QA_POLICY_VERSION


def test_the_verdict_record_carries_the_flip_and_the_numbers() -> None:
    verdict = audit_verdict(_audit(0.354, passed=False))
    assert verdict["flips"] is True
    assert verdict["status_before"] == "PASS" and verdict["status_after"] == "FAIL"
    assert verdict["added_failure_codes"] == [DRIFT_FAILURE_CODE]
    assert verdict["drift_mm"] == 0.354 and verdict["drift_pass"] is False
    assert verdict["identity"]["axis_id"] == "P03"
    assert audit_verdict(_audit(0.0003, passed=True))["flips"] is False


def test_tighten_audits_applies_the_policy_to_a_stream() -> None:
    audits = [_audit(0.354, passed=False), _audit(0.0003, passed=True)]
    tightened = tighten_audits(audits)
    assert [item["status"] for item in tightened] == ["FAIL", "PASS"]
    assert [item["failure_codes"] for item in audits] == [[], []]      # inputs untouched


@pytest.mark.skipif(not GLOBAL_AUDIT.exists(), reason="recorded P03 audit not present")
def test_the_recorded_global_sdf_audit_flips_and_the_narrowband_one_does_not() -> None:
    """The real evidence pair, measured, not asserted from memory."""
    payload = json.loads(GLOBAL_AUDIT.read_text(encoding="utf-8"))
    audit = payload["full"]["audit"]
    verdict = audit_verdict(audit)
    assert verdict["drift_mm"] == pytest.approx(0.35424330830574036, abs=1e-12)
    assert verdict["status_before"] == "PASS" and verdict["status_after"] == "FAIL"
    assert verdict["added_failure_codes"] == [DRIFT_FAILURE_CODE]
    assert apply_qa_policy(audit)["failure_codes"] == [DRIFT_FAILURE_CODE]
    if NARROWBAND_AUDIT.exists():
        narrow = json.loads(NARROWBAND_AUDIT.read_text(encoding="utf-8"))["full"]["audit"]
        verdict_narrow = audit_verdict(narrow)
        assert verdict_narrow["status_before"] == "PASS"
        assert verdict_narrow["status_after"] == "PASS"
        assert verdict_narrow["added_failure_codes"] == []
