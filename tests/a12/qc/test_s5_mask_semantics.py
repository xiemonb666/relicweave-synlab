"""S5 contract: the mask-semantics generation is recorded on the committed assets.

The visible layer (``role = visible_labels``) is computed **from** the delivered mask channels
(``uncertain_mask`` / ``deployment_mask`` / ``id_map``), so which ``coc_units`` generation produced
them decides what its counts mean.  It used to be committed with no marker at all -- measured on
``data/a12_trainable/store``: ``visible_labels`` n=9 with ``mask_semantics`` on **0** of them, while
the other five ``data_semantics`` roles carried it -- so a reader could not tell two generations
apart for exactly the layer whose meaning depends on them.

The two generations disagree by a measured factor of ``D * N`` (74.105 on the L0 views), so this is
a correctness marker, not bookkeeping.
"""

from __future__ import annotations

import types

import pytest

from synlab.pipeline import _stamp_data_semantics, data_semantics
from synlab.qc.data_quality import (
    CURRENT_GENERATION,
    DATA_SEMANTICS_ROLES,
    LEGACY_GENERATION,
    MARKER_FREE_ROLES,
    MARKER_ROLES,
)


def test_visible_labels_is_now_a_marked_role() -> None:
    """The role that carries the marker is the role the gate checks and the census reports."""
    assert "visible_labels" in DATA_SEMANTICS_ROLES
    assert "visible_labels" in MARKER_ROLES
    assert "visible_labels" not in MARKER_FREE_ROLES
    # the other roles keep their classification
    for role in ("mother_mesh", "fragment_mesh", "feature_bundle", "label_bundle", "provenance",
                 "obs_result"):
        assert role in DATA_SEMANTICS_ROLES
    for role in ("clean_truth", "physical_truth", "pattern_recipe", "query_roster"):
        assert role in MARKER_FREE_ROLES


def test_stamp_writes_the_declared_generation() -> None:
    """A freshly stamped object records the checkout's own generation."""
    obj = types.SimpleNamespace(meta={})
    returned = _stamp_data_semantics(obj)
    assert returned is obj
    declared = data_semantics()
    assert obj.meta["mask_semantics"] == declared["mask_semantics"]
    assert obj.meta["mask_semantics"] == CURRENT_GENERATION["mask_semantics"] == "coc_units_v2"
    assert obj.meta["damage_semantics"] == declared["damage_semantics"]
    assert obj.meta["subset_instrument"] == declared["subset_instrument"]
    assert obj.meta["defined_in"] == declared["defined_in"]


def test_stamp_never_overwrites_a_declared_version() -> None:
    """An object that already says which generation it is keeps its own statement."""
    obj = types.SimpleNamespace(meta={"mask_semantics": LEGACY_GENERATION["mask_semantics"]})
    _stamp_data_semantics(obj)
    assert obj.meta["mask_semantics"] == LEGACY_GENERATION["mask_semantics"]


def test_stamp_is_tolerant_of_a_non_mapping() -> None:
    """A wrong call shape must not corrupt a run (same contract as the obs stamp)."""
    assert _stamp_data_semantics(None) is None
    assert _stamp_data_semantics(object()) is not None  # passes through untouched


def test_the_two_generations_are_distinguishable() -> None:
    """``missing`` is the pre-marker discriminator and is never equal to the current value."""
    assert CURRENT_GENERATION["mask_semantics"] != LEGACY_GENERATION["mask_semantics"]
    assert CURRENT_GENERATION["mask_semantics"] == "coc_units_v2"
    assert LEGACY_GENERATION["mask_semantics"] == "coc_units_v1_pixel_units"


@pytest.mark.parametrize("store", ["data/a12_trainable/store", "data/a12_campaign/store"])
def test_census_reads_every_role_the_gate_checks(store: str) -> None:
    """The census driver and the gate must agree on which roles are marked."""
    from _fixtures import REPO_ROOT

    from tools.a12_mask_semantics_census import census

    root = REPO_ROOT / store
    if not (root / "metadata.sqlite").is_file():
        pytest.skip(f"store {store} not present")
    report = census(root)
    assert report["available"] is True
    # the roles the gate is defined over are exactly the ones the census labels as marked, and
    # the two sets are the module's own constants (never a literal in the driver)
    assert set(report["marked_roles"]) == set(DATA_SEMANTICS_ROLES)
    assert set(report["marker_free_roles"]) == set(MARKER_FREE_ROLES)
    # visible_labels is reported explicitly, marker or not
    assert "visible_labels" in report
    assert "visible_labels_carries_marker" in report
    # the value vocabulary is the frozen one, and '<missing>' is a separate bucket
    vocabulary = set(report["value_histogram"])
    assert vocabulary <= {report["current_value"], report["legacy_value"], "<missing>"}
