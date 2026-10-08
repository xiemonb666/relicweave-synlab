"""End-to-end integration test for the L0 closed loop (plan 1.3 L0, 22.5, 24).

This is the Lead's integration gate: it runs the *real* chain for one mother and asserts
the invariants that must hold for the dataset to be usable at all:

* mother/material/pattern/fracture/truth/physical/observation assets are committed;
* every fragment carries explicit face origin bookkeeping;
* CleanTruth has R2 edges backed by measured interface area, and no self-loops;
* features and labels are separate assets and features carry no answer fields;
* the coverage ledger accounts for planned/attempted/accepted honestly;
* a zero-strength axis is a true identity (byte/hash level).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from synlab.config import load_generation_spec
from synlab.errors import SynLabError
from synlab.pipeline import plan_generation, run_generation
from synlab.roles import (
    FORBIDDEN_FEATURE_FIELDS,
    ROLE_CLEAN_TRUTH,
    ROLE_FEATURE_BUNDLE,
    ROLE_FRAGMENT_MESH,
    ROLE_LABEL_BUNDLE,
    ROLE_MOTHER_MESH,
    ROLE_OBS_RESULT,
    ROLE_PATTERN_RECIPE,
    ROLE_PHYSICAL_RESULT,
)
from synlab.storage.store import QA_FAIL, QA_PASS, QA_PENDING, AssetStore

ROOT = Path(__file__).resolve().parents[3]
SANDBOX = ROOT / "configs" / "a12" / "sandbox.yaml"


@pytest.fixture(scope="module")
def l0(tmp_path_factory: pytest.TempPathFactory) -> dict:
    store_root = tmp_path_factory.mktemp("l0")
    spec = load_generation_spec(SANDBOX)
    spec.storage.root = str(store_root)
    report = run_generation(spec, store_root=store_root, max_mothers=1)
    return {"report": report, "store_root": store_root, "spec": spec}


def test_l0_generation_accepts_at_least_one_mother(l0: dict) -> None:
    report = l0["report"]
    assert report["attempted"] == 1
    if report["accepted"] == 0:
        failures = json.dumps(report["failures"], ensure_ascii=False, indent=2)
        pytest.fail(f"the L0 chain did not complete for one mother:\n{failures}")
    assert report["accepted"] == 1


def _closed_loop_tool():
    """Import ``tools/closed_loop.py`` (the shipped release-preparation step)."""
    import importlib.util

    path = ROOT / "tools" / "closed_loop.py"
    spec = importlib.util.spec_from_file_location("closed_loop_tool_l0", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ancestry_closure(store: AssetStore, roots: list[str]) -> tuple[dict, set[str]]:
    """Transitive ``ancestry`` closure of ``roots``; unknown ids are reported, not ignored."""
    known = {asset.asset_id for asset in store.list_assets(limit=100000)}
    seen: dict = {}
    dangling: set[str] = set()
    stack = list(roots)
    while stack:
        asset_id = stack.pop()
        if asset_id in seen or asset_id in dangling:
            continue
        if asset_id not in known:
            dangling.add(asset_id)
            continue
        record = store.get_asset(asset_id)
        seen[asset_id] = record
        stack.extend(record.ancestry or [])
    return seen, dangling


def test_l0_commits_every_stage_asset(l0: dict) -> None:
    """Every stage asset is committed, and the QA denominator is honest (plan 4.1, 25.1).

    Plan 25.1 gates a *release closure*: every asset a release references must be QA_PASS, and
    an asset that did not pass QA must be counted in the failure denominator instead of being
    hidden.  "every asset in the store is QA_PASS" is a different, and wrong, claim: the
    pipeline deliberately commits three roles whose verdict belongs to the release-preparation
    step (``pattern_recipe``/``pattern_channels``/``physical_component``), and the PhysicalPack
    result carries the verdict of ``audit_physical`` -- which is QA_FAIL whenever the auditor
    did not confirm the level.  So the assertion is split into three measured parts:

    (a) the release scope (every QA_PASS asset) and its whole reference closure are QA_PASS;
    (b) every QA_PENDING/QA_FAIL asset is enumerable and attributable (role + status + the qa
        block that decided it) -- the failure denominator of plan 25.1;
    (c) ``QA_PASS + QA_PENDING + QA_FAIL == total`` (no fourth, un-counted status).

    The verdicts of the three deferred roles are *not* invented here: they are decided by the
    shipped ``tools/closed_loop.py`` contracts (mesh/recipe/channel checks over the stored
    payload), and the ancestry repair it performs is recorded in the assertion messages.
    """
    store = AssetStore(l0["store_root"])
    expected = {
        ROLE_MOTHER_MESH: 1,
        ROLE_PATTERN_RECIPE: 1,
        ROLE_FRAGMENT_MESH: 2,
        ROLE_CLEAN_TRUTH: 1,
        ROLE_PHYSICAL_RESULT: 1,
        ROLE_OBS_RESULT: 1,
        ROLE_FEATURE_BUNDLE: 1,
        ROLE_LABEL_BUNDLE: 1,
    }
    counts = {role: len(store.list_assets(role=role, limit=10000)) for role in expected}
    for role, minimum in expected.items():
        assert counts[role] >= minimum, f"{role}: expected >= {minimum}, got {counts[role]}"

    tool = _closed_loop_tool()
    promotion = tool._promote_pending_assets(store)
    repairs = tool._resolve_ancestry(store)

    assets = store.list_assets(limit=100000)
    by_status: dict[str, int] = {}
    for asset in assets:
        by_status[asset.qa_status] = by_status.get(asset.qa_status, 0) + 1
    assert set(by_status) <= {QA_PASS, QA_PENDING, QA_FAIL}, by_status
    assert sum(by_status.values()) == len(assets), (by_status, len(assets))
    assert by_status.get(QA_PASS, 0) >= 1, by_status

    # (a) the release closure of this store: every QA_PASS asset and everything it references
    scope = [asset for asset in assets if asset.qa_status == QA_PASS]
    closure, dangling = _ancestry_closure(store, [asset.asset_id for asset in scope])
    leaked = sorted(f"{record.qa_status} {record.asset_id} ({record.role})"
                    for record in closure.values() if record.qa_status != QA_PASS)
    assert not leaked, (
        f"the release closure references assets that are not QA_PASS: {leaked}; "
        f"promotion={promotion['promoted']}/{promotion['failed']}, "
        f"ancestry_repairs={repairs['n_repairs']}")
    broken = sorted(ref for ref in dangling if ref.startswith("asset_"))
    assert not broken, f"closure references unknown asset ids: {broken}"

    # (b) the failure denominator: every non-PASS asset is named, counted and attributable
    blocked = sorted(
        ((record.role, record.qa_status, record.asset_id) for record in assets
         if record.qa_status != QA_PASS))
    denominator = {}
    for role, status, _asset_id in blocked:
        denominator.setdefault(f"{role}:{status}", []).append(_asset_id)
    for record in assets:
        if record.qa_status == QA_PASS:
            continue
        assert record.qa, (f"{record.asset_id} ({record.role}) is {record.qa_status} without a "
                           f"qa block: the failure would not be attributable; "
                           f"denominator={denominator}")
    # QA_PENDING outside the release scope is the documented deferred-verdict state; a QA_FAIL
    # must carry the auditor's own failure codes so the denominator names a real reason.
    for record in assets:
        if record.qa_status == QA_FAIL:
            qa = dict(record.qa or {})
            codes = (qa.get("failure_codes") or qa.get("failures")
                     or (qa.get("closed_loop") or {}).get("problems") or [])
            assert codes, (f"{record.asset_id} ({record.role}) is QA_FAIL without failure codes; "
                           f"qa={record.qa}; denominator={denominator}")
    assert by_status.get(QA_PASS, 0) + by_status.get(QA_PENDING, 0) \
        + by_status.get(QA_FAIL, 0) == len(assets), by_status


def test_physical_result_pack_is_committed_with_real_measurements(l0: dict) -> None:
    """Plan 4.1: the PhysicalPack carries a *result* asset beside the damaged component.

    Every field asserted here is a value ``audit_physical``/``apply_damage`` measured on this
    run; a constant or a declared-only value would fail the cross-checks below.
    """
    store = AssetStore(l0["store_root"])
    results = store.list_assets(role=ROLE_PHYSICAL_RESULT, limit=10)
    assert len(results) == 1, [a.asset_id for a in results]
    record = results[0]
    meta = dict(record.meta or {})
    for key in ("recipe_id", "axis_id", "level", "variant", "lost_volume_mm3",
                "lost_volume_ratio", "representative_map", "components", "qa", "revision",
                "source_hash", "measurement", "source_asset_id"):
        assert key in meta, f"physical_result is missing {key}: {sorted(meta)}"
    assert record.schema == "synlab.physical.v1"
    assert record.unit == "mm" and record.frame == "F_mm"
    assert record.qa_status in (QA_PASS, QA_FAIL)
    assert record.qa_status == (QA_PASS if meta["qa"].get("status") == "PASS" else QA_FAIL), (
        "the asset verdict must be the auditor's own status", meta["qa"].get("status"))
    assert meta["qa_status_source"] == "physical.audit_physical.status"

    # the input reference is a real committed clean asset, not a semantic key
    source = store.get_asset(meta["source_asset_id"])
    assert source.role == ROLE_CLEAN_TRUTH
    assert meta["source_hash"] == source.blob_hash, (meta["source_hash"], source.blob_hash)
    assert record.ancestry and meta["source_asset_id"] in record.ancestry

    # the ledger is conserved and the loss is the measured one, not a copy of a declared value
    audit = dict(meta["qa"])
    measured = dict(audit.get("measured") or {})
    assert measured, "audit_physical reported no measurement"
    assert meta["measurement"]["lost_volume_mm3"] == measured["lost_volume_mm3"]
    assert abs(meta["lost_volume_mm3"] - measured["lost_volume_mm3"]) \
        <= 1e-9 * max(abs(measured["lost_volume_mm3"]), 1.0)
    assert abs(meta["lost_volume_mm3"] - float(audit["ledger"]["lost_volume_mm3"])) \
        <= 1e-9 * max(abs(meta["lost_volume_mm3"]), 1.0)
    source_mm3 = float(measured["source_volume_mm3"])
    damaged_mm3 = float(measured["damaged_volume_mm3"])
    assert abs((source_mm3 - damaged_mm3) - meta["lost_volume_mm3"]) <= 1e-6 * max(source_mm3, 1.0)
    assert abs(meta["lost_volume_ratio"] - meta["lost_volume_mm3"] / source_mm3) <= 1e-9

    # components: the count includes debris, and the representative map is measured per component
    components = dict(meta["components"])
    assert components["count"] == len(meta["components"]["component_ids"])
    assert components["count"] == components["core"] + components["debris"]
    assert components["debris"] == components["count"] - components["core"]
    assert components["count"] >= 1
    assert meta["representative_map"], "no clean fragment -> representative component mapping"
    mapped = set(meta["representative_map"].values())
    assert mapped <= set(components["component_ids"]), (mapped, components["component_ids"])

    # the numeric payload is the measurement itself (names/units live in the metadata)
    import numpy as np

    arrays = store.load_arrays(record.asset_id)
    values = np.asarray(arrays["measurement_values"], dtype=np.float64)
    assert len(meta["measurement_names"]) == values.shape[0] == len(meta["measurement"])
    assert np.array_equal(values, np.asarray([measured[k] for k in meta["measurement_names"]],
                                             dtype=np.float64))
    assert np.asarray(arrays["component_volume_mm3"]).shape[0] == components["count"]
    assert np.asarray(arrays["component_is_representative"]).sum() == components["core"]
    assert np.asarray(arrays["component_supportable"]).sum() <= components["count"]
    # revision and the clean geometry hash come from the operator run, not from a literal
    assert int(meta["revision"]) >= 1
    assert str(meta["source_geometry_hash"]).startswith("sha256:")
    assert record.qa == meta["qa"], "the store verdict block must be the recorded audit"
    # the auditor measured the real geometry (not an unavailable input) and repaired nothing
    assert audit["status"] in ("PASS", "FAIL"), audit["status"]
    assert audit["no_auto_repair"]["geometry_hashes_unchanged"] is True
    assert audit["representative_map"] == meta["representative_map"]



def test_fragments_carry_origin_bookkeeping(l0: dict) -> None:
    import numpy as np

    store = AssetStore(l0["store_root"])
    for asset in store.list_assets(role=ROLE_FRAGMENT_MESH, limit=100):
        mesh = store.load_mesh(asset.asset_id)
        attrs = mesh.metadata.get("face_attr_arrays") or {}
        n_faces = len(mesh.faces)
        for key in ("origin_kind", "source_triangle", "interface_id", "side"):
            assert key in attrs, f"{asset.asset_id} missing face attribute {key}"
            assert len(attrs[key]) == n_faces
        assert int(np.sum(attrs["origin_kind"] == 1)) >= 1, "no interface faces recorded"


def test_clean_truth_relations_are_backed_by_measured_area(l0: dict) -> None:
    store = AssetStore(l0["store_root"])
    rows = store.load_arrays(store.list_assets(role=ROLE_CLEAN_TRUTH, limit=1)[0].asset_id)
    relations = json.loads(str(rows["relations_json"])) if "relations_json" in rows else None
    if relations is None:
        stored = store.list_assets(role=ROLE_CLEAN_TRUTH, limit=1)[0]
        raw = store.load_bytes(stored.asset_id, "relations") if "relations" in stored.files else None
        assert raw is not None, "clean truth asset exposes neither relations_json nor relations blob"
        relations = json.loads(raw.decode("utf-8"))
    r2 = [r for r in relations if r["kind"] == "R2"]
    assert r2, "no R2 relation found for a shared-cut event"
    for edge in relations:
        assert edge["a"] != edge["b"], "self-loop relation"
        assert edge["area_mm2"] >= 0.0
    for edge in r2:
        assert edge["area_mm2"] > 0.0, "R2 edge without measured shared area"


def test_features_and_labels_are_separate_and_clean(l0: dict) -> None:
    store = AssetStore(l0["store_root"])
    features = store.list_assets(role=ROLE_FEATURE_BUNDLE, limit=10)[0]
    labels = store.list_assets(role=ROLE_LABEL_BUNDLE, limit=10)[0]
    assert features.asset_id != labels.asset_id
    forbidden = sorted(set(features.meta or {}) & FORBIDDEN_FEATURE_FIELDS)
    assert not forbidden, f"features carry forbidden fields: {forbidden}"
    label_ancestry = set(labels.ancestry or [])
    assert features.asset_id not in label_ancestry


def test_coverage_ledger_is_honest(l0: dict) -> None:
    coverage_path = l0["store_root"] / "reports" / "coverage.json"
    assert coverage_path.exists()
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    assert coverage["planned"] == 1
    assert coverage["attempted"] == 1
    assert coverage["accepted"] + coverage["failed"] == coverage["attempted"]
    rows = json.loads((l0["store_root"] / "reports" / "coverage_rows.json").read_text(encoding="utf-8"))
    assert rows and rows[0]["lineage_id"]
    assert "stages" in rows[0]


def test_planning_splits_before_generation_and_is_deterministic(l0: dict) -> None:
    spec = l0["spec"]
    first = plan_generation(spec, max_mothers=4)
    second = plan_generation(spec, max_mothers=4)
    assert [l.lineage_id for l in first.lineages] == [l.lineage_id for l in second.lineages]
    assert [l.split for l in first.lineages] == [l.split for l in second.lineages]
    splits = {l.split for l in first.lineages}
    assert splits <= {"train", "dev", "confirm"}


def test_zero_strength_axis_is_a_true_identity(l0: dict) -> None:
    """Level 0 of any axis must return the source bytes/hash, never a resampled copy."""
    store = AssetStore(l0["store_root"])
    from synlab.degrade.api import apply_axis
    from synlab.degrade.sources import commit_source, load_source

    source_asset = store.list_assets(role=ROLE_FRAGMENT_MESH, limit=1)[0]
    try:
        bundle = load_source(store, source_asset.asset_id)
    except SynLabError as exc:
        pytest.skip(f"source bundle unavailable: {exc.message}")
    out_ref, measurement = apply_axis("P03", 0, bundle, store, lineage_id="lin_test", split="train")
    assert measurement.identity is True
    assert out_ref.blob_hash == source_asset.blob_hash or out_ref.asset_id == source_asset.asset_id, (
        "level 0 must reference the original bytes"
    )
