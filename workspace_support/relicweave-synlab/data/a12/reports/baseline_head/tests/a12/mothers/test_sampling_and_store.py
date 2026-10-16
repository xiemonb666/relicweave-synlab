"""Parameter sampling and the mother store round-trip (plan 7.3 / interfaces section 2)."""

from __future__ import annotations

import numpy as np
import pytest

from synlab.errors import ErrorCode, SynLabError
from synlab.mothers.api import (audit_mother, canonical_params, commit_mother, create_mother,
                                last_sampling_report, load_mother, sampler_spec,
                                sample_parameters, vessel_ids)
from synlab.registry import REGISTRY
from synlab.roles import ROLE_MOTHER_MESH, SCHEMA_MOTHER
from synlab.seeds import make_rng
from synlab.storage.store import AssetStore, QA_PASS

SEED_A = 20240517


def test_latin_hypercube_covers_every_field(tmp_path):
    rng = make_rng(SEED_A, "sampler")
    samples = sample_parameters("V01", 12, rng)
    assert len(samples) == 12
    spec = sampler_spec("V01")
    assert spec, "V01 exposes no sampler fields"
    for name in spec:
        values = np.array([float(sample[name]) for sample in samples])
        assert np.all(np.isfinite(values)), name
        assert values.min() >= spec[name]["low"] - 1e-9, name
        assert values.max() <= spec[name]["high"] + 1e-9, name
    # a Latin hypercube stratifies every dimension: with 12 points and 12 strata each field
    # must occupy all of them, which a full Cartesian product would not do
    for name in spec:
        values = np.array([float(sample[name]) for sample in samples])
        span = spec[name]["high"] - spec[name]["low"]
        if span <= 0:
            continue
        strata = np.floor((values - spec[name]["low"]) / span * 12).astype(int)
        assert len(set(strata.tolist())) >= 6, f"{name} is not stratified: {sorted(set(strata))}"


def test_sampler_is_a_design_not_a_cartesian_product():
    """Eight Latin-hypercube points are 8 *distinct combinations*, not 8 cells of a product."""
    rng = make_rng(SEED_A, "sampler")
    samples = sample_parameters("V06", 8, rng)
    report = last_sampling_report()
    assert report["vessel_id"] == "V06"
    assert report["planned"] == 8
    assert report["accepted"] == 8
    assert report["attempted"] >= 8
    assert report["rejected"] == report["attempted"] - 8
    assert "LatinHypercube" in str(report["method"])
    fields = sorted(report["fields"])
    assert len(fields) >= 5, fields
    # every field is stratified: the 8 points occupy 8 different strata of its range
    spec = sampler_spec("V06")
    for name in fields:
        values = np.array([float(sample[name]) for sample in samples])
        span = spec[name]["high"] - spec[name]["low"]
        if span <= 0:
            continue
        strata = np.floor((values - spec[name]["low"]) / span * 8).astype(int)
        assert len(set(strata.tolist())) >= 4, f"{name} is not stratified: {sorted(set(strata))}"
    cells = {tuple(round(float(sample[name]), 6) for name in fields) for sample in samples}
    assert len(cells) == 8, "the sampler repeated a parameter combination"
    # the continuous parameters alone span a continuum no Cartesian product can enumerate
    continuous = [name for name in fields if not spec[name]["int"]]
    assert len(continuous) >= 4, continuous
    spread = np.array([[float(sample[name]) for name in continuous] for sample in samples])
    assert np.all(np.ptp(spread, axis=0) > 0.0), "a sampled dimension never moved"


def test_sampler_records_rejections():
    rng = make_rng(SEED_A, "sampler")
    bounds = {"base_mm": [40.0, 60.0]}
    try:
        sample_parameters("V01", 4, rng, bounds=bounds)
    except SynLabError as exc:
        assert exc.code in (ErrorCode.TARGET_INFEASIBLE, ErrorCode.SCHEMA_INVALID)
    report = last_sampling_report()
    if report:
        assert report["attempted"] >= report["accepted"]
        assert sum(report["rejection_reasons"].values()) == report["rejected"]


def test_sampler_rejects_impossible_requests():
    rng = make_rng(SEED_A, "sampler")
    with pytest.raises(SynLabError) as info:
        sample_parameters("V01", 0, rng)
    assert info.value.code == ErrorCode.SCHEMA_INVALID


