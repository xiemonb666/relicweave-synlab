from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from synlab.qa.forge_chain_audit import INPUT_SCHEMA, audit_chain


def _write_ref(root: Path, name: str, value: dict) -> dict[str, str]:
    path = root / "refs" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    path.write_bytes(raw)
    return {"path": path.relative_to(root).as_posix(), "sha256": hashlib.sha256(raw).hexdigest()}


def _rewrite_ref(root: Path, document: dict, name: str, value: dict) -> None:
    """Rewrite one fixture-only JSON reference and keep its declared digest current."""
    ref = document["references"][name]
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    (root / ref["path"]).write_bytes(raw)
    ref["sha256"] = hashlib.sha256(raw).hexdigest()


def _complete_fictional_input(root: Path) -> dict:
    parent = {
        "schema": "forge.asset.v1",
        "asset_id": "asset-fictional-1",
        "units": {"length": "mm", "time": "s", "mass": "kg"},
        "frame": "right_handed_z_up",
        "geometry": {"solid_step": "geometry/solid.step", "surface_npz": "geometry/surface.npz"},
        "fields": {"surface_fields_npz": "fields/surface_fields.npz"},
        "ornament": {},
        "files": {
            "geometry/solid.step": {"sha256": "a" * 64, "bytes": 1},
            "geometry/surface.npz": {"sha256": "b" * 64, "bytes": 1},
            "fields/surface_fields.npz": {"sha256": "c" * 64, "bytes": 1},
            "validation/geometry.json": {"sha256": "d" * 64, "bytes": 1},
            "geometry/mesh_lineage.npz": {"sha256": "e" * 64, "bytes": 1},
            "metadata/face_semantics.json": {"sha256": "f" * 64, "bytes": 1},
        },
        "provenance": {"spec": {
            "mesh_lineage_npz": "geometry/mesh_lineage.npz",
            "face_semantics_report": "metadata/face_semantics.json",
            "canonical_step_sha256": "a" * 64,
        }},
        "material": {"id": "material-fictional-1", "calibration_status": "UNVALIDATED_PROTOTYPE"},
        "validation": {"scope": "geometry_only", "status": "PASS", "report": "validation/geometry.json"},
    }
    policy = {
        "schema": "synlab.view_channel_policy.v1",
        "views": {"deploy": {"channels": [{"key": "tiles"}, {"key": "depth_z"}]}},
    }
    references = {
        "parent_asset_manifest": _write_ref(root, "parent", parent),
        "native_job": _write_ref(root, "job", {
            "schema": "pgfrag.job.v1", "job_id": "job-fictional-1",
            "initial_condition": {"kind": "forge_asset_surface", "package_dir": "fixture", "manifest_sha256": "a" * 64},
        }),
        "fragment_set_manifest": _write_ref(root, "fragments", {"schema": "fixture.fragment-set.v1", "count": 2}),
        "crack_surface_manifest": _write_ref(root, "surfaces", {"schema": "fixture.crack-surfaces.v1", "count": 2}),
        "material_calibration_record": _write_ref(root, "material", {"schema": "fixture.material-calibration.v1", "claim": "fictional"}),
        "historical_relations_record": _write_ref(root, "relations", {"schema": "fixture.relations.v1", "claim": "fictional"}),
        "degradation_recipe_record": _write_ref(root, "recipe", {"schema": "fixture.degradation-recipe.v1", "claim": "fictional"}),
        "degradation_measurements": _write_ref(root, "measurements", {"schema": "fixture.degradation-measurements.v1", "claim": "fictional"}),
        "observations_manifest": _write_ref(root, "observations", {"schema": "fixture.observations.v1", "claim": "fictional"}),
        "capture_records": _write_ref(root, "captures", {"schema": "fixture.captures.v1", "claim": "fictional"}),
        "input_feature_spec": _write_ref(root, "features", {"schema": "fixture.features.v1", "claim": "fictional"}),
        "isolated_label_spec": _write_ref(root, "labels", {"schema": "fixture.labels.v1", "claim": "fictional"}),
        "feature_policy": _write_ref(root, "policy", policy),
        "gate_evidence": _write_ref(root, "gates", {"schema": "fixture.gates.v1", "claim": "fictional"}),
    }
    job_hash = references["native_job"]["sha256"]
    references["native_result"] = _write_ref(root, "result", {
        "schema": "pgfrag.result.v1", "job_id": "job-fictional-1", "status": "COMPLETED",
        "input": {"job_sha256": job_hash}, "process": {"returncode": 0}, "solver": {"steps": 1},
        "validation": {"scope": "bounded endpoint serialization and solver process completion only", "status": "PASS"},
    })
    references["dataset_export_manifest"] = _write_ref(root, "export", {
        "schema": "synlab.training_package_manifest.v1", "release_scope": "SYNTHETIC",
        "release_profile": "PILOT_UNFROZEN",
        # Fictional positive aggregate counts keep this structural-only fixture from
        # conflating absent keys with the actual zero counts in the current export.
        "degrade_diversity": {"counts": {"degrade_sources": 1, "degrade_variants": 1}},
    })

    event_id = "event-fictional-1"
    parent_id = parent["asset_id"]
    material_id = parent["material"]["id"]
    fragments = [
        {"fragment_id": "fragment-a", "event_id": event_id, "parent_asset_id": parent_id, "material_id": material_id, "volume_mm3": 1e-9},
        {"fragment_id": "fragment-b", "event_id": event_id, "parent_asset_id": parent_id, "material_id": material_id, "volume_mm3": 1.0},
    ]
    surfaces = [
        {"surface_id": "surface-a", "interface_pair_id": "pair-1", "side": "A", "fragment_id": "fragment-a", "event_id": event_id, "parent_asset_id": parent_id, "material_id": material_id, "area_mm2": 1e-9},
        {"surface_id": "surface-b", "interface_pair_id": "pair-1", "side": "B", "fragment_id": "fragment-b", "event_id": event_id, "parent_asset_id": parent_id, "material_id": material_id, "area_mm2": 1e-9},
    ]
    return {
        "schema": INPUT_SCHEMA,
        "references": references,
        "chain": {
            "parent_asset_id": parent_id,
            "event": {
                "event_id": event_id, "parent_asset_id": parent_id,
                "native_job_id": "job-fictional-1", "native_result_job_id": "job-fictional-1",
                "fragment_ids": [row["fragment_id"] for row in fragments],
            },
            "fragments": fragments,
            "crack_surfaces": surfaces,
            "material": {"material_id": material_id, "calibration_status": "MEASURED_CLAIM"},
            "historical_relations": [{
                "query_fragment_id": "fragment-a", "candidate_fragment_id": "fragment-b",
                "historical_relation": "R2", "event_id": event_id, "interface_pair_id": "pair-1",
            }],
            "degradation": {
                "recipe_id": "recipe-fictional-1",
                "actual_quantities": [{"quantity": "wear_depth", "value": 0.01, "unit": "mm", "fragment_id": "fragment-a"}],
            },
            "observations": [{"observation_id": "obs-fictional-1", "fragment_id": "fragment-a", "capture_id": "capture-1"}],
            "capture_records": [{
                "capture_id": "capture-1", "fragment_id": "fragment-a", "path": "fictional/capture.bin",
                "sha256": "b" * 64, "device_id": "camera-1", "calibration_id": "calibration-1",
                "timestamp": "fictional-time", "source_kind": "RAW_CAPTURE",
            }],
            "features": {"schema": "a12.obs.v1", "asset_role": "feature_bundle", "fields": ["global_rgb", "points"]},
            "labels": {"asset_role": "label_bundle", "separate_asset": True, "fields": ["historical_R2", "relation"]},
            "gates": {name: {"status": "PASS", "evidence_ref": "gate_evidence"} for name in (
                "Geometry", "NativeRun", "NumericPhysical", "CalibratedMaterial", "CrackSurface", "RelicWeaveData",
            )},
        },
    }


