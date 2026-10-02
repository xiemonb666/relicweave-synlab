"""Tests for the read-only data quality gate (``synlab/qc/data_quality.py``).

The fixtures are built in ``tmp_path`` through the real :class:`synlab.storage.store.AssetStore`
so the schema, the payload layout and the QA states are exactly the production ones.  **No
fixture asset is ever committed into a real store** -- every store this file creates lives under
pytest's temporary directory.

Covered here (the cases the task names explicitly, plus the properties that make the verdict
trustworthy):

* mixed semantic generations => not trainable;
* an absent QA denominator / an unreadable closure => not trainable;
* ``negatives == 0`` with encodable positives => ``partial`` (not trainable), and the reason is
  the missing legal negative, not a missing positive;
* a fully marked, self-consistent minimal store => trainable;
* the gate is read-only (byte-identical tree before and after);
* a package can never be green on its own, because the package schema carries no generation
  marker -- the exact gap the gate is meant to surface;
* the thresholds themselves behave (the signed rim rule, the encoder gate reconstruction).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab.qc.data_quality import (  # noqa: E402
    RIM_ABSOLUTE_TOLERANCE_MM,
    encodable_from_arrays,
    rim_verdict,
)
from synlab.storage.store import QA_FAIL, QA_PASS, QA_PENDING, AssetStore  # noqa: E402

CURRENT_DS = {
    "mask_semantics": "coc_units_v2",
    "damage_semantics": "subset_v2",
    "subset_instrument": "trimesh.proximity.signed_distance (exact, float64)",
    "defined_in": "docs/a12/data_semantics_versions.md",
}
TOOL = REPO_ROOT / "tools" / "check_data_quality.py"

#: The fixture store uses the **declared** role vocabulary (``synlab/roles.py``), so the
#: ``contract.declared_role_vocabulary`` check can be exercised on it: a fixture built from
#: invented schema ids would fail that check for a reason that has nothing to do with the store.
from synlab import roles as roles_module  # noqa: E402

_FIXTURE_SCHEMA: dict[str, str] = {
    "mother_mesh": roles_module.SCHEMA_MOTHER,
    "material_profile": roles_module.SCHEMA_MATERIAL,
    "pattern_recipe": roles_module.SCHEMA_PATTERN,
    "pattern_channels": roles_module.SCHEMA_PATTERN,
    "cutter_mesh": roles_module.SCHEMA_CUTTER,
    "fragment_mesh": roles_module.SCHEMA_FRAGMENT,
    "clean_truth": roles_module.SCHEMA_TRUTH_CLEAN,
    "physical_truth": roles_module.SCHEMA_TRUTH_PHYSICAL,
    "visible_labels": roles_module.SCHEMA_TRUTH_VISIBLE,
    "physical_component": roles_module.SCHEMA_PHYSICAL,
    "physical_result": roles_module.SCHEMA_PHYSICAL,
    "obs_view": roles_module.SCHEMA_OBS,
    "obs_result": roles_module.SCHEMA_OBS,
    "obs_fused_geometry": roles_module.SCHEMA_OBS,
    "feature_bundle": roles_module.SCHEMA_FEATURE,
    "degrade_measurement": roles_module.SCHEMA_MEASUREMENT,
    "label_bundle": roles_module.SCHEMA_LABELS,
    "provenance": roles_module.SCHEMA_PROVENANCE,
    "relation_pool": roles_module.SCHEMA_POOL,
    "query_roster": roles_module.SCHEMA_ROSTER,
    "episode_trace": roles_module.SCHEMA_EPISODE,
    "train_checkpoint": roles_module.SCHEMA_CHECKPOINT,
    "diagnostic_report": roles_module.SCHEMA_REPORT,
    "qa_report": roles_module.SCHEMA_QA,
    "coverage": roles_module.SCHEMA_COVERAGE,
    "display_lod_glb": roles_module.SCHEMA_DISPLAY_GLB,
    "context_pack": roles_module.SCHEMA_CONTEXT,
}
_FIXTURE_UNIT: dict[str, str] = {
    "obs_view": roles_module.UNIT_PX,
    "label_bundle": roles_module.UNIT_NONE,
    "provenance": roles_module.UNIT_NONE,
    "qa_report": roles_module.UNIT_NONE,
    "relation_pool": roles_module.UNIT_NONE,
    "query_roster": roles_module.UNIT_NONE,
    "degrade_measurement": roles_module.UNIT_NONE,
    "context_pack": roles_module.UNIT_NONE,
    "display_lod_glb": roles_module.UNIT_M,
}
_FIXTURE_FRAME: dict[str, str] = {
    "physical_component": roles_module.FRAME_FRAGMENT,
    "physical_result": roles_module.FRAME_FRAGMENT,
    "obs_view": roles_module.FRAME_SCAN,
    "obs_result": roles_module.FRAME_SCAN,
    "obs_fused_geometry": roles_module.FRAME_SCAN,
    "feature_bundle": roles_module.FRAME_SCAN,
    "degrade_measurement": roles_module.FRAME_SCAN,
    "provenance": roles_module.FRAME_NONE,
    "qa_report": roles_module.FRAME_NONE,
    "context_pack": roles_module.FRAME_NONE,
    "display_lod_glb": roles_module.FRAME_Y_UP_M,
}


# --------------------------------------------------------------------------------- fixtures
class Fixture:
    """A minimal, fully marked store plus knobs to break exactly one property at a time."""

    def __init__(self, root: Path, *, repo: Path | None = None) -> None:
        self.root = root
        self.repo = repo or root.parent
        self.store = AssetStore(root)
        self.store.create_run("run_qc_fixture", "spec_hash_fixture", scope="SYNTHETIC",
                              profile="SANDBOX_CORE")
        self.assets: list[str] = []

    def commit(self, role: str, *, meta: dict, payload: dict | None = None,
               qa: dict | None = None, qa_status: str = QA_PASS,
               schema: str | None = None, unit: str | None = None,
               frame: str | None = None) -> str:
        record = self.store.commit_asset(
            role=role, schema=schema or _FIXTURE_SCHEMA.get(role, f"fixture.{role}"),
            unit=unit or _FIXTURE_UNIT.get(role, "mm"), frame=frame or _FIXTURE_FRAME.get(
                role, "W_mm"),
            payload=payload if payload is not None else {"note": "fixture"},
            meta=meta, qa=qa or {"ok": True}, qa_status=qa_status,
        )
        self.assets.append(record.asset_id)
        return record.asset_id

    def feature(self, fragment_id: str, *, views: int = 2, data_semantics: bool = True,
                quality_targets: int = 1) -> str:
        meta = {"fragment_id": fragment_id}
        if data_semantics:
            meta["data_semantics"] = dict(CURRENT_DS)
        payload = {
            "global_valid": np.ones((1, max(views, 0)), dtype=bool) if views else
                            np.zeros((1, 1), dtype=bool),
            "quality__valid": np.array([True] * quality_targets, dtype=bool),
        }
        return self.commit("feature_bundle", meta=meta, payload=payload)

    def relations(self, rows: list[tuple[str, str, str, bool, bool]]) -> str:
        ids: list[str] = []
        for a, b, _kind, _valid, _loss in rows:
            for fid in (a, b):
                if fid not in ids:
                    ids.append(fid)
        index = {fid: i for i, fid in enumerate(ids)}
        kind_code = {"R0": 0, "R1": 1, "R2": 2, "TINY_CONTACT": 3, "UNKNOWN": 4}
        return self.commit(
            "relation_pool",
            meta={"pool_id": "pool_fixture"},
            payload={
                "fragment_ids": np.array(ids, dtype="U64"),
                "rel_a": np.array([index[a] for a, _, _, _, _ in rows], dtype=np.int32),
                "rel_b": np.array([index[b] for _, b, _, _, _ in rows], dtype=np.int32),
                "rel_kind": np.array([kind_code[k] for _, _, k, _, _ in rows], dtype=np.int8),
                "rel_area_mm2": np.ones(len(rows), dtype=np.float32),
                "rel_interface": np.zeros(len(rows), dtype=np.int32),
                "rel_valid": np.array([v for _, _, _, v, _ in rows], dtype=bool),
                "rel_loss_mask": np.array([m for _, _, _, _, m in rows], dtype=bool),
            },
        )

    def freeze_release(self, release_id: str = "rel_fixture_1", *,
                       assets: list[str] | None = None) -> Path:
        """Write a release manifest and register it, in the layout the store really uses."""
        refs = list(assets if assets is not None else self.assets)
        manifest = {"release_id": release_id, "manifest_hash": "sha256:fixture",
                    "scope": "SYNTHETIC", "profile": "SANDBOX_CORE",
                    "assets": [{"asset_id": a} for a in refs]}
        path = self.root / "releases" / release_id / "manifest.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        relative = f"{self.repo.name}/{self.root.name}/releases/{release_id}/manifest.json"
        with self.store.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO releases(release_id, manifest_hash, scope, profile,"
                " frozen_at, manifest_path, meta_json) VALUES (?,?,?,?,?,?,?)",
                (release_id, "sha256:fixture", "SYNTHETIC", "SANDBOX_CORE", 1.0, relative, "{}"),
            )
        return path

    def context_pack(self, *, simulated: bool = True, context_id: str = "PIT-1|STR-02|BAG-FIX",
                     members: tuple[str, ...] = ("q1", "p1"), **overrides: object) -> str:
        """A complete simulated context pack (plan t088), with one knob to break per test."""
        meta: dict[str, object] = {
            "simulated": simulated,
            "pack_id": f"ctx_{context_id}",
            "context_id": context_id,
            "batch_id": "BAG-FIX",
            "batch_index": 0,
            "batch_size": len(members),
            "bag_id": "BAG-FIX",
            "pit_id": "PIT-1",
            "site_id": "SYN-SITE-01",
            "institution_id": "SYN",
            "excavation_area_id": "EXA-A",
            "grid_ref": "T0505",
            "unit_code": "U2",
            "stratum_id": "STR-02",
            "stratum_depth_mm": 180,
            "session_id": "SES-FIX",
            "operator_id": "OP-SIM-01",
            "captured_at": "2026-03-05T09:00:00+00:00",
            "site_notes": "SIMULATED context, not an archaeological record (fixture)",
            "scale_reference": {"scale_reference_kind": "steel_ruler", "size_mm": 150.0,
                                "appearance": "in_frame_left_edge_vertical", "simulated": True},
            "coexistents": [{"context_object_kind": "fragment", "id": fid,
                             "role": "event_endpoint", "count": 1, "has_observation": True}
                            for fid in members],
            "coexistent_counts": {"fragments": len(members), "with_observation": len(members),
                                  "vessels": 1, "others": 0},
        }
        meta.update(overrides)
        return self.commit("context_pack", meta=meta)

    def fragment(self, fragment_id: str, *, context_id: str | None = None) -> str:
        meta: dict[str, object] = {"fragment_id": fragment_id,
                                   "data_semantics": dict(CURRENT_DS)}
        if context_id is not None:
            meta["context_id"] = context_id
            meta["batch_id"] = "BAG-FIX"
            meta["context"] = {"schema": roles_module.SCHEMA_CONTEXT, "simulated": True,
                               "bag_id": "BAG-FIX", "pit_id": "PIT-1", "stratum_id": "STR-02",
                               "grid_ref": "T0505", "excavation_area_id": "EXA-A"}
        return self.commit("fragment_mesh", meta=meta)

    def build_green(self) -> "Fixture":
        """Everything the gate requires, present and in the current generation."""
        self.commit("mother_mesh", meta={
            "vessel_id": "V01", "mother_id": "LIN0000_V01_M01_PAT01",
            "registry_version": "1.1",
            "profile_metrics": {"z_rim_target_mm": 100.0, "z_rim": 99.5,
                                "z_rim_shortfall_mm": 0.5},
            "data_semantics": dict(CURRENT_DS),
        }, qa={"ok": True, "geometry_hash": "sha256:fixture-mother"})
        self.fragment("q1", context_id="PIT-1|STR-02|BAG-FIX")
        self.fragment("p1", context_id="PIT-1|STR-02|BAG-FIX")
        self.commit("obs_result", meta={
            "data_semantics": dict(CURRENT_DS), "obs_semantics": "physical_side_v2",
            "meta": {"data_semantics": dict(CURRENT_DS)}})
        self.feature("q1")
        self.feature("p1")
        self.feature("n1")
        self.commit("label_bundle", meta={
            "data_semantics": dict(CURRENT_DS),
            "relations_json": json.dumps([
                {"a": "q1", "b": "p1", "kind": "R2", "area_mm2": 1.0, "valid": True,
                 "loss_mask": True},
            ]),
            "r2_count": 1,
            "task_markers": {"correspondence": "no_correspondence_label",
                             "contradiction": "no_contradiction_label"},
        }, payload={"relations_json": "fixture"})
        self.commit("provenance", meta={"data_semantics": dict(CURRENT_DS)})
        self.commit("physical_result", meta={"damage_semantics": "subset_v2"})
        self.commit("physical_component", meta={"damage_semantics": "subset_v2"})
        self.relations([("q1", "p1", "R2", True, True), ("q1", "n1", "R1", True, True)])
        self.context_pack()
        self.freeze_release()
        return self


def green_store(tmp_path: Path) -> Fixture:
    return Fixture(tmp_path / "green_store", repo=tmp_path).build_green()


def tree_digest(root: Path) -> str:
    """Digest everything the gate must not touch: the payloads and the metadata database.

    The ``-wal``/``-shm`` sidecars are excluded because SQLite creates and removes them
    concurrently with any reader; they carry no committed data of their own.
    """
    digest = hashlib.sha256()
    targets = [p for p in root.rglob("*")
               if p.is_file() and not p.name.endswith(("-wal", "-shm"))]
    targets.append(root / "metadata.sqlite")
    for path in sorted(set(targets)):
        if not path.exists():
            continue
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        try:
            digest.update(hashlib.sha256(path.read_bytes()).digest())
        except FileNotFoundError:  # pragma: no cover - a concurrent sqlite sidecar
            continue
    return digest.hexdigest()


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True,
                          cwd=str(REPO_ROOT), timeout=300)


def check(target: Path, repo: Path, out_dir: Path | None = None, write: bool = False):
    from synlab.qc.data_quality import assess_target, write_report

    report = assess_target(target, repo=repo)
    if write:
        write_report(report, target, repo=repo, out_dir=out_dir)
    return report


def status_of(report: dict, check_id: str) -> str:
    for item in report["checks"]:
        if item["id"] == check_id:
            return item["status"]
    raise AssertionError(f"check {check_id} missing from {[c['id'] for c in report['checks']]}")


# ----------------------------------------------------------------------- 1. all green
def test_fully_marked_minimal_store_is_trainable(tmp_path: Path) -> None:
    fixture = green_store(tmp_path)
    report = check(fixture.root, fixture.repo)

    assert report["trainable"] is True, json.dumps(report["first_cause"], indent=2)
    assert report["verdict"] == "trainable"
    assert report["first_cause"] is None
    required = [c for c in report["checks"] if c["required"]]
    assert required, "the report must carry required checks"
    assert all(c["status"] in {"PASS", "NOT_APPLICABLE"} for c in required), [
        (c["id"], c["status"], c["detail"]) for c in required if c["status"] not in
        {"PASS", "NOT_APPLICABLE"}]
    # every check must carry a real denominator or state why it has none
    for item in required:
        if item["status"] == "PASS" and item["id"] not in {"semantics.generation_uniform"}:
            assert item["denominator"] is not None
    assert status_of(report, "training.legal_negatives") == "PASS"
    assert status_of(report, "qa.release_closure_pass") == "PASS"


# ------------------------------------------------------------- 2. mixed generations
def test_mixed_generations_are_not_trainable(tmp_path: Path) -> None:
    fixture = green_store(tmp_path)
    # an old-generation asset: no marker anywhere, exactly how the pre-fix batches look
    fixture.commit("provenance", meta={"note": "pre-fix asset, no data_semantics"})

    report = check(fixture.root, fixture.repo)
    assert report["trainable"] is False
    assert report["verdict"] == "not_trainable"
    assert status_of(report, "semantics.mask_semantics") == "FAIL"
    assert status_of(report, "semantics.damage_semantics") == "FAIL"
    mask = next(c for c in report["checks"] if c["id"] == "semantics.mask_semantics")
    assert mask["denominator"] > mask["hits"]
    assert mask["evidence"]["value_histogram"]["<missing>"] >= 1
    assert report["first_cause"]["check_id"] == "semantics.mask_semantics"


def test_a_legacy_only_store_is_uniform_but_still_not_trainable(tmp_path: Path) -> None:
    """Uniformly-old is self-consistent, but it is the *old* generation: still untrainable."""
    fixture = green_store(tmp_path)
    with fixture.store.connect() as conn:
        for role in ("provenance", "mother_mesh", "label_bundle", "obs_result",
                     "physical_result", "physical_component", "feature_bundle",
                     "fragment_mesh"):
            rows = conn.execute("SELECT asset_id, meta_json FROM assets WHERE role=?", (role,))
            for row in rows.fetchall():
                meta = json.loads(row["meta_json"])
                meta.pop("data_semantics", None)
                meta.pop("obs_semantics", None)
                meta.pop("damage_semantics", None)
                meta.pop("registry_version", None)
                meta.pop("profile_metrics", None)
                if isinstance(meta.get("meta"), dict):
                    meta["meta"].pop("data_semantics", None)
                conn.execute("UPDATE assets SET meta_json=? WHERE asset_id=?",
                             (json.dumps(meta), row["asset_id"]))

    report = check(fixture.root, fixture.repo)
    assert report["trainable"] is False
    # nothing is *mixed* -- the failure is "this is not the current generation", reported per marker
    assert status_of(report, "semantics.generation_uniform") == "PASS"
    assert status_of(report, "semantics.mask_semantics") == "FAIL"
    assert status_of(report, "geometry.registry_version") == "MISSING"
    assert status_of(report, "geometry.rim_consistency") == "MISSING"


# ---------------------------------------------------------------- 3. missing QA denominator
def test_store_without_assets_has_no_qa_denominator_and_is_not_trainable(tmp_path: Path) -> None:
    root = tmp_path / "empty_store"
    AssetStore(root)
    report = check(root, tmp_path)
    assert report["trainable"] is False
    assert status_of(report, "qa.census_conservation") == "MISSING"
    census = next(c for c in report["checks"] if c["id"] == "qa.census_conservation")
    assert census["denominator"] == 0
    assert report["first_cause"]["status"] == "MISSING"


def test_store_without_a_release_cannot_prove_closure(tmp_path: Path) -> None:
    fixture = Fixture(tmp_path / "no_release", repo=tmp_path).build_green()
    (fixture.root / "releases" / "rel_fixture_1" / "manifest.json").unlink()
    with fixture.store.connect() as conn:
        conn.execute("DELETE FROM releases")

    report = check(fixture.root, fixture.repo)
    assert report["trainable"] is False
    assert status_of(report, "qa.release_closure_pass") == "MISSING"
    closure = next(c for c in report["checks"] if c["id"] == "qa.release_closure_pass")
    assert closure["denominator"] is None
    assert "no frozen release" in closure["detail"]


def test_release_closure_referencing_a_non_pass_asset_fails(tmp_path: Path) -> None:
    fixture = green_store(tmp_path)
    fixture.commit("visible_labels", meta={"note": "pending"}, qa_status=QA_PENDING)
    fixture.freeze_release("rel_fixture_2")   # freeze again, now including the PENDING asset

    report = check(fixture.root, fixture.repo)
    assert status_of(report, "qa.release_closure_pass") == "FAIL"
    closure = next(c for c in report["checks"] if c["id"] == "qa.release_closure_pass")
    assert closure["evidence"]["problem_count"] >= 1
    assert any("QA_PENDING" in p for p in closure["evidence"]["problems"])
    assert report["trainable"] is False


# ------------------------------------------------------------------- 4. negatives == 0
def test_zero_negatives_with_encodable_positives_is_partial(tmp_path: Path) -> None:
    fixture = green_store(tmp_path)
    # replace the pool: a confirmed R2 pair, and nothing negative at all
    with fixture.store.connect() as conn:
        conn.execute("DELETE FROM assets WHERE role='relation_pool'")
    fixture.assets = [a for a in fixture.assets
                      if _role_of(fixture, a) != "relation_pool"]
    fixture.relations([("q1", "p1", "R2", True, True)])
    fixture.freeze_release()

    report = check(fixture.root, fixture.repo)

    negatives = next(c for c in report["checks"] if c["id"] == "training.legal_negatives")
    effective = next(c for c in report["checks"] if c["id"] == "training.effective_queries")
    assert negatives["status"] == "FAIL" and negatives["hits"] == 0
    assert negatives["denominator"] == 1, "the denominator must be the real relation-row count"
    assert effective["status"] == "FAIL" and effective["hits"] == 0
    assert effective["evidence"]["encodable_positive_pairs"] == 1
    # the intermediate verdict: the positive-only tasks still have supervision
    assert report["verdict"] == "partial", report["verdict"]
    assert report["trainable"] is False


def test_zero_negatives_and_no_positive_is_not_trainable(tmp_path: Path) -> None:
    fixture = green_store(tmp_path)
    with fixture.store.connect() as conn:
        conn.execute("DELETE FROM assets WHERE role='relation_pool'")
    fixture.relations([("q1", "n1", "UNKNOWN", False, False)])
    fixture.freeze_release()

    report = check(fixture.root, fixture.repo)
    assert report["verdict"] == "not_trainable"
    assert report["trainable"] is False


# ----------------------------------------------------- 5. the gate only reads
def test_gate_is_read_only(tmp_path: Path) -> None:
    fixture = green_store(tmp_path)
    before = tree_digest(fixture.root)
    report = check(fixture.root, fixture.repo, out_dir=tmp_path / "reports", write=True)
    after = tree_digest(fixture.root)

    assert before == after, "the gate modified the store it was asked to judge"
    assert report["read_only"] is True
    assert (tmp_path / "reports").exists()
    written = list((tmp_path / "reports").glob("data_quality_*.json"))
    assert len(written) == 1
    payload = json.loads(written[0].read_text(encoding="utf-8"))
    assert payload["schema"] == "synlab.data_quality.v1"


def test_report_name_follows_the_store(tmp_path: Path) -> None:
    fixture = green_store(tmp_path)
    report = check(fixture.root, fixture.repo, out_dir=tmp_path / "reports", write=True)
    from synlab.qc.data_quality import report_slug

    assert report_slug(fixture.root, repo=fixture.repo) == "green_store"
    assert (tmp_path / "reports" / "data_quality_green_store.json").exists()
    assert report["counts"]["QA_PASS"] > 0


# ------------------------------------------------------------------ 6. CLI + exit codes
@pytest.mark.parametrize("mode", ["green", "broken"])
def test_cli_exit_codes(tmp_path: Path, mode: str) -> None:
    fixture = green_store(tmp_path)
    if mode == "broken":
        fixture.commit("provenance", meta={"note": "old generation, no marker"})
        expected = 3
    else:
        expected = 0
    proc = run_cli("--store", str(fixture.root), "--repo", str(REPO_ROOT), "--no-report")
    assert proc.returncode == expected, proc.stdout + proc.stderr
    if mode == "green":
        assert "trainable" in proc.stdout
    else:
        assert "first" in proc.stdout


def test_cli_reports_usage_error_for_a_non_target(tmp_path: Path) -> None:
    proc = run_cli("--store", str(tmp_path), "--no-report")
    assert proc.returncode == 2
    combined = proc.stderr + proc.stdout
    assert "neither a store" in combined or "has no metadata.sqlite" in combined


# ------------------------------------------------------------------ 7. package behaviour
def _write_package(tmp_path: Path, *, negatives: int) -> Path:
    """A synthetic export package: manifest + deploy index + relations table."""
    package = tmp_path / "package"
    (package / "deploy").mkdir(parents=True)
    (package / "research").mkdir(parents=True)
    rows = [{"query": "q1", "candidate": "p1", "kind": "R2", "area_mm2": 1.0, "valid": True,
             "loss_mask": True, "eligible_as_negative": False, "has_observation": True}]
    for i in range(negatives):
        rows.append({"query": "q1", "candidate": f"n{i}", "kind": "R1", "area_mm2": 0.0,
                     "valid": True, "loss_mask": True, "eligible_as_negative": True,
                     "has_observation": True})
    import pyarrow as pa
    import pyarrow.parquet as pq

    pq.write_table(pa.Table.from_pylist(rows), package / "research" / "relations.parquet")
    index = {"schema": "synlab.deploy_index.v1", "note": "fixture",
             "rows": {"q1": {"obs_shard": "obs/shard_0000.tar", "geometry_shard": "geometry/shard_0000.npz",
                             "token_shard": "tokens/shard_0000.npz", "opaque": "a"},
                      "p1": {"obs_shard": "obs/shard_0000.tar", "geometry_shard": "geometry/shard_0000.npz",
                             "token_shard": "tokens/shard_0000.npz", "opaque": "b"}}}
    for i in range(negatives):
        index["rows"][f"n{i}"] = dict(index["rows"]["p1"], opaque=f"n{i}")
    (package / "deploy" / "deploy_index.json").write_text(json.dumps(index), encoding="utf-8")
    manifest = {
        "schema": "synlab.training_package_manifest.v1",
        "package_schema": "synlab.training_package.v1",
        "package_id": "pkg_fixture",
        "release_id": "rel_fixture",
        "assets": {"count": 3, "by_role": {"mother_mesh": 1, "feature_bundle": 3}},
        "counts": {"relations": len(rows), "r2_relations": 1, "obs_views": 4,
                   "relation_kinds": {"R2": 1, "R1": negatives}},
        "reference_closure": {"assets": 3, "files_checked": 3, "ok": True, "problems": []},
        "release_gates": {"note": "fixture"},
    }
    from synlab.canonical import hash_json

    manifest["manifest_hash"] = hash_json(manifest)
    (package / "export_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return package


def test_package_never_decides_its_own_generation(tmp_path: Path) -> None:
    """The package schema carries no semantic marker -- that gap is the finding, not a pass."""
    package = _write_package(tmp_path, negatives=1)
    report = check(package, REPO_ROOT)

    assert status_of(report, "semantics.mask_semantics") == "MISSING"
    assert status_of(report, "semantics.generation_uniform") == "MISSING"
    assert status_of(report, "geometry.registry_version") == "NOT_APPLICABLE"
    assert status_of(report, "provenance.export_manifest_hash") == "PASS"
    assert status_of(report, "training.legal_negatives") == "PASS"
    assert report["trainable"] is False
    assert report["verdict"] == "not_trainable"
    assert report["first_cause"]["status"] == "MISSING"


def test_package_with_zero_negatives_is_partial(tmp_path: Path) -> None:
    package = _write_package(tmp_path, negatives=0)
    report = check(package, REPO_ROOT)
    assert status_of(report, "training.legal_negatives") == "FAIL"
    assert report["verdict"] == "partial"
    assert report["trainable"] is False


def test_package_manifest_hash_mismatch_fails(tmp_path: Path) -> None:
    package = _write_package(tmp_path, negatives=1)
    path = package / "export_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["package_id"] = "pkg_tampered"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    report = check(package, REPO_ROOT)
    assert status_of(report, "provenance.export_manifest_hash") == "FAIL"


# ------------------------------------------------------------------ 8. threshold behaviour
@pytest.mark.parametrize("target,shortfall,ok", [
    (100.0, 0.0, True),          # exact agreement
    (100.0, -0.5, True),         # post-fix rim bulge overshoots: fine
    (100.0, 2.0, True),          # exactly at the absolute limit
    (100.0, 2.0001, False),      # truncated => pre-fix geometry
    (357.45244700428395, 3.0, True),   # large vessel: the 1 % band is wider than 2 mm
    (357.45244700428395, 3.6, False),
    (302.46423017156235, -3.487551118437068, True),   # measured good post-fix asset
    (float("nan"), 0.0, False),
    (100.0, float("nan"), False),
])
def test_rim_rule_is_signed_and_scale_aware(target: float, shortfall: float, ok: bool) -> None:
    good, reason = rim_verdict(target, shortfall)
    assert good is ok, reason
    if not ok:
        assert reason != "rim_reaches_declared_target"


def test_absolute_tolerance_constant_is_the_audit_value() -> None:
    assert RIM_ABSOLUTE_TOLERANCE_MM == 2.0


def test_truncated_mother_fails_the_rim_check(tmp_path: Path) -> None:
    fixture = green_store(tmp_path)
    with fixture.store.connect() as conn:
        row = conn.execute("SELECT asset_id, meta_json FROM assets WHERE role='mother_mesh'"
                           ).fetchone()
        meta = json.loads(row["meta_json"])
        meta["profile_metrics"]["z_rim_shortfall_mm"] = 140.851     # the A2 truncation signature
        conn.execute("UPDATE assets SET meta_json=? WHERE asset_id=?",
                     (json.dumps(meta), row["asset_id"]))

    report = check(fixture.root, fixture.repo)
    rim = next(c for c in report["checks"] if c["id"] == "geometry.rim_consistency")
    assert rim["status"] == "FAIL"
    assert rim["denominator"] == 1 and rim["hits"] == 0
    assert report["trainable"] is False


# ------------------------------------------------- 9. encoder-gate reconstruction
def test_encodable_reconstruction_follows_the_encoder_gates() -> None:
    assert encodable_from_arrays({})[0] is False
    assert encodable_from_arrays({"global_valid": np.zeros((1, 4), dtype=bool)})[0] is False
    assert encodable_from_arrays({"global_valid": np.array([[False, True]])})[0] is True
    assert encodable_from_arrays({"point_valid": np.array([[True]]),
                                  "scale_valid": np.array([True])})[0] is True
    assert encodable_from_arrays({"point_valid": np.array([[True]]),
                                  "scale_valid": np.array([False])})[0] is False
    assert encodable_from_arrays({"token_valid": np.array([[True]])})[0] is True
    gates = encodable_from_arrays({"global_valid": np.array([[True]]),
                                   "token_valid": np.array([[False]])})[1]
    assert gates["rgb_gate"] is True and gates["tok_gate"] is False


def test_view_count_uses_per_view_any() -> None:
    from synlab.qc.data_quality import view_counts_from_arrays

    assert view_counts_from_arrays({"global_valid": np.array([[True, False, True]])}) == 2
    assert view_counts_from_arrays({"global_valid": np.zeros((1, 3), dtype=bool)}) == 0
    assert view_counts_from_arrays({}) == 0


def test_task_without_labels_or_marker_fails(tmp_path: Path) -> None:
    """A task with no supervision must carry a persisted marker, or the gate says so."""
    fixture = green_store(tmp_path)
    with fixture.store.connect() as conn:
        row = conn.execute("SELECT asset_id, meta_json FROM assets WHERE role='label_bundle'"
                           ).fetchone()
        meta = json.loads(row["meta_json"])
        meta.pop("task_markers", None)
        conn.execute("UPDATE assets SET meta_json=? WHERE asset_id=?",
                     (json.dumps(meta), row["asset_id"]))

    report = check(fixture.root, fixture.repo)
    per_task = next(c for c in report["checks"] if c["id"] == "training.per_task_labels")
    assert per_task["status"] == "FAIL"
    assert set(per_task["evidence"]["tasks"]) == {"rank", "view", "correspondence", "quality",
                                                 "contradiction"}
    assert per_task["evidence"]["marker_keys_searched"]
    assert report["trainable"] is False


# ------------------------------------------------------------------ 10. honest bookkeeping
def test_summary_prints_first_cause_and_every_check(tmp_path: Path) -> None:
    from synlab.qc.data_quality import format_summary

    fixture = green_store(tmp_path)
    fixture.commit("provenance", meta={"note": "old"})
    report = check(fixture.root, fixture.repo)
    text = format_summary(report)
    assert "verdict" in text and "first" in text
    for item in report["checks"]:
        assert item["id"] in text


def test_report_records_unreadable_paths_never_silently(tmp_path: Path) -> None:
    import shutil

    fixture = green_store(tmp_path)
    # point a release at a manifest that does not exist anywhere, and remove the fallback copy
    with fixture.store.connect() as conn:
        conn.execute("UPDATE releases SET manifest_path=? WHERE release_id=?",
                     ("does/not/exist/manifest.json", "rel_fixture_1"))
    shutil.rmtree(fixture.root / "releases" / "rel_fixture_1")
    report = check(fixture.root, fixture.repo)
    assert report["unreadable"], "an unreadable manifest must be listed, not dropped"
    assert any("manifest not found" in item for item in report["unreadable"])
    assert status_of(report, "qa.release_closure_pass") == "MISSING"


def _role_of(fixture: Fixture, asset_id: str) -> str:
    with fixture.store.connect() as conn:
        row = conn.execute("SELECT role FROM assets WHERE asset_id=?", (asset_id,)).fetchone()
    return str(row["role"]) if row else ""


def test_qa_statuses_are_counted_conservatively(tmp_path: Path) -> None:
    fixture = green_store(tmp_path)
    # distinct payloads so the content-addressed store really commits two assets
    fixture.commit("visible_labels", meta={"tag": "pending"}, payload={"tag": "pending"},
                   qa_status=QA_PENDING)
    fixture.commit("visible_labels", meta={"tag": "fail"}, payload={"tag": "fail"},
                   qa_status=QA_FAIL)
    report = check(fixture.root, fixture.repo)
    census = report["counts"]
    assert census["QA_PASS"] + census["QA_PENDING"] + census["QA_FAIL"] == census["total"]
    assert census["QA_PENDING"] == 1 and census["QA_FAIL"] == 1
    assert status_of(report, "qa.census_conservation") == "PASS"
    # the failing asset is outside every release closure, so the closure rule still holds ...
    assert status_of(report, "qa.release_closure_pass") == "PASS"


def test_a_qa_failed_asset_inside_the_release_closure_blocks(tmp_path: Path) -> None:
    fixture = green_store(tmp_path)
    fixture.commit("visible_labels", meta={"tag": "fail"}, payload={"tag": "fail"},
                   qa_status=QA_FAIL)
    fixture.freeze_release("rel_fixture_2")   # now the QA_FAIL asset is a referenced asset

    report = check(fixture.root, fixture.repo)
    assert status_of(report, "qa.release_closure_pass") == "FAIL"
    assert report["trainable"] is False
    closure = next(c for c in report["checks"] if c["id"] == "qa.release_closure_pass")
    assert closure["denominator"] > closure["hits"]
    assert any("QA_FAIL" in p for p in closure["evidence"]["problems"])


def test_store_sqlite_is_opened_read_only(tmp_path: Path) -> None:
    """A WAL/sidecar write would be visible as a changed file set; assert none appears."""
    fixture = green_store(tmp_path)
    before = {p.name for p in fixture.root.iterdir()}
    check(fixture.root, fixture.repo)
    after = {p.name for p in fixture.root.iterdir()}
    assert before == after
    with pytest.raises(sqlite3.OperationalError):
        conn = sqlite3.connect(f"file:{(fixture.root / 'metadata.sqlite').as_posix()}?mode=ro",
                               uri=True)
        try:
            conn.execute("CREATE TABLE should_not_exist(x)")
        finally:
            conn.close()


# ------------------------------------------------- 11. context pack + channel policy gate
def test_the_context_pack_check_passes_on_a_complete_pack(tmp_path: Path) -> None:
    fixture = green_store(tmp_path)
    report = check(fixture.root, fixture.repo)
    item = next(c for c in report["checks"] if c["id"] == "context.pack_contract")
    assert item["status"] == "PASS", json.dumps(item, ensure_ascii=False, indent=2)[:1200]
    assert item["denominator"] == 1 and item["hits"] == 1
    assert item["evidence"]["batch_size_histogram"] == {2: 1}
    assert item["evidence"]["coexistents_per_pack"] == [2]
    assert item["evidence"]["scale_reference_kinds"] == {"steel_ruler": 1}
    assert item["evidence"]["context_carrying_fragments"] == 2
    assert report["trainable"] is True, json.dumps(report["first_cause"], indent=2)


def test_a_store_without_a_context_pack_is_not_trainable(tmp_path: Path) -> None:
    """The pack is required: without it a fragment's same-batch scope cannot be answered."""
    fixture = Fixture(tmp_path / "no_context", repo=tmp_path).build_green()
    with fixture.store.connect() as conn:
        conn.execute("DELETE FROM assets WHERE role='context_pack'")
    report = check(fixture.root, fixture.repo)
    item = next(c for c in report["checks"] if c["id"] == "context.pack_contract")
    assert item["status"] == "MISSING"
    assert report["trainable"] is False


