"""Fixtures for the relations tests: a real ``AssetStore`` with committed truth/label assets.

The store is *real* (SQLite + blobs + atomic commits); only the producers are local because
``synlab.truth`` / ``synlab.observe`` are still being written in parallel.  The committed
formats are exactly the ones the generation pipeline writes today:

* ``label_bundle`` (``synlab.labels.v1``): ``meta["relations_json"]`` carries the full
  per-event relation list ``[{a, b, kind, area_mm2, valid, loss_mask}, ...]`` (see
  ``synlab.pipeline._commit_labels``), plus ``fragment_id`` / ``mother_id`` / ``history``;
* ``feature_bundle`` (``a12.obs.v1``): the ``adapt_observed_features`` payload, arrays in
  ``arrays.npz`` and scalars in ``meta``;
* ``provenance``: ``ancestry = [feature_asset, label_asset]`` so the pool can rebuild the
  fragment -> feature mapping without reading any identifier from the feature object.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
TESTS_A12 = Path(__file__).resolve().parents[2]
for _path in (str(REPO_ROOT), str(TESTS_A12)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from _fixtures import make_feature_payload  # noqa: E402
from synlab.roles import (  # noqa: E402
    ROLE_CLEAN_TRUTH,
    ROLE_FEATURE_BUNDLE,
    ROLE_LABEL_BUNDLE,
    ROLE_PROVENANCE,
    SCHEMA_FEATURE,
    SCHEMA_TRUTH_CLEAN,
)
from synlab.storage.store import QA_PASS, AssetStore  # noqa: E402


@dataclass
class EventSpec:
    """One fracture event of one mother: mutually exclusive pieces + their relations."""

    lineage_id: str
    mother_id: str
    event_id: str
    split: str = "dev"
    fragments: list[str] = field(default_factory=list)
    r2: list[tuple[str, str]] = field(default_factory=list)
    r1: list[tuple[str, str]] = field(default_factory=list)
    tiny: list[tuple[str, str]] = field(default_factory=list)
    unknown: list[tuple[str, str]] = field(default_factory=list)
    quality_tier: dict[str, int] = field(default_factory=dict)
    tiny_fragments: list[str] = field(default_factory=list)
    with_features: bool = True
    feature_seed: int = 0


def relation_rows(spec: EventSpec) -> list[dict]:
    rows: list[dict] = []
    for pairs, kind in ((spec.r2, "R2"), (spec.r1, "R1"), (spec.tiny, "TINY_CONTACT"),
                        (spec.unknown, "UNKNOWN")):
        for index, (a, b) in enumerate(pairs):
            rows.append({"a": a, "b": b, "kind": kind, "area_mm2": 10.0 + index,
                         "valid": True, "loss_mask": kind in ("R2", "R1")})
    return rows


def commit_event(store: AssetStore, spec: EventSpec) -> dict[str, str]:
    """Commit one event as the pipeline does; returns ``{fragment_id: label_asset_id}``."""
    rows = relation_rows(spec)
    r2_count = sum(1 for row in rows if row["kind"] == "R2")
    out: dict[str, str] = {}
    rng = np.random.default_rng(spec.feature_seed or 3)
    for fid in spec.fragments:
        label = store.commit_asset(
            role=ROLE_LABEL_BUNDLE, schema="synlab.labels.v1", unit="1", frame="W_mm",
            payload={"relations_json": json.dumps(rows, ensure_ascii=False)},
            meta={"fragment_id": fid, "mother_id": spec.mother_id, "event_id": spec.event_id,
                  "component_id": f"{fid}::comp", "observation_id": f"obs::{fid}",
                  "route": "proxy_scan", "input_profile": "SENSOR_PROXY",
                  "source_kind": "OBS_EST", "scale_valid": True,
                  "is_tiny": fid in spec.tiny_fragments,
                  "quality_tier": int(spec.quality_tier.get(fid, 0)),
                  "history": {"historical_R2": [b for a, b in spec.r2 if a == fid]
                              + [a for a, b in spec.r2 if b == fid],
                              "mate_present": any(fid in pair for pair in spec.r2),
                              "association_kind": "EXACT_SURVIVOR"},
                  "relation_count": len(rows), "r2_count": r2_count},
            qa={"ok": True, "layer": "visible"}, qa_status=QA_PASS,
            lineage_id=spec.lineage_id, split=spec.split)
        out[fid] = label.asset_id
        if not spec.with_features:
            continue
        payload = make_feature_payload(fid, rng=rng,
                                       quality_tier=int(spec.quality_tier.get(fid, 0)))
        arrays = {k: v for k, v in payload.items() if isinstance(v, np.ndarray)}
        meta = {k: v for k, v in payload.items() if not isinstance(v, np.ndarray)}
        meta.update({"fragment_id": fid, "schema": "a12.obs.v1", "mother_id": spec.mother_id,
                     "lineage_id": spec.lineage_id})
        feature = store.commit_asset(
            role=ROLE_FEATURE_BUNDLE, schema=SCHEMA_FEATURE, unit="mm", frame="S_mm",
            payload=arrays, meta=meta, qa={"ok": True, "whitelist_checked": True},
            qa_status=QA_PASS, ancestry=[label.asset_id], lineage_id=spec.lineage_id,
            split=spec.split)
        store.commit_asset(
            role=ROLE_PROVENANCE, schema="synlab.provenance.v1", unit="1", frame="none",
            payload={}, meta={"seed_ref": f"[7,\"{spec.lineage_id}\"]", "fragment_id": fid},
            qa={"ok": True}, qa_status=QA_PASS,
            ancestry=[feature.asset_id, label.asset_id], lineage_id=spec.lineage_id,
            split=spec.split)
    return out


def commit_clean_truth(store: AssetStore, spec: EventSpec) -> str:
    """Alternative producer: a ``clean_truth`` asset carrying ``meta["relations"]``."""
    asset = store.commit_asset(
        role=ROLE_CLEAN_TRUTH, schema=SCHEMA_TRUTH_CLEAN, unit="mm", frame="W_mm",
        payload={}, meta={"mother_id": spec.mother_id, "event_id": spec.event_id,
                          "relations": relation_rows(spec),
                          "fragment_ids": list(spec.fragments)},
        qa={"ok": True}, qa_status=QA_PASS, lineage_id=spec.lineage_id, split=spec.split)
    return asset.asset_id


def make_event(lineage_id: str, mother_id: str, prefix: str, count: int, *,
               split: str = "dev", r2_chain: bool = True, r1_to: list[str] | None = None,
               tiny: list[tuple[str, str]] | None = None,
               unknown: list[tuple[str, str]] | None = None,
               features: bool = True, seed: int = 0,
               quality_tier: dict[str, int] | None = None) -> EventSpec:
    """A chain of ``count`` pieces: every piece touches its two chain neighbours (R2)."""
    fragments = [f"{prefix}{i:02d}" for i in range(count)]
    r2: list[tuple[str, str]] = []
    if r2_chain:
        for i in range(count - 1):
            r2.append((fragments[i], fragments[i + 1]))
    return EventSpec(
        lineage_id=lineage_id, mother_id=mother_id, event_id=f"{lineage_id}_E01", split=split,
        fragments=fragments, r2=r2, r1=list(r1_to or []), tiny=list(tiny or []),
        unknown=list(unknown or []), quality_tier=dict(quality_tier or {}),
        with_features=features, feature_seed=seed)


def build_two_event_store(tmp_path: Path, **kwargs) -> tuple[AssetStore, list[EventSpec]]:
    """Two independent lineages (A: 4 pieces, B: 3 pieces) plus a distractor lineage."""
    store = AssetStore(tmp_path)
    specs = [
        make_event("LIN0001_V01_M01", "m::LIN0001", "a", 4, split="dev", seed=1, **kwargs),
        make_event("LIN0002_V02_M02", "m::LIN0002", "b", 3, split="dev", seed=2, **kwargs),
    ]
    specs[0].r1 = [("a00", "b00"), ("a01", "b01")]
    specs[0].tiny = [("a02", "b02")]
    specs[0].unknown = [("a03", "b00")]
    for spec in specs:
        commit_event(store, spec)
    return store, specs