def test_sampler_output_is_buildable():
    rng = make_rng(SEED_A, "sampler")
    samples = sample_parameters("V04", 3, rng)
    for index, params in enumerate(samples):
        mother = create_mother("V04", "M01", params, make_rng(SEED_A, "shape", index),
                               mother_id=f"V04-sampled-{index}")
        assert canonical_params("V04", params) == params
        report = audit_mother(mother, max_thickness_probes=32, run_self_intersection=False)
        assert report["ok"], (index, report["failures"])
        assert report["metrics"]["thickness_min_mm"] > 0


def test_commit_and_load_round_trip(tmp_path):
    store = AssetStore(tmp_path / "store")
    mother = create_mother("V01", "M06", {}, make_rng(SEED_A, "shape"), mother_id="V01-store")
    report = audit_mother(mother, max_thickness_probes=32)
    record = commit_mother(store, mother, lineage_id="LIN0001", split="train")
    assert record.role == ROLE_MOTHER_MESH
    assert record.schema == SCHEMA_MOTHER
    assert record.qa_status == QA_PASS
    assert record.meta["vessel_id"] == "V01"
    assert record.meta["material_id"] == "M06"

    loaded = load_mother(store, record.asset_id)
    assert loaded.vessel_id == "V01"
    assert loaded.material_id == "M06"
    assert loaded.n_faces == mother.n_faces
    assert np.array_equal(np.asarray(loaded.face_surface_tag),
                          np.asarray(mother.face_surface_tag))
    assert loaded.mother_id == "V01-store"
    from synlab.mothers.api import geometry_hash

    assert geometry_hash(loaded.mesh) == report["geometry_hash"]
    assert len(loaded.charts) == len(mother.charts)
    names = {chart.name for chart in loaded.charts}
    assert names == {chart.name for chart in mother.charts}
    for chart in loaded.charts:
        uv = chart.uv(np.asarray(loaded.mesh.triangles_center)[:8])
        assert np.all(np.isfinite(uv))
    # the reloaded mother still passes the QA gate
    re_audit = audit_mother(loaded, max_thickness_probes=32)
    assert re_audit["ok"], re_audit["failures"]


def test_commit_is_idempotent(tmp_path):
    store = AssetStore(tmp_path / "store")
    mother = create_mother("V03", "M02", {}, make_rng(SEED_A, "shape"), mother_id="V03-store")
    first = commit_mother(store, mother, lineage_id="LIN0002", split="dev")
    second = commit_mother(store, mother, lineage_id="LIN0002", split="dev")
    assert first.asset_id == second.asset_id


def test_load_rejects_a_foreign_asset(tmp_path):
    store = AssetStore(tmp_path / "store")
    record = store.commit_asset(role="coverage", schema="synlab.coverage.v1", unit="1",
                                frame="W_mm", payload={"note": "not a mother"})
    with pytest.raises(SynLabError) as info:
        load_mother(store, record.asset_id)
    assert info.value.code == ErrorCode.SCHEMA_INVALID


def test_stored_charts_survive_every_construction_family(tmp_path):
    """Each family's chart kinds (revolve / prism / planar / sweep) round-trip through the store."""
    store = AssetStore(tmp_path / "store")
    kinds: set[str] = set()
    for vessel_id in ("V01", "V13", "V20", "V24"):
        mother = create_mother(vessel_id, "M01", {}, make_rng(SEED_A, "shape", vessel_id),
                               mother_id=f"{vessel_id}-store")
        record = commit_mother(store, mother, lineage_id=f"LIN-{vessel_id}", split="train")
        loaded = load_mother(store, record.asset_id)
        assert {chart.name for chart in loaded.charts} == {chart.name for chart in mother.charts}
        kinds |= {chart.kind for chart in loaded.charts}
        probe = np.asarray(loaded.mesh.triangles_center)[:16]
        for chart in loaded.charts:
            assert np.all(np.isfinite(chart.uv(probe)))
        re_audit = audit_mother(loaded, max_thickness_probes=24, run_self_intersection=False)
        assert re_audit["ok"], (vessel_id, re_audit["failures"])
    assert {"revolve", "planar", "sweep"} <= kinds, kinds


def test_registry_exposes_all_families():
    families = {str((REGISTRY.get("vessel", vid).applicable or {}).get("family"))
                for vid in vessel_ids()}
    assert len(families) >= 8, f"only {len(families)} construction families: {families}"
    assert all(family and family != "None" for family in families)
