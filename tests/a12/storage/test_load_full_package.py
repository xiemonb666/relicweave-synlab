"""Tests for ``tools/load_full_package.py`` (group loading, ``--check``, exit codes).

The loader must be usable **without torch** and must never invent data: a group is loaded by
matching the manifest's own field names, and every printed number is computed from the loaded
bytes.  The tests therefore compare the loader's output against a direct ``np.load`` of the
same files.
"""
from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import numpy as np
import pytest

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
for path in (str(REPO_ROOT), str(HERE), str(REPO_ROOT / "tools")):
    if path not in sys.path:
        sys.path.insert(0, path)

from full_fixture import (  # noqa: E402,F401  (fixtures are re-exported by name)
    FRAGMENT_A,
    full_package,
    full_store,
    real_package,
)
from synlab.storage import export_full as ef  # noqa: E402
from tools import load_full_package as lfp  # noqa: E402


def _manifest(package: Path) -> dict:
    return json.loads((package / "manifest.json").read_text(encoding="utf-8"))


def _run(argv: list[str]) -> tuple[int, str]:
    buffer, errors = io.StringIO(), io.StringIO()
    with redirect_stdout(buffer), redirect_stderr(errors):
        code = lfp.main(argv)
    return code, buffer.getvalue() + errors.getvalue()


# ---------------------------------------------------------------------------------------
# --check
# ---------------------------------------------------------------------------------------
def test_check_returns_zero_for_a_consistent_package(full_package: Path) -> None:
    code, out = _run(["--package", str(full_package), "--check"])
    assert code == lfp.EXIT_OK, out
    verdict = json.loads(out)
    assert verdict["ok"] is True
    assert verdict["files_declared"] == verdict["files_on_disk"]
    assert verdict["bytes_on_disk"] > 0


def test_check_returns_three_for_a_missing_manifest(tmp_path: Path) -> None:
    code, out = _run(["--package", str(tmp_path), "--check"])
    assert code == lfp.EXIT_INCONSISTENT, out


def test_check_returns_three_when_a_file_is_deleted(full_package: Path, tmp_path: Path) -> None:
    import shutil

    copy = tmp_path / "missing_file"
    shutil.copytree(full_package, copy)
    manifest = _manifest(copy)
    victim = copy / next(item["path"] for item in manifest["files"] if item["format"] == "npz")
    victim.unlink()
    code, out = _run(["--package", str(copy), "--check"])
    assert code == lfp.EXIT_INCONSISTENT
    assert "declared but absent" in out


# ---------------------------------------------------------------------------------------
# group listing / selection
# ---------------------------------------------------------------------------------------
def test_list_groups_prints_the_index(full_package: Path) -> None:
    code, out = _run(["--package", str(full_package), "--list-groups"])
    assert code == lfp.EXIT_OK
    index = json.loads((full_package / "ablation_index.json").read_text(encoding="utf-8"))
    for group in index["groups"]:
        assert group["group_id"] in out
    assert "missing" in out


def test_unknown_group_is_a_usage_error(full_package: Path) -> None:
    code, out = _run(["--package", str(full_package), "--groups", "G-NOT-A-GROUP"])
    assert code == lfp.EXIT_USAGE
    assert "unknown group" in out


def test_no_action_is_a_usage_error(full_package: Path) -> None:
    code, _ = _run(["--package", str(full_package)])
    assert code == lfp.EXIT_USAGE


# ---------------------------------------------------------------------------------------
# loading by group: shapes and counts are real
# ---------------------------------------------------------------------------------------
def test_load_group_shapes_match_a_direct_numpy_load(full_package: Path) -> None:
    manifest = _manifest(full_package)
    index = json.loads((full_package / "ablation_index.json").read_text(encoding="utf-8"))
    group = lfp.find_group(index, "G-IMG-RGB")
    report = lfp.load_group(full_package, group, manifest)
    assert report["fields_selected"] > 0
    assert report["fragments"], "the fixture has one observed fragment"
    checked_keys: set[str] = set()
    for fragment, entry in report["fragments"].items():
        for modality_id, shapes in entry["modalities"].items():
            assert modality_id == "obs_result.rgb"
            for key, info in shapes.items():
                checked_keys.add(key)
                assert key == "v000.rgb"
                path = full_package / "fragments" / FRAGMENT_A / (
                    f"obs_result.rgb__{_asset_id(manifest, 'obs_result.rgb')}.npz")
                with np.load(path, allow_pickle=False) as payload:
                    direct = payload[key]
                assert info["shape"] == list(direct.shape)
                assert info["dtype"] == str(direct.dtype)
                assert info["elements"] == int(direct.size)
                assert info["bytes"] == int(direct.nbytes)
    assert checked_keys == {"v000.rgb"}


def _asset_id(manifest: dict, modality_id: str) -> str:
    row = next(item for item in manifest["modalities"] if item["modality_id"] == modality_id)
    return row["files"][0]["asset_id"]


