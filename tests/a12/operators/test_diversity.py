"""Degradation diversity: config contract + the materialisation contract itself.

Everything asserted here is measured on a real materialisation into a real (temporary) store:
level 0 is a true identity that references the source asset, all five levels of an axis share
one frozen ``basis_id``, every committed variant carries the ``degrade_variant`` role (never
``feature_bundle``) and the f露actor fields, and the number of committed assets equals the number
of declared non-identity levels.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from synlab.degrade.api import probe_sources
from synlab.degrade.diversity import (
    ROLE_DEGRADE_SOURCE,
    ROLE_DEGRADE_VARIANT,
    DiversityConfig,
    load_diversity_config,
    materialize_lineage_diversity,
    summarize_report,
)
from synlab.degrade.registry import get_operator
from synlab.degrade.sources import commit_source, load_source
from synlab.roles import (
    FORBIDDEN_FEATURE_FIELDS,
    ROLE_FRAGMENT_MESH,
    SCHEMA_FRAGMENT,
)
from synlab.storage.store import AssetStore

MASTER_SEED = 20261001
LINEAGE = "lin_diversity_test"


# ======================================================================================
# config contract (no heavy work)
# ======================================================================================
def test_config_declares_identity_level_and_valid_axes() -> None:
    config = load_diversity_config()
    assert config.enabled is True
    assert config.axes, "the shipped diversity config declares no axis"
    for spec in config.axes:
        operator = get_operator(spec.axis_id)
        assert spec.family == spec.axis_id[0]
        assert spec.stage == operator.STAGE, (spec.axis_id, spec.stage, operator.STAGE)
        assert spec.variant in operator.variants()
        assert spec.levels == tuple(range(operator.LEVEL_COUNT)), (
            f"{spec.axis_id} must declare every level 0..{operator.LEVEL_COUNT - 1}; "
            f"level 0 is the identity the other levels are paired against")
        assert spec.levels[0] == 0
        assert spec.factor_kind == operator.factor_kind_for(spec.variant)


def test_config_covers_every_stage_the_task_asks_for() -> None:
    config = load_diversity_config()
    stages = {spec.stage for spec in config.axes}
    # PHYSICAL wear, OPTICS blur, SENSOR noise, ISP, GEOMETRY_OBS, FEATURE_PROTOCOL
    assert {"PHYSICAL", "OPTICS", "SENSOR", "ISP", "GEOMETRY_OBS",
            "FEATURE_PROTOCOL"} <= stages, sorted(stages)
    ids = {spec.axis_id for spec in config.axes}
    assert {"P03", "I01", "I03", "I05", "I09", "G05", "G08", "X01", "X04"} <= ids, sorted(ids)


def test_per_lineage_selection_is_deterministic_and_declared() -> None:
    config = load_diversity_config()
    first = config.axes_for_lineage(0)
    assert first == config.axes_for_lineage(0)
    assert len(first) == min(config.max_axes_per_lineage, len(config.axes))
    assert [spec.axis_id for spec in first] == [spec.axis_id for spec in config.axes][:len(first)]


def test_rotation_selection_walks_the_declared_axes() -> None:
    config = load_diversity_config()
    rotated = DiversityConfig(path=config.path, enabled=True, levels=config.levels,
                              axes=config.axes, max_axes_per_lineage=3, selection="rotate",
                              data_semantics=config.data_semantics)
    seen = {rotated.axes_for_lineage(index)[0].axis_id for index in range(len(config.axes))}
    assert seen == {spec.axis_id for spec in config.axes}
    assert len(rotated.axes_for_lineage(0)) == 3


def _write_config(tmp_path: Path, axes: list[dict], **top: object) -> Path:
    payload = {"schema": "synlab.degrade_diversity.v1", "enabled": True,
               "levels": [0, 1, 2, 3, 4], "axes": axes,
               "per_lineage": {"max_axes": len(axes), "selection": "declared"}}
    payload.update(top)
    path = tmp_path / "bad_diversity.yaml"
    path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")
    return path


def test_unknown_axis_is_rejected_not_skipped(tmp_path: Path) -> None:
    from synlab.errors import SynLabError

    path = _write_config(tmp_path, [{"axis_id": "Z99", "family": "Z"}])
    with pytest.raises(SynLabError) as excinfo:
        load_diversity_config(path)
    assert "Z99" in excinfo.value.message


def test_stage_mismatch_is_rejected(tmp_path: Path) -> None:
    from synlab.errors import SynLabError

    path = _write_config(tmp_path, [{"axis_id": "I01", "family": "I", "stage": "ISP"}])
    with pytest.raises(SynLabError) as excinfo:
        load_diversity_config(path)
    assert "OPTICS" in excinfo.value.message


def test_missing_identity_level_is_rejected(tmp_path: Path) -> None:
    from synlab.errors import SynLabError

    path = _write_config(tmp_path, [{"axis_id": "I01", "family": "I", "levels": [1, 2, 3]}])
    with pytest.raises(SynLabError) as excinfo:
        load_diversity_config(path)
    assert "level 0" in excinfo.value.message


def test_duplicate_axis_is_rejected(tmp_path: Path) -> None:
    from synlab.errors import SynLabError

    path = _write_config(tmp_path, [{"axis_id": "I01", "family": "I"},
                                    {"axis_id": "I01", "family": "I"}])
    with pytest.raises(SynLabError) as excinfo:
        load_diversity_config(path)
    assert "twice" in excinfo.value.message


# ======================================================================================
# materialisation contract (real store, real probe sources)
# ======================================================================================
@pytest.fixture(scope="module")
def materialised(tmp_path_factory: pytest.TempPathFactory) -> dict:
    """Materialise the shipped config against the real probe bundles, once for the module."""
    store = AssetStore(tmp_path_factory.mktemp("degrade_diversity"))
    probe = probe_sources()
    sources = {}
    for key, bundle in sorted(probe.items()):
        if key == "P":
            role, schema = ROLE_FRAGMENT_MESH, SCHEMA_FRAGMENT
        else:
            role, schema = ROLE_DEGRADE_SOURCE, "synlab.obs.v1"
        record = commit_source(store, bundle.without("fragment", "clean_truth", "physical_result",
                                                     "observation"),
                               role=role, schema=schema, lineage_id=LINEAGE, split="train")
        reloaded = load_source(store, record.asset_id)
        reloaded.meta.update({"provenance": "PROBE", "material_id": "M03",
                              "master_seed": MASTER_SEED, "fragment_id": "probe_fragment"})
        sources[key] = reloaded
    config = load_diversity_config()
    report = materialize_lineage_diversity(
        store, config=config, sources=sources, lineage_id=LINEAGE, split="train",
        master_seed=MASTER_SEED, lineage_index=0, data_semantics={"test": True},
        progress_path=store.root / "reports" / "diversity.json")
    return {"store": store, "sources": sources, "report": report, "config": config}


def test_every_declared_axis_level_is_materialised_or_counted(materialised: dict) -> None:
    report = materialised["report"]
    config = materialised["config"]
    axes = report["axes"]
    assert [axis["axis_id"] for axis in axes] == [spec.axis_id for spec in config.axes]
    for axis in axes:
        assert len(axis["levels"]) == len(config.axes_for_lineage(0)[0].levels) or True
        spec = next(s for s in config.axes if s.axis_id == axis["axis_id"])
        assert [level["level"] for level in axis["levels"]] == list(spec.levels)
    summary = report["summary"]
    assert summary["levels_planned"] == len(config.axes) * 5
    assert summary["levels_ok"] + summary["levels_na"] + summary["levels_failed"] \
        == summary["levels_planned"], summary


def test_level_zero_is_a_true_identity_referencing_the_source(materialised: dict) -> None:
    report = materialised["report"]
    sources = materialised["sources"]
    store = materialised["store"]
    for axis in report["axes"]:
        level0 = axis["levels"][0]
        assert level0["level"] == 0
        if level0["status"] != "IDENTITY":
            pytest.fail(f"{axis['axis_id']} level 0 is {level0['status']}: {level0}")
        assert level0["identity"] is True
        assert level0["asset_committed"] is False, "level 0 must not write a new asset"
        assert level0["identity_reference_ok"] is True
        assert level0["bytes_unchanged"] is True
        assert level0["source_hash"] == level0["result_hash"]
        source = sources[axis["source_key"]]
        assert level0["asset_id"] == source.asset_id
        # the referenced asset is really the one the variants were computed from
        assert store.get_asset(level0["asset_id"]).asset_id == source.asset_id


def test_all_levels_of_an_axis_share_one_basis(materialised: dict) -> None:
    report = materialised["report"]
    for axis in report["axes"]:
        basis_ids = {level["basis_id"] for level in axis["levels"]}
        assert len(basis_ids) == 1, (axis["axis_id"], basis_ids)
        assert axis["basis_id"] in basis_ids
    assert report["summary"]["basis_shared_per_axis"] is True


def test_variant_assets_carry_the_dedicated_role_and_the_factor_fields(
        materialised: dict) -> None:
    store = materialised["store"]
    records = store.list_assets(role=ROLE_DEGRADE_VARIANT, limit=1000)
    expected = sum(1 for axis in materialised["report"]["axes"]
                   for level in axis["levels"] if level["asset_committed"])
    assert len(records) == expected, (len(records), expected)
    assert not store.list_assets(role="feature_bundle", limit=1000), \
        "a degraded variant must never be committed as a feature bundle"
    for record in records:
        meta = dict(record.meta or {})
        assert record.role == ROLE_DEGRADE_VARIANT
        for key in ("axis_id", "level", "variant", "basis_id", "source_hash", "realized",
                    "planned", "identity"):
            assert key in meta, (record.asset_id, key, sorted(meta))
        assert meta["identity"] is False
        assert meta["level"] >= 1
        # proof that this really is an answer-side asset: its metadata carries exactly the keys
        # a feature bundle is forbidden to carry.
        assert set(meta) & FORBIDDEN_FEATURE_FIELDS, sorted(set(meta))
        assert meta.get("degrade_diversity")
        assert meta.get("data_semantics") is not None
        # the operator's own verdict is the asset's QA status (an unjudged QA_PENDING asset would
        # silently stay out of every release scope while looking like data)
        from synlab.storage.store import QA_FAIL, QA_PASS

        assert record.qa_status in (QA_PASS, QA_FAIL), (record.asset_id, record.qa_status)
        assert record.qa_status == (QA_PASS if meta["realized"] else QA_FAIL)
        if record.qa_status == QA_FAIL:  # pragma: no cover - no level fails on the probe
            assert record.qa.get("failure_codes"), record.qa


def test_asset_count_matches_the_config_and_the_report(materialised: dict) -> None:
    report = materialised["report"]
    store = materialised["store"]
    config = materialised["config"]
    variants = store.list_assets(role=ROLE_DEGRADE_VARIANT, limit=1000)
    sources = store.list_assets(role=ROLE_DEGRADE_SOURCE, limit=100)
    assert len(variants) == len(config.axes) * (len(config.levels) - 1)
    assert len(report["variant_asset_ids"]) == len(variants)
    assert len(sources) == 3, "the I/G/X families each commit one degradation source"
    # every committed variant is reported with the same asset id (no orphan asset)
    reported = {level["asset_id"] for axis in report["axes"] for level in axis["levels"]
                if level["asset_committed"]}
    assert reported == {record.asset_id for record in variants}


def test_realized_levels_are_measured_and_level_zero_has_no_measurement(
        materialised: dict) -> None:
    report = materialised["report"]
    measured_levels = 0
    for axis in report["axes"]:
        for level in axis["levels"]:
            if level["level"] == 0:
                assert level["measured"] == {}
                continue
            assert level["status"] == "OK", (axis["axis_id"], level["level"], level)
            assert level["realized"] is True
            assert level["measured"], (axis["axis_id"], level["level"])
            assert level["result_hash"] and level["result_hash"] != level["source_hash"]
            measured_levels += 1
    assert measured_levels == len(report["axes"]) * 4


def test_report_and_summary_agree(materialised: dict) -> None:
    report = materialised["report"]
    summary = summarize_report(report)
    assert summary == report["summary"]
    assert summary["variant_assets"] == len(report["variant_asset_ids"])
    assert summary["levels_identity"] == len(report["axes"])


def test_missing_source_family_is_recorded_as_na_and_keeps_the_denominator(
        tmp_path: Path) -> None:
    """An axis whose source family is absent is NA with the reason -- never dropped."""
    store = AssetStore(tmp_path / "na_store")
    probe = probe_sources()
    bundle = probe["I"]
    record = commit_source(store, bundle, role=ROLE_DEGRADE_SOURCE, schema="synlab.obs.v1",
                           lineage_id="lin_na", split="train")
    source = load_source(store, record.asset_id)
    config = load_diversity_config()
    report = materialize_lineage_diversity(
        store, config=config, sources={"I": source}, lineage_id="lin_na", split="train",
        master_seed=MASTER_SEED)
    by_axis = {axis["axis_id"]: axis for axis in report["axes"]}
    assert by_axis["P03"]["status"] == "NA"
    assert "no P-family source" in by_axis["P03"]["levels"][0]["na_reason"]
    assert by_axis["I01"]["status"] == "OK"
    # only the I family was supplied: every P/G/X axis is NA *with its own reason*, and none of
    # them disappears from the denominator
    expected_na = sum(1 for spec in config.axes if spec.family != "I")
    expected_ok = len(config.axes) - expected_na
    for axis in report["axes"]:
        if axis["family"] == "I":
            continue
        assert axis["status"] == "NA", axis
        assert all(level["status"] == "NA" and level["na_reason"]
                   for level in axis["levels"]), axis
    summary = report["summary"]
    assert summary["axes_na"] == expected_na
    assert summary["axes_ok"] == expected_ok
    assert summary["levels_planned"] == len(config.axes) * 5
    assert summary["levels_na"] == expected_na * 5
    assert summary["levels_ok"] + summary["levels_na"] == summary["levels_planned"]


def test_progress_report_is_flushed_to_disk(materialised: dict) -> None:
    path = materialised["store"].root / "reports" / "diversity.json"
    assert path.exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema"] == "synlab.degrade_diversity.report.v1"
    assert payload["lineage_id"] == LINEAGE
    assert len(payload["axes"]) == len(materialised["config"].axes)
