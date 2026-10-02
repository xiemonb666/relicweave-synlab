"""Read-only conformance tests for the A12 human adjudications (``D1``-``D12``).

These tests pin the *decisions*, not the data: they fail when
``configs/a12/decision_defaults.json`` stops saying what the Lead ruled, or when the
checker stops measuring it honestly.  Whether a particular store satisfies a ruling is a
measurement (``synlab/qc/decision_checks.py``), not a test -- a store is allowed to be
non-conformant, a ruling is not allowed to silently change.

Nothing here writes to a store, a package or a config.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from synlab.qc import decision_checks as dc  # noqa: E402

DEFAULTS_PATH = REPO / "configs" / "a12" / "decision_defaults.json"


@pytest.fixture(scope="module")
def defaults() -> dict:
    assert DEFAULTS_PATH.exists(), f"{DEFAULTS_PATH} is missing"
    return json.loads(DEFAULTS_PATH.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- D1-D12 shell
def test_the_ten_machine_readable_sections_exist(defaults: dict) -> None:
    assert set(defaults) == set(dc.DEFAULT_SECTIONS)
    assert len(defaults) == 10


def test_every_section_carries_a_source_and_an_assumption_flag(defaults: dict) -> None:
    for section in dc.DEFAULT_SECTIONS:
        block = defaults[section]
        assert isinstance(block, dict), section
        source = block.get("source")
        assert isinstance(source, (list, str)) and source, f"{section}: no source pointer"
        if isinstance(source, list):
            assert all(str(s).strip() for s in source), f"{section}: blank source pointer"
        assert isinstance(block.get("assumption"), bool), f"{section}: assumption is not a bool"


def test_assumption_is_only_true_where_the_document_is_silent(defaults: dict) -> None:
    """D6 is the only section built entirely on assumptions (镜头/畸变/景深/色温)."""
    flagged = {name for name in dc.DEFAULT_SECTIONS if defaults[name]["assumption"]}
    assert flagged == {"assumed_optics"}


# --------------------------------------------------------------------------- D1
def test_d1_union_keeps_every_field_from_all_three_pointers(defaults: dict) -> None:
    block = defaults["action_proposal"]
    names = [entry["name"] for entry in block["fields"]]
    assert names == list(dc.ACTION_PROPOSAL_FIELDS)
    assert block["field_count"] == len(dc.ACTION_PROPOSAL_FIELDS) == 14
    tiers = block["tiers"]
    assert len(tiers["required_core"]) == 6
    assert len(tiers["execution_block_nullable"]) == 5
    assert len(tiers["optional_extension"]) == 3
    assert (len(tiers["required_core"]) + len(tiers["execution_block_nullable"])
            + len(tiers["optional_extension"])) == 14


def test_d1_every_field_names_a_document_pointer_and_optionality(defaults: dict) -> None:
    for entry in defaults["action_proposal"]["fields"]:
        pointers = entry["source"]
        assert pointers, entry["name"]
        assert all(any(p.startswith(known) for known in dc.ACTION_PROPOSAL_SOURCES)
                   for p in pointers), entry
        assert isinstance(entry["optional_extension"], bool), entry
        expected_optional = entry["tier"] == "optional_extension"
        assert entry["optional_extension"] is expected_optional, entry


def test_d1_execution_block_is_nullable_not_absent(defaults: dict) -> None:
    block = defaults["action_proposal"]
    assert "允许为 null" in block["execution_block_rule"]
    assert "必须存在" in block["execution_block_rule"]
    for entry in block["fields"]:
        if entry["tier"] == "execution_block_nullable":
            assert entry["nullable"] is True, entry


def test_d1_pose_id_is_recorded_as_an_open_residual(defaults: dict) -> None:
    """p0574's mapping set also names pose_id; the Lead's list does not -> it stays open."""
    unresolved = defaults["action_proposal"]["unresolved"]
    pose = [item for item in unresolved if item["item"] == "pose_id"]
    assert len(pose) == 1
    assert pose[0]["status"] == "unmapped"
    assert pose[0]["owner_decision"] == "D12.4"


# --------------------------------------------------------------------------- D2
def test_d2_delta_is_a_definition_not_an_invented_number(defaults: dict) -> None:
    rule = defaults["stopping_rule"]
    assert "95% CI 半宽" in rule["delta_definition"]
    assert "dev" in rule["delta_freeze"]["where"]
    for key, value in rule.items():
        if "delta" in key and key not in ("delta_definition", "delta_formula",
                                          "delta_interval_source", "delta_freeze"):
            assert not isinstance(value, (int, float)), f"invented delta: {key}={value}"


def test_d2_K_is_three_and_keeps_the_document_ceiling(defaults: dict) -> None:
    rule = defaults["stopping_rule"]
    assert rule["K"] == 3
    assert rule["K_is_minimum"] is True
    assert rule["document_maximum_ticks"] == 4
    assert "3 <= rounds <= 4" in rule["combined_window"]


def test_d2_M_is_a_recomputable_definition(defaults: dict) -> None:
    rule = defaults["stopping_rule"]
    assert "本次评测所用池的规模" in rule["M_definition"]
    assert "any@M" in rule["M_definition"] and "PoolCov@M" in rule["M_definition"]
    assert "未冻结 δ 之前" in rule["gate"]


# --------------------------------------------------------------------------- D3
def test_d3_primary_metrics_are_exactly_the_seven_document_named_ones(defaults: dict) -> None:
    contract = defaults["metric_contract"]
    ids = [entry["id"] for entry in contract["primary_frozen"]]
    assert ids == list(dc.PRIMARY_METRICS)
    assert contract["primary_count"] == 7


def test_d3_work_time_is_a_process_metric_outside_the_primary_list(defaults: dict) -> None:
    contract = defaults["metric_contract"]
    primary_ids = {entry["id"] for entry in contract["primary_frozen"]}
    process = contract["process_metric_separate"]
    assert [entry["id"] for entry in process] == list(dc.PROCESS_METRIC_IDS)
    assert process[0]["kind"] == "process"
    assert not (primary_ids & {entry["id"] for entry in process})


def test_d3_sy_q_mapping_is_monotone_and_flags_uncalibrated_SY_Q2(defaults: dict) -> None:
    mapping = defaults["metric_contract"]["sy_q_to_q_mapping"]
    pairs = {entry["sy_q"]: entry for entry in mapping["pairs"]}
    assert pairs["SY-Q0_OBS"]["q"] == "Q1" and pairs["SY-Q1"]["q"] == "Q1"
    assert pairs["SY-Q2"]["q"] == "Q2" and pairs["SY-Q2"]["status"] == "unmapped"
    assert pairs["SY-Q3"]["q"] == "Q2"
    assert pairs["SY-Q4"]["q"] == "Q3"
    assert pairs["SY-Q5"]["status"] == "unmapped"
    assert "实测统计校准" in pairs["SY-Q2"]["condition"]


def test_d3_real_side_quality_tiers_are_the_documented_three(defaults: dict) -> None:
    assert defaults["metric_contract"]["real_side_quality_tiers"] == ["clear", "daily", "poor"]


# --------------------------------------------------------------------------- D4
def test_d4_interface_id_is_the_authority_and_origin_kind_is_derived(defaults: dict) -> None:
    block = defaults["surface_authority"]
    assert block["authoritative_predicate"] == "interface_id >= 0"
    assert "派生标签" in block["derived_label"]
    assert block["conflict_counter_field"].endswith(dc.SURFACE_CONFLICT_KEY)
    assert block["silent_failure_forbidden"] is True


def test_d4_baseline_conflict_count_is_recorded_with_its_denominator(defaults: dict) -> None:
    baseline = defaults["surface_authority"]["measured_baseline"]
    assert baseline["conflicts"] == 506
    assert baseline["faces_total"] == 3610
    assert baseline["pct"] == pytest.approx(14.0, abs=0.05)


def test_d4_world_frame_reattachment_is_recorded_as_open(defaults: dict) -> None:
    unresolved = defaults["surface_authority"]["unresolved"]
    frames = [item for item in unresolved if "世界帧" in item["item"]]
    assert len(frames) == 1
    assert frames[0]["status"] == "unmapped"
    assert frames[0]["owner_decision"] == "D12.2"


# --------------------------------------------------------------------------- D5
def test_d5_structured_light_is_excluded_for_v1(defaults: dict) -> None:
    block = defaults["structured_light"]
    assert block["v1_excluded"] is True
    assert set(block["excluded_modalities"]) == {"structured_light", "laser_scan"}
    assert block["assumption"] is False


def test_d5_synthetic_depth_hook_is_upper_bound_and_marked(defaults: dict) -> None:
    hook = defaults["structured_light"]["hook_retained"]
    assert hook["marker"] == "synthetic_only"
    assert hook["upper_bound_only"] is True
    assert any("部署式输入" in item for item in hook["forbidden_uses"])


# --------------------------------------------------------------------------- D6
def test_d6_focal_length_derivation_is_recorded_with_its_inputs(defaults: dict) -> None:
    item = defaults["assumed_optics"]["items"]["focal_length_mm"]
    assert item["assumption"] is True
    assert "tan(FOV_h / 2)" in item["derivation"]
    assert item["derivation_inputs"]["fov_h_deg"] == 84.0
    assert item["derivation_inputs"]["resolution_px"] == [2304, 1296]
    assert item["value_derived_mm"] == pytest.approx(2.77, abs=0.01)


def test_d6_distortion_is_brown_conrady_five_parameter(defaults: dict) -> None:
    item = defaults["assumed_optics"]["items"]["distortion_model"]
    assert item["model"] == "Brown–Conrady"
    assert item["radial_order"] == 2
    assert item["tangential"] is True
    assert item["opencv_parameter_vector"] == ["k1", "k2", "p1", "p2", "k3"]


def test_d6_depth_of_field_value_is_left_null_until_the_aperture_is_known(
        defaults: dict) -> None:
    item = defaults["assumed_optics"]["items"]["depth_of_field_mm"]
    assert item["value"] is None, "a DOF number was invented; the document gives no aperture"
    assert item["mark_out_criterion"] == "2.0 px 弥散圆"
    assert item["circle_of_confusion_mm_by_distance"]["100"] == pytest.approx(0.156)
    assert "光圈" in item["missing_input"]
    assert item["assumption"] is True


def test_d6_color_temperature_is_marked_as_an_assumption(defaults: dict) -> None:
    item = defaults["assumed_optics"]["items"]["color_temperature_K"]
    assert item["value"] == 5500 and item["tolerance_K"] == 500
    assert item["cri_min"] == 90
    assert item["assumption"] is True
    assert "重标定" in item["relabel_after"]


def test_d6_every_item_is_marked_assumption_and_relabelable(defaults: dict) -> None:
    for name, item in defaults["assumed_optics"]["items"].items():
        assert item["assumption"] is True, name
        assert item.get("relabel_after"), name


def test_d6_simulated_size_versus_real_specimen_gate_is_open(defaults: dict) -> None:
    unresolved = defaults["assumed_optics"]["unresolved"]
    size = [item for item in unresolved if "尺寸" in item["item"]]
    assert len(size) == 1
    assert size[0]["status"] == "unmapped"
    assert size[0]["owner_decision"] == "D12.1"


# --------------------------------------------------------------------------- D7
def test_d7_cost_log_splits_human_machine_and_wall_clock(defaults: dict) -> None:
    block = defaults["metric_contract"]["cost_accounting"]
    assert block["decision"] == "D7"
    assert block["columns"] == ["human_time", "machine_time", "wall_clock"]
    assert block["per_fragment_capture_time_s"] is None, "a capture time was invented"
    assert "measure_from_real_session" in block["per_fragment_capture_time_s_status"]


# --------------------------------------------------------------------------- D8
def test_d8_the_two_vector_spaces_are_declared_and_never_merged(defaults: dict) -> None:
    block = defaults["quality_mapping"]
    assert block["spaces"]["quality_8"]["count"] == 8
    assert block["spaces"]["degradation_14"]["count"] == 14
    assert block["spaces"]["quality_8"]["components"] == list(dc.QUALITY_COMPONENTS)
    assert block["spaces"]["degradation_14"]["components"] == list(dc.DEGRADATION_COMPONENTS)
    assert block["forbidden_equivalence"]


def test_d8_every_component_is_mapped_with_a_direction_or_marked_unmapped(
        defaults: dict) -> None:
    block = defaults["quality_mapping"]
    forward = {entry["quality"]: entry for entry in block["mapping"]}
    reverse = {entry["degradation"]: entry for entry in block["reverse_mapping"]}
    assert set(forward) == set(dc.QUALITY_COMPONENTS)
    assert set(reverse) == set(dc.DEGRADATION_COMPONENTS)
    for name, entry in forward.items():
        if not entry["estimated_from"]:
            assert entry["status"] == "unmapped", name
    for name, entry in reverse.items():
        if not entry["drives"]:
            assert entry["status"] == "unmapped", name


def test_d8_unmapped_count_is_declared_and_matches_the_table(defaults: dict) -> None:
    block = defaults["quality_mapping"]
    measured = (sum(1 for e in block["mapping"] if not e["estimated_from"])
                + sum(1 for e in block["reverse_mapping"] if not e["drives"]))
    declared = block["unmapped_count"]
    assert declared["quality_side"] + declared["degradation_side"] == declared["total"]
    assert declared["total"] == measured == 3


def test_d8_occlusion_has_no_degradation_axis(defaults: dict) -> None:
    forward = {entry["quality"]: entry for entry in defaults["quality_mapping"]["mapping"]}
    assert forward["occlusion"]["estimated_from"] == []
    assert forward["occlusion"]["status"] == "unmapped"


# --------------------------------------------------------------------------- D9
def test_d9_misdirection_denominator_excludes_empty_slots(defaults: dict) -> None:
    block = defaults["misdirection_denominator"]
    assert "Σ" in block["r1_misdirection_denominator"]
    assert block["empty_slots_in_denominator"] is False
    assert "实际给出的候选位" in block["empty_slots_rule"]


def test_d9_mate_absent_leaves_the_hit_denominator(defaults: dict) -> None:
    block = defaults["misdirection_denominator"]
    assert "不进入 Hit 与 CovRecall 分母" in block["mate_absent_rule"]
    assert block["two_denominators_must_not_mix"]


def test_d9_r1_misdirection_is_the_accepted_set_share(defaults: dict) -> None:
    block = defaults["misdirection_denominator"]
    assert "接受集" in block["r1_misdirection_definition"]
    assert "UNKNOWN" in block["unknown_rule"]


def test_d9_pair_output_keeps_the_documented_eight_fields_and_their_gaps(
        defaults: dict) -> None:
    block = defaults["misdirection_denominator"]["pair_output"]
    assert len(block["fields"]) == 8
    assert "至少包括" in block["source"]
    assert block["score_type_enum_status"] == "proposed_not_frozen"
    assert len(block["unresolved"]) == 3


# --------------------------------------------------------------------------- D10
def test_d10_loss_mask_is_the_only_gate(defaults: dict) -> None:
    block = defaults["loss_mask_authority"]
    assert block["sole_gate"] == "loss_mask"
    assert block["derived_alias"]["field"] == "valid"
    assert block["derived_alias"]["rule"] == "valid := loss_mask"
    assert block["derived_alias"]["second_truth_forbidden"] is True


def test_d10_eligible_as_negative_is_derived_from_kind_and_loss_mask(defaults: dict) -> None:
    block = defaults["loss_mask_authority"]
    assert block["eligible_as_negative_rule"] == \
        "eligible_as_negative := (kind ∈ {R1, R0}) ∧ loss_mask"
    assert "R0" in block["eligible_source_constants"]


def test_d10_the_zero_negative_supply_consequence_is_written_down(defaults: dict) -> None:
    block = defaults["loss_mask_authority"]
    assert "恒为 0" in block["measured_state_note"]
    assert "联动约束" in block["coupled_consequence"]


def test_d10_visible_layer_gap_is_recorded_as_open(defaults: dict) -> None:
    unresolved = defaults["loss_mask_authority"]["unresolved"]
    visible = [item for item in unresolved if "visible" in item["item"]]
    assert len(visible) == 1
    assert visible[0]["status"] == "unmapped"
    assert visible[0]["owner_decision"] == "D12.3"


# --------------------------------------------------------------------------- D11
def test_d11_v1_field_set_covers_every_named_group(defaults: dict) -> None:
    block = defaults["context_v1_fields"]
    assert block["simulated"] is True
    groups = {entry["group"] for entry in block["v1_fields"]}
    assert {"出土区", "网格", "层位", "层深", "袋号", "坑位", "批次", "共存物", "尺度参考",
            "会话"} <= groups


def test_d11_query_keys_are_marked_and_queryable(defaults: dict) -> None:
    block = defaults["context_v1_fields"]
    assert block["query_keys"] == list(dc.CONTEXT_QUERY_KEYS)
    marked = {entry["field"] for entry in block["v1_fields"] if entry.get("query_key")}
    assert marked == set(dc.CONTEXT_QUERY_KEYS)
    assert "可查询" in block["query_requirement"]


def test_d11_context_is_not_equivalent_to_a_mother_id(defaults: dict) -> None:
    block = defaults["context_v1_fields"]
    assert block["not_equivalent_to_mother_id"] is True
    assert {"mother_id", "fragment_id", "lineage_id"} <= set(block["forbidden_fields"])
    assert "部署式输入" not in " ".join(block["forbidden_fields"])  # keep it a field list


def test_d11_missing_rate_gate_is_recorded_as_open(defaults: dict) -> None:
    unresolved = defaults["context_v1_fields"]["unresolved"]
    assert len(unresolved) == 1
    assert unresolved[0]["status"] == "unmapped"
    assert unresolved[0]["owner_decision"] == "D12.6"


# --------------------------------------------------------------------------- D12 shell
def test_d12_residuals_are_named_by_owner_across_the_sections(defaults: dict) -> None:
    owners = set()
    for section in dc.DEFAULT_SECTIONS:
        for item in defaults[section].get("unresolved", []) or []:
            owners.add(item.get("owner_decision"))
        for field in ("pair_output", "sy_q_to_q_mapping"):
            nested = defaults[section].get(field)
            if isinstance(nested, dict):
                for item in nested.get("unresolved", []) or []:
                    owners.add(item.get("owner_decision"))
    assert {f"D12.{n}" for n in range(1, 8)} <= owners


def test_d12_every_residual_carries_a_temporary_rule(defaults: dict) -> None:
    """An open residual must say what to do until it is decided -- never silence."""
    seen = 0
    for section in dc.DEFAULT_SECTIONS:
        blocks = [defaults[section]]
        for field in ("pair_output", "sy_q_to_q_mapping"):
            nested = defaults[section].get(field)
            if isinstance(nested, dict):
                blocks.append(nested)
        for block in blocks:
            for item in block.get("unresolved", []) or []:
                assert item.get("temporary_rule"), item
                assert item.get("status") == "unmapped", item
                seen += 1
    assert seen >= 7


# --------------------------------------------------------------------------- the checker
def _fixture_store(tmp_path: Path, *, conflicts: int, faces: int) -> Path:
    """A tiny read-only fixture store: one GLB authority block with a conflict count."""
    import sqlite3

    root = tmp_path / "store"
    root.mkdir(parents=True, exist_ok=True)
    db = root / "metadata.sqlite"
    con = sqlite3.connect(db)
    con.execute("create table assets (asset_id text, role text, meta_json text)")
    con.execute("insert into assets values (?,?,?)", (
        "a1", "display_lod_glb",
        json.dumps({"surface_group_authority": {
            "faces_total": faces, dc.SURFACE_CONFLICT_KEY: conflicts}})))
    con.commit()
    con.close()
    return root


def test_checker_reports_zero_conflicts_as_a_pass(tmp_path: Path) -> None:
    store = _fixture_store(tmp_path, conflicts=0, faces=100)
    checks = {c.id: c for c in dc.run_checks(store, repo=REPO, exports_root=tmp_path / "none",
                                            reports_root=tmp_path / "none",
                                            defaults={"surface_authority": {
                                                "authoritative_predicate": "interface_id >= 0"}},
                                            defaults_error=None)}
    result = checks["surface.authority_conflicts"]
    assert result.status == dc.PASS
    assert (result.hits, result.denominator) == (100, 100)


def test_checker_does_not_loosen_a_real_conflict(tmp_path: Path) -> None:
    store = _fixture_store(tmp_path, conflicts=506, faces=3610)
    checks = {c.id: c for c in dc.run_checks(store, repo=REPO, exports_root=tmp_path / "none",
                                            reports_root=tmp_path / "none",
                                            defaults={"surface_authority": {
                                                "authoritative_predicate": "interface_id >= 0"}},
                                            defaults_error=None)}
    result = checks["surface.authority_conflicts"]
    assert result.status == dc.FAIL
    assert (result.hits, result.denominator) == (3104, 3610)
    assert result.evidence["per_asset"][0]["pct"] == pytest.approx(14.02, abs=0.01)


def test_checker_treats_an_empty_denominator_as_not_applicable(tmp_path: Path) -> None:
    target = tmp_path / "empty"
    target.mkdir()
    checks = {c.id: c for c in dc.run_checks(target, repo=REPO, exports_root=tmp_path / "none",
                                            reports_root=tmp_path / "none", defaults=None,
                                            defaults_error="missing")}
    assert checks["surface.authority_conflicts"].status == dc.NOT_APPLICABLE
    assert checks["defaults.present"].status == dc.UNREADABLE


def test_checker_scans_itself_out_of_the_source_claims() -> None:
    """The gate names the forbidden tokens; it must not convict itself for doing so."""
    checks = {c.id: c for c in dc.run_checks(REPO / "data" / "a12", repo=REPO)}
    assert checks["structured_light.claim_free"].evidence["offenders"] == []
    assert checks["defaults.action_proposal_union"].evidence["producers"] == []


def test_checker_is_read_only_on_the_store_it_judges(tmp_path: Path) -> None:
    store = _fixture_store(tmp_path, conflicts=506, faces=3610)
    db = store / "metadata.sqlite"
    before = db.stat().st_mtime_ns
    dc.check_store(store, repo=REPO, exports_root=tmp_path / "none", reports_root=tmp_path / "none")
    assert db.stat().st_mtime_ns == before


def test_report_writer_names_the_file_after_the_store(tmp_path: Path) -> None:
    report = {"schema": dc.SCHEMA, "verdict": "partial", "checks": []}
    path = dc.write_report(report, tmp_path / "data" / "a12" / "store", repo=tmp_path,
                           out_dir=tmp_path / "out")
    assert path.name == "decision_checks_data__a12__store.json"
    assert json.loads(path.read_text(encoding="utf-8"))["verdict"] == "partial"
