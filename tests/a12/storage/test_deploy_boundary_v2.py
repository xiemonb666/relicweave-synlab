"""Serialized v2 deployment boundary and research-only legacy compatibility tests."""

from __future__ import annotations

import io
import json
import shutil
import tarfile
from pathlib import Path

import numpy as np
import pytest

from _fixtures import REPO_ROOT
from synlab.canonical import hash_file, hash_json
from synlab.errors import ErrorCode, SynLabError
from synlab.qc.loader_probe import load_features
from synlab.storage.export import (
    DEPLOY_PUBLIC_FORBIDDEN,
    DEPLOY_PUBLIC_PURPOSE,
    PACKAGE_MANIFEST_SCHEMA,
    PACKAGE_SCHEMA,
    TrainingPackage,
    export_training_package,
)
from synlab.storage.release import PROFILE_GATES, ReleaseManager
from synlab.storage.store import QA_PASS, AssetStore

FRAGMENT_OBSERVED = "LIN9100_V01_M01_PAT01_E01-m"
FRAGMENT_UNOBSERVED = "LIN9100_V01_M01_PAT01_E01-p"
MOTHER = "LIN9100_V01_M01_PAT01"


@pytest.fixture
def tiny_export(tmp_path: Path) -> Path:
    """Export a tiny real AssetStore release with one observed and one truth-only member."""
    store = AssetStore(tmp_path / "store")
    rng = np.random.default_rng(19)
    h, w = 8, 8
    obs_payload = {
        "v000.rgb": rng.integers(0, 256, size=(h, w, 3), dtype=np.uint8),
        "v000.deployment_mask": np.ones((h, w), dtype=bool),
        "v000.depth_z": np.full((h, w), 25.0, dtype=np.float32),
        "v000.uncertain_mask": np.zeros((h, w), dtype=bool),
        "v000.roi": np.zeros((h, w), dtype=bool),
        "v000.K": np.eye(3, dtype=np.float64),
        "points": rng.normal(size=(5, 3)).astype(np.float32),
        "normals": np.tile(np.asarray([[0, 0, 1]], dtype=np.float32), (5, 1)),
        "point_valid": np.ones(5, dtype=bool),
        "normal_valid": np.ones(5, dtype=bool),
    }
    observation = store.commit_asset(
        role="obs_result", schema="synlab.obs.v1", unit="mm", frame="S_mm",
        payload=obs_payload,
        meta={"fragment_id": FRAGMENT_OBSERVED, "mother_id": MOTHER,
              "views": [{"u_position_mm": 3.5}],
              "context": {"bag_id": "BAG-42", "mother_id": MOTHER}},
        qa_status=QA_PASS, lineage_id=MOTHER, split="train",
    )
    truth = store.commit_asset(
        role="clean_truth", schema="synlab.truth.clean.v1", unit="1", frame="W_mm",
        payload={"truth_marker": np.asarray([1], dtype=np.int8)},
        meta={"mother_id": MOTHER, "fragment_ids": [FRAGMENT_OBSERVED, FRAGMENT_UNOBSERVED],
              "relations": [{"a": FRAGMENT_OBSERVED, "b": FRAGMENT_UNOBSERVED,
                             "kind": "R2", "area_mm2": 4.0,
                             "valid": True, "loss_mask": True}]},
        qa_status=QA_PASS, lineage_id=MOTHER, split="train",
    )
    gates = {name: "PASS" for name in PROFILE_GATES["RESEARCH_EVIDENCE"]}
    ReleaseManager(store).freeze(
        release_id="rel_deploy_boundary_fixture", profile="RESEARCH_EVIDENCE",
        scope="tiny deploy-boundary fixture",
        asset_ids=[observation.asset_id, truth.asset_id], gates=gates,
        extra={"pool_id": "pool_fixture"},
    )
    out = tmp_path / "export"
    export_training_package(store, "rel_deploy_boundary_fixture", out,
                            formats=("json", "npz", "tar"), include_truth=True)
    return out


