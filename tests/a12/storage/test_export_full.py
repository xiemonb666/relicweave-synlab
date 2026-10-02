"""Tests for the maximal (``flavour="full"``) exporter and its ablation index.

What is asserted here is the exporter's *contract*, not a property of any particular store:

* the manifest's file table is exactly the file set on disk (no undeclared file, no declared
  file missing);
* every modality is either ``present`` with real files, or ``missing`` with a concrete unlock
  condition -- a channel is never invented;
* no truth/label modality is ever marked deployable, and the deployable set agrees with the
  real policy document ``synlab/schemas/view_channels.json``;
* ``synthetic_only`` is derived from the asset metadata and the measured count of assets that
  declare a real capture is reported next to it;
* every ablation group either names fields that exist in the package or is marked missing;
* the one derived artefact (the fracture-surface subset) is reproducible from the
  authoritative face attribute.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
for path in (str(REPO_ROOT), str(HERE)):
    if path not in sys.path:
        sys.path.insert(0, path)

from full_fixture import (  # noqa: E402,F401  (fixtures are re-exported by name)
    FRAGMENT_A,
    FRAGMENT_B,
    MOTHER,
    full_package,
    full_store,
    real_package,
)
from synlab.roles import (  # noqa: E402
    FORBIDDEN_FEATURE_FIELDS,
    ROLE_CLEAN_TRUTH,
    ROLE_LABEL_BUNDLE,
    ROLE_PHYSICAL_TRUTH,
    ROLE_VISIBLE_LABELS,
)
from synlab.storage import export_full as ef  # noqa: E402


def _manifest(package: Path) -> dict:
    return json.loads((package / "manifest.json").read_text(encoding="utf-8"))


def _index(package: Path) -> dict:
    return json.loads((package / "ablation_index.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------------------
# file set / manifest consistency
# ---------------------------------------------------------------------------------------
def test_manifest_file_table_is_exactly_the_disk_set(full_package: Path) -> None:
    manifest = _manifest(full_package)
    declared = {entry["path"] for entry in manifest["files"]}
    declared |= {"manifest.json", "ablation_index.json", "README.md"}
    on_disk = {str(path.relative_to(full_package)).replace("\\", "/")
               for path in full_package.rglob("*") if path.is_file()}
    assert declared == on_disk
    for entry in manifest["files"]:
        file = full_package / entry["path"]
        assert file.stat().st_size == entry["bytes"], entry["path"]
        assert entry["sha256"].startswith("sha256:")


def test_every_declared_file_is_hashed_and_counted(full_package: Path) -> None:
    manifest = _manifest(full_package)
    assert manifest["counts"]["files"] == len(manifest["files"])
    assert manifest["counts"]["bytes"] == sum(entry["bytes"] for entry in manifest["files"])
    assert manifest["counts"]["bytes"] > 0


def test_check_accepts_the_package_it_just_wrote(full_package: Path) -> None:
    verdict = ef.check_full_package(full_package)
    assert verdict["ok"], verdict["problems"]
    assert verdict["exit_code"] == 0
    assert verdict["files_checked"] == verdict["files_declared"] == verdict["files_on_disk"]


def test_check_rejects_a_tampered_file(full_package: Path, tmp_path: Path) -> None:
    import shutil

    copy = tmp_path / "tampered"
    shutil.copytree(full_package, copy)
    manifest = _manifest(copy)
    entry = next(item for item in manifest["files"] if item["format"] == "npz")
    target = copy / entry["path"]
    payload = bytearray(target.read_bytes())
    payload[-1] ^= 0xFF
    target.write_bytes(bytes(payload))
    verdict = ef.check_full_package(copy)
    assert verdict["exit_code"] == 3
    assert any(entry["path"] in problem for problem in verdict["problems"])


def test_check_rejects_an_undeclared_file(full_package: Path, tmp_path: Path) -> None:
    import shutil

    copy = tmp_path / "undeclared"
    shutil.copytree(full_package, copy)
    (copy / "smuggled.bin").write_bytes(b"not in the manifest")
    verdict = ef.check_full_package(copy)
    assert verdict["exit_code"] == 3
    assert any("smuggled.bin" in problem for problem in verdict["problems"])


# ---------------------------------------------------------------------------------------
# modality registry: present means real, missing means "here is what would unlock it"
# ---------------------------------------------------------------------------------------
def test_every_modality_is_present_with_files_or_missing_with_a_condition(full_package: Path) -> None:
    manifest = _manifest(full_package)
    assert manifest["modalities"], "the registry must not be empty"
    present = [row for row in manifest["modalities"] if row["status"] == "present"]
    missing = [row for row in manifest["modalities"] if row["status"] == "missing"]
    assert present and missing
    for row in manifest["modalities"]:
        assert row["status"] in ("present", "missing"), row["modality_id"]
        for field in ("modality_id", "role", "family", "unit", "frame", "is_label", "is_truth",
                      "deployment_view_allowed", "permission_code", "permission_reason",
                      "synthetic_only", "derived", "counts", "files"):
            assert field in row, (row["modality_id"], field)
    for row in present:
        assert row["files"], row["modality_id"]
        assert row["counts"]["files"] == len(row["files"])
        for entry in row["files"]:
            assert (full_package / entry["path"]).is_file(), entry["path"]
            assert entry["asset_id"], row["modality_id"]
    for row in missing:
        assert not row["files"], row["modality_id"]
        assert row["unlock_condition"], row["modality_id"]
        assert row["counts"]["files"] == 0


def test_modality_counts_are_recomputable_from_the_files(full_package: Path) -> None:
    manifest = _manifest(full_package)
    by_path = {entry["path"]: entry for entry in manifest["files"]}
    for row in manifest["modalities"]:
        if row["status"] != "present":
            continue
        total = 0
        for entry in row["files"]:
            if entry["path"] in by_path:
                total += by_path[entry["path"]]["bytes"]
        assert row["counts"]["bytes"] == total, row["modality_id"]


def test_missing_modalities_are_the_ones_the_store_really_lacks(full_package: Path) -> None:
    manifest = _manifest(full_package)
    present_ids = {row["modality_id"] for row in manifest["modalities"]
                   if row["status"] == "present"}
    # the fixture store has no display GLB and no context pack anywhere in this checkout
    assert "display_lod_glb.glb_scene" not in present_ids
    assert "context_pack.excavation" not in present_ids
    for modality_id in ("display_lod_glb.glb_scene", "context_pack.excavation"):
        row = next(item for item in manifest["modalities"] if item["modality_id"] == modality_id)
        assert row["status"] == "missing"
        assert row["unlock_condition"]


def test_no_modality_of_a_truth_or_label_role_is_deployable(full_package: Path) -> None:
    manifest = _manifest(full_package)
    for row in manifest["modalities"]:
        if row["role"] in (ROLE_CLEAN_TRUTH, ROLE_PHYSICAL_TRUTH, ROLE_VISIBLE_LABELS,
                           ROLE_LABEL_BUNDLE):
            assert row["deployment_view_allowed"] is False, row["modality_id"]
            assert row["permission_code"] in ("truth_layer", "label_layer", "missing")
    assert manifest["truth_permission"]["truth_roles"]
    for field in manifest["truth_permission"]["deployable_fields"]:
        modality_id = field.split("#", 1)[0]
        name = field.split("#", 1)[1].split(".")[-1]
        assert name not in FORBIDDEN_FEATURE_FIELDS, field
        assert modality_id.split(".")[0] not in (ROLE_CLEAN_TRUTH, ROLE_PHYSICAL_TRUTH,
                                                 ROLE_VISIBLE_LABELS, ROLE_LABEL_BUNDLE)


def test_deployable_set_agrees_with_the_channel_policy_document(full_package: Path) -> None:
    manifest = _manifest(full_package)
    policy = manifest["permission_policy"]
    assert policy["status"] == "ok", "the policy document must be readable in this checkout"
    deploy_arrays = set(policy["deploy_source_arrays"])
    for row in manifest["modalities"]:
        if not row["deployment_view_allowed"]:
            continue
        name = row["family"].split(".")[-1]
        allowed = (name in deploy_arrays
                   or (name in ef.GEOMETRY_DEPLOY_ARRAYS and row["role"] == "obs_fused_geometry")
                   or row["role"] == "display_lod_glb")
        assert allowed, (row["modality_id"], name, sorted(deploy_arrays))
        assert row["permission_code"] != "research_only"


def test_permission_policy_is_recorded_with_a_hash(full_package: Path) -> None:
    policy = _manifest(full_package)["permission_policy"]
    assert policy["hash"].startswith("sha256:")
    assert policy["path"].endswith("view_channels.json")
    # every research-only array is explicitly *not* deployable
    for row in _manifest(full_package)["modalities"]:
        if row["family"].split(".")[-1] in set(policy["research_source_arrays"]):
            assert row["deployment_view_allowed"] is False, row["modality_id"]


# ---------------------------------------------------------------------------------------
# synthetic flag / honesty block
# ---------------------------------------------------------------------------------------
def test_synthetic_flag_is_measured_and_reported(full_package: Path) -> None:
    manifest = _manifest(full_package)
    evidence = manifest["synthetic_evidence"]
    assert evidence["assets_declaring_real_capture"] == 0
    assert evidence["assets_synthetic"] == manifest["generated_from"]["assets_exported"]
    assert "source_kind" in evidence["note"] or "real_capture" in evidence["note"]
    for row in manifest["modalities"]:
        if row["status"] == "present":
            assert row["synthetic_only"] is True
            assert row["synthetic_basis"]


def test_a_real_capture_declaration_flips_the_flag() -> None:
    class _Record:
        meta = {"source_kind": "RAW_CAPTURE"}

    synthetic, basis = ef._is_synthetic(_Record())
    assert synthetic is False and "RAW_CAPTURE" in basis

    class _Synthetic:
        meta = {"source_kind": "SENSOR_SIM"}

    synthetic, basis = ef._is_synthetic(_Synthetic())
    assert synthetic is True and "SENSOR_SIM" in basis

    class _Silent:
        meta = {}

    synthetic, basis = ef._is_synthetic(_Silent())
    assert synthetic is True and "no real-capture declaration" in basis


# ---------------------------------------------------------------------------------------
# the derived fracture-surface subset
# ---------------------------------------------------------------------------------------
def test_derived_interface_subset_is_reproducible_from_the_face_attribute(full_package: Path) -> None:
    manifest = _manifest(full_package)
    row = next(item for item in manifest["modalities"]
               if item["modality_id"] == "fragment_mesh.interface_faces")
    assert row["status"] == "present" and row["derived"] is True
    checked = 0
    for entry in row["files"]:
        payload = np.load(full_package / entry["path"], allow_pickle=False)
        index = payload["iface_face_index"]
        faces = payload["iface_faces"]
        # the same fragment's authoritative face attribute, loaded from its own file
        attribute = None
        for attr_entry in next(item for item in manifest["modalities"]
                               if item["modality_id"] == "fragment_mesh.face_attrs")["files"]:
            if attr_entry["asset_id"] != entry["asset_id"]:
                continue
            with np.load(full_package / attr_entry["path"], allow_pickle=False) as attr:
                attribute = attr["mesh.face__origin_kind"]
        assert attribute is not None, entry["asset_id"]
        expected = np.flatnonzero(attribute.astype(np.int64) == 1)
        assert np.array_equal(index, expected)
        assert faces.shape[0] == expected.size
        assert np.all(payload["iface_area_mm2"] >= 0)
        # the compacted vertex list is exactly the vertex set the subset faces use
        assert payload["iface_vertices"].shape[0] == np.unique(faces).size
        assert payload["iface_vertex_index"].max(initial=-1) < payload["iface_vertices"].shape[0]
        norms = np.linalg.norm(payload["iface_normal"], axis=1)
        assert np.allclose(norms, 1.0, atol=1e-9), norms
        checked += 1
    assert checked >= 1


def test_fragment_without_interface_faces_has_no_derived_file(full_package: Path) -> None:
    manifest = _manifest(full_package)
    row = next(item for item in manifest["modalities"]
               if item["modality_id"] == "fragment_mesh.interface_faces")
    assets = {entry["asset_id"] for entry in row["files"]}
    fragments = next(item for item in manifest["modalities"]
                     if item["modality_id"] == "fragment_mesh.face_attrs")
    all_assets = {entry["asset_id"] for entry in fragments["files"]}
    assert assets < all_assets, "the fragment without INTERFACE faces must not get a subset"


# ---------------------------------------------------------------------------------------
# measurements / findings are recomputable
# ---------------------------------------------------------------------------------------
def test_surface_tag_histogram_and_rim_finding_are_recomputable(full_package: Path) -> None:
    manifest = _manifest(full_package)
    row = next(item for item in manifest["modalities"]
               if item["modality_id"] == "obs_result.surface_tag")
    total = 0
    histogram: dict[str, int] = {}
    for entry in row["files"]:
        with np.load(full_package / entry["path"], allow_pickle=False) as payload:
            for key in payload.files:
                values, counts = np.unique(payload[key], return_counts=True)
                total += int(payload[key].size)
                for value, count in zip(values, counts):
                    histogram[str(int(value))] = histogram.get(str(int(value)), 0) + int(count)
    measured = manifest["measurements"]
    assert measured["obs.surface_tag_total_pixels"]["pixels"] == total
    assert measured["obs.surface_tag_histogram"] == histogram
    finding = manifest["findings"]["fracture_visible_in_2d"]
    assert finding["rim_tag_pixels"] == histogram.get("2", 0)
    assert finding["status"] == ("present" if finding["rim_tag_pixels"] else "absent")
    # the fixture really has one rim pixel: the finding is measured, not assumed
    assert finding["rim_tag_pixels"] == 1


def test_geometry_measurements_do_not_mix_mesh_tags_into_the_2d_finding(full_package: Path) -> None:
    manifest = _manifest(full_package)
    geometry = manifest["measurements"].get("geometry.surface_tag_histogram")
    observation = manifest["measurements"].get("obs.surface_tag_histogram")
    assert geometry and observation
    assert geometry != observation
    assert manifest["measurements"]["geometry.origin_kind_histogram"].get("1", 0) == 2


# ---------------------------------------------------------------------------------------
# per-fragment index and scope selection
# ---------------------------------------------------------------------------------------
def test_fragment_index_points_at_real_files(full_package: Path) -> None:
    manifest = _manifest(full_package)
    for fragment in (FRAGMENT_A, FRAGMENT_B):
        block = manifest["fragments"][fragment]
        assert block["mother_id"] == MOTHER
        assert block["modalities"], fragment
        assert block["missing"], "a fragment must carry the shared missing list"
        for modality_id, entries in block["modalities"].items():
            for entry in entries:
                assert (full_package / entry["path"]).is_file(), entry["path"]
                assert entry["modality_id"] == modality_id


def test_store_scoped_asset_lands_outside_the_fragment_trees(full_package: Path) -> None:
    manifest = _manifest(full_package)
    qa = [row for row in manifest["assets"] if row["role"] == "qa_report"]
    assert len(qa) == 1
    assert qa[0]["scope"] == "store"
    assert qa[0]["fragment_ids"] == []
    payload = [path for path in qa[0]["files"] if not path.startswith("assets/")]
    assert payload, "a store-scoped asset must still write its payload"
    assert all(path.startswith("store/qa_report/") for path in payload)
    assert not [path for path in qa[0]["files"] if path.startswith("fragments/")]


def test_limit_is_recorded_as_a_scoped_run(full_store: dict, tmp_path: Path) -> None:
    out = tmp_path / "limited"
    manifest = ef.export_full_package(full_store["root"], out, limit=1)
    assert manifest["selection"]["mode"] == "limit"
    assert manifest["selection"]["fragments_exported"] == 1
    assert manifest["selection"]["fragments_available"] == 2
    assert manifest["counts"]["fragments"] == 1
    assert list(manifest["fragments"]) == [FRAGMENT_A]


def test_limit_does_not_trim_the_modalities_of_a_selected_fragment(full_store: dict,
                                                                  full_package: Path,
                                                                  tmp_path: Path) -> None:
    limited = ef.export_full_package(full_store["root"], tmp_path / "limited2", limit=1)
    full = {row["modality_id"]: row for row in _manifest(full_package)["modalities"]}
    present = [row["modality_id"] for row in limited["modalities"] if row["status"] == "present"]
    assert present, "the scoped run must still write the modalities of the selected fragment"
    for modality_id in present:
        assert full[modality_id]["status"] == "present", modality_id


def test_unknown_flavour_is_refused(full_store: dict, tmp_path: Path) -> None:
    from synlab.errors import SynLabError

    with pytest.raises(SynLabError):
        ef.export_full_package(full_store["root"], tmp_path / "nope", flavor="trimmed")


# ---------------------------------------------------------------------------------------
# ablation index
# ---------------------------------------------------------------------------------------
def test_ablation_index_covers_the_groups_and_reports_availability(full_package: Path) -> None:
    index = _index(full_package)
    assert index["schema"] == ef.ABLATION_INDEX_SCHEMA
    assert len(index["groups"]) == len(ef.ABLATION_GROUPS)
    summary = index["summary"]
    assert summary["groups"] == len(index["groups"])
    assert summary["present"] + summary["partial"] + summary["missing"] == summary["groups"]
    for group in index["groups"]:
        assert group["availability"] in ("present", "partial", "missing")
        assert group["question"], group["group_id"]
        assert group["switch"]["on"] and group["switch"]["off"]
        assert group["switch"]["loader_flag"] == f"--groups {group['group_id']}"
        assert group["dependent_metrics"], group["group_id"]
        if group["availability"] in ("present", "partial"):
            assert group["fields"], group["group_id"]
            assert group["counts"]["modalities_present"] >= 1
            for field in group["fields"]:
                modality_id = field.split("#", 1)[0]
                row = next(item for item in _manifest(full_package)["modalities"]
                           if item["modality_id"] == modality_id)
                assert row["status"] == "present", field
        else:
            assert group["missing"], group["group_id"]
            for row in group["missing"]:
                assert row["unlock_condition"]


def test_ablation_groups_that_are_missing_say_what_would_unlock_them(full_package: Path) -> None:
    index = _index(full_package)
    missing = [group for group in index["groups"] if group["availability"] == "missing"]
    assert missing, "the fixture store cannot satisfy every group; that must be reported"
    for group in missing:
        assert group["counts"]["files"] == 0
        assert all(row["unlock_condition"] for row in group["missing"])
    by_id = {group["group_id"]: group for group in index["groups"]}
    # the fracture groups are backed by the fixture and must be available
    assert by_id["G-FRAC-ATTR"]["availability"] in ("present", "partial")
    assert by_id["G-FRAC-IFACE-DERIVED"]["availability"] in ("present", "partial")
    # the ground-truth group has truth geometry but no visible layer in this fixture
    assert by_id["G-LABEL-VISIBLE"]["availability"] == "missing"


def test_group_field_patterns_match_the_fields_they_name(full_package: Path) -> None:
    import fnmatch

    index = _index(full_package)
    for group in index["groups"]:
        for field in group["fields"]:
            assert any(fnmatch.fnmatchcase(field, pattern) or
                       fnmatch.fnmatchcase(field.split("#", 1)[1], pattern)
                       for pattern in group["field_patterns"]), (group["group_id"], field)


def test_loader_group_selection_is_not_empty_for_available_groups(full_package: Path) -> None:
    sys.path.insert(0, str(REPO_ROOT / "tools"))
    import load_full_package as lfp

    manifest = _manifest(full_package)
    index = _index(full_package)
    modalities = {row["modality_id"]: row for row in manifest["modalities"]}
    for group in index["groups"]:
        if group["availability"] == "missing":
            assert not lfp.group_fields(group, modalities)
            continue
        selected = lfp.group_fields(group, modalities)
        assert selected, group["group_id"]
        for modality_id, key, rel in selected:
            assert (full_package / rel).is_file()


# ---------------------------------------------------------------------------------------
# the real package, when this checkout has one
# ---------------------------------------------------------------------------------------
def test_real_full_package_is_consistent(real_package: Path) -> None:
    verdict = ef.check_full_package(real_package)
    assert verdict["ok"], verdict["problems"][:10]
    manifest = _manifest(real_package)
    assert manifest["flavor"] == "full"
    assert manifest["counts"]["files"] > 0
    assert manifest["counts"]["fragments"] > 0
    for row in manifest["modalities"]:
        if row["status"] == "present":
            for entry in row["files"]:
                assert (real_package / entry["path"]).is_file()
        else:
            assert row["unlock_condition"]
