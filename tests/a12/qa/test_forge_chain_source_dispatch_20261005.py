from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from synlab.qa.forge_chain_audit import INPUT_SCHEMA, INPUT_SCHEMA_V2, audit_chain, main


_FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "tests"
    / "fixtures"
    / "pgfrag"
    / "result_v1_toy_endpoint"
)
_JOB_ID = "osb-fracture-branch-001"


def _file_ref(root: Path, path: Path) -> dict[str, str]:
    raw = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _write_ref(root: Path, name: str, value: dict) -> dict[str, str]:
    path = root / "refs" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    path.write_bytes(raw)
    return {"path": path.relative_to(root).as_posix(), "sha256": hashlib.sha256(raw).hexdigest()}


def _fixture_input(root: Path, schema: str = INPUT_SCHEMA_V2) -> dict:
    producer = root / "producer"
    producer.mkdir(parents=True)
    shutil.copy2(_FIXTURE / "job.json", producer / "job.json")
    shutil.copytree(_FIXTURE / "output", producer / "output")

    parent = {
        "schema": "forge.asset.v1",
        "asset_id": "fixture-parent",
        "units": {"length": "mm", "time": "s", "mass": "kg"},
        "frame": "right_handed_z_up",
        "geometry": {},
        "fields": {},
        "material": {"id": "fixture-material"},
        "ornament": {},
        "files": {},
        "provenance": {"spec": {}},
        "validation": {"scope": "geometry_only", "report": "validation/geometry.json"},
    }
    policy = {"schema": "synlab.view_channel_policy.v1", "views": {"deploy": {"channels": []}}}
    references = {
        "parent_asset_manifest": _write_ref(root, "parent", parent),
        "native_job": _file_ref(root, producer / "job.json"),
        "native_result": _file_ref(root, producer / "output" / "result.json"),
        "fragment_set_manifest": _write_ref(root, "fragments", {"schema": "fixture.fragment-set.v1"}),
        "crack_surface_manifest": _write_ref(root, "surfaces", {"schema": "fixture.crack-surfaces.v1"}),
        "material_calibration_record": _write_ref(root, "material", {"schema": "fixture.material-calibration.v1"}),
        "historical_relations_record": _write_ref(root, "relations", {"schema": "fixture.relations.v1"}),
        "degradation_recipe_record": _write_ref(root, "recipe", {"schema": "fixture.degradation-recipe.v1"}),
        "degradation_measurements": _write_ref(root, "measurements", {"schema": "fixture.degradation-measurements.v1"}),
        "observations_manifest": _write_ref(root, "observations", {"schema": "fixture.observations.v1"}),
        "capture_records": _write_ref(root, "captures", {"schema": "fixture.captures.v1"}),
        "input_feature_spec": _write_ref(root, "features", {"schema": "fixture.features.v1"}),
        "isolated_label_spec": _write_ref(root, "labels", {"schema": "fixture.labels.v1"}),
        "feature_policy": _write_ref(root, "policy", policy),
    }
    return {
        "schema": schema,
        "source_readers": {
            "native_result": {
                "reader_id": "pgfrag.result.v1",
                "job_reference": "native_job",
                "mode": "read_producer_rows",
            },
        },
        "references": references,
        "chain": {
            "parent_asset_id": "fixture-parent",
            "event": {
                "event_id": "fixture-event",
                "parent_asset_id": "fixture-parent",
                "native_job_id": _JOB_ID,
                "native_result_job_id": _JOB_ID,
                "fragment_ids": [],
            },
            "reference_library_fragment_ids": [],
            "fragments": [],
            "crack_surfaces": [],
            "historical_relations": [],
            "degradation": {},
            "observations": [],
            "capture_records": [],
            "features": {"schema": "a12.obs.v1", "asset_role": "feature_bundle", "fields": ["points"]},
            "labels": {"asset_role": "label_bundle", "separate_asset": True, "fields": ["historical_R2"]},
            "gates": {},
        },
    }


def _write_cli_input(root: Path, document: dict) -> None:
    (root / "input.json").write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def _tamper_points_payload(root: Path) -> None:
    path = root / "producer" / "output" / "points.csv"
    raw = bytearray(path.read_bytes())
    raw[0] ^= 1
    path.write_bytes(raw)


def _gap(report: dict, field: str) -> dict | None:
    return next((item for item in report["gaps"] if item["field"] == field), None)


def test_cli_dispatches_real_tracked_pg_fixture_but_keeps_full_chain_incomplete(tmp_path: Path, capsys) -> None:
    document = _fixture_input(tmp_path)
    _write_cli_input(tmp_path, document)

    exit_code = main(["--root", str(tmp_path), "--input", "input.json", "--output", "report.json"])
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    capsys.readouterr()

    assert exit_code == 0
    pgfrag = report["producer_diagnostics"]["pgfrag"]
    assert pgfrag["status"] == "SOURCE_VERIFIED"
    assert pgfrag["diagnostic_status"] == "PG_DIAGNOSTIC_ONLY"
    assert pgfrag["reader_id"] == "pgfrag.result.v1"
    assert pgfrag["row_counts"]["point_rows"] == 576
    assert pgfrag["row_counts"]["component_rows"] == 576
    assert pgfrag["row_counts"]["bond_state_rows"] == 20780
    assert pgfrag["row_counts"]["broken_bond_rows"] == 5236
    assert {name: row["status"] for name, row in pgfrag["source_binding"]["components"].items()} == {
        "points": "SOURCE_VERIFIED",
        "components": "SOURCE_VERIFIED",
        "bonds": "SOURCE_VERIFIED",
    }
    assert pgfrag["caller_match"]["status"] == "UNKNOWN"
    assert pgfrag["fixture_context"]["initial_condition_kind"] == "uniform_box_bar_fixture"
    assert pgfrag["capabilities"]["physical_fragments"]["status"] == "UNKNOWN"
    assert pgfrag["capabilities"]["crack_surfaces"]["status"] == "UNKNOWN"
    assert pgfrag["capabilities"]["historical_R2"]["status"] == "UNKNOWN"
    assert report["status"] == "INCOMPLETE"
    assert report["source_binding"]["status"] == "UNKNOWN"
    assert report["structural_completeness"]["fragment_row_count_audited"] == 0
    assert report["structural_completeness"]["surface_pair_count_audited"] == 0
    assert report["structural_completeness"]["relation_row_count_audited"] == 0
    assert report["science_qualification"]["physics_qualified"] is False
    assert report["science_qualification"]["pretrain_qualified"] is False
    assert _gap(report, "producer_diagnostics.pgfrag") is None