def test_tiny_export_keeps_truth_join_research_only_and_deploy_opaque(
        tiny_export: Path, tmp_path: Path) -> None:
    deploy = TrainingPackage(tiny_export)
    assert deploy.manifest["deploy_schema"] == "synlab.training_package_deploy.v2"
    assert set(deploy.manifest["views"]) == {"deploy"}
    assert all(str(row["path"]).startswith("deploy/") for row in deploy.manifest["files"])
    file_report = deploy.verify_files()
    assert file_report["ok"] and file_report["files_checked"] == len(deploy.manifest["files"])

    rows = deploy.queries()
    assert len(rows) == 1, "an unobserved ground-truth neighbour must not enter public roster"
    assert set(rows[0]) == {"opaque_id", "bag_id"}
    opaque = rows[0]["opaque_id"]
    assert len(opaque) == 32 and opaque == opaque.lower()
    assert deploy.observed_ids() == [opaque]
    payload = load_features(deploy, [opaque])
    assert set(payload) == {opaque}
    assert payload[opaque]["points"].shape == (5, 3)
    with pytest.raises(SynLabError) as denied:
        deploy.relations()
    assert denied.value.code == ErrorCode.LEAKAGE_DETECTED
    with pytest.raises(SynLabError):
        deploy.source_id_for_opaque(opaque)

    research = TrainingPackage(tiny_export, access="research")
    queries = research.queries()
    assert {row["fragment_id"] for row in queries} == {
        FRAGMENT_OBSERVED, FRAGMENT_UNOBSERVED}
    relations = research.relations()
    assert len(relations) == 2
    assert {row["query"] for row in relations} == {FRAGMENT_OBSERVED, FRAGMENT_UNOBSERVED}
    assert research.observed_ids() == [FRAGMENT_OBSERVED]
    mapping = {research.source_id_for_opaque(str(row["opaque_id"])): row["opaque_id"]
               for row in deploy.queries()}
    assert mapping == {FRAGMENT_OBSERVED: opaque}
    assert FRAGMENT_UNOBSERVED not in mapping
    assert research.opaque_id_for_source(FRAGMENT_OBSERVED) == opaque
    assert load_features(research, [FRAGMENT_OBSERVED])[FRAGMENT_OBSERVED]["points"].shape == (5, 3)

    second = tmp_path / "second_export"
    from synlab.storage.export import export_training_package
    from synlab.storage.store import AssetStore

    # Exporting the same source release again creates a fresh UUID namespace.
    export_training_package(AssetStore(tmp_path / "store"), "rel_deploy_boundary_fixture", second,
                            formats=("json", "npz", "tar"), include_truth=True)
    second_reader = TrainingPackage(second)
    assert set(second_reader.observed_ids()).isdisjoint(deploy.observed_ids())


def test_parquet_roster_npz_and_tar_export_and_leak_negative(
        tiny_export: Path, tmp_path: Path) -> None:
    from pyarrow import Table, array
    from pyarrow import parquet as pq

    out = tmp_path / "parquet_export"
    export_training_package(AssetStore(tiny_export.parent / "store"),
                            "rel_deploy_boundary_fixture", out,
                            formats=("parquet", "npz", "tar"), include_truth=True)
    package = TrainingPackage(out)
    row = package.queries()[0]
    assert set(row) == {"opaque_id", "bag_id"}
    assert package.read_observation(row["opaque_id"])["rgb"].dtype == np.uint8
    assert package.read_geometry(row["opaque_id"])["points"].shape == (5, 3)
    assert package.read_tokens(row["opaque_id"])["tokens"].shape[1] == 256
    research = TrainingPackage(out, access="research")
    assert len(research.relations()) == 2
    assert research.verify_files()["ok"]

    corrupted = tmp_path / "parquet_roster_leak"
    shutil.copytree(out, corrupted)
    roster = corrupted / "deploy" / "queries.parquet"
    table = pq.read_table(roster).append_column("historical_N_G", array([1]))
    pq.write_table(table, roster)
    _refresh_manifest(corrupted, "deploy/queries.parquet")
    with pytest.raises(SynLabError, match="query roster has unsupported columns"):
        TrainingPackage(corrupted)


