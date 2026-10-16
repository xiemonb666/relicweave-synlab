"""Level-0 identity, paired bases and reproducibility (plan 15.7 rows 1-2)."""

from __future__ import annotations

import pytest

from synlab.degrade.api import apply_axis
from synlab.degrade.registry import AXIS_REGISTRY, basis_rng
from synlab.errors import SynLabError

from conftest import ALL_AXES, FAMILY_OF


@pytest.mark.parametrize("axis_id", ALL_AXES)
def test_level0_is_a_true_identity(axis_id: str, stored_sources: dict, source_store) -> None:
    """Level 0 returns the original asset reference and bytes for every one of the 31 axes."""
    family = FAMILY_OF[axis_id]
    source = stored_sources[family]
    operator = AXIS_REGISTRY.get(axis_id)
    basis = operator.sample_basis(
        {"source": source, "lineage_id": "lin_identity", "fragment_id": "frag_identity",
         "master_seed": 20261001},
        basis_rng_placeholder := __import__("numpy").random.default_rng(0),
        operator.default_variant)
    result = operator.apply(source, 0, basis, None)
    assert result is source, "the operator itself must return the source object at level 0"

    record, measurement = apply_axis(axis_id, 0, source, source_store, basis=basis,
                                     lineage_id="lin_identity", split="train")
    assert measurement.identity is True
    assert measurement.level == 0
    assert measurement.result_hash == measurement.source_hash
    assert measurement.realized is True
    assert measurement.measured == {}
    assert measurement.planned, "the level-0 parameters are still declared"
    assert getattr(record, "asset_id", None) == source.asset_id, (
        f"{axis_id}: level 0 must reference the original asset, got "
        f"{getattr(record, 'asset_id', None)} vs {source.asset_id}")
    assert source.asset_id is not None and basis_rng_placeholder is not None


@pytest.mark.parametrize("family,axis_id", [("P", "P03"), ("I", "I01"), ("G", "G01"), ("X", "X01")])
def test_five_levels_share_one_basis(family: str, axis_id: str, probe: dict) -> None:
    operator = AXIS_REGISTRY.get(axis_id)
    source = probe[family]
    basis = operator.sample_basis(
        {"source": source, "lineage_id": "lin_basis", "fragment_id": "frag_basis",
         "master_seed": 20261001}, __import__("numpy").random.default_rng(3),
        operator.default_variant)
    seen = set()
    realized_levels = []
    for level in operator.levels():
        try:
            _, measurement = apply_axis(axis_id, level, source, None, basis=basis,
                                        lineage_id="lin_basis")
        except SynLabError as exc:
            # a level the frozen resolution cannot realise is a structured failure; it must not
            # change the basis of the levels that do run
            assert str(getattr(exc.code, "value", exc.code)) in (
                "PRECISION_NOT_REALIZED", "TARGET_INFEASIBLE", "OPERATOR_NOT_REALIZED"), exc
            continue
        seen.add(measurement.extra["basis_id"])
        assert measurement.extra["basis_id"] == basis.basis_id
        assert measurement.extra["basis_seed_ref"] == basis.seed_ref
        if level > 0 and measurement.realized:
            realized_levels.append(level)
    assert seen == {basis.basis_id}
    assert 0 in operator.levels() and basis.basis_id
    assert realized_levels, f"{axis_id}: no non-zero level realized with the shared basis"


def test_repeated_application_is_deterministic(probe: dict) -> None:
    """A fixed environment reproduces the same measurement and the same result hash."""
    for axis_id, level in (("P05", 2), ("I03", 2), ("G01", 2), ("X02", 2)):
        family = FAMILY_OF[axis_id]
        first_ref, first = apply_axis(axis_id, level, probe[family], None,
                                      lineage_id="lin_repeat")
        second_ref, second = apply_axis(axis_id, level, probe[family], None,
                                        lineage_id="lin_repeat")
        assert first.measured == second.measured, axis_id
        assert first.result_hash == second.result_hash, axis_id
        assert first_ref.content_hash == second_ref.content_hash, axis_id


def test_level0_does_not_commit_anything(probe: dict, tmp_path) -> None:
    from synlab.storage.store import AssetStore

    store = AssetStore(tmp_path / "identity_store")
    before = len(store.list_assets(limit=1000))
    apply_axis("P03", 0, probe["P"], store, lineage_id="lin_identity")
    assert len(store.list_assets(limit=1000)) == before, (
        "level 0 must not write a new asset (no resampling, no re-serialisation)")


def test_source_kind_declaration_is_checked(probe: dict) -> None:
    from synlab.errors import SynLabError

    with pytest.raises(SynLabError):
        apply_axis("I01", 1, probe["I"], None, source_kind="GEOMETRY")