def _gap_fields(report: dict) -> set[str]:
    return {item["field"] for item in report["gaps"]}


def test_complete_fictional_fixture_only_passes_structure_and_keeps_n_one_legal(tmp_path: Path) -> None:
    document = _complete_fictional_input(tmp_path)
    # One recorded observation is valid; there is no hard-coded package or sample count.
    report = audit_chain(document, tmp_path)
    assert report["status"] == "STRUCTURAL_PASS"
    assert report["structural_completeness"]["status"] == "COMPLETE"
    assert report["structural_completeness"]["fragment_row_count_audited"] == 2
    assert report["structural_completeness"]["relation_row_count_audited"] == 1
    assert report["science_qualification"]["status"] == "SCIENCE_UNVERIFIED"
    assert report["science_qualification"]["physics_qualified"] is False
    assert report["science_qualification"]["pretrain_qualified"] is False
    assert report["gaps"] == []
    assert all(row["audit_status"] == "CLAIMED_PASS_UNVERIFIED" for row in report["science_qualification"]["gate_statuses"].values())
    assert report["source_binding"]["status"] == "UNKNOWN"
    assert report["source_binding"]["producer_row_contents_compared"] is False
    assert set(report["source_binding"]["status_by_component"].values()) == {"UNKNOWN"}