def test_legacy_v1_is_research_readable_but_never_a_forward_source(tmp_path: Path) -> None:
    root = tmp_path / "legacy_v1"
    (root / "deploy").mkdir(parents=True)
    (root / "research" / "labels").mkdir(parents=True)
    (root / "deploy" / "queries.json").write_text(json.dumps([
        {"fragment_id": FRAGMENT_OBSERVED, "query_id": f"q::{FRAGMENT_OBSERVED}",
         "historical_N_G": 1},
    ]), encoding="utf-8")
    (root / "research" / "relations.json").write_text(json.dumps([
        {"query": FRAGMENT_OBSERVED, "candidate": FRAGMENT_UNOBSERVED, "kind": "R2"},
    ]), encoding="utf-8")
    (root / "research" / "labels" / "clean.json").write_text(json.dumps([
        {"fragment_id": FRAGMENT_OBSERVED, "label": "fixture"},
    ]), encoding="utf-8")
    manifest = {"schema": PACKAGE_MANIFEST_SCHEMA, "package_schema": PACKAGE_SCHEMA,
                "package_id": "legacy-fixture", "files": []}
    manifest["manifest_hash"] = hash_json(manifest)
    (root / "export_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    research = TrainingPackage(root, access="research")
    assert research.queries()[0]["historical_N_G"] == 1
    assert research.relations()[0]["kind"] == "R2"
    assert research.labels("clean")[0]["label"] == "fixture"
    with pytest.raises(SynLabError, match="INVALID_DEPLOY_TRUTH_LEAK"):
        research.read_observation(FRAGMENT_OBSERVED)
    with pytest.raises(SynLabError, match="INVALID_DEPLOY_TRUTH_LEAK"):
        TrainingPackage(root)


def _refresh_manifest(package_root: Path, relative_path: str) -> None:
    manifest_path = package_root / "export_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    target = package_root / relative_path
    for row in manifest["files"]:
        if row["path"] == relative_path:
            row["hash"] = hash_file(target)
            row["bytes"] = target.stat().st_size
            break
    else:
        raise AssertionError(f"manifest lacks {relative_path}")
    manifest["manifest_hash"] = hash_json(
        {key: value for key, value in manifest.items() if key != "manifest_hash"})
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def _write_manifest(package_root: Path, manifest: dict) -> None:
    manifest["manifest_hash"] = hash_json(
        {key: value for key, value in manifest.items() if key != "manifest_hash"})
    (package_root / "export_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8")


def _manifest_strings(value) -> list[str]:
    if isinstance(value, dict):
        return [str(key) for key in value] + [
            item for child in value.values() for item in _manifest_strings(child)]
    if isinstance(value, (list, tuple)):
        return [item for child in value for item in _manifest_strings(child)]
    return [value] if isinstance(value, str) else []


def _add_tar_array(path: Path, member_name: str, array: np.ndarray) -> None:
    payload = io.BytesIO()
    np.save(payload, array, allow_pickle=False)
    existing = io.BytesIO()
    with tarfile.open(path, "r:") as source, tarfile.open(
            fileobj=existing, mode="w:") as output:
        for member in source.getmembers():
            stream = source.extractfile(member)
            assert stream is not None
            member_payload = stream.read()
            info = tarfile.TarInfo(member.name)
            info.size = len(member_payload)
            output.addfile(info, io.BytesIO(member_payload))
        info = tarfile.TarInfo(member_name)
        info.size = payload.tell()
        output.addfile(info, io.BytesIO(payload.getvalue()))
    path.write_bytes(existing.getvalue())


def test_deploy_manifest_projects_only_generated_public_metadata(
        tiny_export: Path, tmp_path: Path) -> None:
    clone = tmp_path / "manifest_projection"
    shutil.copytree(tiny_export, clone)
    manifest_path = clone / "export_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    deploy_view = manifest["views"]["deploy"]
    deploy_view["purpose"] = {MOTHER: [FRAGMENT_OBSERVED, f"q::{FRAGMENT_OBSERVED}"]}
    deploy_view["forbidden"] = [{MOTHER: FRAGMENT_OBSERVED}]
    manifest["package_id"] = FRAGMENT_OBSERVED
    deploy_row = next(row for row in manifest["files"]
                      if str(row.get("path", "")).startswith("deploy/"))
    deploy_row["note"] = {"lineage_id": MOTHER, "query_alias": f"q::{FRAGMENT_OBSERVED}"}
    _write_manifest(clone, manifest)

    package = TrainingPackage(clone)
    public = package.manifest
    strings = _manifest_strings(public)
    assert all(not any(raw in value for value in strings)
               for raw in (MOTHER, FRAGMENT_OBSERVED, f"q::{FRAGMENT_OBSERVED}"))
    assert public["package_id"].startswith("pkg_") and len(public["package_id"]) == 36
    assert public["manifest_hash"] == hash_json(
        {key: value for key, value in public.items() if key != "manifest_hash"})
    assert public["manifest_hash"] != manifest["manifest_hash"]
    assert public["views"]["deploy"] == {
        "role": "deployment", "purpose": DEPLOY_PUBLIC_PURPOSE,
        "contains_truth": False, "files": len(public["files"]),
        "bytes": public["bytes_total"], "forbidden": list(DEPLOY_PUBLIC_FORBIDDEN),
    }
    assert all(set(row) == {"path", "hash", "bytes"} for row in public["files"])
    checked = package.verify_files()
    assert checked["ok"] and checked["files_checked"] == len(public["files"])
    package.manifest["files"][0]["path"] = "research/opaque_map.json"
    checked = package.verify_files()
    assert checked["ok"] and checked["files_checked"] == len(public["files"])


@pytest.mark.parametrize("defect", [
    "missing_table_declaration", "invalid_source_claim", "not_in_deploy_view",
])
def test_bag_id_requires_the_validated_capture_context_declaration(
        tiny_export: Path, tmp_path: Path, defect: str) -> None:
    clone = tmp_path / f"unvalidated_bag_policy_{defect}"
    shutil.copytree(tiny_export, clone)
    manifest_path = clone / "export_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    scan = manifest["separation"]["capture_context_scan"]
    source = scan["declaration_source"]
    if defect == "missing_table_declaration":
        source["blocks"] = ["capture_context_fields"]
    elif defect == "invalid_source_claim":
        source["claim_allowed"] = False
    else:
        next(row for row in scan["declarations"] if row.get("key") == "bag_id")[
            "deploy_view"] = False
    _write_manifest(clone, manifest)

    with pytest.raises(SynLabError, match="query roster has unsupported columns"):
        TrainingPackage(clone)


def test_unknown_version_and_unapproved_roster_fields_fail_closed(
        tiny_export: Path, tmp_path: Path) -> None:
    unknown = tmp_path / "unknown"
    shutil.copytree(tiny_export, unknown)
    path = unknown / "export_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["deploy_schema"] = "synlab.training_package_deploy.v999"
    manifest["manifest_hash"] = hash_json(
        {key: value for key, value in manifest.items() if key != "manifest_hash"})
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(SynLabError, match="unsupported deploy schema"):
        TrainingPackage(unknown)

    raw_query = tmp_path / "raw_query"
    shutil.copytree(tiny_export, raw_query)
    roster_path = raw_query / "deploy" / "queries.json"
    roster = json.loads(roster_path.read_text(encoding="utf-8"))
    roster[0]["historical_N_G"] = 1
    roster_path.write_text(json.dumps(roster), encoding="utf-8")
    with pytest.raises(SynLabError, match="query roster has unsupported columns"):
        TrainingPackage(raw_query)

    raw_bag = tmp_path / "raw_bag"
    shutil.copytree(tiny_export, raw_bag)
    roster_path = raw_bag / "deploy" / "queries.json"
    roster = json.loads(roster_path.read_text(encoding="utf-8"))
    roster[0]["bag_id"] = FRAGMENT_OBSERVED
    roster_path.write_text(json.dumps(roster), encoding="utf-8")
    with pytest.raises(SynLabError, match="source fragment identity"):
        TrainingPackage(raw_bag)


def test_raw_identity_index_key_and_deep_npz_alias_are_rejected(
        tiny_export: Path, tmp_path: Path) -> None:
    raw_index = tmp_path / "raw_index"
    shutil.copytree(tiny_export, raw_index)
    index_path = raw_index / "deploy" / "obs" / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    only_row = next(iter(index["rows"].values()))
    index["rows"] = {FRAGMENT_OBSERVED: only_row}
    index_path.write_text(json.dumps(index), encoding="utf-8")
    with pytest.raises(SynLabError, match="index key is not an opaque id"):
        TrainingPackage(raw_index)

    alias = tmp_path / "deep_npz_alias"
    shutil.copytree(tiny_export, alias)
    token_index = json.loads((alias / "deploy" / "tokens" / "index.json")
                             .read_text(encoding="utf-8"))
    opaque, row = next(iter(token_index["rows"].items()))
    shard = alias / "deploy" / row["shard"]
    with np.load(shard, allow_pickle=False) as archive:
        arrays = {key: archive[key] for key in archive.files}
    arrays[f"{opaque}__historical_N_G"] = np.asarray([1], dtype=np.int32)
    np.savez(shard, **arrays)
    _refresh_manifest(alias, f"deploy/{row['shard']}")
    with pytest.raises(SynLabError, match="NPZ keys do not match the v2 row allowlist"):
        TrainingPackage(alias)


def test_reader_rechecks_exact_index_and_shard_bytes_after_construction(
        tiny_export: Path, tmp_path: Path) -> None:
    mutated = tmp_path / "modified_shard"
    shutil.copytree(tiny_export, mutated)
    reader = TrainingPackage(mutated)
    opaque = reader.observed_ids()[0]
    token_index = reader.deploy / "tokens" / "index.json"
    index = json.loads(token_index.read_text(encoding="utf-8"))
    row = index["rows"][opaque]
    shard = reader.deploy / row["shard"]
    with np.load(shard, allow_pickle=False) as archive:
        arrays = {key: archive[key] for key in archive.files}
    arrays[f"{opaque}__historical_N_G"] = np.asarray([1], dtype=np.int32)
    np.savez(shard, **arrays)
    # Even a manifest rewritten after construction cannot replace the reader's hash snapshot.
    _refresh_manifest(mutated, f"deploy/{row['shard']}")
    with pytest.raises(SynLabError, match="changed after validation"):
        reader.read_tokens(opaque)

    second = tmp_path / "modified_index"
    shutil.copytree(tiny_export, second)
    reader2 = TrainingPackage(second)
    roster_path = second / "deploy" / "queries.json"
    roster = json.loads(roster_path.read_text(encoding="utf-8"))
    roster[0]["mother"] = MOTHER
    roster_path.write_text(json.dumps(roster), encoding="utf-8")
    with pytest.raises(SynLabError, match="changed after validation"):
        reader2.queries()

    third = tmp_path / "modified_index_after_construction"
    shutil.copytree(tiny_export, third)
    reader3 = TrainingPackage(third)
    opaque3 = reader3.observed_ids()[0]
    index_path = third / "deploy" / "tokens" / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["rows"][f"q::{FRAGMENT_OBSERVED}"] = index["rows"][opaque3]
    index_path.write_text(json.dumps(index), encoding="utf-8")
    _refresh_manifest(third, "deploy/tokens/index.json")
    with pytest.raises(SynLabError, match="changed after validation"):
        reader3.read_tokens(opaque3)


def test_observation_reader_rejects_post_construction_tar_alias(
        tiny_export: Path, tmp_path: Path) -> None:
    clone = tmp_path / "modified_obs_tar"
    shutil.copytree(tiny_export, clone)
    reader = TrainingPackage(clone)
    opaque = reader.observed_ids()[0]
    index = json.loads((clone / "deploy" / "obs" / "index.json")
                       .read_text(encoding="utf-8"))
    shard_name = index["rows"][opaque]["shard"]
    shard = clone / "deploy" / shard_name
    _add_tar_array(shard, f"{opaque}/rest_xyz.npy", np.asarray([1], dtype=np.int32))
    _refresh_manifest(clone, f"deploy/{shard_name}")

    with pytest.raises(SynLabError, match="changed after validation"):
        reader.read_observation(opaque)


def test_missing_research_mapping_fails_closed(tiny_export: Path, tmp_path: Path) -> None:
    clone = tmp_path / "missing_map"
    shutil.copytree(tiny_export, clone)
    (clone / "research" / "opaque_map.json").unlink()
    research = TrainingPackage(clone, access="research")
    with pytest.raises(SynLabError):
        research.opaque_id_for_source(FRAGMENT_OBSERVED)


def test_existing_experiment_ready_v1_is_invalid_for_deploy() -> None:
    legacy = REPO_ROOT / "data" / "a12_exports" / "experiment_ready" / "training_package"
    if not (legacy / "export_manifest.json").is_file():
        pytest.skip("this checkout has no stored experiment_ready v1 package")
    with pytest.raises(SynLabError, match="INVALID_DEPLOY_TRUTH_LEAK"):
        TrainingPackage(legacy)
