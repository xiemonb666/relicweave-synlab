"""Integration gate for the degradation-diversity step of the generation pipeline.

Two halves:

* **wiring** (always runs, cheap): the step is opt-in -- with no explicit request and no
  environment variable the pipeline reads no config at all, so every existing caller keeps its
  behaviour; asking for it resolves the shipped config.
* **real output** (runs when ``data/a12_degrade/store`` exists, like the exported-package smoke
  test): the assertions are made against the assets a real ``run_generation`` produced and the
  per-lineage report it flushed, not against a re-computation.

The graded facts are the ones the task names: level 0 is a true identity referencing the source
asset, all levels of an axis share one basis, every committed variant carries the dedicated
``degrade_variant`` role (never ``feature_bundle``), and the asset count agrees with the config
and with the report.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from _fixtures import REPO_ROOT
from synlab.degrade.diversity import (
    ROLE_DEGRADE_SOURCE,
    ROLE_DEGRADE_VARIANT,
    load_diversity_config,
)
from synlab.pipeline import _resolve_degrade_diversity
from synlab.roles import FORBIDDEN_FEATURE_FIELDS
from synlab.storage.store import AssetStore

STORE_ROOT = REPO_ROOT / "data" / "a12_degrade" / "store"
REPORT_DIR = STORE_ROOT / "reports" / "degrade_diversity"

CONFIG = load_diversity_config()


# ======================================================================================
# wiring (cheap, always runs)
# ======================================================================================
def test_step_is_off_unless_explicitly_requested(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SYNLAB_DEGRADE_DIVERSITY", raising=False)
    assert _resolve_degrade_diversity(None) is None
    assert _resolve_degrade_diversity(False) is None


def test_explicit_request_resolves_the_shipped_config() -> None:
    config = _resolve_degrade_diversity(True)
    assert config is not None and config.enabled
    assert [spec.axis_id for spec in config.axes] \
        == [spec.axis_id for spec in CONFIG.axes]
    assert _resolve_degrade_diversity(str(CONFIG.path)) is not None


def test_environment_switch_is_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYNLAB_DEGRADE_DIVERSITY", "0")
    assert _resolve_degrade_diversity(None) is None
    monkeypatch.setenv("SYNLAB_DEGRADE_DIVERSITY", "1")
    resolved = _resolve_degrade_diversity(None)
    assert resolved is not None and len(resolved.axes) == len(CONFIG.axes)
    monkeypatch.setenv("SYNLAB_DEGRADE_DIVERSITY", str(CONFIG.path))
    assert _resolve_degrade_diversity(None) is not None


# ======================================================================================
# real pipeline output
# ======================================================================================
pytestmark_store = pytest.mark.skipif(
    not (STORE_ROOT / "metadata.sqlite").exists(),
    reason="the degradation-diversity store data/a12_degrade/store is not present")


@pytest.fixture(scope="module")
def produced() -> dict:
    reports = [json.loads(path.read_text(encoding="utf-8"))
               for path in sorted(REPORT_DIR.glob("*.json"))]
    return {"store": AssetStore(STORE_ROOT), "reports": reports,
            "coverage": json.loads((STORE_ROOT / "reports" / "coverage.json")
                                   .read_text(encoding="utf-8"))}


@pytestmark_store
def test_pipeline_materialised_every_declared_axis_level(produced: dict) -> None:
    reports = produced["reports"]
    assert reports, "no per-lineage diversity report was written"
    for report in reports:
        assert report["schema"] == "synlab.degrade.diversity.report.v1"
        assert [axis["axis_id"] for axis in report["axes"]] \
            == [spec.axis_id for spec in CONFIG.axes_for_lineage(report["lineage_index"])]
        for axis in report["axes"]:
            spec = next(s for s in CONFIG.axes if s.axis_id == axis["axis_id"])
            assert [level["level"] for level in axis["levels"]] == list(spec.levels)
        summary = report["summary"]
        assert summary["axes_planned"] == len(report["axes"])
        assert summary["levels_planned"] == sum(len(axis["levels"]) for axis in report["axes"])
        assert summary["levels_ok"] + summary["levels_na"] + summary["levels_failed"] \
            == summary["levels_planned"]


@pytestmark_store
def test_level_zero_in_the_produced_data_is_the_source_asset(produced: dict) -> None:
    store = produced["store"]
    for report in produced["reports"]:
        for axis in report["axes"]:
            level0 = axis["levels"][0]
            if level0["status"] == "NA":
                continue
            assert level0["identity"] is True, (axis["axis_id"], level0)
            assert level0["asset_committed"] is False
            assert level0["identity_reference_ok"] is True
            assert level0["bytes_unchanged"] is True
            record = store.get_asset(level0["asset_id"])
            assert record.role != ROLE_DEGRADE_VARIANT, \
                "level 0 must reference the source asset, not a committed variant"
            assert record.lineage_id == report["lineage_id"]


@pytestmark_store
def test_produced_axes_share_one_basis_and_the_assets_carry_the_factor_fields(
        produced: dict) -> None:
    store = produced["store"]
    for report in produced["reports"]:
        for axis in report["axes"]:
            basis_ids = {level["basis_id"] for level in axis["levels"]}
            assert len(basis_ids) == 1, (axis["axis_id"], basis_ids)
    variants = store.list_assets(role=ROLE_DEGRADE_VARIANT, limit=10000)
    assert variants, "no degrade_variant asset was committed"
    for record in variants:
        meta = dict(record.meta or {})
        assert record.role == ROLE_DEGRADE_VARIANT
        for key in ("axis_id", "level", "variant", "basis_id", "source_hash", "result_hash",
                    "planned", "realized", "identity"):
            assert key in meta, (record.asset_id, key)
        assert int(meta["level"]) >= 1 and meta["identity"] is False
        assert meta.get("data_semantics"), record.asset_id
        assert set(meta) & FORBIDDEN_FEATURE_FIELDS, (record.asset_id, sorted(meta))
    assert not store.list_assets(role="feature_bundle", limit=10000) or all(
        record.role != ROLE_DEGRADE_VARIANT
        for record in store.list_assets(role="feature_bundle", limit=10000))


@pytestmark_store
def test_asset_counts_agree_with_the_config_and_the_report(produced: dict) -> None:
    store = produced["store"]
    variants = store.list_assets(role=ROLE_DEGRADE_VARIANT, limit=10000)
    sources = store.list_assets(role=ROLE_DEGRADE_SOURCE, limit=10000)
    reported = {level["asset_id"] for report in produced["reports"]
                for axis in report["axes"] for level in axis["levels"]
                if level.get("asset_committed")}
    assert reported == {record.asset_id for record in variants}, \
        "the store and the flushed report disagree about which variants exist"
    committed_levels = sum(1 for report in produced["reports"] for axis in report["axes"]
                           for level in axis["levels"] if level.get("asset_committed"))
    assert committed_levels == len(variants)
    # one level-0 identity per axis is *not* an asset: it is the source
    identity_levels = sum(1 for report in produced["reports"] for axis in report["axes"]
                          for level in axis["levels"] if level["status"] == "IDENTITY")
    assert identity_levels == sum(len(report["axes"]) for report in produced["reports"])
    assert len(sources) >= 3 * len(produced["reports"]), \
        "every lineage commits one degradation source per I/G/X family"
    for record in sources:
        assert (record.meta or {}).get("source_kind"), record.asset_id


@pytestmark_store
def test_coverage_ledger_carries_the_diversity_denominator(produced: dict) -> None:
    block = produced["coverage"].get("degrade_diversity")
    assert block, "the coverage ledger does not report the degradation-diversity step"
    assert block["lineages"] == len(produced["reports"])
    assert block["axes_planned"] == sum(len(r["axes"]) for r in produced["reports"])
    assert block["levels_planned"] == sum(len(axis["levels"]) for r in produced["reports"]
                                          for axis in r["axes"])
    assert block["variant_assets"] == sum(r["summary"]["variant_assets"]
                                          for r in produced["reports"])
    assert block["levels_ok"] + block["levels_na"] + block["levels_failed"] \
        == block["levels_planned"]
    assert block["basis_shared_per_axis"] is True


@pytestmark_store
def test_failed_levels_are_reported_with_their_own_reason_not_dropped(produced: dict) -> None:
    """A level the operator could not realise stays in the denominator with its own code."""
    failures = [(report["lineage_id"], axis["axis_id"], level)
                for report in produced["reports"] for axis in report["axes"]
                for level in axis["levels"] if level["status"] == "FAILED"]
    for lineage_id, axis_id, level in failures:
        assert level["failure_code"], (lineage_id, axis_id, level)
        assert level["asset_id"] is None and not level["asset_committed"]
    planned = {level["level"] for report in produced["reports"] for axis in report["axes"]
               for level in axis["levels"]}
    assert planned == set(CONFIG.levels), planned
    na = [(axis["axis_id"], level) for report in produced["reports"] for axis in report["axes"]
          for level in axis["levels"] if level["status"] == "NA"]
    for _axis_id, level in na:
        assert level["na_reason"], level


@pytestmark_store
def test_exported_package_indexes_the_variants(produced: dict) -> None:
    """When a training package was exported from this store, it must index the variants."""
    roots = sorted((REPO_ROOT / "data").glob("a12_degrade/exports/*/training_package"))
    if not roots:
        pytest.skip("no training package was exported from the degradation-diversity store")
    for root in roots:
        manifest = json.loads((root / "export_manifest.json").read_text(encoding="utf-8"))
        block = manifest.get("degrade_diversity")
        assert block, f"{root} does not report the degradation-diversity block"
        assert block["counts"]["degrade_variants"] == len(
            produced["store"].list_assets(role=ROLE_DEGRADE_VARIANT, limit=10000))
        index = json.loads((root / "degrade" / "index.json").read_text(encoding="utf-8"))
        assert index["rows"], "the exported variant index is empty"
        for row in index["rows"]:
            assert row["axis_id"] and int(row["level"]) >= 1 and row["basis_id"]
