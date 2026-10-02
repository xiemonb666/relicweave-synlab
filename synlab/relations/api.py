"""Relations façade: gallery/pool building, training sampling and hard negatives.

Frozen entry points (``docs/a12/interfaces.md`` §2, parent plan §16 and §30.10/30.15):

* :func:`build_pool` / :func:`build_pool_from_config` -- fixed physical mother + mutually
  exclusive event set, query excluded from its own candidates, **full** ``N_G(q)`` stored,
  FULL / MATE_REMOVED / NESTED / DISTRACTOR_ONLY scopes, ``distractor_isolated`` flag,
  ``pool_id``/``gallery_version``/``hash``.  ``N x N`` is never materialised.
* :func:`sample_training_batch` -- lineage-balanced micro-batch, 1-2 positives, 4 R1 + 4 R0
  start, explicit R1 fallback, historical R2 / TINY / UNKNOWN removed from negatives.
* :func:`mine_hard_negatives` -- legal-observable TopM retrieval, labels only for exclusion.
* :func:`commit_pool` / :func:`load_pool` -- asset persistence under role ``relation_pool``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from ..canonical import hash_json
from ..config import load_document
from ..errors import ErrorCode, SynLabError
from ..roles import (
    FRAME_WORLD,
    ROLE_POOL,
    ROLE_ROSTER,
    SCHEMA_POOL,
    SCHEMA_ROSTER,
    UNIT_NONE,
)
from ..schemas.runtime import GallerySpec, QueryRosterEntry
from ..seeds import make_rng
from ..storage.store import AssetStore
from .gallery import (
    DISTRACTOR_SPLITS,
    POOL_SCHEMA,
    SCOPES,
    FragmentRecord,
    RelationPool,
    RelationsIndex,
    attach_features,
    collect_fragments,
    gallery_hash,
    load_relations_into,
)
from .sampler import mine_hard_negatives, sample_training_batch  # noqa: F401  (façade re-export)

API_VERSION = "synlab.relations.api.v1"

#: Above this many fragments the portable JSON copy is skipped (the asset stays canonical).
PORTABLE_JSON_LIMIT = 20000


# --------------------------------------------------------------------------------------
# configuration
# --------------------------------------------------------------------------------------
@dataclass
class PoolConfig:
    pool_id: str = "pool"
    gallery_version: str = "v1"
    scope: str = "FULL"
    split: str = "dev"
    lineage_ids: list[str] = field(default_factory=list)
    size_target: int = 200
    exclude_training_lineages: bool = True
    nested_sizes: list[int] = field(default_factory=list)
    mate_removed_variant: bool = False
    query_per_mother: int = 4
    refinement_candidates: list[int] = field(default_factory=lambda: [10, 20, 50])
    top_k: list[int] = field(default_factory=lambda: [1, 5, 10])
    gallery_distractor_only: bool = False
    include_unverified: bool = False
    seed: int = 20261001

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "PoolConfig":
        known = {f for f in cls.__dataclass_fields__}
        unknown = sorted(set(data) - known - {"schema", "note", "notes"})
        if unknown:
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              f"pool config has unknown keys: {unknown}",
                              stage="relations.PoolConfig.from_mapping",
                              evidence_refs=unknown)
        payload = {k: v for k, v in data.items() if k in known}
        cfg = cls(**payload)
        cfg.validate()
        return cfg

    @classmethod
    def from_any(cls, spec_or_config: Any) -> "PoolConfig":
        if isinstance(spec_or_config, PoolConfig):
            return spec_or_config
        if isinstance(spec_or_config, (str, Path)):
            path = Path(spec_or_config)
            data = load_document(path) if path.exists() else None
            if data is None:
                raise SynLabError(ErrorCode.SCHEMA_INVALID,
                                  f"pool config not found: {path}",
                                  stage="relations.PoolConfig.from_any")
            return cls.from_mapping(data)
        if isinstance(spec_or_config, Mapping):
            return cls.from_mapping(spec_or_config)
        # a GenerationSpec / TrainingSpec style object: derive sane gallery defaults
        spec = spec_or_config
        dataset = getattr(spec, "dataset", None)
        storage = getattr(spec, "storage", None)
        seed = int(getattr(spec, "master_seed", 20261001) or 20261001)
        return cls(seed=seed,
                   size_target=int(getattr(dataset, "target_fragments_estimate", 200) or 200),
                   lineage_ids=list(getattr(dataset, "vessel_ids", []) or []),
                   split=str(getattr(getattr(spec, "evaluation", spec), "split", "dev")),
                   pool_id=str(getattr(storage, "root", "pool")).replace("/", "_"))

    def validate(self) -> None:
        if self.scope not in SCOPES:
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              f"unknown gallery scope {self.scope!r}; expected {SCOPES}",
                              stage="relations.PoolConfig.validate")
        if int(self.size_target) < 1:
            raise SynLabError(ErrorCode.SCHEMA_INVALID, "size_target must be >= 1",
                              stage="relations.PoolConfig.validate")
        if int(self.query_per_mother) < 1:
            raise SynLabError(ErrorCode.SCHEMA_INVALID, "query_per_mother must be >= 1",
                              stage="relations.PoolConfig.validate")
        nested = [int(n) for n in self.nested_sizes]
        if any(n < 1 for n in nested):
            raise SynLabError(ErrorCode.SCHEMA_INVALID, "nested_sizes must be positive",
                              stage="relations.PoolConfig.validate")


# --------------------------------------------------------------------------------------
# gallery assembly
# --------------------------------------------------------------------------------------
def _is_distractor(rec: FragmentRecord) -> bool:
    return (rec.split in DISTRACTOR_SPLITS
            or bool(rec.meta.get("gallery_distractor_only"))
            or "DISTRACTOR" in rec.lineage_id.upper())


def _eligible(records: Mapping[str, FragmentRecord], cfg: PoolConfig) -> dict[str, FragmentRecord]:
    lineages = set(cfg.lineage_ids or [])
    out: dict[str, FragmentRecord] = {}
    for fid, rec in records.items():
        if not rec.verified and not cfg.include_unverified:
            continue
        if lineages and rec.lineage_id not in lineages and rec.mother_id not in lineages:
            continue
        if cfg.exclude_training_lineages and rec.split == "train":
            continue
        out[fid] = rec
    return out


def _frozen_order(records: Mapping[str, FragmentRecord], cfg: PoolConfig) -> list[str]:
    """Deterministic nested order: round-robin over shuffled mothers, stable inside a mother."""
    rng = make_rng(cfg.seed, cfg.pool_id, "gallery_order")
    mothers: dict[str, list[str]] = {}
    for fid, rec in records.items():
        mothers.setdefault(rec.mother_id or rec.lineage_id or "?", []).append(fid)
    keys = sorted(mothers)
    rng.shuffle(keys)
    for key in keys:
        mothers[key] = sorted(mothers[key])
    order: list[str] = []
    depth = 0
    while True:
        progressed = False
        for key in keys:
            members = mothers[key]
            if depth < len(members):
                order.append(members[depth])
                progressed = True
        if not progressed:
            break
        depth += 1
    return order


def _neighbour_map(index: RelationsIndex, lineup: Sequence[str]) -> tuple[dict[str, list[str]],
                                                                        dict[str, list[str]]]:
    """(in-gallery N_G(q), out-of-gallery historical neighbours) for the frozen line-up."""
    inside = set(lineup)
    in_gallery: dict[str, list[str]] = {}
    outside: dict[str, list[str]] = {}
    for fid in lineup:
        neighbours = sorted(index.neighbours(fid))
        in_gallery[fid] = [n for n in neighbours if n in inside and n != fid]
        outside[fid] = [n for n in neighbours if n not in inside]
    return in_gallery, outside


def _draw_queries(records: Mapping[str, FragmentRecord], lineup: Sequence[str], cfg: PoolConfig,
                  seed_parts: Sequence[Any]) -> list[str]:
    rng = make_rng(cfg.seed, cfg.pool_id, *seed_parts, "queries")
    by_mother: dict[str, list[str]] = {}
    for fid in lineup:
        by_mother.setdefault(records[fid].mother_id or records[fid].lineage_id, []).append(fid)
    for key in by_mother:
        by_mother[key] = sorted(by_mother[key])
    keys = sorted(by_mother)
    rng.shuffle(keys)
    picked: list[str] = []
    for round_index in range(int(cfg.query_per_mother)):
        for key in keys:
            members = by_mother[key]
            if round_index < len(members):
                picked.append(members[round_index])
    return picked


def _nested_report(records: Mapping[str, FragmentRecord], index: RelationsIndex,
                   order: Sequence[str], cfg: PoolConfig,
                   base_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for size in sorted({int(n) for n in cfg.nested_sizes}):
        if size > len(order):
            out.append({"pool_id": f"{cfg.pool_id}__n{size}", "size_target": size,
                        "size": 0, "status": "GALLERY_SIZE_PENDING",
                        "available": len(order),
                        "reason": f"only {len(order)} eligible fragments are frozen for this gallery"})
            continue
        lineup = list(order[:size])
        in_gallery, outside = _neighbour_map(index, lineup)
        payload = {**base_payload, "size_target": size, "fragment_ids": sorted(lineup),
                   "nested_size": size}
        out.append({
            "pool_id": f"{cfg.pool_id}__n{size}",
            "size_target": size,
            "size": len(lineup),
            "status": "OK",
            "hash": gallery_hash(payload),
            "r2_edges": int(sum(len(v) for v in in_gallery.values()) // 2),
            "queries_with_mates": sum(1 for v in in_gallery.values() if v),
            "out_of_gallery_neighbours": sum(len(v) for v in outside.values()),
        })
    return out


def _scope_variants(records: Mapping[str, FragmentRecord], index: RelationsIndex,
                    lineup: Sequence[str], queries: Sequence[str], cfg: PoolConfig,
                    base_payload: Mapping[str, Any]) -> dict[str, Any]:
    in_gallery, outside = _neighbour_map(index, lineup)
    mate_neighbours = {n for q in queries for n in in_gallery.get(q, [])}
    removed_lineup = [f for f in lineup if f not in mate_neighbours]
    removed_hist, removed_outside = _neighbour_map(index, removed_lineup)
    distractor = [f for f in lineup if _is_distractor(records[f])]
    variants: dict[str, Any] = {
        "FULL": {
            "pool_id": cfg.pool_id, "size": len(lineup), "hash": gallery_hash(base_payload),
            "queries_with_mates": sum(1 for q in queries if in_gallery.get(q)),
        },
        "MATE_REMOVED": {
            "pool_id": f"{cfg.pool_id}__mate_removed",
            "size": len(removed_lineup),
            "removed": len(lineup) - len(removed_lineup),
            "hash": gallery_hash({**base_payload, "scope": "MATE_REMOVED",
                                  "fragment_ids": sorted(removed_lineup)}),
            "queries_with_mates": sum(1 for q in queries if removed_hist.get(q)),
            "note": "all R2 neighbours of the roster queries are removed from the line-up; "
                    "the removed fragments stay recorded as out-of-gallery neighbours",
            "out_of_gallery_neighbours": sum(len(v) for v in removed_outside.values()),
        },
        "DISTRACTOR_ONLY": {
            "pool_id": f"{cfg.pool_id}__distractor_only",
            "size": len(distractor),
            "lineages": sorted({records[f].lineage_id for f in distractor}),
            "hash": gallery_hash({**base_payload, "scope": "DISTRACTOR_ONLY",
                                  "fragment_ids": sorted(distractor)}),
        },
    }
    return variants


# --------------------------------------------------------------------------------------
# build_pool
# --------------------------------------------------------------------------------------
def resolve_release(store: AssetStore, release_id_or_manifest: Any) -> tuple[dict[str, Any] | None,
                                                                            dict[str, Any]]:
    """Resolve a release id / manifest mapping; a missing release is recorded, never hidden."""
    if release_id_or_manifest is None:
        return None, {"resolved": False, "requested": None, "fallback": "store_scan"}
    if isinstance(release_id_or_manifest, Mapping):
        return dict(release_id_or_manifest), {"resolved": True, "requested": "<manifest>",
                                              "fallback": None}
    release_id = str(release_id_or_manifest)
    path = store.root / "releases" / release_id / "manifest.json"
    if not path.exists():
        return None, {"resolved": False, "requested": release_id, "fallback": "store_scan",
                      "reason": f"release manifest {path} does not exist"}
    try:
        from ..storage.release import ReleaseManager

        manifest = ReleaseManager(store).load(release_id)
    except SynLabError as exc:
        return None, {"resolved": False, "requested": release_id, "fallback": "store_scan",
                      "reason": f"{exc.code}: {exc.message}"}
    return manifest, {"resolved": True, "requested": release_id, "fallback": None,
                      "manifest_hash": manifest.get("manifest_hash"),
                      "assets": len(manifest.get("assets", []))}


def build_pool(store: AssetStore, release_id_or_manifest: Any = None,
               spec_or_config: Any = None, *, with_features: bool = True) -> dict[str, Any]:
    """Build one frozen gallery/pool and return the audit dictionary.

    The result always carries ``ok``, ``distractor_isolated``, ``queries``, ``candidates`` and
    ``r2_edges`` (plus a ``metrics`` mirror for the acceptance harness), whether or not a
    gallery could actually be frozen.  Nothing is ever fabricated: an empty store yields
    ``ok=False`` with ``GALLERY_SIZE_PENDING``.
    """
    cfg = PoolConfig.from_any(spec_or_config)
    manifest, release_info = resolve_release(store, release_id_or_manifest)
    warnings: list[str] = []
    if not release_info["resolved"]:
        warnings.append(f"release not resolved ({release_info.get('reason', 'not given')}); "
                        f"falling back to a store-wide scan")

    records = collect_fragments(store, release=manifest)
    eligible = _eligible(records, cfg)
    index = RelationsIndex()
    index.set_members(sorted(records))
    for fid, rec in records.items():
        if not rec.verified:
            index.mark_unverified(fid)
    edge_counts = load_relations_into(
        index, store,
        release=manifest,
        splits=None if not cfg.exclude_training_lineages else
        [s for s in {r.split for r in records.values()} if s != "train"])

    order = _frozen_order(eligible, cfg)
    if cfg.scope == "DISTRACTOR_ONLY":
        order = [f for f in order if _is_distractor(eligible[f])]
    lineup = order[: int(cfg.size_target)] if order else []
    if not lineup:
        return _empty_audit(cfg, release_info, records, eligible, edge_counts, warnings)

    queries = _draw_queries(eligible, lineup, cfg, [release_info.get("manifest_hash", "")])
    if cfg.scope == "MATE_REMOVED":
        in_gallery, _ = _neighbour_map(index, lineup)
        drop = {n for q in queries for n in in_gallery.get(q, [])}
        lineup = [f for f in lineup if f not in drop]

    in_gallery, outside = _neighbour_map(index, lineup)
    distractor_lineages = sorted({eligible[f].lineage_id for f in lineup if _is_distractor(eligible[f])})
    gallery_lineages = sorted({eligible[f].lineage_id for f in lineup})
    training_lineages = sorted({rec.lineage_id for rec in records.values() if rec.split == "train"})
    overlap = sorted(set(distractor_lineages) & set(training_lineages))
    distractor_isolated = not overlap

    lineage_ids = sorted({eligible[f].lineage_id for f in lineup})
    query_entries = [_roster_entry(eligible, f, cfg, in_gallery) for f in queries]
    base_payload = {
        "pool_id": cfg.pool_id, "gallery_version": cfg.gallery_version, "scope": cfg.scope,
        "size_target": int(cfg.size_target), "fragment_ids": sorted(lineup),
        "queries": [q.query_id for q in query_entries],
        "edges": sorted(f"{a}|{b}|{e.kind}" for (a, b), e in index.items()),
        "split": cfg.split,
    }
    pool_hash = gallery_hash(base_payload)
    gallery = GallerySpec(
        pool_id=cfg.pool_id, gallery_version=cfg.gallery_version, scope=cfg.scope,  # type: ignore[arg-type]
        lineage_ids=lineage_ids, fragment_ids=list(lineup), size_target=int(cfg.size_target),
        split=cfg.split, hash=pool_hash,
        meta={"release": release_info, "nested_sizes": list(cfg.nested_sizes),
              "exclude_training_lineages": bool(cfg.exclude_training_lineages),
              "r2_edges": int(sum(len(v) for v in in_gallery.values()) // 2)})

    pool = RelationPool(
        gallery=gallery,
        fragments={fid: eligible[fid] for fid in lineup},
        index=index,
        roster=query_entries,
        historical_neighbours={fid: in_gallery.get(fid, []) for fid in lineup},
        gallery_distractor_only={fid for fid in lineup if _is_distractor(eligible[fid])},
        meta={"release": release_info, "query_per_mother": int(cfg.query_per_mother),
              "refinement_candidates": list(cfg.refinement_candidates),
              "top_k": list(cfg.top_k),
              "out_of_gallery_neighbours": {fid: outside.get(fid, []) for fid in lineup
                                            if outside.get(fid)},
              "distractor_isolated": bool(distractor_isolated),
              "distractor_overlap": overlap,
              "edge_counts_loaded": edge_counts,
              "portable_json": "PENDING"},
    )

    feature_report = {"attached": 0, "missing": len(lineup), "failed": []}
    if with_features:
        feature_report = attach_features(pool, store)
        if feature_report["missing"]:
            warnings.append(f"{feature_report['missing']} gallery fragments have no resolvable "
                            f"legal feature payload (evaluation is first-stage only)")

    variants = _scope_variants(eligible, index, lineup, queries, cfg, base_payload)
    variants["NESTED"] = {"pool_id": f"{cfg.pool_id}__nested",
                          "sizes": _nested_report(eligible, index, order, cfg, base_payload)}
    r2_edges = int(sum(len(v) for v in in_gallery.values()) // 2)
    stats = pool.stats()
    report: dict[str, Any] = {
        "ok": True,
        "status": "QA_PASSED" if release_info["resolved"] else "QA_PASSED_WITH_FALLBACK",
        "api_version": API_VERSION,
        "pool_id": cfg.pool_id,
        "gallery_version": cfg.gallery_version,
        "scope": cfg.scope,
        "hash": pool_hash,
        "distractor_isolated": bool(distractor_isolated),
        "distractor_lineages": distractor_lineages,
        "distractor_overlap": overlap,
        "isolation_basis": ("no distractor lineage is enrolled in training"
                            if distractor_lineages else
                            "no gallery_distractor_only lineage present in this gallery; "
                            "isolation holds vacuously (recorded, not claimed as evidence)"),
        "queries": len(query_entries),
        "queries_with_mates": sum(1 for q in query_entries if q.mate_present),
        "candidates": len(lineup),
        "r2_edges": r2_edges,
        "r1_edges": stats["r1_edges"],
        "tiny_contact_edges": stats["tiny_contact_edges"],
        "unknown_edges": stats["unknown_edges"],
        "explicit_edges": stats["explicit_edges"],
        "n2_materialised": False,
        "lineages": len(lineage_ids),
        "mothers": stats["mothers"],
        "events": stats["events"],
        "out_of_gallery_neighbours": sum(len(v) for v in outside.values()),
        "mate_absent_queries": sum(1 for q in query_entries if not q.mate_present),
        "release": release_info,
        "edge_counts_loaded": edge_counts,
        "features": feature_report,
        "variants": variants,
        "warnings": warnings,
        "stats": stats,
        "pool": pool,
        "gallery": gallery,
        "roster": query_entries,
    }
    report["metrics"] = {
        "pool_id": cfg.pool_id, "gallery_version": cfg.gallery_version, "scope": cfg.scope,
        "hash": pool_hash, "queries": len(query_entries), "candidates": len(lineup),
        "r2_edges": r2_edges, "r1_edges": stats["r1_edges"],
        "tiny_contact_edges": stats["tiny_contact_edges"],
        "unknown_edges": stats["unknown_edges"], "mothers": stats["mothers"],
        "lineages": len(lineage_ids), "mate_absent_queries": report["mate_absent_queries"],
        "distractor_isolated": bool(distractor_isolated),
        "features_attached": feature_report["attached"],
        "n2_materialised": False,
    }
    return report


def _roster_entry(records: Mapping[str, FragmentRecord], fragment_id: str, cfg: PoolConfig,
                  in_gallery: Mapping[str, Sequence[str]]) -> QueryRosterEntry:
    rec = records[fragment_id]
    neighbours = [n for n in in_gallery.get(fragment_id, []) if n != fragment_id]
    return QueryRosterEntry(
        query_id=f"q::{fragment_id}",
        lineage_cluster=rec.lineage_cluster,
        mother_id=rec.mother_id,
        fragment_id=fragment_id,
        split=rec.split or cfg.split,
        gallery_id=cfg.pool_id,
        historical_neighbours=list(neighbours),
        mate_present=bool(neighbours),
        status="FROZEN",
        applicability={"scope": cfg.scope, "gallery_version": cfg.gallery_version},
    )


def _empty_audit(cfg: PoolConfig, release_info: Mapping[str, Any],
                 records: Mapping[str, FragmentRecord], eligible: Mapping[str, FragmentRecord],
                 edge_counts: Mapping[str, int], warnings: list[str]) -> dict[str, Any]:
    reason = ("no committed clean_truth / label_bundle asset provides fragments for this "
              "gallery; generation must run first (plan 16.1: never borrow training pieces)")
    return {
        "ok": False,
        "status": "GALLERY_SIZE_PENDING",
        "api_version": API_VERSION,
        "pool_id": cfg.pool_id,
        "gallery_version": cfg.gallery_version,
        "scope": cfg.scope,
        "hash": "",
        "distractor_isolated": False,
        "queries": 0,
        "candidates": 0,
        "r2_edges": 0,
        "r1_edges": int(edge_counts.get("R1", 0)),
        "tiny_contact_edges": int(edge_counts.get("TINY_CONTACT", 0)),
        "unknown_edges": int(edge_counts.get("UNKNOWN", 0)),
        "explicit_edges": int(sum(edge_counts.values())),
        "n2_materialised": False,
        "lineages": 0,
        "mothers": 0,
        "events": 0,
        "mate_absent_queries": 0,
        "release": dict(release_info),
        "edge_counts_loaded": dict(edge_counts),
        "fragments_seen": len(records),
        "fragments_eligible": len(eligible),
        "features": {"attached": 0, "missing": 0, "failed": []},
        "variants": {},
        "warnings": warnings,
        "error": {"code": ErrorCode.GALLERY_SIZE_PENDING.value, "stage": "relations.build_pool",
                  "message": reason,
                  "measurements": {"fragments_seen": len(records),
                                   "fragments_eligible": len(eligible)}},
        "metrics": {"pool_id": cfg.pool_id, "queries": 0, "candidates": 0, "r2_edges": 0,
                    "gallery_size_pending": True, "n2_materialised": False},
        "pool": None,
        "gallery": None,
        "roster": [],
    }


# --------------------------------------------------------------------------------------
# persistence
# --------------------------------------------------------------------------------------
def pool_arrays(pool: RelationPool) -> dict[str, np.ndarray]:
    lineup = pool.lineup
    arrays = pool.index.to_arrays(lineup)
    arrays["fragment_ids"] = np.asarray(lineup, dtype="U160")
    folds = pool.lineage_of
    arrays["lineage_ids"] = np.asarray([folds[f] for f in lineup], dtype="U160")
    arrays["mother_ids"] = np.asarray([pool.mother_of[f] for f in lineup], dtype="U160")
    arrays["event_ids"] = np.asarray([pool.event_of[f] for f in lineup], dtype="U160")
    arrays["splits"] = np.asarray([pool.split_of[f] for f in lineup], dtype="U32")
    arrays["quality_tier"] = np.asarray([pool.quality_tier[f] for f in lineup], dtype=np.int8)
    arrays["verified"] = np.asarray([bool(pool.fragments[f].verified) for f in lineup], dtype=bool)
    arrays["is_tiny"] = np.asarray([bool(pool.fragments[f].is_tiny) for f in lineup], dtype=bool)
    queries = [q.fragment_id for q in pool.roster]
    arrays["query_fragment_ids"] = np.asarray(queries, dtype="U160")
    hist_ids: list[str] = []
    hist_offsets = [0]
    for query in queries:
        hist_ids.extend(pool.neighbours(query))
        hist_offsets.append(len(hist_ids))
    arrays["hist_ids"] = np.asarray(hist_ids, dtype="U160")
    arrays["hist_offsets"] = np.asarray(hist_offsets, dtype=np.int64)
    return arrays


def commit_pool(store: AssetStore, pool: RelationPool, *, lineage_id: str | None = None,
                split: str | None = None, ancestry: Sequence[str] = (),
                qa: Mapping[str, Any] | None = None) -> Any:
    """Persist the sparse pool under role ``relation_pool`` (never the N^2 relation table)."""
    arrays = pool_arrays(pool)
    meta = {
        "schema": POOL_SCHEMA,
        "api_version": API_VERSION,
        "gallery": {
            "pool_id": pool.pool_id, "gallery_version": pool.gallery_version,
            "scope": pool.scope, "lineage_ids": list(pool.gallery.lineage_ids),
            "size_target": int(pool.gallery.size_target), "split": pool.gallery.split,
            "hash": pool.hash,
        },
        "fragment_records": {fid: pool.fragments[fid].as_dict() for fid in pool.lineup},
        "roster": [_roster_dict(q) for q in pool.roster],
        "gallery_distractor_only": sorted(pool.gallery_distractor_only),
        "pool_meta": _jsonable(pool.meta),
        "relation_storage": "sparse_non_r0_edges_only",
        "n2_materialised": False,
    }
    record = store.commit_asset(
        role=ROLE_POOL, schema=SCHEMA_POOL, unit=UNIT_NONE, frame=FRAME_WORLD,
        payload=arrays, meta=meta, qa=dict(qa or {"ok": True, "n2_materialised": False}),
        ancestry=list(ancestry), lineage_id=lineage_id, split=split,
    )
    meta["asset_id"] = record.asset_id
    pool.meta["committed_asset"] = record.asset_id
    return record


def _roster_dict(entry: QueryRosterEntry) -> dict[str, Any]:
    return {
        "query_id": entry.query_id, "lineage_cluster": entry.lineage_cluster,
        "mother_id": entry.mother_id, "fragment_id": entry.fragment_id, "split": entry.split,
        "gallery_id": entry.gallery_id, "historical_neighbours": list(entry.historical_neighbours),
        "mate_present": bool(entry.mate_present), "status": entry.status,
        "applicability": dict(entry.applicability),
    }


def commit_roster(store: AssetStore, pool: RelationPool, *, lineage_id: str | None = None,
                  split: str | None = None, ancestry: Sequence[str] = ()) -> Any:
    return store.commit_asset(
        role=ROLE_ROSTER, schema=SCHEMA_ROSTER, unit=UNIT_NONE, frame=FRAME_WORLD,
        payload={"roster": [_roster_dict(q) for q in pool.roster], "pool_id": pool.pool_id,
                 "gallery_version": pool.gallery_version, "hash": pool.hash},
        meta={"pool_id": pool.pool_id, "queries": len(pool.roster),
              "frozen": True, "hash": pool.hash},
        qa={"ok": True, "frozen_query_ids": True}, ancestry=list(ancestry),
        lineage_id=lineage_id, split=split,
    )


def load_pool(store: AssetStore, asset_id: str) -> RelationPool:
    record = store.get_asset(asset_id)
    if record.role != ROLE_POOL:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"asset {asset_id} role {record.role} != {ROLE_POOL}",
                          stage="relations.load_pool")
    return pool_from_asset(store, record)


def pool_from_asset(store: AssetStore, record: Any) -> RelationPool:
    arrays = store.load_arrays(record.asset_id)
    if "fragment_ids" not in arrays:
        raise SynLabError(ErrorCode.ASSET_HASH_MISMATCH,
                          f"pool asset {record.asset_id} has no fragment_ids array",
                          stage="relations.pool_from_asset")
    meta = dict(record.meta or {})
    lineup = [str(x) for x in np.asarray(arrays["fragment_ids"]).tolist()]
    records_meta = dict(meta.get("fragment_records") or {})
    fragments: dict[str, FragmentRecord] = {}
    for fid in lineup:
        payload = dict(records_meta.get(fid) or {})
        fragments[fid] = FragmentRecord(
            fragment_id=fid, lineage_id=str(payload.get("lineage_id", "")),
            mother_id=str(payload.get("mother_id", "")), event_id=str(payload.get("event_id", "")),
            split=str(payload.get("split", "")), feature_ref=payload.get("feature_ref"),
            label_ref=payload.get("label_ref"), obs_ref=payload.get("obs_ref"),
            is_tiny=bool(payload.get("is_tiny", False)),
            quality_tier=int(payload.get("quality_tier", 0) or 0),
            verified=bool(payload.get("verified", True)))
    index = RelationsIndex.from_arrays(lineup, arrays)
    index.set_members(lineup)
    for fid in lineup:
        if not fragments[fid].verified:
            index.mark_unverified(fid)
    roster = [QueryRosterEntry(**entry) for entry in (meta.get("roster") or [])]
    hist: dict[str, list[str]] = {}
    hist_ids = [str(x) for x in np.asarray(arrays.get("hist_ids", np.zeros(0, dtype="U1"))).tolist()]
    offsets = np.asarray(arrays.get("hist_offsets", np.zeros(0, dtype=np.int64)), dtype=np.int64)
    query_ids = [str(x) for x in np.asarray(
        arrays.get("query_fragment_ids", np.zeros(0, dtype="U1"))).tolist()]
    for i, query in enumerate(query_ids):
        if i + 1 < offsets.size:
            hist[query] = hist_ids[int(offsets[i]):int(offsets[i + 1])]
    for fid in lineup:
        hist.setdefault(fid, [n for n in index.neighbours(fid)])
    gallery_meta = dict(meta.get("gallery") or {})
    gallery = GallerySpec(
        pool_id=str(gallery_meta.get("pool_id", "")),
        gallery_version=str(gallery_meta.get("gallery_version", "")),
        scope=str(gallery_meta.get("scope", "FULL")),  # type: ignore[arg-type]
        lineage_ids=list(gallery_meta.get("lineage_ids") or []),
        fragment_ids=lineup, size_target=int(gallery_meta.get("size_target", len(lineup))),
        split=str(gallery_meta.get("split", "")), hash=str(gallery_meta.get("hash", "")),
        meta={"source_asset": record.asset_id})
    return RelationPool(
        gallery=gallery, fragments=fragments, index=index, roster=roster,
        historical_neighbours=hist,
        gallery_distractor_only={str(f) for f in (meta.get("gallery_distractor_only") or [])},
        meta={**dict(meta.get("pool_meta") or {}), "source_asset": record.asset_id})


def save_pool_json(pool: RelationPool, path: str | Path, *,
                   limit: int = PORTABLE_JSON_LIMIT) -> dict[str, Any]:
    """Write the portable pool artifact consumed by ``candidate_pool_ref``."""
    path = Path(path)
    if len(pool.lineup) > limit:
        return {"path": str(path), "written": False, "status": "SKIPPED_SIZE",
                "reason": f"{len(pool.lineup)} fragments exceed the portable JSON limit {limit}; "
                          f"the committed pool asset stays canonical"}
    payload = {
        "schema": POOL_SCHEMA,
        "pool_id": pool.pool_id,
        "gallery_version": pool.gallery_version,
        "scope": pool.scope,
        "split": pool.gallery.split,
        "hash": pool.hash,
        "size_target": int(pool.gallery.size_target),
        "lineage_ids": list(pool.gallery.lineage_ids),
        "fragment_ids": pool.lineup,
        "fragments": {fid: pool.fragments[fid].as_dict() for fid in pool.lineup},
        "edges": pool.index.to_json_records(),
        "historical_neighbours": {fid: pool.neighbours(fid) for fid in pool.lineup},
        "roster": [_roster_dict(q) for q in pool.roster],
        "gallery_distractor_only": sorted(pool.gallery_distractor_only),
        "meta": _jsonable(pool.meta),
        "relation_storage": "sparse_non_r0_edges_only",
        "n2_materialised": False,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
                    encoding="utf-8")
    return {"path": str(path), "written": True, "status": "OK", "fragments": len(pool.lineup),
            "edges": len(payload["edges"])}


def save_roster_json(pool: RelationPool, path: str | Path) -> dict[str, Any]:
    path = Path(path)
    payload = {"schema": "synlab.roster.v1", "pool_id": pool.pool_id,
               "gallery_version": pool.gallery_version, "hash": pool.hash,
               "queries": [_roster_dict(q) for q in pool.roster]}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
                    encoding="utf-8")
    return {"path": str(path), "written": True, "queries": len(pool.roster)}


def load_pool_json(path: str | Path, *, features: Mapping[str, dict] | None = None
                   ) -> tuple[RelationPool, list[dict[str, Any]]]:
    """Load a portable pool artifact (no store needed) plus its raw roster rows."""
    path = Path(path)
    if not path.exists():
        raise SynLabError(ErrorCode.INPUT_UNAVAILABLE, f"pool artifact not found: {path}",
                          stage="relations.load_pool_json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    lineup = [str(f) for f in payload.get("fragment_ids") or []]
    fragments: dict[str, FragmentRecord] = {}
    for fid in lineup:
        raw = dict((payload.get("fragments") or {}).get(fid) or {})
        fragments[fid] = FragmentRecord(
            fragment_id=fid, lineage_id=str(raw.get("lineage_id", "")),
            mother_id=str(raw.get("mother_id", "")), event_id=str(raw.get("event_id", "")),
            split=str(raw.get("split", "")), feature_ref=raw.get("feature_ref"),
            label_ref=raw.get("label_ref"), obs_ref=raw.get("obs_ref"),
            is_tiny=bool(raw.get("is_tiny", False)),
            quality_tier=int(raw.get("quality_tier", 0) or 0),
            verified=bool(raw.get("verified", True)))
    index = RelationsIndex()
    index.set_members(lineup)
    for edge in payload.get("edges") or []:
        index.add(str(edge.get("a")), str(edge.get("b")), str(edge.get("kind", "R0")),
                  interface_id=edge.get("interface_id"),
                  area_mm2=float(edge.get("area_mm2", 0.0) or 0.0),
                  valid=bool(edge.get("valid", True)),
                  loss_mask=bool(edge.get("loss_mask", True)))
    for fid, rec in fragments.items():
        if not rec.verified:
            index.mark_unverified(fid)
    roster_rows = list(payload.get("roster") or [])
    roster = [QueryRosterEntry(**row) for row in roster_rows]
    hist = {str(k): [str(x) for x in v] for k, v in
            (payload.get("historical_neighbours") or {}).items()}
    gallery = GallerySpec(
        pool_id=str(payload.get("pool_id", path.stem)),
        gallery_version=str(payload.get("gallery_version", "v1")),
        scope=str(payload.get("scope", "FULL")),  # type: ignore[arg-type]
        lineage_ids=list(payload.get("lineage_ids") or []), fragment_ids=lineup,
        size_target=int(payload.get("size_target", len(lineup))),
        split=str(payload.get("split", "dev")), hash=str(payload.get("hash", "")),
        meta={"artifact": str(path)})
    pool = RelationPool(gallery=gallery, fragments=fragments, index=index, roster=roster,
                        historical_neighbours=hist,
                        features=dict(features or {}),
                        gallery_distractor_only={str(f) for f in
                                                 (payload.get("gallery_distractor_only") or [])},
                        meta={**dict(payload.get("meta") or {}), "artifact": str(path)})
    return pool, roster_rows


def load_roster_json(path: str | Path) -> list[dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        raise SynLabError(ErrorCode.INPUT_UNAVAILABLE, f"roster artifact not found: {path}",
                          stage="relations.load_roster_json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return list(payload.get("queries") or [])


# --------------------------------------------------------------------------------------
# config-driven build (CLI / evidence chain)
# --------------------------------------------------------------------------------------
def build_pool_from_config(store: AssetStore, release: str, config_path: str | Path) -> dict[str, Any]:
    """``synlab build-pool --release --config``: build, freeze and persist one gallery."""
    path = Path(config_path)
    document = load_document(path)
    cfg = PoolConfig.from_mapping(document)
    report = build_pool(store, release, cfg)
    report["config"] = {"path": str(path), "hash": hash_json(_jsonable(document)),
                        "pool_id": cfg.pool_id, "scope": cfg.scope,
                        "nested_sizes": list(cfg.nested_sizes)}
    if not report["ok"]:
        return report

    pool: RelationPool = report["pool"]
    asset = commit_pool(store, pool, split=cfg.split)
    roster_asset = commit_roster(store, pool, split=cfg.split, ancestry=[asset.asset_id])
    pools_dir = store.root / "pools"
    portable = save_pool_json(pool, pools_dir / f"{cfg.pool_id}.json")
    roster_file = save_roster_json(pool, pools_dir / f"{cfg.pool_id}_queries.json")
    report["artifacts"] = {
        "pool_asset": asset.asset_id, "roster_asset": roster_asset.asset_id,
        "portable_json": portable, "roster_json": roster_file,
    }
    report["pool_id"] = cfg.pool_id
    report["metrics"]["pool_asset"] = asset.asset_id
    report["metrics"]["portable_json"] = portable.get("status")
    report.pop("pool", None)
    return report


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


__all__ = [
    "API_VERSION", "PORTABLE_JSON_LIMIT", "PoolConfig", "build_pool", "build_pool_from_config",
    "commit_pool", "commit_roster", "load_pool", "pool_from_asset", "pool_arrays",
    "save_pool_json", "save_roster_json", "load_pool_json", "load_roster_json",
    "resolve_release", "sample_training_batch", "mine_hard_negatives",
]