def test_a_pack_without_simulated_true_fails_the_gate(tmp_path: Path) -> None:
    fixture = Fixture(tmp_path / "not_simulated", repo=tmp_path).build_green()
    with fixture.store.connect() as conn:
        row = conn.execute("SELECT asset_id, meta_json FROM assets WHERE role='context_pack'"
                           ).fetchone()
        meta = json.loads(row["meta_json"])
        meta["simulated"] = False
        conn.execute("UPDATE assets SET meta_json=? WHERE asset_id=?",
                     (json.dumps(meta), row["asset_id"]))
    report = check(fixture.root, fixture.repo)
    item = next(c for c in report["checks"] if c["id"] == "context.pack_contract")
    assert item["status"] == "FAIL"
    assert item["evidence"]["not_simulated"], item["evidence"]
    assert report["trainable"] is False


def test_an_incomplete_pack_fails_with_the_missing_field_names(tmp_path: Path) -> None:
    fixture = Fixture(tmp_path / "incomplete", repo=tmp_path).build_green()
    with fixture.store.connect() as conn:
        row = conn.execute("SELECT asset_id, meta_json FROM assets WHERE role='context_pack'"
                           ).fetchone()
        meta = json.loads(row["meta_json"])
        del meta["stratum_depth_mm"]
        del meta["scale_reference"]
        conn.execute("UPDATE assets SET meta_json=? WHERE asset_id=?",
                     (json.dumps(meta), row["asset_id"]))
    report = check(fixture.root, fixture.repo)
    item = next(c for c in report["checks"] if c["id"] == "context.pack_contract")
    assert item["status"] == "FAIL"
    joined = " ".join(item["evidence"]["incomplete"])
    assert "stratum_depth_mm" in joined and "scale_reference" in joined


