"""Foundation tests: seeds, storage, scheduler, leases, release gates (M01)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import trimesh

from synlab.canonical import array_hash, canonical_json, hash_json
from synlab.config import compile_spec, load_generation_spec
from synlab.errors import ErrorCode, SynLabError
from synlab.jobs.leases import LeaseManager
from synlab.jobs.recovery import recovery_probe, resume_run
from synlab.jobs.resources import Estimate, ResourceBudget, ResourceGuard
from synlab.jobs.scheduler import Scheduler
from synlab.jobs.state import JobState, can_transition
from synlab.seeds import derive_named_rngs, make_rng, seed64
from synlab.storage.mesh_io import arrays_to_mesh, mesh_arrays, with_face_attrs
from synlab.storage.release import ReleaseManager
from synlab.storage.store import QA_PASS, AssetStore, health_check


@pytest.fixture()
def store(tmp_path: Path) -> AssetStore:
    return AssetStore(tmp_path / "data")


# ---------------------------------------------------------------------------- seeds
def test_seed_is_stable_and_order_independent() -> None:
    a = seed64(1, "lineage", "shape")
    b = seed64(1, "lineage", "shape")
    assert a == b
    assert seed64(1, "shape", "lineage") != a
    rngs = derive_named_rngs(7, "L1")
    again = derive_named_rngs(7, "L1")
    assert np.allclose(rngs["shape"].random(5), again["shape"].random(5))
    # different modules must not share a stream
    assert not np.allclose(rngs["shape"].random(5), rngs["cut"].random(5))
    # worker order cannot change a stream: each module derives from its own key
    per_module = {name: make_rng(7, "L1", name).random(3) for name in ("shape", "cut", "damage")}
    reordered = {name: make_rng(7, "L1", name).random(3) for name in ("damage", "shape", "cut")}
    for name in per_module:
        assert np.allclose(per_module[name], reordered[name])


def test_canonical_json_rejects_nan() -> None:
    with pytest.raises(ValueError):
        canonical_json({"x": float("nan")})
    assert hash_json({"b": 1, "a": 2}) == hash_json({"a": 2, "b": 1})


# ---------------------------------------------------------------------------- storage
def test_asset_commit_is_idempotent_and_verified(store: AssetStore) -> None:
    payload = {"arr": np.arange(8, dtype=np.float32)}
    first = store.commit_asset(role="qa_report", schema="synlab.qa.v1", unit="1", frame="none",
                               payload=payload, qa={"ok": True}, qa_status=QA_PASS)
    second = store.commit_asset(role="qa_report", schema="synlab.qa.v1", unit="1", frame="none",
                                payload=payload, qa={"ok": True}, qa_status=QA_PASS)
    assert first.asset_id == second.asset_id
    assert np.allclose(store.load_arrays(first.asset_id)["arr"], payload["arr"])
    assert health_check(str(store.root))["ok"]


def test_asset_tampering_is_detected(store: AssetStore) -> None:
    rec = store.commit_asset(role="qa_report", schema="synlab.qa.v1", unit="1", frame="none",
                             payload={"arr": np.ones(4, dtype=np.float32)}, qa_status=QA_PASS)
    path = store.asset_path(rec.asset_id, "arrays")
    data = bytearray(path.read_bytes())
    data[-1] ^= 0xFF
    path.write_bytes(bytes(data))
    health = health_check(str(store.root))
    assert not health["ok"]
    assert any("hash mismatch" in p for p in health["problems"])


def test_mesh_roundtrip_keeps_face_semantics(store: AssetStore) -> None:
    mesh = trimesh.creation.box(extents=(10.0, 20.0, 30.0))
    tags = np.arange(len(mesh.faces), dtype=np.int32)
    with_face_attrs(mesh, surface_tag=tags, origin_kind=np.zeros(len(mesh.faces), dtype=np.uint8))
    rec = store.commit_asset(role="fragment_mesh", schema="synlab.fragment.v1", unit="mm",
                             frame="W_mm", payload={"mesh": mesh}, qa_status=QA_PASS)
    loaded = store.load_mesh(rec.asset_id)
    attrs = loaded.metadata["face_attr_arrays"]
    assert np.array_equal(attrs["surface_tag"], tags)
    assert len(loaded.faces) == len(mesh.faces)
    assert abs(float(loaded.volume) - float(mesh.volume)) < 1e-6
    arrays = mesh_arrays(mesh)
    back, attrs2 = arrays_to_mesh(arrays)
    assert np.array_equal(attrs2["surface_tag"], tags)


# ---------------------------------------------------------------------------- scheduler
def test_scheduler_state_machine_and_fencing(store: AssetStore) -> None:
    scheduler = Scheduler(store)
    store.create_run("run1", hash_json({"spec": 1}), scope="SYNTHETIC", profile="SANDBOX_CORE")
    scheduler.create_job(job_id="j1", run_id="run1", stage="mother", spec={})
    record, token, fence = scheduler.claim("j1")
    assert record.state == JobState.RUNNING.value
    scheduler.transition("j1", JobState.OUTPUT_READY, token=token, fence=fence)
    scheduler.transition("j1", JobState.QA_PASS, token=token, fence=fence)
    scheduler.transition("j1", JobState.COMMITTED, token=token, fence=fence)
    # stale token must be rejected
    with pytest.raises(SynLabError) as exc:
        scheduler.transition("j1", JobState.QA_PASS, token="bogus", fence=fence)
    assert exc.value.code == ErrorCode.LEASE_STALE
    with pytest.raises(Exception):
        scheduler.transition("j1", JobState.RUNNING, token=token, fence=fence)
    assert can_transition(JobState.PENDING, JobState.RUNNING)
    assert not can_transition(JobState.COMMITTED, JobState.PENDING)


def test_dependency_gating_and_blocking(store: AssetStore) -> None:
    scheduler = Scheduler(store)
    store.create_run("run2", hash_json({"spec": 2}), scope="SYNTHETIC", profile="SANDBOX_CORE")
    scheduler.create_job(job_id="a", run_id="run2", stage="mother", spec={})
    scheduler.create_job(job_id="b", run_id="run2", stage="fracture", spec={}, depends_on=["a"])
    assert [j.job_id for j in scheduler.ready()] == ["a"]
    with pytest.raises(SynLabError):
        scheduler.claim("b")
    record, token, fence = scheduler.claim("a")
    for state in (JobState.OUTPUT_READY, JobState.QA_PASS, JobState.COMMITTED):
        scheduler.transition("a", state, token=token, fence=fence)
    assert [j.job_id for j in scheduler.ready()] == ["b"]
    scheduler.fail("b", SynLabError(ErrorCode.MOTHER_INVALID, "boom", stage="fracture"))
    assert scheduler.get_job("b").state == JobState.FAILED.value
    scheduler.create_job(job_id="c", run_id="run2", stage="observe", spec={}, depends_on=["b"])
    blocked = scheduler.block_dependents("b", "dependency failed")
    assert blocked == ["c"]
    assert scheduler.get_job("c").state == JobState.BLOCKED.value


def test_retry_keeps_content_seed_and_dependency_cycle_rejected(store: AssetStore) -> None:
    scheduler = Scheduler(store)
    store.create_run("run3", hash_json({"spec": 3}), scope="SYNTHETIC", profile="SANDBOX_CORE")
    scheduler.create_job(job_id="x", run_id="run3", stage="damage", spec={"seed": 42})
    first, _, _ = scheduler.claim("x")
    assert first.attempt == 1
    scheduler.fail("x", SynLabError(ErrorCode.DAMAGE_EFFECT_MISSING, "transient",
                                    stage="damage", retryable=True))
    assert scheduler.get_job("x").state == JobState.RETRYABLE.value
    scheduler.requeue("x")
    record, _, _ = scheduler.claim("x")
    assert record.attempt == 2
    assert record.spec["seed"] == 42
    with pytest.raises(SynLabError):
        scheduler.create_job(job_id="y", run_id="run3", stage="a", spec={}, depends_on=["z"])
        scheduler.create_job(job_id="z", run_id="run3", stage="b", spec={}, depends_on=["y"])


def test_idempotency_conflict(store: AssetStore) -> None:
    scheduler = Scheduler(store)
    payload = {"a": 1}
    assert scheduler.idempotent_lookup("key1", payload) is None
    scheduler.idempotent_record("key1", payload, "j1", "r1")
    assert scheduler.idempotent_lookup("key1", payload) == ("j1", "r1")
    with pytest.raises(SynLabError):
        scheduler.idempotent_lookup("key1", {"a": 2})


def test_recovery_probe_blocks_stale_commit(store: AssetStore) -> None:
    report = recovery_probe(store)
    assert report["stale_commit_blocked"], report
    assert report["final_state"] == JobState.COMMITTED.value


def test_resume_run_reports_states(store: AssetStore) -> None:
    scheduler = Scheduler(store)
    store.create_run("run4", hash_json({"spec": 4}), scope="SYNTHETIC", profile="SANDBOX_CORE")
    scheduler.create_job(job_id="q1", run_id="run4", stage="mother", spec={})
    scheduler.claim("q1")
    scheduler.fail("q1", SynLabError(ErrorCode.MOTHER_INVALID, "transient", stage="mother",
                                     retryable=True))
    report = resume_run(store, "run4")
    assert report["ok"] and "q1" in report["requeued"]


# ---------------------------------------------------------------------------- leases / budget
def test_gpu_lease_excludes_and_drains(store: AssetStore) -> None:
    manager = LeaseManager(store, ttl_seconds=100.0)
    lease = manager.acquire("gpu0", "trainer")
    with pytest.raises(SynLabError) as exc:
        manager.acquire("gpu0", "renderer")
    assert exc.value.code == ErrorCode.BUDGET_EXCEEDED
    manager.release("gpu0", lease.token)
    second = manager.acquire("gpu0", "renderer")
    assert second.token != lease.token


def test_expired_lease_requires_drain(store: AssetStore) -> None:
    manager = LeaseManager(store, ttl_seconds=-1.0)
    manager.acquire("gpu1", "old")
    with pytest.raises(SynLabError) as exc:
        manager.acquire("gpu1", "new")
    assert exc.value.code == ErrorCode.GPU_DRAIN_PENDING
    manager.confirm_drained("gpu1", stopped_pid=12345)
    fresh = manager.acquire("gpu1", "new")
    assert fresh.state == "HELD"


def test_budget_admission_counts_all_reservations(store: AssetStore) -> None:
    guard = ResourceGuard(store, ResourceBudget(cpu_rss_budget_gb=4.0, gpu_budget_gb=4.0))
    first = guard.admit("job-a", Estimate(rss_gb=2.0, vram_gb=2.0), requires_gpu=True)
    with pytest.raises(SynLabError) as exc:
        guard.admit("job-b", Estimate(rss_gb=3.0, vram_gb=2.0), requires_gpu=True)
    assert exc.value.code == ErrorCode.BUDGET_EXCEEDED
    guard.release(first["reservation_id"])
    guard.admit("job-c", Estimate(rss_gb=3.0, vram_gb=1.0), requires_gpu=True)


# ---------------------------------------------------------------------------- release gates
def test_release_gates_block_pending_required(store: AssetStore) -> None:
    manager = ReleaseManager(store)
    rec = store.commit_asset(role="mother_mesh", schema="synlab.mother.v1", unit="mm", frame="W_mm",
                             payload={"arr": np.zeros(3, dtype=np.float32)}, qa_status=QA_PASS)
    with pytest.raises(SynLabError) as exc:
        manager.freeze(release_id="r1", profile="PILOT", scope="run1", asset_ids=[rec.asset_id],
                       gates={"fixture_contract": "PASS"})
    assert exc.value.code == ErrorCode.STOP_QA
    gates = {gate: "PASS" for gate in
             __import__("synlab.storage.release", fromlist=["PROFILE_GATES"]).PROFILE_GATES["SANDBOX_CORE"]}
    frozen = manager.freeze(release_id="r2", profile="SANDBOX_CORE", scope="run1",
                            asset_ids=[rec.asset_id], gates=gates)
    assert frozen.manifest_hash.startswith("sha256:")
    manifest = manager.load("r2")
    assert manifest["release_id"] == "r2"
    # second freeze with the same id must be rejected (immutability)
    with pytest.raises(SynLabError):
        manager.freeze(release_id="r2", profile="SANDBOX_CORE", scope="run1",
                       asset_ids=[rec.asset_id], gates=gates)
    # manifest tampering is detected
    path = Path(frozen.manifest_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["scope"] = "tampered"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SynLabError):
        manager.load("r2")


def test_release_closure_requires_qa_pass(store: AssetStore) -> None:
    manager = ReleaseManager(store)
    pending = store.commit_asset(role="mother_mesh", schema="synlab.mother.v1", unit="mm",
                                 frame="W_mm", payload={"arr": np.zeros(3, dtype=np.float32)},
                                 qa_status="QA_PENDING")
    closure = manager.verify_closure([pending.asset_id])
    assert not closure["ok"]


# ---------------------------------------------------------------------------- config compile
def test_generation_spec_rejects_unknown_and_unregistered(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    spec = load_generation_spec(root / "configs" / "a12" / "sandbox.yaml")
    compiled = compile_spec(spec)
    assert compiled.ok, compiled.errors
    assert compiled.spec_hash.startswith("sha256:")
    bad = spec.model_dump(by_alias=True)
    bad["dataset"]["vessel_ids"] = ["V99"]
    from synlab.schemas.spec import GenerationSpec

    compiled_bad = compile_spec(GenerationSpec.model_validate(bad), registry_ids={
        "vessel": ["V01"], "material": ["M01"], "pattern": ["PAT01"], "layer_combo": ["L01"]})
    assert not compiled_bad.ok
    assert "V99" in compiled_bad.errors[0]


def test_canonical_hash_differs_on_any_field_change() -> None:
    a = {"axis": "P03", "level": 2, "params": {"depth_mm": 0.1}}
    b = {"axis": "P03", "level": 2, "params": {"depth_mm": 0.100001}}
    assert hash_json(a) != hash_json(b)
    assert array_hash(np.zeros(3, dtype=np.float32)) != array_hash(np.zeros(3, dtype=np.float64))
