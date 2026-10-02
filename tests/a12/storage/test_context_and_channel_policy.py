"""Storage-contract tests: the simulated excavation context and the view channel policy.

Everything here is a *contract* assertion about what the code guarantees, and every fixture is
built in ``tmp_path`` through the real :class:`synlab.storage.store.AssetStore` -- no fixture asset
is ever committed into a real store.

Covered:

* ``synlab.context.v1`` / ``context_pack`` are declared, and the batch identity a real product
  writes (``meta.context_id`` + ``meta.context.bag_id``) is declared too;
* the context pack contract itself: ``simulated=true`` is mandatory, the t088 field list is
  required, and a pack may not carry an answer-side field (it raises instead of being committed);
* the batch layout is deterministic and independent of fragment order, and a fragment's
  ``context_id`` resolves to exactly the pack that names it;
* the deployment/research channel split is read from a *policy document*: the env override is
  honoured, a policy that lists one channel in both views is refused, and the deployment list is
  the one the task allows (``depth_z``/``deployment_mask``/``uncertain_mask``/``roi``/``K``) while
  the answer channels (``id_map``/``surface_tag``/``T_WC``/``dist``) stay research-only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab import roles  # noqa: E402
from synlab.errors import SynLabError  # noqa: E402
from synlab.pipeline import (  # noqa: E402
    CONTEXT_VOCABULARY,
    assert_context_is_not_answer_bearing,
    batch_slot_layout,
    build_context_pack,
    context_query,
    context_identity_fields,
    plan_context,
)
from synlab.storage.export import (  # noqa: E402
    OPTIONAL_DEPLOY_CHANNELS,
    VIEW_CHANNEL_POLICY_ENV,
    VIEW_DEPLOY,
    VIEW_RESEARCH,
    channel_table,
    declared_channels,
    load_channel_policy,
    observed_channels,
)
from synlab.storage.store import QA_PASS, AssetStore  # noqa: E402


# ------------------------------------------------------------------------------------ fixtures
class _Lineage:
    """The subset of ``pipeline.LineagePlan`` ``plan_context`` reads (id + plan index)."""

    def __init__(self, lineage_id: str, index: int = 0, split: str = "train") -> None:
        self.lineage_id = lineage_id
        self.mother_index = index
        self.split = split
        self.vessel_id = "V01"
        self.material_id = "M01"
        self.pattern_id = "PAT01"
        self.layer_combo_id = "L01"
        self.params: dict = {}
        self.event_ids = [f"{lineage_id}_E01"]


class _Plan:
    def __init__(self) -> None:
        self.spec_hash = "sha256:fixture"
        self.code_fingerprint = {"git": False}
        self.backend_fingerprints = {}


def _pack_document(context) -> dict:
    """The document ``build_context_pack`` writes, without touching a store."""
    return {
        **context.as_dict(),
        "batch_size": 2,
        "batch_size_target": context.batch_size_target,
        "coexistents": [
            {"kind": "fragment", "id": f"{context.bag_id}-a", "role": "target_observed",
             "count": 1, "has_observation": True},
            {"kind": "fragment", "id": f"{context.bag_id}-b", "role": "event_endpoint",
             "count": 1, "has_observation": False},
        ],
        "coexistent_counts": {"fragments": 2, "with_observation": 1, "vessels": 1, "others": 0},
        "coexistence_scope": "every fragment of this lineage's event",
    }


# ------------------------------------------------------------------------------ declarations
def test_context_role_and_schema_are_declared() -> None:
    assert roles.ROLE_CONTEXT_PACK == "context_pack"
    assert roles.SCHEMA_CONTEXT == "synlab.context.v1"
    assert roles.SCHEMA_CONTEXT in roles.DECLARED_SCHEMAS
    # the context pack is metadata, so it has no spatial frame and no physical unit
    assert roles.UNIT_NONE in roles.DECLARED_UNITS
    assert roles.FRAME_NONE in roles.DECLARED_FRAMES


@pytest.mark.parametrize("schema", ["synlab.labels.v1", "synlab.provenance.v1",
                                    "synlab.display_glb.v1"])
def test_contract_debt_schemas_are_declared(schema: str) -> None:
    """The three schema ids the census found in real products are now declared."""
    assert schema in roles.DECLARED_SCHEMAS


@pytest.mark.parametrize(("constant", "value", "table"), [
    ("UNIT_M", "m", "DECLARED_UNITS"),
    ("FRAME_Y_UP_M", "Y_up_m", "DECLARED_FRAMES"),
    ("FRAME_NONE", "none", "DECLARED_FRAMES"),
])
def test_contract_debt_units_and_frames_are_declared(constant: str, value: str,
                                                     table: str) -> None:
    assert getattr(roles, constant) == value
    assert value in getattr(roles, table)


def test_bag_id_stays_a_forbidden_feature_field() -> None:
    """Context group bookkeeping is storable but may never enter a forward pass."""
    assert "bag_id" in roles.FORBIDDEN_FEATURE_FIELDS
    fields = context_identity_fields(plan_context(7, _Lineage("LIN0000_V01_M01_PAT01")))
    # the flat keys are the ones the leak scan sees; ``bag_id`` lives one level down
    assert set(fields) == {"context_id", "batch_id", "context"}
    assert fields["context"]["bag_id"]


# ------------------------------------------------------------------------------- plan_context
def test_context_plan_is_deterministic_and_seed_dependent() -> None:
    lineage = _Lineage("LIN0000_V01_M01_PAT01")
    first = plan_context(20261001, lineage).as_dict()
    again = plan_context(20261001, lineage).as_dict()
    other_seed = plan_context(20261002, lineage).as_dict()
    assert first == again
    assert first != other_seed
    assert first["simulated"] is True


def test_context_fields_follow_the_t088_vocabulary() -> None:
    context = plan_context(20261001, _Lineage("LIN0000_V01_M01_PAT01"))
    area = {row[0] for row in CONTEXT_VOCABULARY["excavation_areas"]}
    strata = {row[0] for row in CONTEXT_VOCABULARY["strata"]}
    scales = {row[0] for row in CONTEXT_VOCABULARY["scale_references"]}
    assert context.excavation_area_id in area
    assert context.stratum_id in strata
    assert context.stratum_depth_mm > 0
    # the key is ``scale_reference_kind`` (not a bare ``kind``): a bare ``kind`` anywhere in the
    # package would collide with the exporter's truth-bearing field vocabulary
    assert context.scale_reference["scale_reference_kind"] in scales
    assert context.scale_reference["size_mm"] > 0
    assert context.scale_reference["simulated"] is True
    assert context.bag_id.startswith("BAG-")
    assert context.context_id == f"{context.pit_id}|{context.stratum_id}|{context.batch_id}"
    assert context.site_notes and "SIMULATED" in context.site_notes
    assert context.captured_at.startswith("2026-03-")


def test_whole_lineage_is_one_batch_by_default() -> None:
    context = plan_context(20261001, _Lineage("LIN0000_V01_M01_PAT01"))
    assert context.batch_size_target == 0
    assert context.batch_index == 0
    assert context.batch_id == context.bag_id
    assert "#b" not in context.context_id


def test_batch_layout_is_order_independent_and_slots_are_distinct() -> None:
    lineage = _Lineage("LIN0000_V01_M01_PAT01")
    ids = ["F-d", "F-a", "F-c", "F-b"]
    layout = batch_slot_layout(20261001, lineage, ids, divisor=2)
    assert set(layout) == set(ids)
    # the slot of a fragment is decided by the *sorted* id, not by the order handed in
    reversed_layout = batch_slot_layout(20261001, lineage, list(reversed(ids)), divisor=2)
    assert {key: value.context_id for key, value in layout.items()} == \
           {key: value.context_id for key, value in reversed_layout.items()}
    slots = {value.batch_index for value in layout.values()}
    assert slots == {0, 1}
    assert len({value.context_id for value in layout.values()}) == 2
    for value in layout.values():
        assert value.batch_size_target == 2
        assert value.context_id.endswith(value.batch_id)


def test_single_batch_layout_gives_every_fragment_the_same_pack() -> None:
    layout = batch_slot_layout(20261001, _Lineage("LIN0000_V01_M01_PAT01"),
                               ["F-a", "F-b"], divisor=0)
    assert {value.pack_id for value in layout.values()} == {"ctx_LIN0000_V01_M01_PAT01"}


# ------------------------------------------------------------------------- the pack contract
def test_a_pack_without_simulated_is_refused() -> None:
    document = _pack_document(plan_context(20261001, _Lineage("LIN0000_V01_M01_PAT01")))
    document["simulated"] = False
    with pytest.raises(SynLabError) as excinfo:
        assert_context_is_not_answer_bearing(document)
    assert "simulated=true" in str(excinfo.value)


@pytest.mark.parametrize("field", ["lineage_id", "mother_id", "fragment_id", "relation"])
def test_a_pack_carrying_an_answer_field_is_refused(field: str) -> None:
    document = _pack_document(plan_context(20261001, _Lineage("LIN0000_V01_M01_PAT01")))
    document["nested"] = {"deep": {field: "x"}}
    with pytest.raises(SynLabError) as excinfo:
        assert_context_is_not_answer_bearing(document)
    assert field in str(excinfo.value)


def test_the_pack_commits_and_carries_every_t088_field(tmp_path: Path) -> None:
    store = AssetStore(tmp_path / "store")
    lineage = _Lineage("LIN0000_V01_M01_PAT01")
    context = plan_context(20261001, lineage)
    record, document = build_context_pack(
        store, _Plan(), lineage, context,
        batches=[{"fragment_id": "F-a", "role": "target_observed", "has_observation": True,
                  "geometry_asset": "asset_a", "observation_asset": "asset_b", "note": "n"},
                 {"fragment_id": "F-b", "role": "event_endpoint", "has_observation": False,
                  "geometry_asset": "asset_c", "observation_asset": "", "note": "n"}])
    stored = store.get_asset(record.asset_id)
    assert stored.role == roles.ROLE_CONTEXT_PACK
    assert stored.schema == roles.SCHEMA_CONTEXT
    assert stored.unit == roles.UNIT_NONE
    assert stored.frame == roles.FRAME_NONE
    assert stored.qa_status == QA_PASS
    for field in ("simulated", "excavation_area_id", "grid_ref", "stratum_id", "stratum_depth_mm",
                  "bag_id", "pit_id", "context_id", "batch_id", "coexistents", "scale_reference",
                  "session_id", "operator_id", "captured_at", "site_notes"):
        assert field in document, field
    assert stored.meta["simulated"] is True
    assert stored.meta["batch_size"] == 2
    assert len(stored.meta["coexistents"]) == 2


def test_context_query_resolves_a_fragment_to_its_batch(tmp_path: Path) -> None:
    store = AssetStore(tmp_path / "store")
    lineage = _Lineage("LIN0000_V01_M01_PAT01")
    context = plan_context(20261001, lineage)
    build_context_pack(store, _Plan(), lineage, context,
                       batches=[{"fragment_id": "F-a", "role": "target_observed",
                                 "has_observation": True},
                                {"fragment_id": "F-b", "role": "event_endpoint",
                                 "has_observation": False}])
    store.commit_asset(role=roles.ROLE_FRAGMENT_MESH, schema=roles.SCHEMA_FRAGMENT,
                       unit=roles.UNIT_MM, frame=roles.FRAME_WORLD,
                       payload={"vertices": np.zeros((3, 3), dtype=np.float64)},
                       meta={"fragment_id": "F-a", **context_identity_fields(context)},
                       qa={"ok": True}, qa_status=QA_PASS)
    answer = context_query(store, "F-a")
    assert answer["found"] is True
    assert answer["simulated"] is True
    assert answer["batch_id"] == context.batch_id
    assert answer["bag_id"] == context.bag_id
    assert answer["same_batch_candidates"] == ["F-b"]
    assert answer["same_batch_size"] == 2


def test_context_query_reports_a_fragment_without_context(tmp_path: Path) -> None:
    store = AssetStore(tmp_path / "store")
    store.commit_asset(role=roles.ROLE_FRAGMENT_MESH, schema=roles.SCHEMA_FRAGMENT,
                       unit=roles.UNIT_MM, frame=roles.FRAME_WORLD,
                       payload={"vertices": np.zeros((3, 3), dtype=np.float64)},
                       meta={"fragment_id": "F-none"}, qa={"ok": True}, qa_status=QA_PASS)
    answer = context_query(store, "F-none")
    assert answer["found"] is False
    assert "no context_id" in answer["reason"]


# ------------------------------------------------------------------------------ channel policy
def test_the_shipped_policy_has_the_permitted_deploy_split() -> None:
    policy = load_channel_policy()
    deploy = channel_table(policy, VIEW_DEPLOY)
    research = channel_table(policy, VIEW_RESEARCH)
    assert {"depth_z", "deployment_mask", "uncertain_mask", "roi", "K"} <= set(deploy)
    assert {"id_map", "surface_tag", "T_WC", "dist"} <= set(research)
    assert not (set(deploy) & set(research))
    assert set(policy["research_only"]) == set(research)
    assert policy["path"].endswith("view_channels.json")
    assert policy["hash"].startswith("sha256:")


def test_optional_deploy_channels_match_the_policy_document() -> None:
    policy = load_channel_policy()
    declared = {str(item["key"]) for item in policy["channels"][VIEW_DEPLOY]
                if str(item["key"]) not in {"tiles", "valid", "view_pos"}}
    assert declared == {key for key, _array, _dtype in OPTIONAL_DEPLOY_CHANNELS}


def test_the_policy_path_is_env_configurable(tmp_path: Path) -> None:
    custom = tmp_path / "custom_policy.json"
    custom.write_text(json.dumps({
        "schema": "synlab.view_channel_policy.v1",
        "views": {
            VIEW_DEPLOY: {"channels": [{"key": "tiles"}, {"key": "depth_z"}]},
            VIEW_RESEARCH: {"channels": [{"key": "surface_tag"}]},
        },
    }), encoding="utf-8")
    policy = load_channel_policy(custom)
    assert channel_table(policy, VIEW_DEPLOY) == {"tiles": {"key": "tiles"},
                                                  "depth_z": {"key": "depth_z"}}
    assert policy["research_only"] == ["surface_tag"]


def test_a_channel_in_both_views_is_refused(tmp_path: Path) -> None:
    clash = tmp_path / "clash.json"
    clash.write_text(json.dumps({
        "views": {
            VIEW_DEPLOY: {"channels": [{"key": "depth_z"}]},
            VIEW_RESEARCH: {"channels": [{"key": "depth_z"}]},
        },
    }), encoding="utf-8")
    with pytest.raises(SynLabError) as excinfo:
        load_channel_policy(clash)
    assert "both views" in str(excinfo.value)


def test_a_missing_policy_is_an_error_not_a_default(tmp_path: Path) -> None:
    with pytest.raises(SynLabError):
        load_channel_policy(tmp_path / "does_not_exist.json")


def test_observed_channels_reads_real_files(tmp_path: Path) -> None:
    """The scan is a measurement: an npz array name and a json list both show up."""
    view = tmp_path / "deploy"
    (view / "geometry").mkdir(parents=True)
    np.savez(view / "geometry" / "shard_0000.npz",
             aaa__points=np.zeros((2, 3), dtype=np.float32),
             aaa__depth_z=np.zeros((2,), dtype=np.float32))
    (view / "obs").mkdir(parents=True)
    (view / "obs" / "index.json").write_text(json.dumps(
        {"channel_names": ["tiles", "depth_z", "K"]}), encoding="utf-8")
    scan = observed_channels(view)
    assert "points" in scan["counts"] and "depth_z" in scan["counts"]
    assert scan["counts"]["points"] == 1
    declared = declared_channels(view)
    assert declared["channels"] == ["K", "depth_z", "tiles"]
    # a declaration is not content: obs/index.json is read by its own accessor and excluded here
    assert "tiles" not in scan["counts"]
    assert "K" not in scan["counts"]
    assert set(scan["counts"]) == {"depth_z", "points"}


def test_env_override_selects_the_policy(monkeypatch: pytest.MonkeyPatch,
                                         tmp_path: Path) -> None:
    custom = tmp_path / "env_policy.json"
    custom.write_text(json.dumps({
        "views": {
            VIEW_DEPLOY: {"channels": [{"key": "tiles"}]},
            VIEW_RESEARCH: {"channels": [{"key": "id_map"}]},
        },
    }), encoding="utf-8")
    monkeypatch.setenv(VIEW_CHANNEL_POLICY_ENV, str(custom))
    try:
        policy = load_channel_policy()
        assert str(custom) == policy["path"]
        assert channel_table(policy, VIEW_DEPLOY) == {"tiles": {"key": "tiles"}}
    finally:
        monkeypatch.delenv(VIEW_CHANNEL_POLICY_ENV, raising=False)