def test_missing_event_fragment_roster_is_incomplete(tmp_path: Path) -> None:
    document = _complete_fictional_input(tmp_path)
    document["chain"]["event"].pop("fragment_ids")
    report = audit_chain(document, tmp_path)
    assert report["status"] == "INCOMPLETE"
    assert "event.fragment_ids" in _gap_fields(report)


def test_duplicate_event_fragment_roster_id_is_rejected(tmp_path: Path) -> None:
    document = _complete_fictional_input(tmp_path)
    document["chain"]["event"]["fragment_ids"].append("fragment-a")
    report = audit_chain(document, tmp_path)
    assert report["status"] == "INCOMPLETE"
    assert "event.fragment_ids[2]" in _gap_fields(report)


def test_event_roster_must_match_all_normalized_fragment_rows(tmp_path: Path) -> None:
    document = _complete_fictional_input(tmp_path)
    document["chain"]["event"]["fragment_ids"].remove("fragment-b")
    report = audit_chain(document, tmp_path)
    assert report["status"] == "INCOMPLETE"
    assert "event.fragment_ids" in _gap_fields(report)


@pytest.mark.parametrize(("relation_label", "declare_gallery", "expected_status"), [
    ("R0", True, "STRUCTURAL_PASS"),
    ("R1", True, "STRUCTURAL_PASS"),
    ("R0", False, "INCOMPLETE"),
    ("R1", False, "INCOMPLETE"),
])
def test_external_r0_r1_candidate_requires_declared_gallery_roster(
    tmp_path: Path, relation_label: str, declare_gallery: bool, expected_status: str,
) -> None:
    document = _complete_fictional_input(tmp_path)
    document["chain"]["historical_relations"].append({
        "query_fragment_id": "fragment-a",
        "candidate_fragment_id": "gallery-fragment-1",
        "historical_relation": relation_label,
        "event_id": "event-fictional-1",
    })
    if declare_gallery:
        document["chain"]["reference_library_fragment_ids"] = ["gallery-fragment-1"]
    report = audit_chain(document, tmp_path)
    assert report["status"] == expected_status
    endpoint_gap = next((row for row in report["gaps"] if row["field"] == "historical_relations[1].candidate_fragment_id"), None)
    if declare_gallery:
        assert endpoint_gap is None
    else:
        assert endpoint_gap is not None
        assert endpoint_gap["status"] == "UNKNOWN"


def test_deploy_channel_name_does_not_validate_featurebundle_tensor(tmp_path: Path) -> None:
    document = _complete_fictional_input(tmp_path)
    document["chain"]["features"]["fields"] = ["tiles"]
    report = audit_chain(document, tmp_path)
    assert report["status"] == "INCOMPLETE"
    gap = next(row for row in report["gaps"] if row["field"] == "features.fields.tiles")
    assert gap["status"] == "UNKNOWN"
    assert "not proof" in gap["reason"]
    assert report["feature_input_audit"]["deploy_channel_names_are_feature_bundle_fields"] is False


def test_missing_degradation_aggregate_is_unknown_not_zero(tmp_path: Path) -> None:
    document = _complete_fictional_input(tmp_path)
    export_ref = document["references"]["dataset_export_manifest"]
    export_path = tmp_path / export_ref["path"]
    export = json.loads(export_path.read_text(encoding="utf-8"))
    del export["degrade_diversity"]["counts"]["degrade_sources"]
    _rewrite_ref(tmp_path, document, "dataset_export_manifest", export)

    report = audit_chain(document, tmp_path)
    gap = next(row for row in report["gaps"] if row["field"].endswith("counts.degrade_sources"))
    assert report["status"] == "INCOMPLETE"
    assert gap["status"] == "UNKNOWN"
    assert "MISSING_AGGREGATE" in gap["reason"]
    assert "degradation.actual_measurements" not in _gap_fields(report)


