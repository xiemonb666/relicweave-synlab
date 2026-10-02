"""Asset routes: role whitelist, payload integrity, path rejection, workspace scoping."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from conftest import create_job, run_worker_once, valid_spec

from synlab.api.security import assert_within, safe_join
from synlab.errors import SynLabError


def test_asset_listing_without_assets_gives_an_empty_state_not_placeholders(researcher):
    body = researcher.get("/api/synlab/assets").json()
    assert body["count"] == 0
    assert body["items"] == []
    assert "never fabricates" in body["empty_reason"]
    assert body["has_more"] is False
    assert body["next_cursor"] is None


def test_asset_metadata_and_file_download_verify_hash(store_root, researcher, cube_asset):
    asset = researcher.get(f"/api/synlab/assets/{cube_asset}").json()["asset"]
    assert asset["role"] == "mother_mesh"
    assert asset["unit"] == "mm"
    assert asset["frame"] == "W_mm"
    assert asset["integrity"]["ok"] is True
    assert asset["file_urls"]

    response = researcher.get(f"/api/synlab/assets/{cube_asset}/files/mother_mesh",
                              params={"key": "arrays"})
    assert response.status_code == 200
    assert response.headers["X-SynLab-Hash-Verified"] in ("recorded", "first_seen")
    assert response.headers["X-SynLab-File-Sha256"].startswith("sha256:")
    assert response.headers["X-SynLab-Asset-Role"] == "mother_mesh"
    assert len(response.content) > 0

    # tamper with the payload on disk: the next download must refuse
    target = store_root / "assets" / cube_asset / "arrays.npz"
    assert target.exists()
    original = target.read_bytes()
    target.write_bytes(original + b"tampered")
    try:
        tampered = researcher.get(f"/api/synlab/assets/{cube_asset}/files/mother_mesh",
                                  params={"key": "arrays"})
        assert tampered.status_code == 409
        assert tampered.json()["error"]["code"] == "ASSET_HASH_MISMATCH"
        detail = researcher.get(f"/api/synlab/assets/{cube_asset}").json()["asset"]
        assert detail["integrity"]["ok"] is False
    finally:
        target.write_bytes(original)


def test_file_role_must_be_on_the_whitelist_and_match_the_asset(store_root, researcher, cube_asset):
    unknown = researcher.get(f"/api/synlab/assets/{cube_asset}/files/../../etc/passwd")
    assert unknown.status_code in (403, 404)
    assert unknown.json()["error"]["code"] in ("FILE_ROLE_NOT_SERVABLE", "NOT_FOUND")

    not_a_role = researcher.get(f"/api/synlab/assets/{cube_asset}/files/definitely_not_a_role")
    assert not_a_role.status_code == 403
    assert not_a_role.json()["error"]["code"] == "FILE_ROLE_NOT_SERVABLE"

    mismatched = researcher.get(f"/api/synlab/assets/{cube_asset}/files/display_lod_glb")
    assert mismatched.status_code == 409
    assert mismatched.json()["error"]["code"] == "FILE_ROLE_MISMATCH"

    bad_key = researcher.get(f"/api/synlab/assets/{cube_asset}/files/mother_mesh",
                             params={"key": "../../meta.json"})
    assert bad_key.status_code == 404


def test_asset_id_must_be_a_registered_reference(researcher):
    for candidate in ("not-an-asset", "asset_zzzz", "../../etc/passwd"):
        response = researcher.get(f"/api/synlab/assets/{candidate}")
        assert response.status_code in (400, 404, 422), candidate


def test_input_refs_reject_paths_and_injection(researcher):
    for ref in ("../../etc/passwd", "C:\\Windows\\System32\\config\\SAM", "file:///etc/passwd",
                "asset_ok/../../secret", "https://example.invalid/asset"):
        response = create_job(researcher, stage="freeze_spec", input_refs=[ref],
                              key=f"path-{abs(hash(ref))}")
        assert response.status_code == 400, (ref, response.status_code, response.text)
        assert response.json()["error"]["code"] == "PATH_REJECTED", (ref, response.text)
    well_formed_but_unknown = create_job(researcher, stage="freeze_spec",
                                         input_refs=["asset_0000000000000000abcd"],
                                         key="path-unknown")
    assert well_formed_but_unknown.status_code == 404


def test_workspace_scoping_hides_other_workspaces(store_root, cube_asset):
    from conftest import make_client

    other = make_client(store_root, "researcher", workspace="other-ws")
    try:
        listing = other.get("/api/synlab/assets").json()
        assert listing["count"] == 0
        assert listing["workspace"] == "other-ws"
        denied = other.get(f"/api/synlab/assets/{cube_asset}")
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "WORKSPACE_FORBIDDEN"
        denied_job = create_job(other, stage="freeze_spec", input_refs=[cube_asset], key="ws-1")
        assert denied_job.status_code == 403
    finally:
        other.close()


def test_safe_join_and_assert_within_block_escapes(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    assert safe_join(root, "a/b.json") == (root / "a" / "b.json").resolve()
    for bad in ("../escape", "a/../../escape", "/etc/passwd", "\\\\server\\share"):
        with pytest.raises(Exception):
            safe_join(root, bad)
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(Exception):
        assert_within(root, outside / "file.bin")


def test_symlink_escape_is_refused(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.bin").write_bytes(b"secret")
    link = root / "link"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this host does not allow creating symlinks without elevation")
    with pytest.raises(Exception):
        assert_within(root, link / "secret.bin")


def test_asset_listing_pagination_is_stable(store_root, researcher):
    from conftest import make_client
    from synlab.api.integrity import record_integrity
    from synlab.roles import ROLE_RUN_SPEC

    store = make_client(store_root, "researcher").app.state.ctx.store
    for index in range(4):
        record = store.commit_asset(role=ROLE_RUN_SPEC, schema="synlab.run_spec.v1", unit="1",
                                    frame="none", payload={"index": index},
                                    meta={"workspace": "default"}, qa_status="QA_PASS")
        record_integrity(store, record.asset_id)
    first = researcher.get("/api/synlab/assets", params={"limit": 2, "role": "run_spec"}).json()
    assert first["count"] == 2 and first["has_more"] is True
    seen = [item["asset_id"] for item in first["items"]]
    page = researcher.get("/api/synlab/assets",
                          params={"limit": 2, "role": "run_spec",
                                  "cursor": first["next_cursor"]}).json()
    seen.extend(item["asset_id"] for item in page["items"])
    assert len(seen) == len(set(seen)) == 4


def test_verify_all_files_reports_missing_payload(store_root, researcher, cube_asset):
    target = store_root / "assets" / cube_asset / "arrays.npz"
    original = target.read_bytes()
    target.unlink()
    try:
        detail = researcher.get(f"/api/synlab/assets/{cube_asset}").json()["asset"]
        assert detail["integrity"]["ok"] is False
        assert any("arrays" in problem for problem in detail["integrity"]["problems"])
    finally:
        target.write_bytes(original)


def test_freeze_spec_verifies_input_hashes_before_committing(store_root, researcher, cube_asset):
    created = create_job(researcher, stage="freeze_spec", key="freeze-hash",
                         input_refs=[cube_asset]).json()
    target = store_root / "assets" / cube_asset / "arrays.npz"
    original = target.read_bytes()
    target.write_bytes(original + b"corrupt")
    try:
        report = run_worker_once(store_root)
        assert report["failed"] >= 1
    finally:
        target.write_bytes(original)
    job = researcher.get(f"/api/synlab/jobs/{created['job_id']}").json()["job"]
    assert job["state"] in ("FAILED", "RETRYABLE")
    assert job["error"]["code"] == "ASSET_HASH_MISMATCH"


def test_missing_release_and_asset_return_structured_404(researcher):
    assert researcher.get("/api/synlab/assets/asset_0000000000000000ffff").status_code == 404
    body = researcher.get("/api/synlab/assets/asset_0000000000000000ffff").json()
    assert body["ok"] is False
    assert body["error"]["request_id"]


def test_error_messages_never_leak_server_paths(store_root, researcher):
    response = researcher.get("/api/synlab/assets/asset_0000000000000000ffff")
    text = response.text
    assert str(store_root).replace("\\", "\\\\") not in text
    assert str(store_root) not in text
    assert "C:\\" not in text


def test_resolve_file_helper_rejects_unregistered_key(store_root, cube_asset):
    from synlab.api.integrity import resolve_file
    from synlab.api.problems import ApiProblem
    from synlab.storage.store import AssetStore

    store = AssetStore(store_root)
    # resolve_file is the HTTP-facing resolver, so it reports an ApiProblem; both it and
    # SynLabError are structured refusals, and neither returns a path for an unknown key.
    with pytest.raises((SynLabError, ApiProblem)) as excinfo:
        resolve_file(store, cube_asset, "nope")
    raised = excinfo.value
    code = getattr(raised, "code", None)
    assert code == "NOT_FOUND", code
    assert "nope" in str(raised)
    # the unregistered key must never be turned into a filesystem path
    assert not hasattr(raised, "path")
