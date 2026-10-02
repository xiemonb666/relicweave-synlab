"""The ``bag_id`` capture-context ruling: positive, negative and regression controls.

Lead ruling (2026-10-02): ``bag_id`` is **acquisition context**, so it may enter the deployment
view and a capability claim may use it, but it must be declared with
``evidence_class="capture_context"``, ``rig_obtainable=true`` and ``claim_allowed=true``, and it
must be separated from the *answer field* semantics of ``roles.FORBIDDEN_FEATURE_FIELDS``.

These tests pin the separation from both sides:

* the declaration exists and carries the three required properties;
* the deployment-view answer-field scan no longer records ``bag_id`` as a hit, while every other
  forbidden name still does (the exemption is not a general loosening);
* the policy loader **refuses** a capture-context declaration that names a truth layer, a
  truth-critical array, a research-only channel or a supervision column -- so the exemption can
  never be widened into the truth-leak check;
* ``bag_id`` is still forbidden inside a ``feature_bundle`` (the model-forward-pass rule is
  untouched).

Everything is measured through the shipped code (``load_channel_policy`` / ``scan_answer_fields`` /
``truth_bearing_files``), never through a copy of its arithmetic.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab.errors import SynLabError  # noqa: E402
from synlab.roles import FORBIDDEN_FEATURE_FIELDS  # noqa: E402
from synlab.storage.export import (  # noqa: E402
    CAPTURE_CONTEXT_CLASS,
    TRUTH_CRITICAL_FIELDS,
    capture_context_keys,
    load_channel_policy,
    scan_answer_fields,
    truth_bearing_files,
)

POLICY = REPO_ROOT / "synlab" / "schemas" / "view_channels.json"


# ---------------------------------------------------------------------------------------
# the declaration itself
# ---------------------------------------------------------------------------------------
def test_bag_id_is_declared_capture_context_with_the_three_required_properties() -> None:
    policy = load_channel_policy()
    entries = {str(entry["key"]): entry for entry in policy["capture_context"]}
    assert "bag_id" in entries, sorted(entries)
    entry = entries["bag_id"]
    assert entry["evidence_class"] == CAPTURE_CONTEXT_CLASS
    assert entry["rig_obtainable"] is True
    assert entry["claim_allowed"] is True
    assert entry["deploy_view"] is True
    assert policy["capture_context_keys"] == ["bag_id"]
    assert policy["hash"].startswith("sha256:"), policy["hash"]
    assert policy["path"] == str(POLICY)


def test_bag_id_stays_forbidden_inside_a_feature_bundle() -> None:
    """The ruling is about the deployment view, not about the model forward pass."""
    assert "bag_id" in FORBIDDEN_FEATURE_FIELDS
    from synlab.observe.features import FORBIDDEN_UNION

    assert "bag_id" in FORBIDDEN_UNION


# ---------------------------------------------------------------------------------------
# the scan: bag_id is no longer an answer-field hit, everything else still is
# ---------------------------------------------------------------------------------------
def test_answer_scan_exempts_only_the_declared_capture_context_name(tmp_path: Path) -> None:
    deploy = tmp_path / "deploy"
    deploy.mkdir(parents=True)
    (deploy / "queries.json").write_text(json.dumps({
        "rows": {"q::a": {"bag_id": "BAG-1", "context_id": "c", "batch_id": "b",
                          "lineage_id": "LIN0", "split": "train", "fragment_id": "f",
                          "variant": "v", "axis_id": "P03", "level": 2}},
    }, ensure_ascii=False), encoding="utf-8")
    report = scan_answer_fields(deploy, capture_keys=capture_context_keys())
    assert sorted(hit["field"] for hit in report["capture_hits"]) == ["bag_id"]
    assert sorted(hit["field"] for hit in report["answer_hits"]) == [
        "axis_id", "fragment_id", "level", "lineage_id", "split", "variant"]
    assert "bag_id" not in report["effective_answer_fields"]
    assert report["exempt_capture_context_fields"] == ["bag_id"]
    # the full declared list is still reported unchanged, so the exemption is auditable
    assert report["forbidden_fields"] == sorted(FORBIDDEN_FEATURE_FIELDS)


def test_the_answer_scan_still_reports_a_truth_critical_style_field(tmp_path: Path) -> None:
    """Counter-example: an undefined-but-forbidden name inside deploy/ is still a hit."""
    deploy = tmp_path / "deploy"
    deploy.mkdir(parents=True)
    (deploy / "obs.json").write_text(json.dumps({
        "rows": {"x": {"split": "confirm", "mother_id": "LIN1", "bag_id": "BAG-9"}},
    }, ensure_ascii=False), encoding="utf-8")
    report = scan_answer_fields(deploy, capture_keys=capture_context_keys())
    hits = sorted(hit["field"] for hit in report["answer_hits"])
    assert hits == ["mother_id", "split"], hits


# ---------------------------------------------------------------------------------------
# the guard: an exemption may never cover a truth field
# ---------------------------------------------------------------------------------------
def _policy_with_capture_context(tmp_path: Path, key: str, **overrides: object) -> Path:
    payload = json.loads(POLICY.read_text(encoding="utf-8"))
    entry = {"key": key, "evidence_class": CAPTURE_CONTEXT_CLASS, "rig_obtainable": True,
             "claim_allowed": True, "deploy_view": True, "feature_bundle": False,
             "reason": "test fixture"}
    entry.update(overrides)
    payload["capture_context_fields"] = {"fields": [entry]}
    target = tmp_path / f"policy_{key}.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


@pytest.mark.parametrize("key", [
    "iface_id", "iface_area_mm2", "corr_weight", "corr_valid", "id_map", "T_WC", "dist",
    "surface_tag", "rgb_linear", "clean_truth", "physical_truth", "visible_labels",
])
def test_policy_loader_refuses_to_exempt_a_truth_field(tmp_path: Path, key: str) -> None:
    """Every name here is a truth layer, a truth-critical array or a research-only channel."""
    assert key.lower() in {name.lower() for name in TRUTH_CRITICAL_FIELDS} | {
        "rgb_linear", "id_map", "surface_tag", "T_WC", "dist"}
    target = _policy_with_capture_context(tmp_path, key)
    with pytest.raises(SynLabError) as excinfo:
        load_channel_policy(target)
    assert "capture-context declaration" in str(excinfo.value)
    assert str(excinfo.value.code).endswith("LEAKAGE_DETECTED")


def test_policy_loader_refuses_a_supervision_column(tmp_path: Path) -> None:
    from synlab.storage.export import TRUTH_BEARING_FIELDS

    key = sorted(TRUTH_BEARING_FIELDS)[0]
    target = _policy_with_capture_context(tmp_path, key)
    with pytest.raises(SynLabError):
        load_channel_policy(target)


@pytest.mark.parametrize("overrides", [
    {"evidence_class": "SENSOR_PROXY"},
    {"rig_obtainable": False},
    {"claim_allowed": False},
])
def test_policy_loader_requires_the_three_declarations(tmp_path: Path,
                                                       overrides: dict[str, object]) -> None:
    target = _policy_with_capture_context(tmp_path, "bag_id", **overrides)
    with pytest.raises(SynLabError):
        load_channel_policy(target)


# ---------------------------------------------------------------------------------------
# the truth-content scan is untouched
# ---------------------------------------------------------------------------------------
def test_truth_content_scan_still_flags_supervision_and_the_id_map(tmp_path: Path) -> None:
    deploy = tmp_path / "deploy"
    deploy.mkdir(parents=True)
    (deploy / "labels.json").write_text(json.dumps([{"kind": "R2", "loss_mask": True}]),
                                        encoding="utf-8")
    (deploy / "leak.json").write_text(json.dumps({
        "rows": {"a1b2c3d4e5f60718293a4b5c": "LIN0000_E01-m"}}), encoding="utf-8")
    scan = scan_answer_fields(deploy, capture_keys=capture_context_keys())
    flagged = truth_bearing_files(deploy, {"keys_by_container": scan_rows(deploy)})
    reasons = {entry["file"]: entry["reason"] for entry in flagged}
    assert "labels.json" in reasons and "supervision fields" in reasons["labels.json"]
    assert "leak.json" in reasons and "opaque names back to real ids" in reasons["leak.json"]


def scan_rows(view_root: Path) -> dict[str, list[str]]:
    """The key set of one view, read exactly as the exporter reads it."""
    from synlab.storage.export import scan_view_fields

    return scan_view_fields(view_root)["keys_by_container"]
