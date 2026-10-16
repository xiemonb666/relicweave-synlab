"""Storage-layer tests: the package loader/checker, the zarr reader and the fixed writer.

The package-backed tests read the real exported package when it is present and ``skip`` (never
fail, never fabricate) when it is not -- a missing artifact is a fact about the checkout, not a
regression of this code.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pytest

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
for path in (str(REPO_ROOT),):
    if path not in sys.path:
        sys.path.insert(0, path)

from tools import load_package as lp                                    # noqa: E402

PACKAGE = REPO_ROOT / "data/a12_exports/closed_loop/training_package"
PACKAGE_V2 = REPO_ROOT / "data/a12_exports/closed_loop/training_package_v2"


def _package() -> Path:
    for candidate in (PACKAGE, PACKAGE_V2):
        if (candidate / "export_manifest.json").is_file():
            return candidate
    pytest.skip("no exported training package in this checkout")


# ---------------------------------------------------------------------------------------
# the fixed writer (pure unit tests: no package required)
# ---------------------------------------------------------------------------------------
def _tile(n_views: int = 2, height: int = 48, width: int = 64, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, size=(n_views, height, width, 3), dtype=np.uint8)


def test_token_block_is_not_a_scaled_broadcast() -> None:
    """D1 regression: the token columns must be real content, not copies of one scalar."""
    from synlab.storage.export import TOKEN_DIM, _token_arrays

    tile = _tile()
    payload = _token_arrays(tile, np.ones(tile.shape[:3], dtype=bool))
    tokens = np.asarray(payload["tokens"], dtype=np.float64)
    assert tokens.shape[1] == TOKEN_DIM
    assert tokens.shape[0] == payload["token_input"].size
    matrix = tokens
    singular = np.linalg.svd(matrix, compute_uv=False)
    assert singular[1] / singular[0] > 1e-3, "token block collapsed to rank 1"
    first = matrix[:, 0]
    predicted = first[:, None] * (1.0 - 1e-6 * np.arange(matrix.shape[1]))[None, :]
    assert np.abs(matrix - predicted).max() > 1e-3, "token block is still a scaled broadcast"
    # each token really carries its own patch: tokens of one view are not all equal
    per_view = 48
    assert not np.allclose(matrix[0], matrix[1])
    assert np.unique(matrix[:per_view].std(axis=0)).size > 1


def test_view_position_uses_the_delivered_pose() -> None:
    """D2 regression: a placeholder ``u_position_mm = 0.0`` must not win over a real ``T_WC``."""
    from synlab.storage.export import _view_u_position_mm

    pose = np.eye(4, dtype=np.float64)
    pose[0, 3] = -12.5
    value, source = _view_u_position_mm({"u_position_mm": 0.0}, {"v000.T_WC": pose}, 0)
    assert value == pytest.approx(-12.5)
    assert source == "T_WC[0,3]"
    value, source = _view_u_position_mm({"u_position_mm": 3.25}, {}, 0)
    assert value == pytest.approx(3.25)
    assert source == "view_meta.u_position_mm"
    value, source = _view_u_position_mm({}, {}, 0)
    assert value is None and source == "unavailable"


def test_frame_id_comes_from_the_delivered_views() -> None:
    """D3 regression: a point must be matched to the view that really renders it."""
    from synlab.storage.export import _frame_ids_from_views

    # view 0 renders the plane z = 5 mm, view 1 the plane z = 50 mm; both project identity-K
    points = np.array([[0.0, 0.0, 5.0], [0.0, 0.0, 50.0], [0.0, 0.0, -5.0]], dtype=np.float32)
    arrays = {
        "v000.T_WC": np.eye(4),
        "v000.K": np.eye(3),
        "v000.depth_z": np.full((8, 8), 5.0),
        "v001.T_WC": np.eye(4),
        "v001.K": np.eye(3),
        "v001.depth_z": np.full((8, 8), 50.0),
    }
    frame_id, report = _frame_ids_from_views(points, arrays, 2)
    assert frame_id[0] == 0, "the point on view 0's plane must belong to view 0"
    assert frame_id[1] == 1, "the point on view 1's plane must belong to view 1"
    assert frame_id[2] == -1, "a point behind every camera must stay unmatched"
    assert report["source"] == "T_WC+K+depth_z"
    assert report["matched"] == 2 and report["unmatched"] == 1
    assert not np.array_equal(frame_id, np.arange(3) % 2)

    frame_id, report = _frame_ids_from_views(points, {}, 2)
    assert set(frame_id.tolist()) == {-1}
    assert report["source"] == "unavailable"


# ---------------------------------------------------------------------------------------
# loader API
# ---------------------------------------------------------------------------------------
def test_loader_reads_relations_and_labels() -> None:
    package = _package()
    relations = lp.load_relations(package)
    assert set(relations.columns) >= {"query", "candidate", "kind", "valid", "loss_mask"}
    for layer in ("clean", "physical", "visible"):
        frame = lp.load_labels(package, layer)
        assert not frame.empty
    queries = lp.load_queries(package)
    assert not queries.empty


def test_load_arrays_npz_matches_zarr() -> None:
    package = _package()
    pkg = lp.Package(package)
    fragment = next(iter(pkg.geometry_index["rows"]))
    from_npz = lp.load_arrays(package, fragment, kind="geometry", source="npz")
    from_zarr = lp.load_arrays(package, fragment, kind="geometry", source="zarr")
    assert set(from_npz) == set(from_zarr)
    for name, array in from_npz.items():
        assert array.shape == from_zarr[name].shape
        assert array.tobytes() == from_zarr[name].tobytes(), f"{name} differs between replicas"
    report = lp.zarr_npz_consistency(package)
    assert report["ok"] and report["arrays_checked"] > 0
    assert report["arrays_checked"] == report["arrays_identical"]


def test_load_arrays_all_fragments_and_obs_members() -> None:
    package = _package()
    geometry = lp.load_arrays(package, kind="geometry")
    assert geometry and all(isinstance(v, dict) for v in geometry.values())
    pkg = lp.Package(package)
    fragment = next(iter(pkg.obs_index["rows"]))
    obs = lp.load_arrays(package, fragment, kind="obs")
    assert {"tiles", "valid", "view_pos"} <= set(obs)
    assert obs["tiles"].ndim == 4 and obs["tiles"].shape[-1] == 3


def test_iter_batches_yields_real_batches() -> None:
    package = _package()
    seen = 0
    for item in lp.iter_batches(package, batch_size=2):
        seen += 1
        assert set(item) >= {"index", "rows", "features", "supervision", "provenance"}
        assert item["provenance"]["fragment_ids"]
        for payload in item["features"].values():
            assert "global_rgb" in payload and "local_tokens" in payload
            tokens = np.asarray(payload["local_tokens"])
            assert tokens.ndim == 2 and tokens.shape[1] in (0, 256)
        if item["labels"]:
            pair = np.asarray(item["labels"]["pair_index"])
            assert pair.ndim == 3 and pair.shape[-1] == 2
        break
    assert seen == 1


def test_supervision_table_covers_the_five_tasks() -> None:
    package = _package()
    built = lp.build_batch(package)
    table = lp.supervision_table(built)
    for task in lp.TASKS:
        entry = table[task]
        assert isinstance(entry["n_valid"], int) and isinstance(entry["n_allowed"], int)
        assert entry["why"], "a task without supervision must say why"
        if entry["n_allowed"] == 0:
            assert entry["unlock_condition"] or entry["blocked_by"]
    assert table["_z_valid_fragments"] >= 0


def test_encoder_valid_matches_the_model_definition() -> None:
    package = _package()
    built = lp.build_batch(package)
    z_valid = lp.encoder_valid(built["bundle"])
    bundle = built["bundle"]
    expected = ((np.asarray(bundle.global_valid).any(axis=tuple(
        range(1, np.asarray(bundle.global_valid).ndim))))
        | ((np.asarray(bundle.point_valid) | np.asarray(bundle.normal_valid))
           & np.asarray(bundle.scale_valid).reshape(-1, 1)).any(axis=1)
        | np.asarray(bundle.token_valid).any(axis=1))
    assert np.array_equal(z_valid, expected.astype(bool))


# ---------------------------------------------------------------------------------------
# data card + check
# ---------------------------------------------------------------------------------------
def test_data_card_is_scanned_not_hardcoded() -> None:
    package = _package()
    card, scan = lp.build_data_card(package, hash_files=False, sample_fragments=1)
    for key in ("identity", "package", "columns", "arrays", "splits", "labels", "tasks",
                "honest_boundaries", "mini_batch"):
        assert key in card, key
    identity = card["identity"]
    assert identity["release_id"] == scan["release_id"]
    assert identity["manifest_hash"] == scan["manifest_hash"]
    assert identity["run_id"] in ("missing",) or isinstance(identity["run_id"], str)
    assert identity["git_head"]["head"] != ""
    assert identity["registry"]["fingerprint"].startswith("sha256:")
    # every declared file is in the card with a real size and a purpose
    assert len(card["package"]["files"]) == len(scan["files"])
    for entry in card["package"]["files"]:
        assert entry["bytes"] is not None and entry["purpose"]
        assert entry["unit"] and entry["frame"]
    # the column dictionary is measured, not invented
    for path, table in card["columns"].items():
        assert table["rows"] >= 0 and table["columns"]
        for name, column in table["columns"].items():
            assert "missing_rate" in column and "is_label" in column
    # the five tasks are described with real denominators
    for task in lp.TASKS:
        assert card["tasks"][task]["measured"] is not None
    # honest boundaries always name an impact and an unlock condition
    for boundary in card["honest_boundaries"]:
        assert boundary["impact"] and boundary["unlock_condition"] and boundary["status"]


def test_check_package_accepts_the_package_and_a_card_artifact() -> None:
    package = _package()
    verdict = lp.check_package(package)
    assert verdict["checks"]["sha256"]["ok"]
    assert verdict["checks"]["splits"]["ok"]
    assert verdict["exit_code"] == (lp.EXIT_OK if verdict["ok"] else lp.EXIT_INCONSISTENT)
    if verdict["ok"]:
        assert verdict["exit_code"] == 0
    else:                                   # a package without a card is inconsistent by design
        assert any(lp.CARD_NAME in problem for problem in verdict["problems"])


def test_check_package_detects_a_tampered_file(tmp_path: Path) -> None:
    package = _package()
    copy = tmp_path / "pkg"
    shutil.copytree(package, copy)
    target = copy / "research/relations.parquet"
    payload = bytearray(target.read_bytes())
    payload[-1] ^= 0xFF
    target.write_bytes(bytes(payload))
    verdict = lp.check_package(copy)
    assert verdict["exit_code"] == lp.EXIT_INCONSISTENT
    assert any("relations.parquet" in problem for problem in verdict["problems"])


def test_check_package_detects_an_undeclared_file(tmp_path: Path) -> None:
    package = _package()
    copy = tmp_path / "pkg"
    shutil.copytree(package, copy)
    (copy / "smuggled.bin").write_bytes(b"not in the manifest")
    verdict = lp.check_package(copy)
    assert verdict["exit_code"] == lp.EXIT_INCONSISTENT
    assert any("smuggled.bin" in problem for problem in verdict["problems"])


def test_readme_contains_the_measured_numbers() -> None:
    package = _package()
    card, scan = lp.build_data_card(package, hash_files=False, sample_fragments=1)
    readme = lp.render_readme(json.loads(json.dumps(lp._jsonable(card))))
    assert card["package"]["files"][0]["path"] in readme
    assert str(card["labels"].get("eligible_as_negative")) in readme
    for boundary in card["honest_boundaries"]:
        assert boundary["id"] in readme