def test_explicit_zero_degradation_aggregate_remains_a_known_zero(tmp_path: Path) -> None:
    document = _complete_fictional_input(tmp_path)
    export_ref = document["references"]["dataset_export_manifest"]
    export_path = tmp_path / export_ref["path"]
    export = json.loads(export_path.read_text(encoding="utf-8"))
    export["degrade_diversity"]["counts"]["degrade_sources"] = 0
    _rewrite_ref(tmp_path, document, "dataset_export_manifest", export)

    report = audit_chain(document, tmp_path)
    gap = next(row for row in report["gaps"] if row["field"] == "degradation.actual_measurements")
    assert report["status"] == "INCOMPLETE"
    assert "explicitly records degrade_sources=0" in gap["reason"]
    assert "MISSING_AGGREGATE" not in gap["reason"]


def test_missing_historical_annotation_is_unknown_and_incomplete(tmp_path: Path) -> None:
    document = _complete_fictional_input(tmp_path)
    document["chain"]["historical_relations"] = []
    report = audit_chain(document, tmp_path)
    assert report["status"] == "INCOMPLETE"
    assert "historical_relations" in _gap_fields(report)


def test_feature_label_leak_is_rejected(tmp_path: Path) -> None:
    document = _complete_fictional_input(tmp_path)
    document["chain"]["features"]["fields"].append("historical_R2")
    report = audit_chain(document, tmp_path)
    assert report["status"] == "INCOMPLETE"
    assert "features.fields.historical_R2" in _gap_fields(report)


def test_orphan_fragment_is_retained_and_reported_including_tiny_piece(tmp_path: Path) -> None:
    document = _complete_fictional_input(tmp_path)
    document["chain"]["fragments"][0]["event_id"] = "orphan-event"
    document["chain"]["fragments"][0]["volume_mm3"] = 1e-30
    report = audit_chain(document, tmp_path)
    assert report["status"] == "INCOMPLETE"
    assert report["structural_completeness"]["fragment_row_count_audited"] == 2
    assert "fragment_set.fragments[0].event_id" in _gap_fields(report)


def test_unknown_relation_value_is_not_coerced_to_r0(tmp_path: Path) -> None:
    document = _complete_fictional_input(tmp_path)
    document["chain"]["historical_relations"][0]["historical_relation"] = "R9"
    report = audit_chain(document, tmp_path)
    assert report["status"] == "INCOMPLETE"
    assert "historical_relations[0].historical_relation" in _gap_fields(report)
    assert report["structural_completeness"]["relation_labels_seen"] == {}


def test_missing_crack_surface_pair_blocks_structural_pass(tmp_path: Path) -> None:
    document = _complete_fictional_input(tmp_path)
    document["chain"]["crack_surfaces"] = []
    report = audit_chain(document, tmp_path)
    assert report["status"] == "INCOMPLETE"
    assert "crack_surfaces" in _gap_fields(report)


def test_pass_string_without_reference_is_not_evidence(tmp_path: Path) -> None:
    document = _complete_fictional_input(tmp_path)
    document["chain"]["gates"]["NumericPhysical"] = {"status": "PASS"}
    report = audit_chain(document, tmp_path)
    gate = report["science_qualification"]["gate_statuses"]["NumericPhysical"]
    assert gate["audit_status"] == "CLAIMED_PASS_UNVERIFIED"
    assert gate["evidence_reference_status"] == "UNKNOWN"
    assert report["science_qualification"]["physics_qualified"] is False
    assert "gates.NumericPhysical.evidence_ref" in _gap_fields(report)


def test_path_traversal_and_hash_mismatch_are_incomplete(tmp_path: Path) -> None:
    document = _complete_fictional_input(tmp_path)
    document["references"]["parent_asset_manifest"] = {"path": "../outside.json", "sha256": "0" * 64}
    traversal = audit_chain(document, tmp_path)
    assert traversal["evidence_reference_completeness"]["status"] == "INCOMPLETE"
    assert traversal["evidence_reference_completeness"]["status_by_reference"]["parent_asset_manifest"]["status"] == "UNSAFE_PATH"

    document = _complete_fictional_input(tmp_path / "other")
    document["references"]["parent_asset_manifest"]["sha256"] = "0" * 64
    mismatch = audit_chain(document, tmp_path / "other")
    assert mismatch["evidence_reference_completeness"]["status_by_reference"]["parent_asset_manifest"]["status"] == "HASH_MISMATCH"
    assert mismatch["status"] == "INCOMPLETE"