def test_a_pack_carrying_an_answer_field_fails_the_gate(tmp_path: Path) -> None:
    fixture = Fixture(tmp_path / "answer_field", repo=tmp_path).build_green()
    with fixture.store.connect() as conn:
        row = conn.execute("SELECT asset_id, meta_json FROM assets WHERE role='context_pack'"
                           ).fetchone()
        meta = json.loads(row["meta_json"])
        meta["batch_provenance"] = {"lineage_id": "LIN0000"}     # nested on purpose
        conn.execute("UPDATE assets SET meta_json=? WHERE asset_id=?",
                     (json.dumps(meta), row["asset_id"]))
    report = check(fixture.root, fixture.repo)
    item = next(c for c in report["checks"] if c["id"] == "context.pack_contract")
    assert item["status"] == "FAIL"
    assert any("lineage_id" in entry for entry in item["evidence"]["answer_side_fields"])


def test_a_fragment_pointing_at_no_pack_fails_the_gate(tmp_path: Path) -> None:
    """A context_id that no pack owns is an addressability hole, not a cosmetic difference."""
    fixture = Fixture(tmp_path / "dangling", repo=tmp_path).build_green()
    with fixture.store.connect() as conn:
        row = conn.execute("SELECT asset_id, meta_json FROM assets WHERE role='fragment_mesh' "
                           "AND meta_json LIKE '%\"q1\"%'").fetchone()
        meta = json.loads(row["meta_json"])
        meta["context_id"] = "PIT-9|STR-99|BAG-GONE"
        conn.execute("UPDATE assets SET meta_json=? WHERE asset_id=?",
                     (json.dumps(meta), row["asset_id"]))
    report = check(fixture.root, fixture.repo)
    item = next(c for c in report["checks"] if c["id"] == "context.pack_contract")
    assert item["status"] == "FAIL"
    assert any("no pack" in entry for entry in item["evidence"]["unresolvable"])


