"""The coverage gates read *real* coverage: the cross-run aggregate and the real key names.

Three defects are pinned here:

1. ``coverage.json`` is store-global -- ``pipeline.run_generation`` rewrites it once per run, so it
   can only describe the newest run, while a batch of data is many runs (one ``run_id`` per
   batch).  The gates therefore read ``reports/coverage_aggregate.json`` (the cross-run aggregate
   :func:`synlab.qc.gates.write_coverage_aggregate` derives from ``runs``/``assets``/coverage rows)
   when it exists.
2. ``coverage_4_backends`` read ``coverage["fracture_backends"]`` while the single-run ledger
   spells the key in the singular (``"fracture_backend": "plane_shared_cut"``) -- the gate read a
   key that never existed.
3. ``coverage_31_axes`` read ``coverage["axes"]``, a key the single-run ledger never carried.  The
   axes a run really exercised are recorded on its own physical assets (``meta.axis_id``), so that
   is what the gate reads when no aggregate is present.

Nothing here is relaxed: each test also pins the *negative* direction (a gate that is short of its
target stays PENDING and reports the measured shortfall), so a gate can be neither always-PENDING
nor always-PASS.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from synlab.qc import gates as gates_mod
from synlab.roles import (
    FRAME_FRAGMENT,
    FRAME_WORLD,
    ROLE_FRAGMENT_MESH,
    ROLE_MOTHER_MESH,
    ROLE_PATTERN_RECIPE,
    ROLE_PHYSICAL_COMPONENT,
    SCHEMA_FRAGMENT,
    SCHEMA_MOTHER,
    SCHEMA_PATTERN,
    SCHEMA_PHYSICAL,
    UNIT_MM,
)
from synlab.storage.store import QA_PASS, AssetStore

RUN_ID = "run_covtest"


def _store(tmp_path: Path) -> AssetStore:
    store = AssetStore(tmp_path / "store")
    store.create_run(RUN_ID, "sha256:spec", scope="SYNTHETIC", profile="CORE_COVERAGE")
    return store


def _commit(store: AssetStore, role: str, schema: str, *, run_id: str | None, **meta) -> str:
    record = store.commit_asset(
        role=role, schema=schema, unit=UNIT_MM,
        frame=FRAME_WORLD if role != ROLE_PHYSICAL_COMPONENT else FRAME_FRAGMENT,
        payload={}, meta=({**meta, "run_id": run_id} if run_id else dict(meta)),
        qa={"ok": True}, qa_status=QA_PASS,
        lineage_id=meta.get("lineage_id"), split="dev")
    return record.asset_id


def _populate(store: AssetStore, *, run_id: str | None = RUN_ID, vessels: int = 2,
              materials: int = 2, patterns: int = 2, backends: tuple[str, ...] = ("plane_shared_cut",),
              axes: tuple[str, ...] = (), fragments_per_backend: int = 1) -> None:
    for index in range(max(vessels, materials, patterns)):
        _commit(store, ROLE_MOTHER_MESH, SCHEMA_MOTHER, run_id=run_id,
                mother_id=f"m::{index:03d}", vessel_id=f"V{index:02d}",
                material_id=f"M{index:02d}", lineage_id=f"LIN{index:04d}")
    for index in range(patterns):
        _commit(store, ROLE_PATTERN_RECIPE, SCHEMA_PATTERN, run_id=run_id,
                family_id=f"PAT{index:02d}", lineage_id=f"LIN{index:04d}")
    for backend in backends:
        for _ in range(fragments_per_backend):
            _commit(store, ROLE_FRAGMENT_MESH, SCHEMA_FRAGMENT, run_id=run_id,
                    backend=backend, fragment_id=f"f::{backend}")
    for axis in axes:
        _commit(store, ROLE_PHYSICAL_COMPONENT, SCHEMA_PHYSICAL, run_id=run_id, axis_id=axis)


def _write_single_run_coverage(store: AssetStore, *, run_id: str = RUN_ID, **summary) -> Path:
    path = store.root / "reports" / "coverage.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": "synlab.coverage.v1", "run_id": run_id, **summary}),
                    encoding="utf-8")
    return path


# ---------------------------------------------------------------------------------------
# 1. the aggregate itself
# ---------------------------------------------------------------------------------------
def test_aggregate_counts_only_assets_a_run_claims(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _populate(store, vessels=3, materials=2, patterns=2, backends=("plane_shared_cut",))
    _populate(store, run_id=None, vessels=1, materials=1, patterns=1, backends=("rough_shared_cut",))
    payload = gates_mod.coverage_aggregate(store)
    assert payload["run_count"] == 1
    run = payload["runs"][0]
    assert run["run_id"] == RUN_ID
    assert run["assets"] == 6          # 3 mothers + 2 pattern recipes + 1 fragment
    assert run["run_id_attribution"] == {"stamped_at_commit": 6, "repair": 0, "none": 0}
    assert run["mothers"] == 3 and run["fragments"] == 1
    assert run["vessels"] == ["V00", "V01", "V02"]
    assert payload["unattributed_assets"]["count"] == 3
    # the unattributed assets are real, so the store-wide totals carry their backend, while the
    # run-scoped record does not claim it
    assert run["fracture_backends"] == ["plane_shared_cut"]
    assert payload["fracture_backends"] == ["plane_shared_cut", "rough_shared_cut"]
    assert payload["totals"]["assets"] == 9


def test_aggregate_reports_orphan_runs_instead_of_dropping_them(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _populate(store, run_id="run_not_in_the_table")
    payload = gates_mod.coverage_aggregate(store)
    assert payload["orphan_run_ids"] == ["run_not_in_the_table"]
    by_run = {run["run_id"]: run for run in payload["runs"]}
    assert by_run["run_not_in_the_table"]["status"] == "UNRECORDED"
    assert by_run["run_not_in_the_table"]["assets"] == 5   # 2 mothers + 2 recipes + 1 fragment


def test_aggregate_is_reproducible(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _populate(store, vessels=2, materials=2, patterns=2, axes=("P03", "G01"))
    first = gates_mod.coverage_aggregate(store)
    second = gates_mod.coverage_aggregate(store)
    assert first["content_hash"] == second["content_hash"]


def test_write_coverage_aggregate_writes_json_and_parquet(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _populate(store)
    payload = gates_mod.write_coverage_aggregate(store)
    assert Path(payload["artifacts"]["json"]).exists()
    assert payload["artifacts"]["parquet_written"] is True
    assert Path(payload["artifacts"]["parquet"]).exists()


# ---------------------------------------------------------------------------------------
# 2. layer combos come from the per-lineage coverage rows (the only place they exist)
# ---------------------------------------------------------------------------------------
def test_layer_combos_are_read_from_the_runs_own_coverage_rows(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _populate(store)
    _write_single_run_coverage(store, fracture_backend="plane_shared_cut")
    rows = store.root / "reports" / "coverage_rows.json"
    rows.write_text(json.dumps([
        {"lineage_id": f"LIN{i:04d}", "split": "dev", "vessel_id": f"V{i:02d}",
         "material_id": f"M{i:02d}", "pattern_id": f"PAT{i:02d}", "layer_combo_id": f"L{i + 1:02d}",
         "accepted": 1, "backend": "plane_shared_cut"} for i in range(4)]), encoding="utf-8")
    payload = gates_mod.coverage_aggregate(store)
    assert payload["layer_combos"] == ["L01", "L02", "L03", "L04"]
    assert payload["runs"][0]["coverage_rows"] == 4
    assert payload["gaps"]["coverage_4_layers"]["status"] == "PASS"


def test_rows_of_another_run_are_not_attributed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _populate(store)
    _write_single_run_coverage(store, run_id="run_someone_else", fracture_backend="plane_shared_cut")
    (store.root / "reports" / "coverage_rows.json").write_text(
        json.dumps([{"lineage_id": "LIN0000", "layer_combo_id": "L09", "accepted": 1}]),
        encoding="utf-8")
    payload = gates_mod.coverage_aggregate(store)
    assert payload["layer_combos"] == []


def test_batch_ledger_rows_keep_their_own_run_attribution(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _populate(store, run_id="run_a")
    store.create_run("run_b", "sha256:spec", scope="SYNTHETIC", profile="PILOT")
    (store.root / "reports" / "next_experiment_batches.json").write_text(json.dumps({
        "schema": "synlab.next_experiment.batches.v1",
        "batches": [
            {"run_id": "run_a", "lineage_id": "LIN0000", "layer_combo_id": "L01", "ok": True},
            {"run_id": "run_b", "lineage_id": "LIN0001", "layer_combo_id": "L02", "ok": True},
            {"run_id": "run_b", "lineage_id": "LIN0002", "layer_combo_id": "L03", "ok": False},
        ]}), encoding="utf-8")
    payload = gates_mod.coverage_aggregate(store)
    by_run = {run["run_id"]: run for run in payload["runs"]}
    assert by_run["run_a"]["layer_combos"] == ["L01"]
    # a failed attempt is not coverage
    assert by_run["run_b"]["layer_combos"] == ["L02"]
    assert payload["layer_combos"] == ["L01", "L02"]


# ---------------------------------------------------------------------------------------
# 3. the gates read the real keys of both payload shapes
# ---------------------------------------------------------------------------------------
def test_backend_gate_reads_the_singular_key_of_the_single_run_ledger(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _populate(store, backends=("plane_shared_cut",))
    _write_single_run_coverage(store, fracture_backend="plane_shared_cut",
                               vessels=["V00", "V01"], materials=["M00", "M01"])
    gates, _assets, _profile = gates_mod.evaluate_gates(store, RUN_ID)
    # one backend is really present, so the gate is judged (PENDING: the target is 4) -- the old
    # reader asked for a "fracture_backends" key that never existed and could not see even this
    assert gates["coverage_4_backends"] == "PENDING"
    measured = gates_mod.gate_measurements(store, RUN_ID)["gates"]["coverage_4_backends"]
    assert measured["present"] == 1 and measured["target"] == 4 and measured["shortfall"] == 3


def test_backend_gate_passes_with_four_real_backends(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _populate(store, backends=("plane_shared_cut", "rough_shared_cut", "secondary_fracture",
                               "plane_axis_aligned"))
    gates_mod.write_coverage_aggregate(store)
    gates, _assets, _profile = gates_mod.evaluate_gates(store, RUN_ID)
    assert gates["coverage_4_backends"] == "PASS"


def test_vessel_gate_is_judged_in_both_directions(tmp_path: Path) -> None:
    short = _store(tmp_path / "short")
    _populate(short, vessels=23)
    gates_mod.write_coverage_aggregate(short)
    assert gates_mod.evaluate_gates(short, RUN_ID)[0]["coverage_24_vessels"] == "PENDING"

    full = _store(tmp_path / "full")
    _populate(full, vessels=24)
    gates_mod.write_coverage_aggregate(full)
    assert gates_mod.evaluate_gates(full, RUN_ID)[0]["coverage_24_vessels"] == "PASS"


def test_axis_gate_reads_the_axes_the_run_really_exercised(tmp_path: Path) -> None:
    registered = gates_mod.registered_axis_ids()
    assert len(registered) == 31, "the 31-axis target is the registered axis set of this build"

    store = _store(tmp_path)
    _populate(store, axes=tuple(registered[:-1]))          # 30 of 31
    _write_single_run_coverage(store, fracture_backend="plane_shared_cut")
    gates, _assets, _profile = gates_mod.evaluate_gates(store, RUN_ID)
    assert gates["coverage_31_axes"] == "PENDING"
    measured = gates_mod.gate_measurements(store, RUN_ID)["gates"]["coverage_31_axes"]
    assert measured["present"] == 30 and measured["missing"] == [registered[-1]]

    store2 = _store(tmp_path / "store2")
    _populate(store2, axes=tuple(registered))
    _write_single_run_coverage(store2, fracture_backend="plane_shared_cut")
    assert gates_mod.evaluate_gates(store2, RUN_ID)[0]["coverage_31_axes"] == "PASS"


def test_aggregate_is_preferred_over_the_single_run_ledger(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _populate(store, vessels=24)
    _write_single_run_coverage(store, fracture_backend="plane_shared_cut", vessels=["V00"])
    gates, _assets, _profile = gates_mod.evaluate_gates(store, RUN_ID)
    # no aggregate yet -> the single-run ledger says 1 vessel
    assert gates["coverage_24_vessels"] == "PENDING"
    gates_mod.write_coverage_aggregate(store)
    gates, _assets, _profile = gates_mod.evaluate_gates(store, RUN_ID)
    assert gates["coverage_24_vessels"] == "PASS"


def test_missing_coverage_evidence_stays_pending(tmp_path: Path) -> None:
    """No aggregate and no ledger: every coverage gate is PENDING, not PASS."""
    store = _store(tmp_path)
    _populate(store, vessels=30, materials=13, patterns=17, axes=("P03",))
    gates, _assets, _profile = gates_mod.evaluate_gates(store, RUN_ID)
    for gate in gates_mod.COVERAGE_GATE_KEYS:
        assert gates[gate] == "PENDING", (gate, gates[gate])


def test_coverage_targets_match_the_release_gate_names() -> None:
    assert set(gates_mod.COVERAGE_GATE_KEYS) == {
        "coverage_24_vessels", "coverage_12_materials", "coverage_16_patterns",
        "coverage_4_layers", "coverage_4_backends", "coverage_31_axes"}
    assert gates_mod.COVERAGE_TARGETS == {
        "vessels": 24, "materials": 12, "patterns": 16, "layer_combos": 4,
        "fracture_backends": 4, "axes": 31}
    # the gates these targets describe are part of a real profile
    assert set(gates_mod.COVERAGE_GATE_KEYS) <= set(
        __import__("synlab.storage.release", fromlist=["PROFILE_GATES"]).PROFILE_GATES["CORE_COVERAGE"])


def test_coverage_gaps_report_status_present_and_shortfall(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _populate(store, vessels=3, materials=2, patterns=1, backends=("plane_shared_cut",))
    payload = gates_mod.write_coverage_aggregate(store)
    gaps = payload["gaps"]
    assert gaps["coverage_24_vessels"] == {"key": "vessels", "present": 3, "target": 24,
                                          "shortfall": 21, "status": "PENDING"}
    # the shortfall is target - measured, and the measured value is the payload's own set
    for gate, key in gates_mod.COVERAGE_GATE_KEYS.items():
        assert gaps[gate]["present"] == len(payload[key]), gate
        assert gaps[gate]["shortfall"] == max(0, gaps[gate]["target"] - gaps[gate]["present"])
    assert gaps["coverage_31_axes"]["present"] == 0
    assert gaps["coverage_31_axes"]["missing"] == gates_mod.registered_axis_ids()


def test_gate_evidence_includes_the_aggregate_file(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _populate(store, vessels=2)
    gates_mod.write_coverage_aggregate(store)
    evidence = gates_mod.gate_evidence(store, RUN_ID)
    assert "coverage_aggregate" in evidence
    assert evidence["coverage_aggregate"]["metrics"]["schema"] == \
        gates_mod.COVERAGE_AGGREGATE_SCHEMA
    assert evidence["coverage_aggregate"]["hash"].startswith("sha256:")