def test_tampered_actual_pg_payload_fails_chain_dispatch(tmp_path: Path) -> None:
    document = _fixture_input(tmp_path)
    _tamper_points_payload(tmp_path)

    report = audit_chain(document, tmp_path)

    assert report["status"] == "FAIL"
    pgfrag = report["producer_diagnostics"]["pgfrag"]
    assert pgfrag["status"] == "FAIL"
    assert pgfrag["diagnostic_status"] == "FAIL"
    assert any(item["status"] == "FAIL" for item in pgfrag["reader_report"]["errors"])
    assert pgfrag["source_binding"]["status"] == "UNKNOWN"
    assert pgfrag["producer_payload_byte_evidence"] == "UNKNOWN"
    assert _gap(report, "producer_diagnostics.pgfrag")["status"] == "FAIL"
    assert report["science_qualification"]["physics_qualified"] is False
    assert report["science_qualification"]["pretrain_qualified"] is False


def test_result_metadata_read_without_verified_csv_keeps_payload_evidence_unknown(tmp_path: Path) -> None:
    document = _fixture_input(tmp_path)
    (tmp_path / "producer" / "output" / "bond_states.csv").unlink()

    report = audit_chain(document, tmp_path)

    pgfrag = report["producer_diagnostics"]["pgfrag"]
    assert report["status"] == "INCOMPLETE"
    assert pgfrag["status"] == "UNKNOWN"
    assert pgfrag["reader_dispatched"] is True
    assert pgfrag["reader_result_metadata_read"] is True
    assert pgfrag["producer_payload_byte_evidence"] == "UNKNOWN"
    assert pgfrag["verified_payload_files"] == {}
    assert pgfrag["reader_report"]["status"] == "INCOMPLETE"
    assert report["evidence_reference_completeness"]["only_explicit_json_references_read"] is None
    assert report["source_binding"]["producer_payload_bytes_read"] is None


def test_v1_ignores_reader_declaration_and_does_not_read_pg_payloads(tmp_path: Path) -> None:
    document = _fixture_input(tmp_path, schema=INPUT_SCHEMA)
    _tamper_points_payload(tmp_path)

    report = audit_chain(document, tmp_path)

    assert "producer_diagnostics" not in report
    assert report["status"] == "INCOMPLETE"
    assert report["source_binding"]["status"] == "UNKNOWN"
    assert report["source_binding"]["producer_payload_bytes_read"] is False


def test_unsupported_reader_id_is_unknown_without_payload_dispatch(tmp_path: Path) -> None:
    document = _fixture_input(tmp_path)
    document["source_readers"]["native_result"]["reader_id"] = "untrusted.module:Reader"
    _tamper_points_payload(tmp_path)

    report = audit_chain(document, tmp_path)

    pgfrag = report["producer_diagnostics"]["pgfrag"]
    assert report["status"] == "INCOMPLETE"
    assert pgfrag["status"] == "UNKNOWN"
    assert pgfrag["reader_report"] is None
    assert pgfrag["source_binding"]["status"] == "UNKNOWN"
    assert _gap(report, "producer_diagnostics.pgfrag")["status"] == "UNKNOWN"


def test_caller_claim_must_match_real_source_rows_and_cannot_supply_gt(tmp_path: Path) -> None:
    document = _fixture_input(tmp_path)
    document["chain"]["pgfrag_normalized_rows"] = {
        "points": [],
        "components": [],
        "bonds": [],
        "broken_bonds": [],
    }

    report = audit_chain(document, tmp_path)

    pgfrag = report["producer_diagnostics"]["pgfrag"]
    assert report["status"] == "FAIL"
    assert pgfrag["status"] == "FAIL"
    assert pgfrag["reader_report"]["caller_match"]["status"] == "MISMATCH"
    assert pgfrag["source_binding"]["status"] == "SOURCE_VERIFIED"
    assert pgfrag["producer_payload_byte_evidence"] == "COMPLETE"
    assert report["evidence_reference_completeness"]["pgfrag_caller_rows_compared"] is True
    assert pgfrag["capabilities"]["historical_R2"]["status"] == "UNKNOWN"
    assert report["science_qualification"]["physics_qualified"] is False
    assert report["science_qualification"]["pretrain_qualified"] is False


def test_explicit_null_caller_claim_is_not_treated_as_absent(tmp_path: Path) -> None:
    document = _fixture_input(tmp_path)
    document["chain"]["pgfrag_normalized_rows"] = None

    report = audit_chain(document, tmp_path)

    pgfrag = report["producer_diagnostics"]["pgfrag"]
    assert report["status"] == "FAIL"
    assert pgfrag["status"] == "FAIL"
    assert pgfrag["reader_dispatched"] is False
    assert pgfrag["reason"] == "an explicitly supplied chain.pgfrag_normalized_rows claim must be a typed mapping"
