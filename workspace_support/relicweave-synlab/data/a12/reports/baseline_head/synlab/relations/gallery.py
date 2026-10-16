"""Gallery construction, sparse relation index and the frozen relation pool (plan 16.1).

Design constraints implemented here
-----------------------------------
* A gallery fixes one physical mother / a set of **mutually exclusive** fracture events and
  always excludes the query itself (``candidate_ids`` never contains ``q``).
* The **full** R2 set ``N_G(q)`` is stored, independently of the gallery line-up: a query may
  have neighbours outside the gallery (mate-removed variant, nested size) and the original
  Cov denominator must not shrink because a candidate is invisible or out of pool
  (plan 16.1, 30.14).
* Relations are **sparse**: only non-R0 edges are materialised.  ``R0`` is implicit and
  *derived* from the frozen construction rule (different event ⇒ never adjacent; same event
  without a shared interface ⇒ non-adjacent), ``UNKNOWN`` only when a fragment's truth is
  incomplete.  An ``N x N`` table is never built (plan 16.1: 100k fragments ⇒ ~5e9 pairs).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from ..canonical import hash_json
from ..errors import ErrorCode, SynLabError
from ..roles import (
    FRAME_WORLD,
    ROLE_CLEAN_TRUTH,
    ROLE_FEATURE_BUNDLE,
    ROLE_LABEL_BUNDLE,
    SCHEMA_POOL,
    UNIT_NONE,
)
from ..schemas.runtime import (
    RELATION_R0,
    RELATION_R1,
    RELATION_R2,
    RELATION_TINY,
    RELATION_UNKNOWN,
    GallerySpec,
    QueryRosterEntry,
    RelationEdge,
)
from ..storage.store import AssetStore

#: Portable pool artifact schema (written next to the store so a roster/pool can be frozen).
POOL_SCHEMA = "synlab.pool.v1"

#: Scopes (frozen in :class:`~synlab.schemas.runtime.GallerySpec`).
SCOPES = ("FULL", "MATE_REMOVED", "NESTED", "DISTRACTOR_ONLY")

#: Relation names that may carry supervision; everything else is R0 (implicit).
EXPLICIT_KINDS = (RELATION_R2, RELATION_R1, RELATION_TINY, RELATION_UNKNOWN)

_KIND_CODE = {RELATION_R2: 2, RELATION_R1: 1, RELATION_R0: 0,
              RELATION_TINY: 3, RELATION_UNKNOWN: 4}
_CODE_KIND = {v: k for k, v in _KIND_CODE.items()}

SELF_RELATION = "SELF"
ABSENT_RELATION = "ABSENT"

#: Splits that mark a lineage as distractor-only (isolated from the training lineages).
DISTRACTOR_SPLITS = ("gallery_distractor", "distractor", "gallery_distractor_only")


def canonical_pair(a: str, b: str) -> tuple[str, str]:
    """Unordered pair key: symmetric relations must be stored exactly once."""
    return (a, b) if a <= b else (b, a)


# --------------------------------------------------------------------------------------
# Fragment bookkeeping
# --------------------------------------------------------------------------------------
@dataclass
class FragmentRecord:
    """One fragment identity inside a gallery (opaque; never a model input)."""

    fragment_id: str
    lineage_id: str
    mother_id: str
    event_id: str
    split: str
    feature_ref: str | None = None
    label_ref: str | None = None
    obs_ref: str | None = None
    is_tiny: bool = False
    quality_tier: int = 0
    verified: bool = True
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def lineage_cluster(self) -> str:
        """Bootstrap/sampling cluster: the independent mother lineage (plan 19.4)."""
        return self.lineage_id or self.mother_id or "UNKNOWN"

    def as_dict(self) -> dict[str, Any]:
        return {
            "fragment_id": self.fragment_id, "lineage_id": self.lineage_id,
            "mother_id": self.mother_id, "event_id": self.event_id, "split": self.split,
            "feature_ref": self.feature_ref, "label_ref": self.label_ref, "obs_ref": self.obs_ref,
            "is_tiny": bool(self.is_tiny), "quality_tier": int(self.quality_tier),
            "verified": bool(self.verified),
        }


# --------------------------------------------------------------------------------------
# Sparse relation index
# --------------------------------------------------------------------------------------
class RelationsIndex:
    """Sparse symmetric relation index over an explicit fragment set."""

    def __init__(self) -> None:
        self._edges: dict[tuple[str, str], RelationEdge] = {}
        self._r2: dict[str, set[str]] = {}
        self._members: set[str] = set()
        self._unverified: set[str] = set()

    # ------------------------------------------------------------------ construction
    def set_members(self, fragment_ids: Iterable[str]) -> None:
        self._members = {str(f) for f in fragment_ids}

    def mark_unverified(self, fragment_id: str) -> None:
        self._unverified.add(str(fragment_id))

    def add(self, a: str, b: str, kind: str, *, interface_id: int | None = None,
            area_mm2: float = 0.0, valid: bool = True, loss_mask: bool = True,
            reason: str = "") -> None:
        a, b = str(a), str(b)
        if a == b:
            return
        kind = str(kind)
        if kind == RELATION_R0:
            # R0 is implicit; storing it would materialise the N^2 table (plan 16.1).
            self._edges.pop(canonical_pair(a, b), None)
            return
        if kind not in EXPLICIT_KINDS:
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              f"unknown relation kind {kind!r} for {a}/{b}",
                              stage="relations.RelationsIndex.add")
        key = canonical_pair(a, b)
        self._edges[key] = RelationEdge(fragment_a=key[0], fragment_b=key[1], kind=kind,
                                        interface_id=(None if interface_id is None
                                                      else int(interface_id)),
                                        area_mm2=float(area_mm2), valid=bool(valid),
                                        reason=reason, loss_mask=bool(loss_mask))
        if kind == RELATION_R2:
            self._r2.setdefault(a, set()).add(b)
            self._r2.setdefault(b, set()).add(a)
        else:
            self._r2.setdefault(a, set()).discard(b)
            self._r2.setdefault(b, set()).discard(a)

    # ------------------------------------------------------------------ queries
    def relation(self, a: str, b: str) -> str:
        a, b = str(a), str(b)
        if a == b:
            return SELF_RELATION
        if a not in self._members or b not in self._members:
            return ABSENT_RELATION
        edge = self._edges.get(canonical_pair(a, b))
        if edge is not None:
            return edge.kind
        if not edge and (a in self._unverified or b in self._unverified):
            return RELATION_UNKNOWN
        # Implicit R0: confirmed non-adjacency *by construction*.  Two fragments either come
        # from mutually exclusive fracture events (never adjacent), or from the same event
        # without a shared interface (non-adjacent inside one body).
        return RELATION_R0

    def confirmed(self, a: str, b: str) -> bool:
        rel = self.relation(a, b)
        return rel not in (RELATION_UNKNOWN, ABSENT_RELATION, SELF_RELATION)

    def neighbours(self, query_id: str) -> tuple[str, ...]:
        """Full in-gallery R2 set ``N_G(q)`` excluding ``q`` itself."""
        q = str(query_id)
        return tuple(sorted(n for n in self._r2.get(q, ()) if n != q))

    def r2_neighbours(self, query_id: str) -> tuple[str, ...]:
        return self.neighbours(query_id)

    def edge(self, a: str, b: str) -> RelationEdge | None:
        return self._edges.get(canonical_pair(a, b))

    # ------------------------------------------------------------------ accounting
    @property
    def explicit_edges(self) -> int:
        return len(self._edges)

    @property
    def r2_edges(self) -> int:
        return sum(1 for e in self._edges.values() if e.kind == RELATION_R2)

    @property
    def r1_edges(self) -> int:
        return sum(1 for e in self._edges.values() if e.kind == RELATION_R1)

    @property
    def tiny_edges(self) -> int:
        return sum(1 for e in self._edges.values() if e.kind == RELATION_TINY)

    @property
    def unknown_edges(self) -> int:
        return sum(1 for e in self._edges.values() if e.kind == RELATION_UNKNOWN)

    def kind_histogram(self) -> dict[str, int]:
        out = {RELATION_R2: 0, RELATION_R1: 0, RELATION_R0: 0, RELATION_TINY: 0,
               RELATION_UNKNOWN: 0}
        for edge in self._edges.values():
            out[edge.kind] = out.get(edge.kind, 0) + 1
        return out

    def items(self) -> Iterable[tuple[tuple[str, str], RelationEdge]]:
        return self._edges.items()

    def unverified(self) -> frozenset[str]:
        return frozenset(self._unverified)

    # ------------------------------------------------------------------ serialisation
    def to_arrays(self, fragment_ids: Sequence[str]) -> dict[str, np.ndarray]:
        """Sparse array payload (only non-R0 edges; no N^2 materialisation)."""
        index = {fid: i for i, fid in enumerate(fragment_ids)}
        rows = [(index[a], index[b], edge) for (a, b), edge in sorted(self._edges.items())
                if a in index and b in index]
        a = np.asarray([r[0] for r in rows], dtype=np.int32)
        b = np.asarray([r[1] for r in rows], dtype=np.int32)
        code = np.asarray([_KIND_CODE[r[2].kind] for r in rows], dtype=np.int8)
        area = np.asarray([float(r[2].area_mm2) for r in rows], dtype=np.float32)
        iface = np.asarray([(-1 if r[2].interface_id is None else int(r[2].interface_id))
                            for r in rows], dtype=np.int32)
        valid = np.asarray([bool(r[2].valid) for r in rows], dtype=bool)
        loss_mask = np.asarray([bool(r[2].loss_mask) for r in rows], dtype=bool)
        return {"rel_a": a, "rel_b": b, "rel_kind": code, "rel_area_mm2": area,
                "rel_interface": iface, "rel_valid": valid, "rel_loss_mask": loss_mask}

    @classmethod
    def from_arrays(cls, fragment_ids: Sequence[str],
                    arrays: Mapping[str, np.ndarray]) -> "RelationsIndex":
        index = cls()
        index.set_members(fragment_ids)
        ids = list(fragment_ids)
        a = np.asarray(arrays.get("rel_a", np.zeros(0, dtype=np.int32)), dtype=np.int64)
        b = np.asarray(arrays.get("rel_b", np.zeros(0, dtype=np.int32)), dtype=np.int64)
        kind = np.asarray(arrays.get("rel_kind", np.zeros(0, dtype=np.int8)), dtype=np.int64)
        area = np.asarray(arrays.get("rel_area_mm2", np.zeros(a.size, dtype=np.float32)),
                          dtype=np.float64)
        iface = np.asarray(arrays.get("rel_interface", np.full(a.size, -1, dtype=np.int32)),
                           dtype=np.int64)
        valid = np.asarray(arrays.get("rel_valid", np.ones(a.size, dtype=bool)), dtype=bool)
        loss_mask = np.asarray(arrays.get("rel_loss_mask", np.ones(a.size, dtype=bool)), dtype=bool)
        for i in range(a.size):
            ka, kb = int(a[i]), int(b[i])
            if ka >= len(ids) or kb >= len(ids) or ka == kb:
                continue
            index.add(ids[ka], ids[kb], _CODE_KIND.get(int(kind[i]), RELATION_UNKNOWN),
                      interface_id=None if int(iface[i]) < 0 else int(iface[i]),
                      area_mm2=float(area[i]), valid=bool(valid[i]),
                      loss_mask=bool(loss_mask[i]))
        return index

    def to_json_records(self) -> list[dict[str, Any]]:
        return [{"a": key[0], "b": key[1], "kind": edge.kind, "interface_id": edge.interface_id,
                 "area_mm2": edge.area_mm2, "valid": edge.valid, "loss_mask": edge.loss_mask}
                for key, edge in sorted(self._edges.items())]


# --------------------------------------------------------------------------------------
# The pool object (duck-typed to the frozen fixture interface)
# --------------------------------------------------------------------------------------
@dataclass
class RelationPool:
    """Frozen gallery + full historical neighbour sets + the sparse relation index.

    Attribute/method names match ``tests/a12/_fixtures.FixturePool`` so that
    ``synlab.training`` and ``synlab.diagnostics`` consume either without changes.
    """

    gallery: GallerySpec
    fragments: dict[str, FragmentRecord]
    index: RelationsIndex
    roster: list[QueryRosterEntry] = field(default_factory=list)
    historical_neighbours: dict[str, list[str]] = field(default_factory=dict)
    features: dict[str, dict] = field(default_factory=dict)
    gallery_distractor_only: set[str] = field(default_factory=set)
    meta: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------ identity
    @property
    def pool_id(self) -> str:
        return self.gallery.pool_id

    @property
    def gallery_version(self) -> str:
        return self.gallery.gallery_version

    @property
    def hash(self) -> str:
        return self.gallery.hash

    @property
    def scope(self) -> str:
        return self.gallery.scope

    @property
    def lineup(self) -> list[str]:
        return list(self.gallery.fragment_ids)

    @property
    def fragment_ids(self) -> list[str]:
        return list(self.gallery.fragment_ids)

    @property
    def split_of(self) -> dict[str, str]:
        return {fid: rec.split for fid, rec in self.fragments.items()}

    @property
    def lineage_of(self) -> dict[str, str]:
        return {fid: rec.lineage_id for fid, rec in self.fragments.items()}

    @property
    def lineage_cluster_of(self) -> dict[str, str]:
        return {fid: rec.lineage_cluster for fid, rec in self.fragments.items()}

    @property
    def mother_of(self) -> dict[str, str]:
        return {fid: rec.mother_id for fid, rec in self.fragments.items()}

    @property
    def event_of(self) -> dict[str, str]:
        return {fid: rec.event_id for fid, rec in self.fragments.items()}

    @property
    def quality_tier(self) -> dict[str, int]:
        return {fid: int(rec.quality_tier) for fid, rec in self.fragments.items()}

    @property
    def mate_absent(self) -> set[str]:
        return {fid for fid in self.lineup if not self.neighbours(fid)}

    @property
    def relations(self) -> dict[tuple[str, str], str]:
        """Explicit (non-R0) edges only -- R0 is implicit and never materialised."""
        return {key: edge.kind for key, edge in self.index.items()}

    @property
    def r2_edges(self) -> int:
        return self.index.r2_edges

    # ------------------------------------------------------------------ queries
    def relation(self, a: str, b: str) -> str:
        return self.index.relation(a, b)

    def confirmed(self, a: str, b: str) -> bool:
        return self.index.confirmed(a, b)

    def neighbours(self, fragment_id: str) -> list[str]:
        """``N_G(q)``: the **full** historical R2 set inside this gallery, excluding ``q``."""
        hist = self.historical_neighbours.get(str(fragment_id))
        if hist is not None:
            return [f for f in hist if f != fragment_id]
        return list(self.index.neighbours(fragment_id))

    def historical_r2(self, fragment_id: str) -> list[str]:
        """Including neighbours that were removed from the gallery line-up."""
        return self.neighbours(fragment_id)

    def candidate_ids(self, fragment_id: str) -> list[str]:
        """The query itself is never a candidate (plan 16.1)."""
        return [f for f in self.lineup if f != fragment_id]

    def feature_for(self, fragment_id: str) -> dict | None:
        return self.features.get(str(fragment_id))

    def roster_entry(self, fragment_id: str, *, gallery_id: str | None = None,
                     split: str = "dev", status: str = "FROZEN") -> QueryRosterEntry:
        fid = str(fragment_id)
        rec = self.fragments.get(fid)
        neighbours = self.neighbours(fid)
        return QueryRosterEntry(
            query_id=f"q::{fid}",
            lineage_cluster=(rec.lineage_cluster if rec else self.index.relation(fid, fid)),
            mother_id=(rec.mother_id if rec else ""),
            fragment_id=fid,
            split=(rec.split if rec else split),
            gallery_id=gallery_id or self.pool_id,
            historical_neighbours=list(neighbours),
            mate_present=bool(neighbours),
            status=status,
            applicability={},
        )

    # ------------------------------------------------------------------ accounting
    def stats(self) -> dict[str, Any]:
        hist = self.index.kind_histogram()
        n_r2 = self.index.r2_edges
        return {
            "pool_id": self.pool_id,
            "gallery_version": self.gallery_version,
            "hash": self.hash,
            "scope": self.scope,
            "split": self.gallery.split,
            "fragments": len(self.lineup),
            "lineages": len({rec.lineage_id for rec in self.fragments.values()}),
            "mothers": len({rec.mother_id for rec in self.fragments.values()}),
            "events": len({rec.event_id for rec in self.fragments.values()}),
            "r2_edges": n_r2,
            "r1_edges": hist[RELATION_R1],
            "tiny_contact_edges": hist[RELATION_TINY],
            "unknown_edges": hist[RELATION_UNKNOWN],
            "explicit_edges": self.index.explicit_edges,
            "r0_implicit_pairs": (len(self.lineup) * (len(self.lineup) - 1) // 2
                                  - self.index.explicit_edges),
            "n2_materialised": False,
            "mate_absent": len(self.mate_absent),
            "queries": len(self.roster),
            "queries_with_mates": sum(1 for q in self.roster if q.mate_present),
            "features_attached": len(self.features),
            "gallery_distractor_only": sorted(self.gallery_distractor_only),
        }


# --------------------------------------------------------------------------------------
# Building a pool from the store
# --------------------------------------------------------------------------------------
def _iter_assets(store: AssetStore, *, role: str | None = None, split: str | None = None,
                 page: int = 2000) -> list[Any]:
    out: list[Any] = []
    offset = 0
    while True:
        chunk = store.list_assets(role=role, split=split, limit=page, offset=offset)
        out.extend(chunk)
        if len(chunk) < page:
            return out
        offset += page


def _json_loads(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return None
    return None


def _relations_from_record(record: Any, arrays: Mapping[str, np.ndarray]) -> list[dict[str, Any]]:
    """Read relation edges from a committed truth/label asset (documented encodings).

    Accepted forms (first match wins):
      * ``meta["relations"]``: list of ``{"a","b","kind",...}`` or ``{"a|b": kind}`` mapping;
      * ``meta["relations_json"]``: JSON string of the same list (written by
        ``synlab.pipeline._commit_labels``);
      * arrays ``rel_a``/``rel_b``/``rel_kind`` with ``fragment_ids`` in ``meta``.
    """
    meta = dict(getattr(record, "meta", {}) or {})
    payload = meta.get("relations")
    if payload is None:
        payload = _json_loads(meta.get("relations_json"))
    out: list[dict[str, Any]] = []
    if isinstance(payload, Mapping):
        for key, kind in payload.items():
            if isinstance(key, (tuple, list)) and len(key) == 2:
                a, b = str(key[0]), str(key[1])
            elif isinstance(key, str) and "|" in key:
                a, b = key.split("|", 1)
            else:
                continue
            if isinstance(kind, Mapping):
                out.append({"a": a, "b": b, **dict(kind)})
            else:
                out.append({"a": a, "b": b, "kind": str(kind)})
        return out
    if isinstance(payload, Sequence):
        for item in payload:
            if isinstance(item, Mapping):
                a = item.get("a") or item.get("fragment_a")
                b = item.get("b") or item.get("fragment_b")
                if a is None or b is None:
                    continue
                out.append({"a": str(a), "b": str(b), "kind": str(item.get("kind", RELATION_R0)),
                            "interface_id": item.get("interface_id"),
                            "area_mm2": float(item.get("area_mm2", 0.0) or 0.0),
                            "valid": bool(item.get("valid", True)),
                            "loss_mask": bool(item.get("loss_mask", True))})
        return out
    ids = meta.get("fragment_ids")
    if ids is not None and "rel_a" in arrays:
        ids = [str(i) for i in ids]
        a = np.asarray(arrays["rel_a"], dtype=np.int64)
        b = np.asarray(arrays["rel_b"], dtype=np.int64)
        code = np.asarray(arrays.get("rel_kind", np.zeros(a.size, dtype=np.int8)), dtype=np.int64)
        for i in range(a.size):
            if int(a[i]) >= len(ids) or int(b[i]) >= len(ids):
                continue
            out.append({"a": ids[int(a[i])], "b": ids[int(b[i])],
                        "kind": _CODE_KIND.get(int(code[i]), RELATION_UNKNOWN)})
    return out


def collect_fragments(store: AssetStore, *, release: Mapping[str, Any] | None = None,
                      splits: Sequence[str] | None = None) -> dict[str, FragmentRecord]:
    """Collect fragment records + relation edges from committed truth/label assets."""
    allowed: set[str] | None = None
    if release is not None:
        allowed = {str(a.get("asset_id")) for a in release.get("assets", [])}
    records: dict[str, FragmentRecord] = {}
    edges: list[dict[str, Any]] = []
    for role in (ROLE_LABEL_BUNDLE, ROLE_CLEAN_TRUTH):
        for asset in _iter_assets(store, role=role):
            if allowed is not None and asset.asset_id not in allowed:
                continue
            if splits is not None and asset.split is not None and asset.split not in splits:
                continue
            meta = dict(asset.meta or {})
            fragment_id = str(meta.get("fragment_id") or meta.get("component_id") or "")
            lineage_id = str(asset.lineage_id or meta.get("lineage_id") or "")
            mother_id = str(meta.get("mother_id") or lineage_id)
            event_id = str(meta.get("event_id") or
                           (meta.get("history") or {}).get("event_id") or "")
            verified = bool(asset.qa_status == "QA_PASS") and not bool(meta.get("truth_incomplete"))
            history = meta.get("history") or {}
            association = str(history.get("association_kind", "EXACT_SURVIVOR"))
            if association == "UNKNOWN_MAPPING":
                verified = False
            if fragment_id:
                records[fragment_id] = FragmentRecord(
                    fragment_id=fragment_id, lineage_id=lineage_id, mother_id=mother_id,
                    event_id=event_id, split=str(asset.split or meta.get("split") or ""),
                    feature_ref=meta.get("feature_ref"), label_ref=asset.asset_id,
                    obs_ref=meta.get("observation_id"),
                    is_tiny=bool(meta.get("is_tiny", False)),
                    quality_tier=int(meta.get("quality_tier", 0) or 0),
                    verified=verified,
                    meta={"label_asset": asset.asset_id,
                          "r2_count": int(meta.get("r2_count", 0) or 0)},
                )
            record_edges = _relations_from_record(asset, store.load_arrays(asset.asset_id))
            for edge in record_edges:
                edge.setdefault("lineage_id", lineage_id)
                edge.setdefault("mother_id", mother_id)
                edge.setdefault("event_id", event_id)
                edge.setdefault("split", str(asset.split or ""))
                edge.setdefault("verified", verified)
                edges.append(edge)
            if role == ROLE_CLEAN_TRUTH:
                for edge in record_edges:
                    for endpoint in (str(edge.get("a")), str(edge.get("b"))):
                        records.setdefault(endpoint, FragmentRecord(
                            fragment_id=endpoint, lineage_id=lineage_id, mother_id=mother_id,
                            event_id=event_id, split=str(asset.split or ""),
                            label_ref=asset.asset_id, verified=verified))
    for edge in edges:
        a, b = str(edge.get("a")), str(edge.get("b"))
        for endpoint in (a, b):
            rec = records.get(endpoint)
            if rec is None:
                records[endpoint] = FragmentRecord(
                    fragment_id=endpoint, lineage_id=str(edge.get("lineage_id", "")),
                    mother_id=str(edge.get("mother_id", "")),
                    event_id=str(edge.get("event_id", "")), split=str(edge.get("split", "")),
                    verified=bool(edge.get("verified", True)))
            if not rec.event_id and edge.get("event_id"):
                rec.event_id = str(edge["event_id"])
    return records


def load_relations_into(index: RelationsIndex, store: AssetStore, *,
                        release: Mapping[str, Any] | None = None,
                        splits: Sequence[str] | None = None) -> dict[str, int]:
    """Populate ``index`` from the store; returns the edge histogram actually loaded."""
    allowed: set[str] | None = None
    if release is not None:
        allowed = {str(a.get("asset_id")) for a in release.get("assets", [])}
    counts = {kind: 0 for kind in EXPLICIT_KINDS}
    for role in (ROLE_LABEL_BUNDLE, ROLE_CLEAN_TRUTH):
        for asset in _iter_assets(store, role=role):
            if allowed is not None and asset.asset_id not in allowed:
                continue
            if splits is not None and asset.split is not None and asset.split not in splits:
                continue
            for edge in _relations_from_record(asset, store.load_arrays(asset.asset_id)):
                kind = str(edge.get("kind", RELATION_R0))
                if kind not in EXPLICIT_KINDS:
                    continue
                index.add(str(edge.get("a")), str(edge.get("b")), kind,
                          interface_id=edge.get("interface_id"),
                          area_mm2=float(edge.get("area_mm2", 0.0) or 0.0),
                          valid=bool(edge.get("valid", True)),
                          loss_mask=bool(edge.get("loss_mask", True)))
                counts[kind] = counts.get(kind, 0) + 1
    return counts


def attach_features(pool: RelationPool, store: AssetStore) -> dict[str, Any]:
    """Attach legal observation feature payloads (``a12.obs.v1``) by fragment id.

    Feature assets are matched through the provenance chain written by the pipeline
    (``provenance.ancestry = [feature_asset, label_asset]``) and through an explicit
    ``meta["feature_ref"]``; a fragment whose payload cannot be resolved keeps a missing
    entry (never a zero vector masquerading as a real observation).
    """
    label_to_fragment = {rec.label_ref: fid for fid, rec in pool.fragments.items()
                         if rec.label_ref}
    feature_refs: dict[str, str] = {
        fid: rec.feature_ref for fid, rec in pool.fragments.items() if rec.feature_ref}
    feature_assets: dict[str, str] = {}
    for asset in _iter_assets(store, role=ROLE_FEATURE_BUNDLE):
        meta = dict(asset.meta or {})
        fid = str(meta.get("fragment_id") or "")
        if fid:
            feature_assets[fid] = asset.asset_id
        for ancestor in asset.ancestry or []:
            if ancestor in label_to_fragment:
                feature_assets.setdefault(label_to_fragment[ancestor], asset.asset_id)
    for asset in _iter_assets(store, role="provenance"):
        ancestry = list(asset.ancestry or [])
        if len(ancestry) >= 2 and ancestry[1] in label_to_fragment:
            feature_assets.setdefault(label_to_fragment[ancestry[1]], ancestry[0])
    attached, failed = {}, []
    for fid in pool.lineup:
        ref = feature_refs.get(fid) or feature_assets.get(fid)
        if not ref:
            continue
        try:
            arrays = store.load_arrays(ref)
        except SynLabError:
            failed.append(fid)
            continue
        payload = _feature_payload(store, ref, arrays)
        if payload:
            attached[fid] = payload
            pool.fragments[fid].feature_ref = ref
    pool.features = attached
    return {"attached": len(attached), "missing": len(pool.lineup) - len(attached),
            "failed": sorted(failed)}


#: ``a12.obs.v1`` fields stored as arrays (``arrays.npz`` or a JSON list in ``meta``).
_ARRAY_FIELDS = (
    "global_rgb", "global_valid", "pixel_valid", "local_tokens", "token_valid",
    "token_view", "token_pixel", "token_modality", "token_source", "token_retrieval",
    "points", "point_valid", "normals", "normal_valid", "quality", "quality_valid",
    "presence", "presence_valid", "view_tokens", "roi_weight", "token_index", "roi_area_px",
)

#: ``a12.obs.v1`` scalar fields that stay scalars.
_SCALAR_FIELDS = ("tokens_total", "scale_valid", "obs_version", "quality_tier")


def _feature_payload(store: AssetStore, asset_id: str, arrays: Mapping[str, np.ndarray]) -> dict:
    """Rebuild an ``a12.obs.v1`` payload from a committed feature bundle asset."""
    if not any(key in arrays for key in ("points", "global_rgb", "local_tokens")):
        return {}
    record = store.get_asset(asset_id)
    meta = dict(record.meta or {})
    payload: dict[str, Any] = {"schema": str(meta.get("schema", "a12.obs.v1"))}
    for key in _ARRAY_FIELDS:
        if key in arrays:
            payload[key] = np.asarray(arrays[key])
        elif key in meta:
            value = meta[key]
            if isinstance(value, (list, tuple)):
                payload[key] = np.asarray(value)
            elif isinstance(value, np.ndarray):
                payload[key] = value
    for key in _SCALAR_FIELDS:
        if key in arrays:
            value = np.asarray(arrays[key])
            payload[key] = (bool(value.reshape(-1)[0]) if key == "scale_valid"
                            else (value.reshape(-1)[0].item() if value.size else None))
        elif key in meta:
            payload[key] = meta[key]
    if "points" not in payload or "global_rgb" not in payload:
        return {}
    payload.setdefault("scale_valid", bool(meta.get("scale_valid", False)))
    return payload


def gallery_hash(payload: Mapping[str, Any]) -> str:
    return hash_json({k: v for k, v in payload.items() if k != "hash"})


__all__ = [
    "POOL_SCHEMA", "SCOPES", "EXPLICIT_KINDS", "DISTRACTOR_SPLITS", "SELF_RELATION",
    "ABSENT_RELATION", "canonical_pair", "FragmentRecord", "RelationsIndex", "RelationPool",
    "collect_fragments", "load_relations_into", "attach_features", "gallery_hash",
]
