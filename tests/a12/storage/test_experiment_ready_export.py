"""The merged, experiment-ready export: construction rules and the shipped artifacts.

Two layers of tests:

* **pure unit tests** -- they build a tiny tree in ``tmp_path`` and pin the two construction
  rules the merge depends on: every annotation flag names the real source it came from, and
  ``declare()`` re-derives the file set / hashes from the bytes on disk (so an undeclared or a
  stale file can never survive a ``--check``).
* **package-backed tests** -- they read the real merged package when it is present and ``skip``
  (never fabricate) when it is not.  They assert that every count published by a dimension index
  equals the count of the bytes that are actually on disk, that the deploy view of the merged
  package carries no truth channel and no answer field, and that the ablation index covers every
  merged dimension with a switch field and both gain directions.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

PACKAGE = REPO_ROOT / "data/a12_exports/experiment_ready/training_package"
TOOL = REPO_ROOT / "tools/a12_experiment_ready_export.py"

TRUTH_CHANNELS = ("id_map", "surface_tag", "T_WC", "dist")
TRUTH_PREFIXES = ("iface_", "corr_")
REQUIRED_GROUPS = {"ABL_ROI_VIEWS", "ABL_SYNTHETIC_EXTRAS", "ABL_CONTEXT", "ABL_DEGRADE",
                   "ABL_HARD_NEGATIVES"}
REQUIRED_GROUP_FIELDS = ("dimension", "group_id", "switch_field", "availability", "hypothesis",
                         "positive_gain", "negative_gain", "evidence")


def _tool():
    spec = importlib.util.spec_from_file_location("_experiment_ready_export", TOOL)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _package() -> Path:
    if not (PACKAGE / "export_manifest.json").is_file():
        pytest.skip("the merged experiment-ready package is not present in this checkout")
    return PACKAGE


# ---------------------------------------------------------------------------------------
# construction rules (no package needed)
# ---------------------------------------------------------------------------------------
def test_annotation_flags_name_their_source() -> None:
    """Each of the three required flags must carry the source it was derived from."""
    tool = _tool()
    product = tool.annotation("tiles", deploy_channels={"tiles", "valid"}, source_kind="SENSOR_SIM",
                              route="proxy_scan")
    assert product["rig_obtainable"] is True and product["rig_obtainable_basis"]
    assert product["synthetic_only"] is True and product["synthetic_only_basis"]
    assert product["claim_allowed"] is True and product["claim_allowed_basis"]
    # a research-only channel is *measured* as not rig-obtainable because the deploy view of this
    # package does not ship it
    research = tool.annotation("id_map", deploy_channels={"tiles", "valid"})
    assert research["rig_obtainable"] is False
    assert research["claim_allowed"] is False
    assert research["policy_view"] == "research"
    # an undeclared channel is flagged as undeclared rather than silently allowed
    unknown = tool.annotation("no_such_channel", deploy_channels=set())
    assert unknown["evidence_class"] == "NOT_DECLARED_BY_POLICY"
    assert unknown["claim_allowed"] is False
    assert tool.POLICY_SHA.startswith("sha256:")


def test_a_caveat_evidence_class_is_never_claim_allowed() -> None:
    tool = _tool()
    caveat = tool.annotation("depth_z", deploy_channels={"depth_z"})
    assert caveat["policy_view"] == "deploy"
    assert caveat["evidence_class"].startswith("CAVEAT")
    assert caveat["claim_allowed"] is False, "a CAVEAT_* channel must not be claim-allowed"
    assert caveat["rig_obtainable"] is True


def test_declare_recomputes_the_file_set_from_disk(tmp_path: Path) -> None:
    """A stale declaration or an undeclared file must not survive ``declare()``."""
    tool = _tool()
    root = tmp_path / "pkg"
    (root / "research").mkdir(parents=True)
    (root / "deploy").mkdir()
    (root / "deploy" / "a.json").write_text("{}", encoding="utf-8")
    (root / "research" / "b.parquet").write_bytes(b"not really parquet")
    (root / "research" / "undeclared.bin").write_bytes(b"x" * 10)
    (root / "export_manifest.json").write_text("{}", encoding="utf-8")
    manifest = {"files": [{"path": "deploy/a.json", "hash": "sha256:stale", "bytes": 1}]}
    out = tool.declare(manifest, root, extras=("dataset_card.json", "README.md"))
    paths = [entry["path"] for entry in out["files"]]
    assert "export_manifest.json" not in paths, "the manifest cannot declare itself"
    assert paths == ["deploy/a.json", "research/b.parquet", "research/undeclared.bin"]
    assert out["counts_total"] == 3
    assert out["bytes_total"] == sum((root / p).stat().st_size for p in paths)
    for entry in out["files"]:
        assert entry["hash"] == tool.sha256(root / entry["path"]), entry["path"]
    assert out["files"][0]["hash"] != "sha256:stale"
    assert out["manifest_hash"].startswith("sha256:")


def test_declare_is_stable_and_not_a_constant(tmp_path: Path) -> None:
    tool = _tool()
    root = tmp_path / "pkg"
    root.mkdir()
    (root / "x.bin").write_bytes(b"abc")
    first = tool.declare({"files": []}, root)
    second = tool.declare({"files": []}, root)
    assert first["manifest_hash"] == second["manifest_hash"], "the hash must be deterministic"
    (root / "y.bin").write_bytes(b"abcd")
    third = tool.declare({"files": []}, root)
    assert third["manifest_hash"] != first["manifest_hash"], "the hash must track the bytes"


def test_dimension_counts_reads_only_measured_values() -> None:
    tool = _tool()
    bundle = {"dimensions": [
        {"dimension": "roi_views", "counts": {"assets": 4, "views": 96, "bytes": 2122449698}},
        {"dimension": "degrade", "counts": {"registered_axes": 31, "materialised_variants": 33}},
    ], "missing": [{"missing": "research/hard_negatives.parquet"}]}
    counts = tool._dimension_counts(bundle)
    assert counts["roi_view_family_assets"] == 4
    assert counts["roi_view_family_views"] == 96
    assert counts["degrade_registered_axes"] == 31
    assert counts["experiment_ready_missing_dimensions"] == 1
    assert "context_packs" not in counts, "an absent dimension must not invent a zero"


# ---------------------------------------------------------------------------------------
# the shipped package
# ---------------------------------------------------------------------------------------
def _index(name: str) -> dict:
    path = _package() / "research" / name / "index.json"
    if not path.is_file():
        pytest.skip(f"dimension index {name} is not present")
    return json.loads(path.read_text(encoding="utf-8"))


def test_roi_index_counts_match_the_bytes_on_disk() -> None:
    package = _package()
    index = _index("roi_views")
    rows = index["rows"]
    assert rows, "the ROI index carries no observation"
    npz = sorted((package / "research" / "roi_views").glob("*.npz"))
    assert len(npz) == len(rows) == index["counts"]["assets"]
    assert sum(p.stat().st_size for p in npz) == sum(int(r["bytes"]) for r in rows)
    assert index["counts"]["views"] == sum(int(r["n_views"]) for r in rows)
    families = index["counts"]["view_families"]
    assert families, "the view-family split must be measured"
    assert sum(int(v) for v in families.values()) == index["counts"]["views"]
    # every row must describe a real npz header, and the ROI family must really be present
    for row in rows:
        assert row["arrays"], f"{row['asset_id']} has an empty array header"
        assert row["n_arrays"] == len(row["arrays"])
        assert row["views"], "per-view records must be measured"
        whole = [v for v in row["views"] if v["view_family"] == "WHOLE_FRAGMENT"]
        roi = [v for v in row["views"] if v["view_family"] == "FRACTURE_ROI"]
        assert whole and roi, "both the whole-slice and the ROI close-up family must be present"


def test_every_dimension_index_publishes_its_three_flags() -> None:
    """The required annotation must exist per item and name its evidence."""
    package = _package()
    roi = _index("roi_views")
    assert roi["annotations"], "no channel annotations"
    for item in roi["annotations"]:
        for field in ("rig_obtainable", "synthetic_only", "claim_allowed"):
            assert isinstance(item[field], bool), f"{item['channel']}.{field} is not a bool"
        assert item["evidence_class"]
    extras = _index("synthetic_extras")
    assert extras["modalities"], "no extras modalities"
    for item in extras["modalities"]:
        for field in ("rig_obtainable", "synthetic_only", "claim_allowed"):
            assert isinstance(item[field], bool), f"{item['modality_id']}.{field}"
        assert item["switch_field"], "each extras modality must name its switch field"
    fracture = _index("fracture")
    for item in fracture["channels"]:
        assert isinstance(item["rig_obtainable"], bool)
    # the extras payload bytes must really be in the package
    files = sorted((package / "research" / "synthetic_extras").glob("*.npz"))
    assert len(files) == extras["counts"]["modalities"] * 2, "2 fragments per modality expected"


def test_degrade_index_registry_is_measured_not_declared() -> None:
    index = _index("degrade")
    axes = index["axes"]
    assert axes, "no axes"
    materialised = [a for a in axes if a["materialised"]]
    assert materialised, "no axis has materialised levels"
    assert index["counts"]["materialised_variants"] == sum(
        1 for v in index["variants"] if v["role"] == "degrade_variant")
    real_variants = sorted((_package() / "research" / "degrade" / "variants").glob("*.npz"))
    assert len(real_variants) == index["counts"]["materialised_variants"] + index["counts"]["sources"]
    for axis in materialised:
        assert axis["materialised_levels"], axis["axis_id"]
        assert axis["n_materialised_levels"] == len(axis["materialised_levels"])
    # the registry must be wider than what is materialised (that gap is the honest finding)
    assert index["counts"]["registered_axes"] >= index["counts"]["axes_with_materialised_levels"]


def test_fracture_planarity_is_measured_per_fragment() -> None:
    index = _index("fracture")
    rows = [r for r in index["rows"] if r.get("n_interface_faces")]
    assert rows, "no fragment carries an INTERFACE face"
    import pandas as pd

    root = _package() / "research" / "fracture"
    frame = pd.read_parquet(root / "fragments.parquet")
    patches = pd.read_parquet(root / "interfaces.parquet")
    assert len(frame) == len(index["rows"])
    assert len(patches) == index["counts"]["interface_patches"] == len(index["patches"])
    assert int(frame["n_interface_faces"].fillna(0).sum()) == index["counts"]["interface_faces"]
    assert len(patches) == int(frame["n_patches"].fillna(0).sum())
    planar = frame[frame["planar_geometry"] == True]                     # noqa: E712
    nonplanar = frame[frame["planar_geometry"] == False]                 # noqa: E712
    assert len(planar) == index["counts"]["planar_fragments"]
    assert len(nonplanar) == index["counts"]["non_planar_fragments"]
    # the flag must be exactly the conjunction of its patches -- not a constant
    for _, row in frame.iterrows():
        own = patches[patches["asset_id"] == row["asset_id"]]
        if not len(own):
            continue
        assert bool(row["planar_geometry"]) == bool(own["planar"].all()), row["asset_id"]
        assert int(row["planar_patches"]) == int(own["planar"].sum())
    # the planarity flag is backed by the residual it claims to measure
    assert (patches[patches["planar"] == True]["plane_residual_max_mm"] <= 1e-9).all()  # noqa: E712
    assert (patches[patches["planar"] == False]["plane_residual_max_mm"] > 1e-9).all()  # noqa: E712
    # the band statistic is the instrument's, so the exactly-zero sub-mm population is real
    zero = patches[patches["ra_below_1mm_mm"] == 0.0]
    assert len(zero) == index["counts"]["patches_below_1mm_ra_exactly_zero"]
    assert len(patches) - len(zero) == index["counts"]["patches_below_1mm_ra_nonzero"]


def test_deploy_view_of_the_merged_package_carries_no_truth_channel() -> None:
    """Acceptance 3: the deployment view must stay free of truth channels and answer fields."""
    package = _package()
    manifest = json.loads((package / "export_manifest.json").read_text(encoding="utf-8"))
    separation = manifest.get("separation") or {}
    scan = separation.get("answer_field_scan") or {}
    assert scan.get("hits") == [], f"answer-field hits in the deploy view: {scan.get('hits')}"
    assert separation.get("features_carry_answer_fields") is False

    # real scan of what the deploy index says it ships
    obs = json.loads((package / "deploy" / "obs" / "index.json").read_text(encoding="utf-8"))
    shipped: set[str] = set()
    for entry in (obs.get("rows") or {}).values():
        shipped.update(str(name) for name in (entry.get("channels") or []))
    for channel in list(TRUTH_CHANNELS) + list(TRUTH_PREFIXES):
        assert channel not in shipped, f"deploy view ships the truth channel {channel}"
    # and none of the research-side payloads leaked into deploy/
    leaked = [p.relative_to(package).as_posix()
              for p in (package / "deploy").rglob("*") if p.is_file()
              and any(token in p.name for token in ("roi_views", "synthetic_extras", "context",
                                                    "hard_negatives"))]
    assert leaked == [], f"research dimensions leaked into deploy/: {leaked}"
    for name in ("id_map", "surface_tag", "T_WC", "dist"):
        assert name not in json.dumps(manifest.get("views") or {}), name


def test_merged_manifest_declares_every_file_that_is_on_disk() -> None:
    package = _package()
    manifest = json.loads((package / "export_manifest.json").read_text(encoding="utf-8"))
    declared = {str(entry["path"]) for entry in manifest["files"]}
    on_disk = {p.relative_to(package).as_posix() for p in package.rglob("*") if p.is_file()}
    allowed_extras = {"export_manifest.json", "dataset_card.json", "README.md"}
    assert declared <= on_disk, f"declared but absent: {sorted(declared - on_disk)[:5]}"
    assert on_disk - declared <= allowed_extras, (
        f"undeclared files present: {sorted(on_disk - declared)[:5]}")
    assert manifest["counts_total"] == len(manifest["files"])
    assert manifest["bytes_total"] == sum(int(e["bytes"]) for e in manifest["files"])
    assert manifest["manifest_hash"].startswith("sha256:")
    block = manifest.get("experiment_ready_dimensions") or {}
    assert block.get("dimensions"), "the manifest must name the merged dimensions"


def test_ablation_index_covers_every_merged_dimension() -> None:
    package = _package()
    path = package / "ablation_index.json"
    if not path.is_file():
        pytest.skip("ablation_index.json is not present")
    index = json.loads(path.read_text(encoding="utf-8"))
    groups = index["groups"]
    ids = {g["group_id"] for g in groups}
    assert REQUIRED_GROUPS <= ids, f"missing ablation groups: {sorted(REQUIRED_GROUPS - ids)}"
    for group in groups:
        for field in REQUIRED_GROUP_FIELDS:
            assert group.get(field) is not None, f"{group.get('group_id')}.{field} is missing"
        assert group["availability"] in ("present", "missing")
        if group["availability"] == "missing":
            assert group.get("unlock_condition"), (
                f"{group['group_id']} is missing without an unlock condition")
            assert not (package / group["files"][0]).exists()
        else:
            assert all((package / f).exists() for f in group["files"]), group["group_id"]
    assert index["counts"]["groups"] == len(groups)
    assert index["counts"]["present"] == sum(1 for g in groups if g["availability"] == "present")
    assert index["counts"]["missing"] == sum(1 for g in groups if g["availability"] == "missing")


def test_the_missing_dimension_is_recorded_and_not_faked() -> None:
    package = _package()
    assert not (package / "research" / "hard_negatives.parquet").exists()
    gap = json.loads((package / "research" / "hard_negatives.index.json").read_text(encoding="utf-8"))
    assert gap["status"] == "missing"
    assert gap["unlock_condition"]
    assert gap["scanned"]
    assert gap["ablation_group"] == "ABL_HARD_NEGATIVES"
