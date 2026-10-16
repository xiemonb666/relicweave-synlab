"""Pool / roster run attribution (``meta.run_id``) and what the gates read from it.

``relation_pool`` and ``query_roster`` are committed by :func:`synlab.relations.api.commit_pool`
/ :func:`commit_roster`, and every run-scoped reader (``qc.gates.evaluate_gates``,
``qc.audit.audit_run``, the frozen release scope) selects assets through ``meta["run_id"]``.  The
``run_id`` argument is therefore *optional*: it is written only when it is supplied, so every
caller that does not pass one keeps the exact metadata and the exact asset id it had before, and
a pool that is supplied with a run id becomes visible to ``relations_complete`` (a PILOT required
gate) instead of leaving it PENDING forever.

The store is a real ``AssetStore``; the producers are the local fixtures
(``pool_fixtures``), because building a real pool does not need a generated dataset.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pool_fixtures import build_two_event_store, make_event, commit_event
from synlab.qc import gates as gates_mod
from synlab.relations.api import (
    PoolConfig,
    build_pool,
    build_pool_from_config,
    commit_pool,
    commit_roster,
    contributing_run_ids,
)
from synlab.roles import ROLE_CLEAN_TRUTH, ROLE_LABEL_BUNDLE, ROLE_POOL, ROLE_ROSTER
from synlab.storage.store import QA_PASS, AssetStore

#: The metadata contract of ``commit_pool`` *without* a run id.  Asserting the exact key set is
#: what makes "adding run_id is backwards compatible" checkable: an accidental new key would
#: change the interpretation hash and therefore the asset id of every existing caller.
POOL_META_KEYS = {
    "schema", "api_version", "gallery", "fragment_records", "roster", "gallery_distractor_only",
    "pool_meta", "relation_storage", "n2_materialised",
}
#: ``commit_roster`` hands its payload keys to the store, which folds the JSON-serialisable ones
#: into the metadata as well, so ``gallery_version``/``roster`` appear next to the declared ones.
ROSTER_META_KEYS = {"pool_id", "queries", "frozen", "hash", "gallery_version", "roster"}


def _pool(tmp_path: Path):
    store, specs = build_two_event_store(tmp_path)
    report = build_pool(store, None, PoolConfig(pool_id="pool_attr", size_target=100,
                                               query_per_mother=1))
    assert report["ok"], report.get("error")
    return store, specs, report["pool"]


def _rebuild(store: AssetStore):
    """A second, independent build of the same gallery (``commit_pool`` mutates ``pool.meta``)."""
    report = build_pool(store, None, PoolConfig(pool_id="pool_attr", size_target=100,
                                               query_per_mother=1))
    assert report["ok"], report.get("error")
    return report["pool"]


def _stamp_lineage_run(store: AssetStore, lineage_id: str, run_id: str) -> int:
    """Write ``meta.run_id`` on the truth/label assets of one lineage (what the pipeline does)."""
    changed = 0
    with store.connect() as conn:
        rows = conn.execute("SELECT asset_id, meta_json FROM assets WHERE lineage_id=?",
                            (lineage_id,)).fetchall()
        for row in rows:
            meta = json.loads(row["meta_json"] or "{}")
            meta["run_id"] = run_id
            conn.execute("UPDATE assets SET meta_json=? WHERE asset_id=?",
                         (json.dumps(meta, sort_keys=True), row["asset_id"]))
            changed += 1
    return changed


# ---------------------------------------------------------------------------------------
# 1. the helper is backwards compatible
# ---------------------------------------------------------------------------------------
def test_pool_without_run_id_keeps_the_frozen_metadata_and_asset_id(tmp_path: Path) -> None:
    store, _specs, pool = _pool(tmp_path)
    first = commit_pool(store, pool, split="dev")
    # a second, independent build of the same gallery commits to the very same asset
    second = commit_pool(store, _rebuild(store), split="dev")
    assert first.asset_id == second.asset_id
    assert set(first.meta) == POOL_META_KEYS, sorted(first.meta)
    assert "run_id" not in first.meta
    assert first.role == ROLE_POOL


def test_roster_without_run_id_keeps_the_frozen_metadata(tmp_path: Path) -> None:
    store, _specs, pool = _pool(tmp_path)
    asset = commit_roster(store, pool, split="dev")
    assert set(asset.meta) == ROSTER_META_KEYS, sorted(asset.meta)
    assert asset.role == ROLE_ROSTER


def test_run_id_changes_only_the_run_key(tmp_path: Path) -> None:
    store, _specs, pool = _pool(tmp_path)
    plain = commit_pool(store, pool, split="dev")
    stamped = commit_pool(store, _rebuild(store), split="dev", run_id="run_abc123")
    assert stamped.asset_id != plain.asset_id, "the run attribution is part of the identity"
    assert stamped.meta["run_id"] == "run_abc123"
    assert set(stamped.meta) == POOL_META_KEYS | {"run_id"}
    for key in POOL_META_KEYS:
        assert stamped.meta[key] == plain.meta[key], key


def test_roster_run_id_is_written_only_when_given(tmp_path: Path) -> None:
    store, _specs, pool = _pool(tmp_path)
    plain = commit_roster(store, pool, split="dev")
    stamped = commit_roster(store, _rebuild(store), split="dev", run_id="run_abc123")
    assert stamped.asset_id != plain.asset_id
    assert stamped.meta["run_id"] == "run_abc123"
    assert set(stamped.meta) == ROSTER_META_KEYS | {"run_id"}


# ---------------------------------------------------------------------------------------
# 2. the gate reads the run-scoped pool (and nothing else)
# ---------------------------------------------------------------------------------------
def test_relations_complete_follows_the_run_scoped_pool(tmp_path: Path) -> None:
    store, _specs, pool = _pool(tmp_path)
    run_id = "run_poolgate"
    store.create_run(run_id, "sha256:spec", scope="SYNTHETIC", profile="PILOT")
    qa = {"ok": True, "n2_materialised": False, "verdict": "PASS"}

    # (a) a pool committed without a run id is invisible to the run: still PENDING
    orphan = commit_pool(store, pool, split="dev", qa=qa)
    store.set_qa(orphan.asset_id, QA_PASS, qa)
    gates, _assets, _profile = gates_mod.evaluate_gates(store, run_id)
    assert gates["relations_complete"] == "PENDING"

    # (b) the same pool committed *with* the run id is the run's evidence
    stamped = commit_pool(store, pool, split="dev", qa=qa, run_id=run_id)
    store.set_qa(stamped.asset_id, QA_PASS, qa)
    gates, _assets, _profile = gates_mod.evaluate_gates(store, run_id)
    assert gates["relations_complete"] == "PASS"
    assert "relations_complete" in gates_mod.PROFILE_GATES["PILOT"]


def test_relations_complete_requires_a_pass_verdict(tmp_path: Path) -> None:
    """A run-stamped pool that is not QA_PASS does not satisfy the gate."""
    store, _specs, pool = _pool(tmp_path)
    run_id = "run_poolgate_pending"
    store.create_run(run_id, "sha256:spec", scope="SYNTHETIC", profile="PILOT")
    asset = commit_pool(store, pool, split="dev", run_id=run_id)  # QA_PENDING on purpose
    assert asset.qa_status != QA_PASS
    gates, _assets, _profile = gates_mod.evaluate_gates(store, run_id)
    assert gates["relations_complete"] == "PENDING"


# ---------------------------------------------------------------------------------------
# 3. config-driven build: attribute only when it is unambiguous
# ---------------------------------------------------------------------------------------
def _config(tmp_path: Path) -> Path:
    path = tmp_path / "pool.yaml"
    path.write_text("schema: synlab.pool.v1\n"
                    "pool_id: attr_pool\n"
                    "gallery_version: v1\n"
                    "scope: FULL\n"
                    "split: dev\n"
                    "size_target: 100\n"
                    "exclude_training_lineages: false\n"
                    "query_per_mother: 1\n"
                    "include_unverified: true\n"
                    "nested_sizes: [2]\n"
                    "seed: 20261001\n", encoding="utf-8")
    return path


def test_contributing_run_ids_are_measured_from_the_store(tmp_path: Path) -> None:
    store, specs, pool = _pool(tmp_path)
    assert contributing_run_ids(store, pool) == []
    for spec in specs:
        _stamp_lineage_run(store, spec.lineage_id, "run_one")
    assert contributing_run_ids(store, pool) == ["run_one"]


def test_build_pool_from_config_uses_the_single_contributing_run(tmp_path: Path) -> None:
    store, specs, _pool_report = _pool(tmp_path)
    for spec in specs:
        _stamp_lineage_run(store, spec.lineage_id, "run_one")
    report = build_pool_from_config(store, "sandbox", _config(tmp_path))
    assert report["ok"], report.get("error")
    attribution = report["run_id_attribution"]
    assert attribution["run_id"] == "run_one"
    assert attribution["source"] == "contributing_runs"
    assert store.get_asset(report["artifacts"]["pool_asset"]).meta["run_id"] == "run_one"
    assert store.get_asset(report["artifacts"]["roster_asset"]).meta["run_id"] == "run_one"
    # the gallery that was just built and audited is the evidence for the QA verdict, so the pool
    # really is usable as `relations_complete` evidence (a committed-but-PENDING asset is not)
    pool_asset = store.get_asset(report["artifacts"]["pool_asset"])
    assert pool_asset.qa_status == QA_PASS
    assert pool_asset.qa["verdict"] == "PASS" and pool_asset.qa["gallery_hash"] == report["hash"]
    assert store.get_asset(report["artifacts"]["roster_asset"]).qa_status == QA_PASS


def test_build_pool_from_config_refuses_to_guess_across_runs(tmp_path: Path) -> None:
    store, specs, _pool_report = _pool(tmp_path)
    _stamp_lineage_run(store, specs[0].lineage_id, "run_one")
    _stamp_lineage_run(store, specs[1].lineage_id, "run_two")
    report = build_pool_from_config(store, "sandbox", _config(tmp_path))
    attribution = report["run_id_attribution"]
    assert attribution["run_id"] is None
    assert attribution["source"] == "ambiguous"
    assert sorted(attribution["contributing_run_ids"]) == ["run_one", "run_two"]
    assert "2 runs" in attribution["reason"]
    assert "run_id" not in store.get_asset(report["artifacts"]["pool_asset"]).meta


def test_build_pool_from_config_honours_an_explicit_run_id(tmp_path: Path) -> None:
    store, specs, _pool_report = _pool(tmp_path)
    _stamp_lineage_run(store, specs[0].lineage_id, "run_one")
    _stamp_lineage_run(store, specs[1].lineage_id, "run_two")
    report = build_pool_from_config(store, "sandbox", _config(tmp_path), run_id="run_batch")
    attribution = report["run_id_attribution"]
    assert attribution["run_id"] == "run_batch"
    assert attribution["source"] == "caller"
    assert attribution["caller_run_id_is_contributing"] is False
    assert store.get_asset(report["artifacts"]["pool_asset"]).meta["run_id"] == "run_batch"


def test_no_run_can_be_attributed_without_a_clean_truth_or_label_bundle(tmp_path: Path) -> None:
    """A store whose assets carry no run id records *why* nothing was stamped."""
    store = AssetStore(tmp_path)
    spec = make_event("LIN0007_V07_M07", "m::7", "q", 3, split="dev", seed=7)
    commit_event(store, spec)
    report = build_pool_from_config(store, "sandbox", _config(tmp_path))
    assert report["ok"], report.get("error")
    attribution = report["run_id_attribution"]
    assert attribution["run_id"] is None
    assert attribution["source"] == "unavailable"
    assert "meta.run_id" in attribution["reason"]
