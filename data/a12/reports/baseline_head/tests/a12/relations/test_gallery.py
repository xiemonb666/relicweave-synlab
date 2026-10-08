"""Gallery/pool construction tests (plan 16.1, 30.10, 30.15).

The store is a real ``AssetStore``; the producers are the local fixtures because
``synlab.truth`` / ``synlab.observe`` do not exist in this checkout yet (documented in
``docs/a12/relations_diagnostics_episodes.md``).  The real evidence store ``data/a12`` is also
exercised read-only: it currently holds no truth/label asset, so the honest outcome is
``ok=false`` with ``GALLERY_SIZE_PENDING``.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from pool_fixtures import EventSpec, build_two_event_store, commit_event, commit_clean_truth, \
    make_event
from synlab.errors import ErrorCode, SynLabError
from synlab.relations.api import (
    PoolConfig,
    build_pool,
    build_pool_from_config,
    commit_pool,
    commit_roster,
    load_pool,
    load_pool_json,
    load_roster_json,
    save_pool_json,
)
from synlab.roles import ROLE_POOL, ROLE_ROSTER
from synlab.storage.store import AssetStore

REPO_ROOT = Path(__file__).resolve().parents[3]
REQUIRED_KEYS = ("ok", "distractor_isolated", "queries", "candidates", "r2_edges")


def _pool(tmp_path: Path, **config):
    store, specs = build_two_event_store(tmp_path)
    cfg = PoolConfig(pool_id=config.pop("pool_id", "pool_test"), size_target=100,
                     query_per_mother=config.pop("query_per_mother", 2), **config)
    report = build_pool(store, None, cfg)
    assert report["ok"], report.get("error")
    return store, specs, report, report["pool"]


def test_build_pool_contract_keys(tmp_path: Path):
    _store, _specs, report, pool = _pool(tmp_path)
    for key in REQUIRED_KEYS:
        assert key in report, key
    assert report["ok"] is True
    assert report["n2_materialised"] is False
    assert report["candidates"] == len(pool.lineup) == 7
    assert report["r2_edges"] == 5
    assert set(report["metrics"]) >= {"pool_id", "queries", "candidates", "r2_edges"}
    assert report["metrics"]["distractor_isolated"] is True
    assert report["gallery"].scope == "FULL"
    assert report["gallery"].gallery_version == "v1"
    assert report["hash"].startswith("sha256:")
    assert report["pool_id"] == "pool_test"


def test_full_r2_set_is_stored_and_self_excluded(tmp_path: Path):
    _store, _specs, report, pool = _pool(tmp_path)
    # full N_G(q): the middle pieces have two neighbours even though only the chain is known
    assert pool.neighbours("a01") == ["a00", "a02"]
    assert pool.neighbours("a00") == ["a01"]
    assert report["stats"]["r2_edges"] == 5
    for query in pool.lineup:
        assert query not in pool.candidate_ids(query)
        assert query not in pool.neighbours(query)
    # R0 is implicit and never materialised; only non-R0 edges are stored
    assert report["explicit_edges"] == 5 + 2 + 1 + 1
    assert pool.relation("a00", "b00") == "R1"
    assert pool.relation("a02", "b02") == "TINY_CONTACT"
    assert pool.relation("a03", "b00") == "UNKNOWN"
    assert pool.relation("a00", "a02") == "R0"
    assert pool.relation("a00", "a00") == "SELF"
    assert pool.relation("a00", "nope") == "ABSENT"
    assert report["stats"]["r0_implicit_pairs"] == 21 - 9


def test_no_neighbour_entries_are_not_confirmed_as_R0(tmp_path: Path):
    store = AssetStore(tmp_path)
    spec = make_event("LIN0009_V09_M09", "m::LIN0009", "z", 3, split="dev", seed=9)
    spec.unknown = []
    commit_event(store, spec)
    report = build_pool(store, None, PoolConfig(pool_id="p_unknown", size_target=10,
                                                query_per_mother=1))
    assert report["ok"]
    pool = report["pool"]
    # an unpublished pair inside one event is still R0 (no shared interface), never UNKNOWN
    assert pool.relation("z00", "z02") == "R0"
    assert pool.confirmed("z00", "z02") is True
    # an explicitly unverified fragment turns its unlabelled pairs into UNKNOWN
    pool.index.mark_unverified("z02")
    assert pool.relation("z00", "z02") == "UNKNOWN"
    assert pool.confirmed("z00", "z02") is False


def test_scopes_and_variants(tmp_path: Path):
    _store, _specs, report, pool = _pool(tmp_path, mate_removed_variant=True,
                                         nested_sizes=[2, 20])
    variants = report["variants"]
    assert variants["MATE_REMOVED"]["removed"] > 0
    assert variants["MATE_REMOVED"]["queries_with_mates"] == 0
    assert variants["MATE_REMOVED"]["out_of_gallery_neighbours"] > 0
    nested = {entry["pool_id"]: entry for entry in variants["NESTED"]["sizes"]}
    assert nested["pool_test__n2"]["size"] == 2
    assert nested["pool_test__n20"]["status"] == "GALLERY_SIZE_PENDING"
    assert nested["pool_test__n20"]["reason"]
    # mate_removed as its own scope keeps N_G(q) empty for the roster queries
    mate_report = build_pool(_store, None, PoolConfig(pool_id="p_mate", size_target=100,
                                                      scope="MATE_REMOVED",
                                                      query_per_mother=2))
    assert mate_report["ok"]
    assert mate_report["queries_with_mates"] == 0
    assert mate_report["mate_absent_queries"] == mate_report["queries"]
    assert mate_report["out_of_gallery_neighbours"] > 0


def test_distractor_scope_and_isolation(tmp_path: Path):
    store = AssetStore(tmp_path)
    dev = make_event("LIN0001_V01_M01", "m::1", "a", 3, split="dev", seed=1)
    train = make_event("LIN0002_V02_M02", "m::2", "b", 3, split="train", seed=2)
    distractor = make_event("LIN0003_DISTRACTOR", "m::3", "c", 3, split="gallery_distractor",
                            seed=3)
    for spec in (dev, train, distractor):
        commit_event(store, spec)
    report = build_pool(store, None, PoolConfig(pool_id="p_iso", size_target=100,
                                                query_per_mother=1,
                                                exclude_training_lineages=True))
    assert report["ok"]
    lineup = report["pool"].lineup
    assert all(not fid.startswith("b") for fid in lineup), lineup
    assert report["distractor_isolated"] is True
    assert report["distractor_lineages"] == ["LIN0003_DISTRACTOR"]
    distractor_pool = build_pool(store, None, PoolConfig(pool_id="p_dist", size_target=100,
                                                         scope="DISTRACTOR_ONLY",
                                                         query_per_mother=1))
    assert distractor_pool["ok"]
    assert sorted(distractor_pool["pool"].lineup) == ["c00", "c01", "c02"]
    # a lineage that is *both* a training lineage and a distractor-only lineage is not isolated
    both = make_event("LIN0004_DISTRACTOR_TRAIN", "m::4", "e", 2, split="train", seed=4)
    commit_event(store, both)
    contaminated = build_pool(store, None, PoolConfig(pool_id="p_bad", size_target=100,
                                                      query_per_mother=1,
                                                      exclude_training_lineages=False,
                                                      scope="DISTRACTOR_ONLY"))
    assert contaminated["ok"]
    assert contaminated["distractor_overlap"] == ["LIN0004_DISTRACTOR_TRAIN"]
    assert contaminated["distractor_isolated"] is False


def test_clean_truth_asset_is_also_a_relation_source(tmp_path: Path):
    store = AssetStore(tmp_path)
    spec = make_event("LIN0010_V10_M10", "m::10", "d", 3, split="dev", seed=10)
    commit_clean_truth(store, spec)
    report = build_pool(store, None, PoolConfig(pool_id="p_truth", size_target=10,
                                                query_per_mother=1))
    assert report["ok"]
    assert sorted(report["pool"].lineup) == ["d00", "d01", "d02"]
    assert report["pool"].neighbours("d00") == ["d01"]
    assert report["features"]["attached"] == 0       # no feature asset was committed


def test_pool_asset_roundtrip_keeps_the_full_neighbour_set(tmp_path: Path):
    store, _specs, report, pool = _pool(tmp_path)
    asset = commit_pool(store, pool, split="dev")
    assert asset.role == ROLE_POOL
    restored = load_pool(store, asset.asset_id)
    assert restored.hash == pool.hash
    assert restored.scope == "FULL"
    assert restored.lineup == pool.lineup
    for fid in pool.lineup:
        assert restored.neighbours(fid) == pool.neighbours(fid)
    assert restored.relation("a00", "b00") == "R1"
    assert restored.relation("a00", "a02") == "R0"
    assert restored.relation("a02", "b02") == "TINY_CONTACT"
    assert restored.relation("a03", "b00") == "UNKNOWN"
    assert restored.roster and restored.roster[0].query_id.startswith("q::")
    assert set(restored.features) == set()
    roster_asset = commit_roster(store, pool, split="dev", ancestry=[asset.asset_id])
    assert roster_asset.role == ROLE_ROSTER
    assert roster_asset.meta["queries"] == len(pool.roster)


def test_portable_json_and_roster_artifacts(tmp_path: Path):
    store, _specs, report, pool = _pool(tmp_path)
    pool_path = tmp_path / "pools" / "pool_test.json"
    written = save_pool_json(pool, pool_path)
    assert written["written"] is True
    payload = json.loads(pool_path.read_text(encoding="utf-8"))
    assert payload["n2_materialised"] is False
    assert payload["relation_storage"] == "sparse_non_r0_edges_only"
    assert len(payload["edges"]) == report["explicit_edges"]
    restored, roster_rows = load_pool_json(pool_path)
    assert restored.neighbours("a01") == ["a00", "a02"]
    assert restored.relation("a03", "b00") == "UNKNOWN"
    assert len(roster_rows) == report["queries"]
    oversized = save_pool_json(pool, tmp_path / "big.json", limit=1)
    assert oversized["written"] is False and oversized["status"] == "SKIPPED_SIZE"


def test_build_pool_from_config_writes_artifacts(tmp_path: Path):
    store, _specs = build_two_event_store(tmp_path)
    config = tmp_path / "pool.yaml"
    config.write_text(
        "schema: synlab.pool.v1\n"
        "pool_id: sandbox_dev\n"
        "gallery_version: v1\n"
        "scope: FULL\n"
        "split: dev\n"
        "size_target: 100\n"
        "exclude_training_lineages: true\n"
        "nested_sizes: [2, 4]\n"
        "mate_removed_variant: true\n"
        "query_per_mother: 2\n"
        "refinement_candidates: [10, 20]\n"
        "top_k: [1, 5]\n",
        encoding="utf-8")
    report = build_pool_from_config(store, "sandbox", config)
    assert report["ok"], report.get("error")
    assert report["pool_id"] == "sandbox_dev"
    artifacts = report["artifacts"]
    assert Path(artifacts["portable_json"]["path"]).exists()
    assert Path(artifacts["roster_json"]["path"]).exists()
    assert store.get_asset(artifacts["pool_asset"]).role == ROLE_POOL
    assert load_roster_json(artifacts["roster_json"]["path"])
    # the portable artifact is what `candidate_pool_ref` points at
    pool, _rows = load_pool_json(artifacts["portable_json"]["path"])
    assert pool.pool_id == "sandbox_dev"
    assert pool.neighbours("a00") == ["a01"]


def test_unknown_config_keys_are_rejected(tmp_path: Path):
    store, _specs = build_two_event_store(tmp_path)
    config = tmp_path / "bad.yaml"
    config.write_text("pool_id: x\nsize_target: 10\nunit: mm\n", encoding="utf-8")
    with pytest.raises(SynLabError) as excinfo:
        build_pool_from_config(store, "sandbox", config)
    assert excinfo.value.code == ErrorCode.SCHEMA_INVALID


def test_empty_store_reports_gallery_size_pending(tmp_path: Path):
    store = AssetStore(tmp_path / "empty")
    report = build_pool(store, "sandbox", PoolConfig(pool_id="p_empty", size_target=10))
    assert report["ok"] is False
    assert report["status"] == "GALLERY_SIZE_PENDING"
    for key in REQUIRED_KEYS:
        assert key in report
    assert report["error"]["code"] == ErrorCode.GALLERY_SIZE_PENDING.value
    assert report["candidates"] == 0 and report["r2_edges"] == 0
    assert report["pool"] is None


def test_real_evidence_store_is_read_only_and_reports_pending():
    """The shipped ``data/a12`` store has no truth/label asset yet -> honest PENDING."""
    store_root = REPO_ROOT / "data" / "a12"
    if not store_root.exists():
        pytest.skip("no data/a12 store in this checkout")
    store = AssetStore(store_root)
    report = build_pool(store, "sandbox", PoolConfig(pool_id="real_probe", size_target=10))
    assert report["ok"] in (True, False)
    if not report["ok"]:
        assert report["status"] == "GALLERY_SIZE_PENDING"
        assert report["fragments_seen"] == report["fragments_eligible"]
    # nothing was written into the real store by this read-only probe
    assert not (store_root / "pools" / "real_probe.json").exists()