def test_boolean_and_integer_measurements_are_computed_from_bytes(full_package: Path) -> None:
    manifest = _manifest(full_package)
    index = json.loads((full_package / "ablation_index.json").read_text(encoding="utf-8"))
    deploy = lfp.load_group(full_package, lfp.find_group(index, "G-MASK-DEPLOY"), manifest)
    true_counts = [info["true_count"] for entry in deploy["fragments"].values()
                   for shapes in entry["modalities"].values()
                   for info in shapes.values()]
    assert true_counts and all(isinstance(value, int) for value in true_counts)
    assert max(true_counts) > 0, "the fixture deployment mask has a real non-empty region"

    tag = lfp.load_group(full_package, lfp.find_group(index, "G-IMG-TAG"), manifest)
    histograms = [info["histogram"] for entry in tag["fragments"].values()
                  for shapes in entry["modalities"].values()
                  for info in shapes.values() if "histogram" in info]
    assert histograms, "an integer tag map must report its histogram"
    assert histograms[0].get("2") == 1, "the fixture has exactly one rim pixel"


def test_group_selection_never_leaks_another_group_s_field(full_package: Path) -> None:
    manifest = _manifest(full_package)
    index = json.loads((full_package / "ablation_index.json").read_text(encoding="utf-8"))
    modalities = {row["modality_id"]: row for row in manifest["modalities"]}
    rgb = lfp.group_fields(lfp.find_group(index, "G-IMG-RGB"), modalities)
    depth = lfp.group_fields(lfp.find_group(index, "G-IMG-DEPTH"), modalities)
    assert {item[1] for item in rgb} == {"v000.rgb"}
    assert {item[1] for item in depth} == {"v000.depth_z"}
    assert not ({item[2] for item in rgb} & {item[2] for item in depth})


def test_fragment_filter_limits_the_loaded_fragments(full_package: Path) -> None:
    manifest = _manifest(full_package)
    index = json.loads((full_package / "ablation_index.json").read_text(encoding="utf-8"))
    group = lfp.find_group(index, "G-FRAC-ATTR")
    everyone = lfp.load_group(full_package, group, manifest)
    one = lfp.load_group(full_package, group, manifest, fragments=[FRAGMENT_A])
    assert set(one["fragments"]) == {FRAGMENT_A}
    assert len(one["fragments"]) <= len(everyone["fragments"])


def test_missing_group_loads_nothing_and_says_why(full_package: Path) -> None:
    index = json.loads((full_package / "ablation_index.json").read_text(encoding="utf-8"))
    empty = [group for group in index["groups"] if group["availability"] == "missing"]
    assert empty
    code, out = _run(["--package", str(full_package), "--groups", empty[0]["group_id"]])
    assert code == lfp.EXIT_OK
    assert "availability=missing" in out
    assert "unlock condition" in out


def test_verbose_output_prints_shapes_for_an_available_group(full_package: Path) -> None:
    code, out = _run(["--package", str(full_package), "--groups", "G-IMG-RGB", "--verbose"])
    assert code == lfp.EXIT_OK
    assert "obs_result.rgb#v000.rgb" in out
    assert "[8, 8, 3]" in out, out


def test_summary_lists_present_and_missing_modalities(full_package: Path) -> None:
    code, out = _run(["--package", str(full_package), "--summary"])
    assert code == lfp.EXIT_OK
    assert "modalities present=" in out
    assert "missing (modality_id -> unlock condition):" in out
    assert "context_pack.excavation" in out


def test_loader_does_not_require_torch(full_package: Path) -> None:
    """The loader must work with torch absent; it only prints tensor shapes when present."""
    import builtins

    real_import = builtins.__import__

    def _blocked(name: str, *args: object, **kwargs: object) -> object:
        if name == "torch" or name.startswith("torch."):
            raise ImportError("torch blocked by the test")
        return real_import(name, *args, **kwargs)

    builtins.__import__ = _blocked
    try:
        code, out = _run(["--package", str(full_package), "--groups", "G-IMG-RGB"])
    finally:
        builtins.__import__ = real_import
    assert code == lfp.EXIT_OK
    assert "torch not importable" in out


# ---------------------------------------------------------------------------------------
# the real package, when this checkout has one
# ---------------------------------------------------------------------------------------
def test_real_package_check_and_one_group(real_package: Path) -> None:
    code, out = _run(["--package", str(real_package), "--check"])
    assert code == lfp.EXIT_OK, out[:2000]
    manifest = _manifest(real_package)
    index = json.loads((real_package / "ablation_index.json").read_text(encoding="utf-8"))
    available = [group for group in index["groups"]
                 if group["availability"] in ("present", "partial")]
    assert available, "the real export must satisfy at least one ablation group"
    group = available[0]
    report = lfp.load_group(real_package, group, _manifest(real_package),
                            max_files=4)
    assert report["fields_selected"] > 0
    assert report["fragments"]
    for entry in report["fragments"].values():
        assert entry["arrays"] > 0