def test_undeclared_schema_units_fail_the_contract_check(tmp_path: Path) -> None:
    fixture = green_store(tmp_path)
    fixture.commit("diagnostic_report", schema="synlab.invented.v9", unit="furlong",
                   frame="Q_mm", meta={"note": "drift"})
    report = check(fixture.root, fixture.repo)
    item = next(c for c in report["checks"] if c["id"] == "contract.declared_role_vocabulary")
    assert item["status"] == "FAIL"
    undeclared = " ".join(item["evidence"]["undeclared"])
    assert "synlab.invented.v9" in undeclared and "furlong" in undeclared and "Q_mm" in undeclared


def test_the_declared_vocabulary_covers_the_contract_debt_rows() -> None:
    """The three schema ids and three unit/frame values the census found are declared."""
    from synlab import roles as roles_module

    assert {"synlab.labels.v1", "synlab.provenance.v1",
            "synlab.display_glb.v1"} <= set(roles_module.DECLARED_SCHEMAS)
    assert {"m"} <= set(roles_module.DECLARED_UNITS)
    assert {"Y_up_m", "none"} <= set(roles_module.DECLARED_FRAMES)


def test_the_channel_check_reads_the_policy_and_the_package(tmp_path: Path) -> None:
    """A package whose deploy view carries a research-only channel must fail the gate."""
    from synlab.storage.export import (OPTIONAL_DEPLOY_CHANNELS, VIEW_CHANNEL_POLICY_ENV,
                                       load_channel_policy)

    package = _write_package(tmp_path, negatives=1)
    deploy = package / "deploy"
    (deploy / "obs").mkdir(parents=True, exist_ok=True)
    import numpy as np

    import tarfile

    with tarfile.open(deploy / "obs" / "shard_0000.tar", "w") as tar:
        for name, array in (("aaaa/tiles.npy", np.zeros((1, 2, 2, 3), dtype=np.uint8)),
                            ("aaaa/valid.npy", np.ones((1, 2, 2), dtype=bool)),
                            ("aaaa/view_pos.npy", np.zeros((1,), dtype=np.float32)),
                            ("aaaa/surface_tag.npy", np.zeros((1, 2, 2), dtype=np.int16))):
            import io

            buffer = io.BytesIO()
            np.save(buffer, array, allow_pickle=False)
            data = buffer.getvalue()
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    policy = load_channel_policy()
    manifest_path = package / "export_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["counts"]["deploy_channels_per_fragment"] = {
        entry[0]: 1 for entry in OPTIONAL_DEPLOY_CHANNELS}
    from synlab.canonical import hash_json

    manifest["manifest_hash"] = hash_json({k: v for k, v in manifest.items()
                                          if k != "manifest_hash"})
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    report = check(package, REPO_ROOT)
    item = next(c for c in report["checks"] if c["id"] == "separation.deploy_channel_policy")
    assert item["status"] == "FAIL"
    assert "surface_tag" in item["evidence"]["leaked"], item["evidence"]
    assert item["evidence"]["policy"]["path"] == policy["path"]
    assert item["evidence"]["policy"]["hash"] == policy["hash"]


