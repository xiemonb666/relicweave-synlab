"""Shared A12 test fixtures for training / diagnostics / episode modules.

These fixtures are **self-contained**: the parallel modules ``synlab.observe`` and
``synlab.relations`` are not present in this checkout yet, so every upstream object is
reproduced here with the *same field names and units* the frozen contracts use
(``GallerySpec`` / ``QueryRosterEntry`` from ``synlab.schemas.runtime`` and the
``a12.obs.v1`` feature payload of ``synlab.observe.api.adapt_observed_features``).

Swapping these fixtures for the real upstream modules must not require any change inside
``synlab/training``, ``synlab/diagnostics`` or ``synlab/episodes``: all three consume them
through structural duck typing (see ``docs/a12/training_diagnostics_episodes.md`` §2).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:  # pragma: no cover - import guard for direct execution
    sys.path.insert(0, str(REPO_ROOT))

from synlab.schemas.runtime import GallerySpec, QueryRosterEntry  # noqa: E402

# --------------------------------------------------------------------------------------
# Feature bundle fixture (a12.obs.v1)
# --------------------------------------------------------------------------------------

TOKEN_DIM = 256
QUALITY_CHANNELS = 4
PRESENCE_CHANNELS = 3


def make_feature_payload(
    fragment_id: str,
    *,
    n_views: int = 3,
    image_size: tuple[int, int] = (12, 12),
    n_tokens: int = 24,
    max_tokens: int | None = None,
    n_points: int = 16,
    n_regions: int = 2,
    rng: np.random.Generator | None = None,
    scale_valid: bool = True,
    seed_offset: int = 0,
    quality_tier: int = 0,
) -> dict:
    """One ``a12.obs.v1`` payload, shaped exactly like ``adapt_observed_features`` output."""
    rng = rng or np.random.default_rng(0)
    height, width = image_size
    max_tokens = max(max_tokens or n_tokens, n_tokens)

    global_rgb = rng.random((n_views, 3, height, width), dtype=np.float32)
    global_valid = np.ones((n_views,), dtype=bool)
    pixel_valid = rng.random((n_views, height, width)) > 0.15

    local_tokens = np.zeros((max_tokens, TOKEN_DIM), dtype=np.float32)
    token_valid = np.zeros((max_tokens,), dtype=bool)
    token_view = np.full((max_tokens,), -1, dtype=np.int32)
    token_pixel = np.full((max_tokens, 2), -1, dtype=np.int32)
    token_modality = np.full((max_tokens,), -1, dtype=np.int32)
    token_source = np.full((max_tokens,), -1, dtype=np.int32)
    token_retrieval = np.full((max_tokens,), -1, dtype=np.int32)

    base = rng.normal(size=(TOKEN_DIM,)).astype(np.float32)
    for i in range(n_tokens):
        view = i % n_views
        # two source groups: even/odd tokens come from different captures
        src = 0 if view % 2 == 0 else 1
        local_tokens[i] = base * 0.5 + rng.normal(scale=0.3, size=(TOKEN_DIM,)).astype(np.float32)
        token_valid[i] = True
        token_view[i] = view
        token_pixel[i] = (int(rng.integers(0, height)), int(rng.integers(0, width)))
        token_modality[i] = 0
        token_source[i] = src
    for i in range(n_tokens, max_tokens):
        token_retrieval[i] = i  # over-quota token -> retrieval index back into the full table

    points = rng.normal(size=(n_points, 3)).astype(np.float32)
    point_valid = np.ones((n_points,), dtype=bool)
    normals = rng.normal(size=(n_points, 3)).astype(np.float32)
    normals /= np.linalg.norm(normals, axis=1, keepdims=True)
    normal_valid = np.ones((n_points,), dtype=bool)

    quality = rng.random((n_regions, QUALITY_CHANNELS), dtype=np.float32)
    quality_valid = np.ones((n_regions, QUALITY_CHANNELS), dtype=bool)
    presence = rng.random((PRESENCE_CHANNELS,), dtype=np.float32)
    presence_valid = np.ones((PRESENCE_CHANNELS,), dtype=bool)

    return {
        "schema": "a12.obs.v1",
        "fragment_id": fragment_id,
        "obs_version": 0 + seed_offset,
        "global_rgb": global_rgb,
        "global_valid": global_valid,
        "pixel_valid": pixel_valid,
        "local_tokens": local_tokens,
        "token_valid": token_valid,
        "token_view": token_view,
        "token_pixel": token_pixel,
        "token_modality": token_modality,
        "token_source": token_source,
        "token_retrieval": token_retrieval,
        "tokens_total": np.int32(max_tokens),
        "points": points,
        "point_valid": point_valid,
        "normals": normals,
        "normal_valid": normal_valid,
        "quality": quality,
        "quality_valid": quality_valid,
        "presence": presence,
        "presence_valid": presence_valid,
        "scale_valid": bool(scale_valid),
        "quality_tier": int(quality_tier),
        "roi_area_px": np.array([float(np.count_nonzero(pixel_valid[k])) for k in range(n_views)],
                                dtype=np.float32),
    }


def make_feature_payloads(fragment_ids, *, rng=None, **kwargs) -> dict[str, dict]:
    rng = rng or np.random.default_rng(7)
    return {fid: make_feature_payload(fid, rng=rng, **kwargs) for fid in fragment_ids}


# --------------------------------------------------------------------------------------
# Pool fixture (structural stand-in for synlab.relations.api.build_pool)
# --------------------------------------------------------------------------------------

RELATION_CODES = {"R0": 0, "R1": 1, "R2": 2, "TINY_CONTACT": 3, "UNKNOWN": 4}
RELATION_NAMES = {v: k for k, v in RELATION_CODES.items()}


@dataclass
class FixturePool:
    """Minimal in-memory relation pool carrying the frozen ``GallerySpec`` fields.

    ``synlab.relations.api.sample_training_batch`` is expected to return a dict with the
    same keys as :meth:`sample_training_batch`.
    """

    gallery: GallerySpec
    fragment_ids: list[str]
    lineage_of: dict[str, str]
    relations: dict[tuple[str, str], str]          # frozen opaque pair key -> relation name
    historical_neighbours: dict[str, list[str]]    # N_G(q) minus q
    quality_tier: dict[str, int] = field(default_factory=dict)
    split_of: dict[str, str] = field(default_factory=dict)
    mate_absent: set[str] = field(default_factory=set)
    lineage_cluster_of: dict[str, str] = field(default_factory=dict)
    mother_of: dict[str, str] = field(default_factory=dict)
    features: dict[str, dict] = field(default_factory=dict)
    gallery_distractor_only: set[str] = field(default_factory=set)
    meta: dict = field(default_factory=dict)

    # -- frozen interface used by training / diagnostics -------------------------------
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
    def lineup(self) -> list[str]:
        return list(self.gallery.fragment_ids)

    def relation(self, a: str, b: str) -> str:
        if a == b:
            return "SELF"
        return self.relations.get((a, b), self.relations.get((b, a), "UNKNOWN"))

    def neighbours(self, fragment_id: str) -> list[str]:
        """``N_G(q)``: historical R2 neighbours inside this gallery, excluding q itself."""
        return [f for f in self.historical_neighbours.get(fragment_id, []) if f != fragment_id]

    def candidate_ids(self, fragment_id: str) -> list[str]:
        return [f for f in self.lineup if f != fragment_id]

    def roster_entry(self, fragment_id: str, *, gallery_id: str | None = None,
                     split: str = "dev") -> QueryRosterEntry:
        neighbours = self.neighbours(fragment_id)
        return QueryRosterEntry(
            query_id=f"q::{fragment_id}",
            lineage_cluster=self.lineage_cluster_of.get(fragment_id, self.lineage_of.get(fragment_id, "L?")),
            mother_id=self.mother_of.get(fragment_id, "m?"),
            fragment_id=fragment_id,
            split=self.split_of.get(fragment_id, split),
            gallery_id=gallery_id or self.gallery.pool_id,
            historical_neighbours=list(neighbours),
            mate_present=bool(neighbours),
            status="FROZEN",
            applicability={},
        )

    def sample_training_batch(self, rng: np.random.Generator, *, queries: int = 2,
                              positive_limit: int = 2, negative_limit: int = 8) -> dict:
        """Stand-in for ``relations.api.sample_training_batch``.

        The exclusion rules are the frozen ones (plan 18.2 / 18.3): a *sampled* query's
        positives are its confirmed R2 neighbours; negatives may only be confirmed R1/R0
        that are neither historical R2 nor UNKNOWN nor TINY nor the query itself.
        """
        qs = [f for f in self.lineup if self.historical_neighbours.get(f)]
        if not qs:
            qs = list(self.lineup)
        q_sel = list(rng.choice(qs, size=min(queries, len(qs)), replace=False))
        rows = []
        for q in q_sel:
            pos = [n for n in self.neighbours(q) if n in self.lineup]
            neg_pool = [c for c in self.candidate_ids(q)
                        if c not in self.neighbours(q)
                        and self.relation(q, c) in ("R1", "R0")]
            neg = list(rng.permutation(neg_pool)[:negative_limit]) if neg_pool else []
            rows.append({"query": q, "positives": pos[:positive_limit], "negatives": neg})
        return {"pool_id": self.pool_id, "rows": rows}

    def stats(self) -> dict:
        n_edges = sum(1 for k, v in self.relations.items() if v == "R2")
        return {
            "pool_id": self.pool_id,
            "gallery_version": self.gallery_version,
            "hash": self.hash,
            "fragments": len(self.lineup),
            "lineages": len({self.lineage_of.get(f, "?") for f in self.lineup}),
            "r2_edges": n_edges,
            "mate_absent": len(self.mate_absent),
        }


def build_fixture_pool(
    *,
    lineages: dict[str, list[str]],
    r2: dict[str, list[str]] | None = None,
    r1: list[tuple[str, str]] | None = None,
    tiny: list[tuple[str, str]] | None = None,
    unknown: list[tuple[str, str]] | None = None,
    quality_tier: dict[str, int] | None = None,
    split_of: dict[str, str] | None = None,
    mate_absent: set[str] | None = None,
    pool_id: str = "pool_fixture_v1",
    scope: str = "FULL",
    mother_prefix: str = "m",
    with_features: bool = False,
    token_kwargs: dict | None = None,
) -> FixturePool:
    """Deterministic pool builder.

    ``r2`` maps one fragment to its confirmed R2 neighbours (symmetric closure applied).
    ``mate_absent`` defaults to every fragment with no R2 edge.
    """
    fragment_ids: list[str] = []
    lineage_of: dict[str, str] = {}
    lineage_cluster_of: dict[str, str] = {}
    mother_of: dict[str, str] = {}
    for lineage_id, frags in lineages.items():
        for frag in frags:
            fragment_ids.append(frag)
            lineage_of[frag] = lineage_id
            lineage_cluster_of[frag] = lineage_id
            mother_of[frag] = f"{mother_prefix}:{lineage_id}"

    relations: dict[tuple[str, str], str] = {}
    hist: dict[str, list[str]] = {f: [] for f in fragment_ids}
    for a, nb in (r2 or {}).items():
        for b in nb:
            if a == b or a not in lineage_of or b not in lineage_of:
                continue
            relations[(a, b)] = "R2"
            relations[(b, a)] = "R2"
            if b not in hist[a]:
                hist[a].append(b)
            if a not in hist[b]:
                hist[b].append(a)
    for pairs, name in ((r1, "R1"), (tiny, "TINY_CONTACT"), (unknown, "UNKNOWN")):
        for a, b in pairs or []:
            relations[(a, b)] = name
            relations[(b, a)] = name
    for a in fragment_ids:
        for b in fragment_ids:
            if a != b and (a, b) not in relations:
                relations[(a, b)] = "R0"

    for f in fragment_ids:
        hist[f] = sorted(hist[f])

    absent = set(mate_absent) if mate_absent is not None else {f for f in fragment_ids if not hist[f]}

    features: dict[str, dict] = {}
    if with_features:
        f_rng = np.random.default_rng(11)
        for f in fragment_ids:
            features[f] = make_feature_payload(
                f, rng=f_rng, quality_tier=(quality_tier or {}).get(f, 0),
                **(token_kwargs or {}),
            )

    gallery = GallerySpec(
        pool_id=pool_id,
        gallery_version="gal_v1",
        scope=scope,
        lineage_ids=sorted(lineages),
        fragment_ids=list(fragment_ids),
        size_target=len(fragment_ids),
        split="dev",
        hash=f"sha256:fixture-{pool_id}",
        meta={"source": "tests/a12/_fixtures.py"},
    )
    return FixturePool(
        gallery=gallery,
        fragment_ids=fragment_ids,
        lineage_of=lineage_of,
        relations=relations,
        historical_neighbours=hist,
        quality_tier=dict(quality_tier or {}),
        split_of=dict(split_of or {}),
        mate_absent=absent,
        lineage_cluster_of=lineage_cluster_of,
        mother_of=mother_of,
        features=features,
        gallery_distractor_only=set(),
        meta={"scope": scope},
    )


# --------------------------------------------------------------------------------------
# Synthetic retrieval task with a known separable structure (toy fit checks)
# --------------------------------------------------------------------------------------

def make_separable_retrieval_fixture(*, n_clusters: int = 4, per_cluster: int = 3,
                                     dim: int = 32, spread: float = 0.05, seed: int = 3):
    """Fragments whose R2 mates share a class centre; every other fragment does not.

    Returns ``(payloads, labels)`` where ``labels[fid]['R2']`` is the confirmed neighbour
    set.  A correctly trained dual tower must move Hit@1 well above the 1/(n-1) chance.
    """
    rng = np.random.default_rng(seed)
    centres = rng.normal(size=(n_clusters, dim)).astype(np.float32)
    payloads: dict[str, dict] = {}
    labels: dict[str, dict] = {}
    lineage_of: dict[str, str] = {}
    lineages: dict[str, list[str]] = {}
    for c in range(n_clusters):
        members = []
        for k in range(per_cluster):
            fid = f"frag{c}_{k}"
            members.append(fid)
            vec = centres[c] + rng.normal(scale=spread, size=(dim,)).astype(np.float32)
            payloads[fid] = {"feature": vec, "fragment_id": fid}
        for fid in members:
            labels[fid] = {"R2": [m for m in members if m != fid]}
            lineage_of[fid] = f"lin{c}"
        lineages[f"lin{c}"] = members
    return payloads, labels, lineages


__all__ = [
    "REPO_ROOT", "TOKEN_DIM", "QUALITY_CHANNELS", "PRESENCE_CHANNELS",
    "RELATION_CODES", "RELATION_NAMES",
    "make_feature_payload", "make_feature_payloads",
    "FixturePool", "build_fixture_pool",
    "make_separable_retrieval_fixture",
]
