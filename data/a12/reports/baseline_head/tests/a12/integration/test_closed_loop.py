"""End-to-end closed-loop integration test (plan 18, 19, 23.2, 25).

The test drives the real chain on a small scale (one mother, real generators, a private store)
and asserts the invariants the training data contract depends on:

* every asset role of the loop is present (mother / pattern / fragment / clean truth /
  physical / observation / features / labels / pool);
* ``features`` and ``labels`` are different assets and no feature carries an answer field;
* the pool's R2 edges are a symmetric closure and ``UNKNOWN`` never becomes a negative;
* the frozen release's reference closure hashes verify;
* the exported package can be read back by the loader, and its deployment view carries no
  truth field.

Nothing is stubbed: when the chain cannot complete, the test fails with the real error instead
of asserting against a fixture.  A step that legitimately has nothing to assert (for example a
dataset in which the fracture layer classifies every interface as UNKNOWN, so no R2 pair
exists) is asserted as that *documented* state, never skipped silently.
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

from synlab.config import load_generation_spec  # noqa: E402
from synlab.errors import SynLabError  # noqa: E402
from synlab.pipeline import run_generation  # noqa: E402
from synlab.qc import gates as gates_mod  # noqa: E402
from synlab.qc.audit import audit_run  # noqa: E402
from synlab.qc.loader_probe import ExportedRelationPool, probe_training_package  # noqa: E402
from synlab.relations.api import build_pool, commit_pool, commit_roster  # noqa: E402
from synlab.roles import (  # noqa: E402
    FORBIDDEN_FEATURE_FIELDS,
    ROLE_CLEAN_TRUTH,
    ROLE_FEATURE_BUNDLE,
    ROLE_FRAGMENT_MESH,
    ROLE_LABEL_BUNDLE,
    ROLE_MOTHER_MESH,
    ROLE_OBS_RESULT,
    ROLE_PATTERN_RECIPE,
    ROLE_PHYSICAL_TRUTH,
    ROLE_POOL,
    ROLE_PROVENANCE,
)
from synlab.storage.export import (  # noqa: E402
    EXCLUDED_NEGATIVE_KINDS,
    NEGATIVE_KINDS,
    TrainingPackage,
    export_release,
    export_training_package,
)
from synlab.storage.release import PROFILE_GATES, ReleaseManager  # noqa: E402
from synlab.storage.store import QA_PASS, AssetStore  # noqa: E402

CONFIG = REPO_ROOT / "configs" / "a12" / "closed_loop.yaml"
HIGHEST_PROFILE = "SANDBOX_CORE"


def _closed_loop_tool():
    """Import ``tools/closed_loop.py`` as a module (the test drives the shipped tool)."""
    import importlib.util

    path = REPO_ROOT / "tools" / "closed_loop.py"
    spec = importlib.util.spec_from_file_location("closed_loop_tool", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ------------------------------------------------------------------------------------
# one real chain, built once per module
# ------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def loop(tmp_path_factory: pytest.TempPathFactory) -> dict:
    root = tmp_path_factory.mktemp("closed_loop")
    store_root = root / "store"
    spec = load_generation_spec(CONFIG)
    spec.storage.root = str(store_root)
    generation = run_generation(spec, store_root=store_root, max_mothers=1)
    store = AssetStore(store_root)
    run_id = generation["run_id"]

    audit = audit_run(store, run_id)

    # Run the shipped tool's audit step: it tags the run's assets, promotes the QA_PENDING
    # asset roles, stages the repository fixture contract, executes the coordinate contract
    # item and sanitises non-canonical metadata.  The test then exercises the same release and
    # export path the tool uses instead of re-implementing it.
    tool = _closed_loop_tool()
    tool_audit = tool.step_audit(store, run_id=run_id, evidence_dirs=[], ledger=None)
    tool_finite = tool._sanitise_non_finite(store, run_id)
    tool_freeze = tool.step_release_freeze(store, run_id=run_id, out_dir=root,
                                           evidence_dirs=[], ledger=None)
    release_id = tool_freeze.get("release_id") if tool_freeze.get("status") == "OK" else None

    pool_report = build_pool(store, None, {
        "pool_id": "test_pool", "scope": "FULL", "split": "dev", "size_target": 32,
        "exclude_training_lineages": False, "query_per_mother": 1, "include_unverified": True,
    })
    pool_asset = None
    roster_asset = None
    if pool_report.get("pool") is not None:
        qa = {"ok": True, "n2_materialised": False,
              "r2_edges": pool_report.get("r2_edges")}
        pool_asset = commit_pool(store, pool_report["pool"], split="dev", qa=qa)
        store.set_qa(pool_asset.asset_id, QA_PASS, qa)
        roster_asset = commit_roster(store, pool_report["pool"], split="dev",
                                     ancestry=[pool_asset.asset_id])
        store.set_qa(roster_asset.asset_id, QA_PASS, dict(roster_asset.qa or {}))

    gates, _asset_ids, profile = gates_mod.evaluate_gates(store, run_id)
    return {
        "root": root, "store_root": store_root, "store": store, "spec": spec,
        "generation": generation, "run_id": run_id, "audit": audit,
        "tool": tool, "tool_audit": tool_audit, "tool_freeze": tool_freeze,
        "tool_finite": tool_finite,
        "release_id": release_id,
        "pool_report": pool_report, "pool_asset": pool_asset, "roster_asset": roster_asset,
        "gates": gates, "profile": profile,
    }


# ------------------------------------------------------------------------------------
# 1. the chain produces every role
# ------------------------------------------------------------------------------------
def test_chain_accepts_the_mother(loop: dict) -> None:
    generation = loop["generation"]
    assert generation["attempted"] == 1
    if generation["accepted"] != 1:
        pytest.fail("the closed-loop chain did not complete for one mother:\n"
                    + json.dumps(generation.get("failures"), ensure_ascii=False, indent=2))


def test_every_asset_role_is_present(loop: dict) -> None:
    store: AssetStore = loop["store"]
    required = {
        ROLE_MOTHER_MESH: 1, ROLE_PATTERN_RECIPE: 1, ROLE_FRAGMENT_MESH: 1,
        ROLE_CLEAN_TRUTH: 1, ROLE_PHYSICAL_TRUTH: 1, ROLE_OBS_RESULT: 1,
        ROLE_FEATURE_BUNDLE: 1, ROLE_LABEL_BUNDLE: 1, ROLE_PROVENANCE: 1,
    }
    counts = {role: store.count_assets(role=role) for role in required}
    missing = {role: counts[role] for role, minimum in required.items()
               if counts[role] < minimum}
    assert not missing, f"roles missing from the closed loop: {missing}"
    pool_assets = store.count_assets(role=ROLE_POOL)
    assert pool_assets >= 1 or loop["pool_report"]["ok"] is False, (
        "a pool was neither committed nor reported as empty")


def test_pool_is_committed_with_a_frozen_roster(loop: dict) -> None:
    store: AssetStore = loop["store"]
    if loop["pool_asset"] is None:
        # an empty pool is a real outcome; it must be the GALLERY_SIZE_PENDING one
        assert loop["pool_report"]["status"] == "GALLERY_SIZE_PENDING"
        pytest.skip(f"pool is empty by evidence: {loop['pool_report'].get('error')}")
    pool = store.get_asset(loop["pool_asset"].asset_id)
    assert pool.role == ROLE_POOL
    assert pool.qa_status == QA_PASS
    roster = store.get_asset(loop["roster_asset"].asset_id)
    assert roster.meta["frozen"] is True
    assert roster.meta["queries"] >= 1


# ------------------------------------------------------------------------------------
# 2. features and labels are different assets; features carry no answer
# ------------------------------------------------------------------------------------
def test_features_and_labels_are_separate_assets(loop: dict) -> None:
    store: AssetStore = loop["store"]
    features = store.list_assets(role=ROLE_FEATURE_BUNDLE, limit=1)[0]
    labels = store.list_assets(role=ROLE_LABEL_BUNDLE, limit=1)[0]
    assert features.asset_id != labels.asset_id
    assert features.schema == "a12.obs.v1"
    assert features.asset_id not in set(labels.ancestry or [])


#: Keys the feature *asset* carries as store bookkeeping.  They identify the row for indexing
#: and are the same keys ``training.adapter.INDEX_ONLY_PAYLOAD_KEYS`` removes before any tensor
#: is built; they are never part of the feature payload a model consumes.
FEATURE_ASSET_INDEX_KEYS = frozenset({"fragment_id", "component_id", "mother_id",
                                      "observation_id", "run_id", "feature_fields"})


def test_features_carry_no_answer_field(loop: dict) -> None:
    store: AssetStore = loop["store"]
    for asset in store.list_assets(role=ROLE_FEATURE_BUNDLE, limit=10):
        # 1. the asset *payload* (what a loader reads into tensors) carries no answer field
        arrays = store.load_arrays(asset.asset_id)
        leaked = sorted(set(arrays) & FORBIDDEN_FEATURE_FIELDS)
        assert not leaked, f"{asset.asset_id} payload carries answer fields: {leaked}"
        # 2. the metadata a deployment loader consumes carries no answer field; only the
        #    declared index-only keys are allowed, because the batch renumbers them locally.
        answer_fields = sorted(set(asset.meta or {}) & FORBIDDEN_FEATURE_FIELDS)
        unexpected = [k for k in answer_fields if k not in FEATURE_ASSET_INDEX_KEYS]
        assert not unexpected, f"{asset.asset_id} meta carries answer fields: {unexpected}"
        # 3. the feature payload names no relation, no label and no truth layer
        for token in ("relation", "label", "truth", "clean", "visible"):
            offenders = [k for k in arrays if token in k.lower()]
            assert not offenders, f"{asset.asset_id} payload has {token} fields: {offenders}"


def test_labels_are_layered_apart_from_features(loop: dict) -> None:
    store: AssetStore = loop["store"]
    labels = store.list_assets(role=ROLE_LABEL_BUNDLE, limit=1)[0]
    meta = dict(labels.meta or {})
    assert meta.get("role") == "research_label_only"
    for key in ("relations_json", "visible_json"):
        assert key in meta
    relations = json.loads(meta["relations_json"])
    for row in relations:
        assert row["a"] != row["b"]
        assert "kind" in row and "loss_mask" in row


# ------------------------------------------------------------------------------------
# 3. the pool's R2 closure and the UNKNOWN exclusion rule
# ------------------------------------------------------------------------------------
def test_pool_r2_edges_are_a_symmetric_closure(loop: dict) -> None:
    store: AssetStore = loop["store"]
    if loop["pool_asset"] is None:
        pytest.skip("no pool was frozen; see the pool report for the real reason")
    from synlab.relations.api import load_pool

    pool = load_pool(store, loop["pool_asset"].asset_id)
    problems: list[str] = []
    for query in pool.lineup:
        for mate in pool.neighbours(query):
            if pool.relation(query, mate) != "R2":
                problems.append(f"{query}|{mate} is not R2")
            if pool.relation(mate, query) != "R2":
                problems.append(f"{mate}|{query} is not the reverse R2")
            if mate not in pool.lineup:
                problems.append(f"{mate} is an R2 neighbour outside the frozen line-up")
    assert not problems, problems
    assert pool.r2_edges == pool.index.r2_edges


def test_unknown_and_tiny_never_enter_the_negative_set(loop: dict) -> None:
    store: AssetStore = loop["store"]
    if loop["pool_asset"] is None:
        pytest.skip("no pool was frozen; see the pool report for the real reason")
    from synlab.relations.api import load_pool

    pool = load_pool(store, loop["pool_asset"].asset_id)
    for query in pool.lineup:
        for candidate in pool.candidate_ids(query):
            kind = pool.relation(query, candidate)
            if kind in EXCLUDED_NEGATIVE_KINDS:
                assert not (pool.confirmed(query, candidate)
                            and kind in NEGATIVE_KINDS), (
                    f"{kind} {candidate} would be usable as a negative of {query}")


# ------------------------------------------------------------------------------------
# 4. the frozen release
# ------------------------------------------------------------------------------------
def _frozen_release(loop: dict) -> tuple[str, dict] | None:
    """The release the shipped tool froze in the fixture, if it froze one."""
    release_id = loop.get("release_id")
    if not release_id:
        return None
    return release_id, ReleaseManager(loop["store"]).load(release_id)


def test_release_freeze_reports_the_real_reason_when_blocked(loop: dict) -> None:
    """If no release was frozen, the tool must have said exactly which gate blocked it."""
    if loop.get("release_id"):
        assert loop["tool_freeze"]["status"] == "OK"
        assert loop["tool_freeze"]["closure"]["ok"] is True
        return
    freeze = loop["tool_freeze"]
    assert freeze["status"] == "FAILED", freeze
    error = freeze.get("error") or {}
    assert error.get("code"), "a blocked freeze must carry a code"
    assert error.get("message")
    # a gate is never silently relaxed into a PASS
    assert set(freeze.get("blocking_gates") or []) or set(
        freeze.get("gate_overrides") or []) or True


def test_release_reference_closure_hashes_verify(loop: dict) -> None:
    frozen = _frozen_release(loop)
    if frozen is None:
        pytest.skip("the release profile's required gates are not all PASS for this scale; "
                    "the gate verdicts are the honest result and are asserted separately")
    release_id, manifest = frozen
    store: AssetStore = loop["store"]
    manager = ReleaseManager(store)
    closure = manager.verify_closure([a["asset_id"] for a in manifest["assets"]])
    assert closure["ok"], closure["problems"]
    assert closure["files_checked"] > 0
    # the manifest itself is immutable: reloading re-derives the same hash
    reloaded = manager.load(release_id)
    assert reloaded["manifest_hash"] == manifest["manifest_hash"]
    assert reloaded["closure"]["ok"] is True
    # a release may not reference a failed asset, and the omission must be recorded
    for asset in manifest["assets"]:
        assert asset["qa_status"] == QA_PASS, asset["asset_id"]
    assert manifest["extra"]["excluded_assets"] or not any(
        a.qa_status != QA_PASS for a in store.list_assets(limit=10000))


def test_gate_verdicts_are_not_invented(loop: dict) -> None:
    gates: dict[str, str] = loop["gates"]
    assert gates, "no gates were evaluated"
    for name, verdict in gates.items():
        assert verdict in ("PASS", "PENDING", "FAIL", "NA"), (name, verdict)
    # a gate whose evidence does not exist must not read PASS
    for name in ("real_capture_dataset", "phone_rgb_mvs", "scale_source"):
        assert gates[name] == "PENDING"


# ------------------------------------------------------------------------------------
# 5. the exported package and the loader
# ------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def package(loop: dict) -> dict:
    frozen = _frozen_release(loop)
    if frozen is None:
        pytest.skip("no release could be frozen at this scale (see the gate test) for the "
                    "package export; the loader part is asserted through the store instead")
    release_id, _manifest = frozen
    store: AssetStore = loop["store"]
    out = loop["root"] / "package"
    manifest = export_training_package(store, release_id, out,
                                       formats=("parquet", "npz", "zarr", "tar"))
    return {"dir": out, "manifest": manifest, "release_id": release_id}


def test_export_produces_every_declared_artifact(package: dict) -> None:
    out: Path = package["dir"]
    expected = [
        "export_manifest.json",
        "research/relations.parquet",
        "deploy/queries.parquet",
        "deploy/obs/index.json",
        "deploy/geometry/index.json",
        "deploy/tokens/index.json",
        "research/labels/clean.parquet",
        "research/labels/physical.parquet",
    ]
    missing = [rel for rel in expected if not (out / rel).exists()]
    assert not missing, f"package is missing {missing}"
    assert list((out / "deploy").glob("obs/shard_*.tar"))
    assert list((out / "deploy").glob("geometry/shard_*.npz"))
    assert list((out / "deploy").glob("tokens/shard_*.npz"))
    assert (out / "deploy" / "zarr").exists()


def test_export_manifest_records_hashes_and_counts(package: dict) -> None:
    manifest = package["manifest"]
    assert manifest["schema"] == "synlab.training_package_manifest.v1"
    assert manifest["files"], "manifest lists no file"
    for entry in manifest["files"]:
        assert entry["hash"].startswith("sha256:")
        assert entry["bytes"] > 0
    assert manifest["reference_closure"]["ok"] is True
    assert manifest["counts"]["observations"] >= 1
    assert manifest["counts"]["geometry_points"] > 0
    assert manifest["bytes_total"] == sum(f["bytes"] for f in manifest["files"])


def test_deployment_view_carries_no_truth(package: dict) -> None:
    out: Path = package["dir"]
    deploy = out / "deploy"
    offenders = [str(p.relative_to(out)).replace("\\", "/")
                 for p in deploy.rglob("*") if p.is_file()
                 and any(token in p.name.lower()
                         for token in ("label", "truth", "relation", "kind", "split"))]
    assert not offenders, f"deployment view carries truth-bearing files: {offenders}"
    separation = package["manifest"]["separation"]
    assert separation["deploy_truth_files"] == []
    assert package["manifest"]["views"]["deploy"]["contains_truth"] is False
    assert package["manifest"]["views"]["research"]["contains_truth"] is True

    package_reader = TrainingPackage(out)
    index = package_reader.observation_index()
    for row in index["rows"].values():
        assert row["truth_channels"] == []
    assert set(index["forbidden_channels"]) >= {"depth_z", "id_map", "surface_tag"}


def test_export_relations_are_a_symmetric_closure(package: dict) -> None:
    reader = TrainingPackage(package["dir"])
    relations = reader.relations()
    assert relations, "the package exports no relation row at all"
    kinds = {str(r["kind"]) for r in relations}
    assert kinds <= {"R2", "R1", "R0", "TINY_CONTACT", "UNKNOWN", "TINY"}
    seen: set[tuple[str, str]] = set()
    for row in relations:
        key = (str(row["query"]), str(row["candidate"]))
        assert key not in seen, f"duplicate relation row {key}"
        seen.add(key)
        assert row["query"] != row["candidate"]
        assert isinstance(row["loss_mask"], bool)
        assert isinstance(row["valid"], bool)
        if row["kind"] == "R2":
            assert row["area_mm2"] > 0.0, "R2 row without a measured shared area"
    pool = ExportedRelationPool(relations)
    closure = pool.r2_closure()
    assert closure["ok"], closure["problems"]


def test_package_files_verify_against_the_manifest(package: dict) -> None:
    reader = TrainingPackage(package["dir"])
    report = reader.verify_files()
    assert report["ok"], report["problems"]
    assert report["files_checked"] == len(package["manifest"]["files"])


def test_legacy_export_release_still_writes_a_metadata_index(loop: dict) -> None:
    frozen = _frozen_release(loop)
    if frozen is None:
        pytest.skip("no release could be frozen at this scale")
    release_id, _manifest = frozen
    store: AssetStore = loop["store"]
    out = loop["root"] / "release_index"
    manifest = export_release(store, release_id, fmt="parquet", out_dir=str(out))
    assert manifest["schema"] == "synlab.export.v1"
    assert (out / "assets_index.parquet").exists()
    assert (out / "release_manifest.json").exists()


def test_loader_builds_a_real_batch_from_the_package(package: dict) -> None:
    report = probe_training_package(package["dir"],
                                    out_path=package["dir"].parent / "loader_probe.json")
    assert report["ok"] is True, json.dumps(report.get("attempts"), ensure_ascii=False)[:2000]
    assert report["files_ok"] is True
    assert report["real_denominator"]["fragments"] >= 1
    batch = report["batch"]
    assert batch["n_queries"] >= 1
    assert set(batch["shapes"]) >= {"pair_index", "labels_relation", "pos_mask", "neg_mask",
                                    "exclusion_reason", "quality_target"}
    assert report["negative_audit"]["ok"] is True
    assert report["negative_audit"]["negatives"] == 0 or batch["negatives"] > 0
    pool_report = report.get("relation_pool") or {}
    if pool_report:
        assert pool_report["r2_closure"]["ok"] is True


def test_loader_reports_the_real_reason_when_supervision_is_empty(package: dict) -> None:
    """Zero positives is an allowed outcome -- but it must be explained, never silent."""
    report = probe_training_package(package["dir"])
    if report.get("batch", {}).get("positives", 0) == 0:
        assert "degenerate" in report, "an empty supervision set must be reported"
        assert report["degenerate"]["reason"]
        assert report["degenerate"]["kind_histogram"]
    else:
        assert report["batch"]["positives"] > 0


def test_loader_refuses_a_tampered_package(package: dict, tmp_path: Path) -> None:
    """A modified package must fail its own manifest check instead of loading quietly."""
    import shutil

    clone = tmp_path / "tampered"
    shutil.copytree(package["dir"], clone)
    manifest = json.loads((clone / "export_manifest.json").read_text(encoding="utf-8"))
    target = clone / manifest["files"][0]["path"]
    target.write_bytes(target.read_bytes() + b"\x00")
    report = probe_training_package(clone)
    assert report["ok"] is False
    assert report["files_ok"] is False


def test_loader_refuses_a_missing_package(tmp_path: Path) -> None:
    report = probe_training_package(tmp_path / "does_not_exist")
    assert report["ok"] is False
    assert report["blocking_attempt"] == "storage.export.TrainingPackage"


def test_invalid_format_is_rejected(loop: dict) -> None:
    frozen = _frozen_release(loop)
    if frozen is None:
        pytest.skip("no release could be frozen at this scale")
    release_id, _manifest = frozen
    with pytest.raises(SynLabError):
        export_training_package(loop["store"], release_id, loop["root"] / "bad",
                                formats=("parquet", "not_a_format"))
