"""Relation-negative library: labelling rules, batch legality and the negative recheck.

The fixtures here are small **hand-built** libraries -- they carry whichever measured facts the
rule under test needs, so a failure points at the rule and not at a fracture run.  The real,
measured library lives in ``data/a12_exports/relation_negatives`` and is exercised by the
acceptance scripts referenced in ``docs/a12/relation_negatives.md``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab.errors import SynLabError  # noqa: E402
from synlab.relations.multi_event import (  # noqa: E402
    ROLE_UNRESOLVED, classify_library, library_fragments, plan_event_library,
    relation_histogram, verify_event_exclusion,
)
from synlab.relations.negatives import (  # noqa: E402
    audit_negative_sample, batch_rows_from_relations,
)


# --------------------------------------------------------------------------------------
# hand-built measured library
# --------------------------------------------------------------------------------------
def _event(event_id: str, mother: str, fragments, relations, *, plane_normal,
           truth_status: str = "COMPUTED", patches=None) -> dict:
    return {
        "event_id": event_id, "ok": True, "truth_status": truth_status,
        "plan": {"event_id": event_id, "mother_index": 0, "lineage_id": mother,
                 "role": ROLE_UNRESOLVED if truth_status != "COMPUTED" else "primary",
                 "seed_ref": f'[7,"{mother}","cut","{event_id}"]', "plane_point": [0.0, 0.0, 0.0],
                 "plane_normal": list(plane_normal), "note": ""},
        "fragment_ids": [f for f, _ in fragments],
        "fragments": [{"fragment_id": f, "volume_mm3": v, "area_mm2": 10.0, "is_tiny": False,
                       "vertices": 8, "faces": 12, "mesh_hash": f"hash::{f}",
                       "interface_face_count": 2, "interface_face_area_mm2": 4.0,
                       "interface_plane": {"plane_normal": list(plane_normal),
                                           "offset_mm": 0.0, "normal_spread_max_deg": 0.0,
                                           "source": "measured_from_fragment_interface_faces"}}
                      for f, v in fragments],
        "interfaces": patches if patches is not None else [],
        "relations": relations, "relation_histogram": {},
        "plane": {"plane_normal": list(plane_normal), "plane_point": [0.0, 0.0, 0.0],
                  "offset_mm": 0.0, "source": "measured_from_interface_patches"},
    }


def _small_library() -> dict:
    """Two mothers x three events (one of them unresolved) x two fragments."""
    mothers = []
    for index, (lineage, normal, split) in enumerate((("MTH_A", (1.0, 0.0, 0.0), "train"),
                                                      ("MTH_B", (0.0, 1.0, 0.0), "dev"))):
        events = []
        for order, event_normal in enumerate((normal, (0.0, 0.0, 1.0), (0.5, 0.5, 0.7))):
            event_id = f"{lineage}_E{order + 1:02d}"
            left, right = f"{event_id}-m", f"{event_id}-p"
            unresolved = (order == 2)
            relations = [] if unresolved else [
                {"a": left, "b": right, "kind": "R2", "area_mm2": 40.0, "valid": True,
                 "loss_mask": True, "interface_id": 0, "reason": "shared_new_fracture_surface"}]
            patches = [] if unresolved else [
                {"interface_id": 0, "fragment_a": left, "fragment_b": right, "area_mm2": 40.0,
                 "common_clip_area_mm2": 40.0, "pair_common_clip_area_mm2": 40.0,
                 "patch_kind": "R2", "patch_reason": "structurally_valid_cut_face"}]
            events.append(_event(event_id, lineage, [(left, 10.0), (right, 10.0)], relations,
                                 plane_normal=event_normal, patches=patches,
                                 truth_status=("NOT_COMPUTED" if unresolved else "COMPUTED")))
        mothers.append({"mother": {"lineage_id": lineage, "split": split, "vessel_id": "V01",
                                   "material_id": "M01", "pattern_id": "PAT01",
                                   "layer_combo_id": None, "params": {}, "mother_index": index,
                                   "distractor": False},
                        "events": events, "ok": True})
    library = {"schema": "synlab.relations.event_library.v1", "mothers": mothers,
               "master_seed": 7, "plan": {"mothers": [], "events": []}}
    library["exclusion"] = verify_event_exclusion(library)
    return library


# --------------------------------------------------------------------------------------
# planning
# --------------------------------------------------------------------------------------
def test_planning_needs_at_least_three_events_per_mother():
    with pytest.raises(SynLabError):
        plan_event_library([{"lineage_id": "L", "vessel_id": "V01", "material_id": "M01",
                             "params": {}, "mother_index": 0}], n_events=2)


def test_planning_gives_every_event_its_own_id_and_seed():
    plan = plan_event_library(
        [{"lineage_id": "L1", "vessel_id": "V01", "material_id": "M01", "params": {},
          "mother_index": 0},
         {"lineage_id": "L2", "vessel_id": "V02", "material_id": "M01", "params": {},
          "mother_index": 1}],
        n_events=3, master_seed=11, distractor_indices=[1], unresolved_mothers=[0])
    ids = [event.event_id for event in plan.events]
    assert len(ids) == len(set(ids)), "event ids must be unique"
    assert plan.events_per_mother == 3
    # 2 mothers x 3 independent events + 1 unresolved-source event = 7.  The earlier expectation
    # of 4 counted only L1 and contradicted the frozen rule this test itself relies on: a mother
    # needs >= 3 mutually exclusive events (plan 11.1; docs/a12/v144_data_requirements.md 2.4
    # line 239 "来自同母体不同替代碎裂事件的碎片..."), and the unresolved-source event is an
    # *additional* event on top of them.  The implementation is correct; the number was not.
    assert plan.events_total == 7, "2 mothers x 3 events + L1's unresolved-source event"
    refs = {event.event_id: event.seed_ref for event in plan.events}
    assert len(set(refs.values())) == len(refs), "every event draws its own seed sub-stream"
    # L1's fixture entry declares no ``split``, so the conservative default applies: a lineage
    # whose split is not stated must never be silently enrolled as training data (plan 1.3
    # train/val/confirm split ratios).  Only the *distractor* flag is an explicit override.
    assert [m.split for m in plan.mothers] == ["dev", "gallery_distractor"]
    assert plan.events_of(0)[0].seed_ref != plan.events_of(1)[0].seed_ref


# --------------------------------------------------------------------------------------
# exclusion verification
# --------------------------------------------------------------------------------------
def test_exclusion_rejects_a_shared_cut_plane():
    library = _small_library()
    assert library["exclusion"]["ok"] is True
    # make two events of the same mother cut along the very same plane
    shared = dict(library["mothers"][0]["events"][0]["plane"])
    library["mothers"][0]["events"][1]["plane"] = dict(shared)
    for fragment in library["mothers"][0]["events"][1]["fragments"]:
        fragment["interface_plane"] = {"plane_normal": list(shared["plane_normal"]),
                                       "offset_mm": shared["offset_mm"],
                                       "normal_spread_max_deg": 0.0, "source": "test"}
    exclusion = verify_event_exclusion(library)
    assert exclusion["ok"] is False
    assert any(problem["check"] == "distinct_plane" for problem in exclusion["problems"])


# --------------------------------------------------------------------------------------
# labelling
# --------------------------------------------------------------------------------------
def test_labels_follow_mother_event_and_surface_evidence():
    rows = classify_library(_small_library())
    by_kind = relation_histogram(rows)
    assert by_kind["R2"] == 4          # 2 events x 2 mothers
    assert by_kind["R0"] > 0           # cross-mother pairs
    assert by_kind["UNKNOWN"] > 0      # pairs that mention an unresolved-source fragment
    cross_event = [row for row in rows
                   if row["mother_a"] == row["mother_b"] and row["event_a"] != row["event_b"]
                   and "UNKNOWN" != row["kind"]]
    assert cross_event and all(row["kind"] == "R1" for row in cross_event)
    assert all(row["decidability"] == "mutually_exclusive_event" for row in cross_event)
    cross_mother = [row for row in rows if row["mother_a"] != row["mother_b"]
                    and row["decidability"] != "insufficient_evidence"]
    assert cross_mother and all(row["kind"] == "R0" for row in cross_mother)
    unresolved_cross = [row for row in rows if row["mother_a"] != row["mother_b"]
                        and row["decidability"] == "insufficient_evidence"]
    assert unresolved_cross, "an unresolved-source fragment keeps its pairs at UNKNOWN"
    assert all(row["kind"] == "UNKNOWN" for row in unresolved_cross)
    r2 = [row for row in rows if row["kind"] == "R2"]
    assert all(row["decidability"] == "surface" and row["area_mm2"] == 40.0 for row in r2)


def test_unknown_is_never_a_negative_and_carries_no_loss_mask():
    rows = classify_library(_small_library())
    unknown = [row for row in rows if row["kind"] == "UNKNOWN"]
    assert unknown
    assert all(row["loss_mask"] is False and row["valid"] is False for row in unknown)
    assert all(row["decidability"] == "insufficient_evidence" for row in unknown)


def test_pairs_are_symmetric_unique_and_have_no_self_loops():
    rows = classify_library(_small_library())
    keys = [(row["a"], row["b"]) for row in rows]
    assert all(a != b for a, b in keys)
    assert len(keys) == len(set(keys))
    assert len(keys) == len({frozenset(key) for key in keys})


def test_cross_event_r1_is_withdrawn_when_the_exclusion_check_fails():
    library = _small_library()
    library["exclusion"] = {"ok": False, "problems": [{"check": "distinct_plane",
                                                       "events": ["MTH_A_E01", "MTH_A_E02"]}]}
    rows = classify_library(library)
    withdrawn = [row for row in rows if row["decidability"] == "unverified"]
    assert withdrawn
    assert all(row["kind"] == "UNKNOWN" and row["loss_mask"] is False for row in withdrawn)


def test_library_fragments_records_the_source_event_of_every_fragment():
    fragments = library_fragments(_small_library())
    assert fragments["MTH_A_E02-m"]["event_id"] == "MTH_A_E02"
    assert fragments["MTH_A_E02-m"]["mother_id"] == "MTH_A"
    assert fragments["MTH_A_E03-m"]["truth_status"] == "NOT_COMPUTED"


# --------------------------------------------------------------------------------------
# batch rows
# --------------------------------------------------------------------------------------
def _export_rows() -> list[dict]:
    return [
        {"query": "q", "candidate": "p", "kind": "R2", "valid": True, "loss_mask": True},
        {"query": "q", "candidate": "r1", "kind": "R1", "valid": True, "loss_mask": True},
        {"query": "q", "candidate": "r0", "kind": "R0", "valid": True, "loss_mask": True},
        {"query": "q", "candidate": "tiny", "kind": "TINY_CONTACT", "valid": True,
         "loss_mask": False},
        {"query": "q", "candidate": "unk", "kind": "UNKNOWN", "valid": False,
         "loss_mask": False},
        {"query": "q", "candidate": "bad_r1", "kind": "R1", "valid": False, "loss_mask": True},
    ]


def test_batch_rows_exclude_unknown_tiny_and_invalid_rows():
    ids = ["q", "p", "r1", "r0", "tiny", "unk", "bad_r1"]
    rows = batch_rows_from_relations(_export_rows(), ids)
    assert len(rows) == 1
    row = rows[0]
    assert row["positives"] == ["p"]
    assert row["negatives"] == ["r0", "r1"]
    assert "unk" in row["excluded"] and "tiny" in row["excluded"]
    assert "bad_r1" in row["excluded"]
    assert row["r1_fallback"] is False


def test_batch_rows_record_the_r1_fallback_when_only_r0_remains():
    rows = batch_rows_from_relations(
        [{"query": "q", "candidate": "r0", "kind": "R0", "valid": True, "loss_mask": True}],
        ["q", "r0"])
    assert rows[0]["r1_fallback"] is True
    assert rows[0]["negatives"] == ["r0"]


def test_batch_rows_ignore_pairs_whose_fragment_is_outside_the_package():
    rows = batch_rows_from_relations(_export_rows(), ["q", "p", "r1", "r0"])
    assert rows[0]["negatives"] == ["r0", "r1"]
    assert "tiny" not in rows[0]["excluded"]


# --------------------------------------------------------------------------------------
# the independent recheck
# --------------------------------------------------------------------------------------
def test_recheck_accepts_the_hand_built_labels():
    library = _small_library()
    rows = classify_library(library)
    audit = audit_negative_sample(library, rows, sample_size=50, seed=3)
    assert audit["sampled"] > 0
    assert audit["ok"] is True, audit["mismatches"][:3]
    assert audit["method"] == "raw_event_ledger"


def test_recheck_catches_a_mislabelled_negative():
    library = _small_library()
    rows = classify_library(library)
    # claim a cross-mother pair (a true R0) is R2 -- the recheck must refuse it
    target = next(row for row in rows if row["kind"] == "R0")
    target["kind"] = "R1"
    audit = audit_negative_sample(library, rows, sample_size=500, seed=3)
    assert audit["ok"] is False
    assert any(mismatch["a"] == target["a"] and mismatch["b"] == target["b"]
               for mismatch in audit["mismatches"])


def test_recheck_refuses_an_r2_pair_smuggled_in_as_a_negative():
    library = _small_library()
    rows = classify_library(library)
    r2 = next(row for row in rows if row["kind"] == "R2")
    r2["kind"] = "R1"
    r2["valid"] = True
    r2["loss_mask"] = True
    audit = audit_negative_sample(library, rows, sample_size=500, seed=5)
    assert audit["ok"] is False
    assert any(mismatch.get("is_measured_R2") for mismatch in audit["mismatches"])


# --------------------------------------------------------------------------------------
# discrimination experiment
# --------------------------------------------------------------------------------------
class _TinyPool:
    """Two lineages whose R2 mates really do share a feature centre (a separable toy)."""

    def __init__(self) -> None:
        rng = np.random.default_rng(0)
        self.features = {}
        self.mother_of = {}
        for cluster, prefix in enumerate(("a", "b")):
            centre = np.zeros(3, dtype=np.float64)
            centre[cluster] = 1.0
            for member in range(2):
                fid = f"{prefix}{member}"
                points = (centre[None, :] + rng.normal(0, 0.01, (6, 3))).astype(np.float64)
                self.features[fid] = {
                    "points": points,
                    "point_valid": np.ones(6, dtype=bool),
                    "normals": np.tile(np.array([0.0, 0.0, 1.0]), (6, 1)),
                    "normal_valid": np.ones(6, dtype=bool),
                    "view_tokens": (np.tile(centre, (3, 1))
                                    + rng.normal(0, 0.01, (3, 3))).astype(np.float64),
                }
                self.mother_of[fid] = f"lin{cluster}"
        self.pool_id = "tiny"


def test_discrimination_reports_a_real_auc_and_a_clustered_interval():
    from synlab.relations.negatives import discrimination_auc

    pool = _TinyPool()
    rows = [{"query": "a0", "candidate": "a1", "kind": "R2", "valid": True},
            {"query": "b0", "candidate": "b1", "kind": "R2", "valid": True},
            {"query": "a0", "candidate": "b0", "kind": "R0", "valid": True},
            {"query": "a1", "candidate": "b1", "kind": "R0", "valid": True}]
    report = discrimination_auc(pool, rows, bootstrap=200, seed=1)
    assert report["ok"] is True
    assert report["positives"] == 2 and report["negatives"] == 2
    assert report["auc"] is not None and 0.0 <= report["auc"] <= 1.0
    assert report["auc_interval"] is not None
    # one cluster per independent mother (the unit `discrimination_auc` documents and the frozen
    # convention of synlab.diagnostics.stats: `n_clusters = len(per_cluster)` over shape lineages)
    assert report["auc_interval"]["unit"] == "mother_cluster"
    assert report["clusters"] == 2


def test_discrimination_is_not_run_when_no_payload_can_be_encoded():
    from synlab.relations.negatives import discrimination_auc

    class _Empty:
        features = {}
        mother_of = {}

    report = discrimination_auc(_Empty(), [{"query": "a", "candidate": "b", "kind": "R0",
                                            "valid": True}])
    assert report["ok"] is False and report["status"] == "NOT_RUN"