def test_the_channel_check_passes_when_only_permitted_channels_are_present(
        tmp_path: Path) -> None:
    import io
    import tarfile

    import numpy as np

    from synlab.storage.export import OPTIONAL_DEPLOY_CHANNELS

    package = _write_package(tmp_path, negatives=1)
    deploy = package / "deploy"
    (deploy / "obs").mkdir(parents=True, exist_ok=True)
    members = [("aaaa/tiles.npy", np.zeros((1, 2, 2, 3), dtype=np.uint8)),
               ("aaaa/valid.npy", np.ones((1, 2, 2), dtype=bool)),
               ("aaaa/view_pos.npy", np.zeros((1,), dtype=np.float32))]
    for key, _array, dtype in OPTIONAL_DEPLOY_CHANNELS:
        shape = (3, 3) if key == "K" else ((1, 2, 2) if key != "depth_z" else (1, 2, 2))
        members.append((f"aaaa/{key}.npy", np.zeros(shape, dtype=dtype)))
    with tarfile.open(deploy / "obs" / "shard_0000.tar", "w") as tar:
        for name, array in members:
            buffer = io.BytesIO()
            np.save(buffer, array, allow_pickle=False)
            data = buffer.getvalue()
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    (deploy / "obs" / "index.json").write_text(json.dumps(
        {"channel_names": ["tiles", "valid", "view_pos"]
         + [key for key, _a, _d in OPTIONAL_DEPLOY_CHANNELS]}), encoding="utf-8")
    manifest_path = package / "export_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["counts"]["deploy_channels_per_fragment"] = {
        entry[0]: 1 for entry in OPTIONAL_DEPLOY_CHANNELS}
    from synlab.canonical import hash_json

    manifest["manifest_hash"] = hash_json({k: v for k, v in manifest.items()
                                          if k != "manifest_hash"})
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    report = check(package, REPO_ROOT)
    item = next(c for c in report["checks"] if c["id"] == "separation.deploy_channel_policy")
    assert item["status"] == "PASS", json.dumps(item["evidence"], ensure_ascii=False)[:1500]
    assert item["evidence"]["leaked"] == []
    assert item["evidence"]["unexpected"] == []
    assert set(item["evidence"]["deploy_channels_present"]) >= {"depth_z", "deployment_mask",
                                                               "uncertain_mask", "roi", "K"}

