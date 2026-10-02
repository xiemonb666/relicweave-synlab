"""Loader probe: read a real training package and build a real training batch from it.

This is the "the loader really reads it" check.  It does **not** synthesise anything: it
reads the packaged ObsPack RGB shards, geometry shards, token cache, relation table and
labels, assembles the ``a12.obs.v1`` payload form that
:meth:`synlab.training.adapter.FeatureBundle.from_dict` consumes, and then builds a real
:class:`~synlab.training.batch.TrainingBatch` through
:func:`synlab.training.batch.build_training_batch`.

Two integration gaps are closed **here**, in the offline reader, rather than by changing the
frozen tensor contract:

``local_tokens``
    ``observe.features.adapt_observed_features`` returns *grouped* features
    (``point_cloud.xyz``, ``normal_field.normals``, ...) plus ``view_tokens``; the tensor
    contract consumes a flat ``local_tokens`` block.  The probe builds that block from the
    packaged token cache (which is derived from the ObsPack RGB tiles only) and keeps the
    flat per-point geometry beside it.  The contract itself is untouched.
``relation_pool``
    :class:`~synlab.training.sampler.ShardedIterableDataset` needs a *frozen* pool as its
    cursor-replay unit.  The online pool lives in the asset store; an offline consumer has
    only the exported ``relations.parquet``.  :class:`ExportedRelationPool` is the minimal
    adapter over that table and it is deliberately conservative: a pair that is not in the
    table is ``UNKNOWN`` and unconfirmed, so it can never become a legal negative.

The report is written to ``data/a12/reports/loader_probe.json`` (or ``--out``) and always
carries ``ok``, the batch shapes, the real denominator and the failure reason.
"""

from __future__ import annotations

import json
import time
import traceback
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from ..errors import ErrorCode, SynLabError
from ..roles import FORBIDDEN_FEATURE_FIELDS
from ..storage.export import (
    EXCLUDED_NEGATIVE_KINDS,
    NEGATIVE_KINDS,
    TOKEN_DIM,
    TrainingPackage,
    _jsonable,
)
from ..training.adapter import FEATURE_SCHEMA, FeatureBundle
from ..training.batch import build_training_batch, negative_audit

PROBE_SCHEMA = "synlab.loader_probe.v1"

#: Feature-container keys that must never be produced by a loader.
FORBIDDEN_PAYLOAD_KEYS = frozenset(FORBIDDEN_FEATURE_FIELDS) | {
    "relation", "labels_relation", "R2", "historical_R2", "neg_mask", "pos_mask",
    "quality_target", "corr_weight", "split", "lineage_id", "lineage_cluster",
}


class ExportedRelationPool:
    """Minimal frozen-pool adapter over an exported relation table.

    Only pairs present in the table with a *confirmed* relation are returned; everything else
    is ``UNKNOWN`` and unconfirmed.  ``R2``/``TINY``/``UNKNOWN`` pairs are never offered as
    ordinary negatives.
    """

    def __init__(self, rows: Sequence[Mapping[str, Any]], *, pool_id: str = "exported",
                 quality_tier: Mapping[str, int] | None = None,
                 mother_of: Mapping[str, str] | None = None,
                 event_of: Mapping[str, str] | None = None):
        self.pool_id = str(pool_id)
        self._kinds: dict[tuple[str, str], str] = {}
        self._confirmed: dict[tuple[str, str], bool] = {}
        self._neighbours: dict[str, set[str]] = {}
        self._r2: dict[str, set[str]] = {}
        #: maps (not methods), matching ``relations.gallery.RelationPool``: the training batch
        #: reads ``pool.quality_tier.get(fid, 0)`` and ``dict(pool.lineage_cluster_of)``.
        self.quality_tier: dict[str, int] = dict(quality_tier or {})
        self.mother_of: dict[str, str] = dict(mother_of or {})
        self.event_of: dict[str, str] = dict(event_of or {})
        self.lineage_cluster_of: dict[str, str] = {}
        self.split_of: dict[str, str] = {}
        for row in rows:
            query = str(row.get("query", ""))
            candidate = str(row.get("candidate", ""))
            if not query or not candidate:
                continue
            kind = str(row.get("kind", "UNKNOWN"))
            # The exported table is the authoritative, deduplicated pair list (the exporter
            # already resolved pool-vs-truth disagreement and records it in
            # ``superseded_relations``).  The adapter still indexes both directions, because
            # relations are symmetric and a consumer may ask either way round.
            self._kinds[(query, candidate)] = kind
            self._kinds.setdefault((candidate, query), kind)
            confirmed = bool(row.get("valid", False)) and kind in NEGATIVE_KINDS
            self._confirmed[(query, candidate)] = confirmed
            self._confirmed.setdefault((candidate, query), confirmed)
            if kind == "R2":
                self._r2.setdefault(query, set()).add(candidate)
                self._r2.setdefault(candidate, set()).add(query)
            if confirmed:
                self._neighbours.setdefault(query, set()).add(candidate)
                self._neighbours.setdefault(candidate, set()).add(query)
            lineage = str(row.get("lineage_cluster", "") or "")
            split = str(row.get("split", "") or "")
            if lineage:
                self.lineage_cluster_of.setdefault(query, lineage)
                self.lineage_cluster_of.setdefault(candidate, lineage)
            if split:
                self.split_of.setdefault(query, split)
                self.split_of.setdefault(candidate, split)

    # ------------------------------------------------------------------ pool protocol
    def relation(self, a: str, b: str) -> str:
        return self._kinds.get((str(a), str(b)), "UNKNOWN")

    def neighbours(self, fragment_id: str) -> set[str]:
        """Historical R2 mate set -- the meaning the pool protocol gives this method.

        ``training.batch`` reads ``neighbours(q)`` as the *mate* set when it checks that a
        negative is not a historical R2 pair.  Returning the confirmed R1/R0 set here made
        every legal negative look like a mate and tripped the anti-shortcut guard for all 55
        queries of the exported package; the three other pool implementations in the repo
        (``training.sampler.PoolIndex``, ``training.smoke.TrainingPoolView``,
        ``relations.gallery.RelationPool``) all define it as the mate set.
        """
        return self.mates(fragment_id)

    def mates(self, fragment_id: str) -> set[str]:
        return set(self._r2.get(str(fragment_id), set()))

    def legal_negatives(self, fragment_id: str) -> set[str]:
        """Confirmed R1/R0 candidates; deliberately NOT what ``neighbours`` returns."""
        return set(self._neighbours.get(str(fragment_id), set()))

    def confirmed(self, a: str, b: str) -> bool:
        return bool(self._confirmed.get((str(a), str(b)), False))

    def history_exclusions(self, fragment_id: str) -> set[str]:
        return self.mates(fragment_id)

    def candidate_ids(self, fragment_id: str) -> list[str]:
        known = {a for a, _ in self._kinds} | {b for _, b in self._kinds}
        return sorted(f for f in known if f != str(fragment_id))

    def legal_pool(self, fragment_id: str, *, relation: str | None = None) -> list[str]:
        wanted = {relation} if relation else set(NEGATIVE_KINDS)
        return sorted(cid for cid in self._neighbours.get(str(fragment_id), set())
                      if self.relation(fragment_id, cid) in wanted)

    def assert_legal_negative(self, query_id: str, candidate_id: str) -> None:
        kind = self.relation(query_id, candidate_id)
        if kind not in NEGATIVE_KINDS or not self.confirmed(query_id, candidate_id):
            raise SynLabError(
                ErrorCode.LEAKAGE_DETECTED,
                f"{candidate_id} ({kind}) is not a legal negative of {query_id}",
                stage="qc.loader_probe.ExportedRelationPool.assert_legal_negative",
            )

    # ------------------------------------------------------------------ introspection
    def kind_histogram(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for (a, b), kind in self._kinds.items():
            if a < b:
                out[kind] = out.get(kind, 0) + 1
        return out

    def r2_closure(self) -> dict[str, Any]:
        """Every R2 edge must name two fragments that are both in the gallery."""
        problems = []
        for query, candidates in sorted(self._r2.items()):
            for candidate in sorted(candidates):
                if self.relation(query, candidate) != "R2":
                    problems.append(f"{query}|{candidate} asymmetric R2")
                if self.relation(candidate, query) != "R2":
                    problems.append(f"{candidate}|{query} missing reverse R2")
        return {"ok": not problems, "problems": problems,
                "edges": int(sum(len(v) for v in self._r2.values()) // 2),
                "fragments_with_mates": int(sum(1 for v in self._r2.values() if v))}


def load_features(package: TrainingPackage, fragment_ids: Sequence[str], *,
                  token_budget: int | None = None) -> dict[str, dict[str, Any]]:
    """Assemble the ``a12.obs.v1`` payload form from the packaged shards.

    A fragment the release models but does not observe (the unobserved mate of a shared-cut
    event) is returned as an **absent** row: every validity mask is False, its token block is
    empty and ``tokens_total`` is 0.  It must never be dressed up as a valid observation, and
    the loader reports the split between observed and absent rows.
    """
    payloads: dict[str, dict[str, Any]] = {}
    available = set(package.observation_index().get("rows", {}))
    for fragment_id in fragment_ids:
        if fragment_id in available:
            payloads[fragment_id] = _observed_payload(package, fragment_id,
                                                      token_budget=token_budget)
        else:
            payloads[fragment_id] = _absent_payload()
    return payloads


def _absent_payload() -> dict[str, Any]:
    """A modelled-but-unobserved fragment: present for indexing, invalid by every mask."""
    return {
        "schema": FEATURE_SCHEMA,
        "global_rgb": np.zeros((1, 3, 1, 1), dtype=np.float32),
        "global_valid": np.zeros((1,), dtype=bool),
        "pixel_valid": np.zeros((1, 1, 1), dtype=bool),
        "points": np.zeros((0, 3), dtype=np.float32),
        "point_valid": np.zeros((0,), dtype=bool),
        "normals": np.zeros((0, 3), dtype=np.float32),
        "normal_valid": np.zeros((0,), dtype=bool),
        "local_tokens": np.zeros((0, TOKEN_DIM), dtype=np.float32),
        "token_valid": np.zeros((0,), dtype=bool),
        "token_view": np.zeros((0,), dtype=np.int32),
        "token_modality": np.zeros((0,), dtype=np.int32),
        "token_source": np.zeros((0,), dtype=np.int32),
        "tokens_total": np.int32(0),
        "quality": np.zeros((1, 1), dtype=np.float32),
        "quality_valid": np.zeros((1, 1), dtype=bool),
        "presence": np.zeros((1,), dtype=np.float32),
        "presence_valid": np.zeros((1,), dtype=bool),
        "scale_valid": False,
        "obs_version": np.int32(0),
        "token_budget": TOKEN_DIM,
    }


def _observed_payload(package: TrainingPackage, fragment_id: str, *,
                      token_budget: int | None) -> dict[str, Any]:
    obs = package.read_observation(fragment_id)
    geometry = package.read_geometry(fragment_id)
    tokens = package.read_tokens(fragment_id)
    rgb = np.asarray(obs["rgb"], dtype=np.uint8)
    valid = np.asarray(obs["valid"], dtype=bool)
    if rgb.max(initial=0) > 1:
        rgb_f = rgb.astype(np.float32) / 255.0
    else:
        rgb_f = rgb.astype(np.float32)
    n_tokens = int(np.asarray(tokens["tokens"]).shape[0])
    # S7: the fragment's measured OBS_EST observation-quality channels, when the package carries
    # them.  They used to be hard-coded to ``zeros((1, 1))`` here, so ``FeatureBundle.quality``
    # (the tensor the model's quality head reads) was all-zero for every package.  A fragment with
    # no measurement keeps a *masked* row -- validity False -- so "not measured" and "measured 0"
    # stay distinguishable.
    quality_row, quality_valid_row, quality_provenance = _quality_row(package, fragment_id)
    payload = {
        "schema": FEATURE_SCHEMA,
        "global_rgb": np.transpose(rgb_f, (0, 3, 1, 2)),          # [V,3,H,W]
        "global_valid": np.asarray([bool(v.any()) for v in valid], dtype=bool),
        "pixel_valid": valid,
        "points": np.asarray(geometry["points"], dtype=np.float32),
        "point_valid": np.asarray(geometry["point_valid"], dtype=bool),
        "normals": np.asarray(geometry["normals"], dtype=np.float32),
        "normal_valid": np.asarray(geometry["normal_valid"], dtype=bool),
        "local_tokens": np.asarray(tokens["tokens"], dtype=np.float32),
        "token_valid": np.asarray(tokens["token_valid"], dtype=bool),
        "token_view": np.asarray(tokens["token_view"], dtype=np.int32),
        "token_modality": np.zeros(n_tokens, dtype=np.int32),
        "token_source": np.zeros(n_tokens, dtype=np.int32),
        "tokens_total": np.int32(n_tokens),
        "quality": quality_row,
        "quality_valid": quality_valid_row,
        "quality_provenance": quality_provenance,
        "presence": np.zeros((1,), dtype=np.float32),
        "presence_valid": np.zeros((1,), dtype=bool),
        "scale_valid": bool(np.asarray(geometry["scale_valid"], dtype=bool).any()),
        "obs_version": np.int32(1),
        "token_budget": int(token_budget or n_tokens),
    }
    leaked = sorted(FORBIDDEN_PAYLOAD_KEYS.intersection(payload.keys()))
    if leaked:
        raise SynLabError(ErrorCode.LEAKAGE_DETECTED,
                          f"loader payload {fragment_id} carries {leaked}",
                          stage="qc.loader_probe.load_features",
                          evidence_refs=leaked)
    return payload


#: Feature-schema version that ships the observation-quality block in the obs index (S7).
OBSERVATION_QUALITY_FEATURE = "observation_quality_channels"


def _quality_row(package: TrainingPackage, fragment_id: str
                 ) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """``([1,C] values, [1,C] valid, provenance)`` from the package's measured quality channels.

    No measurement for this fragment (or no block in the package at all) returns a single masked
    slot: ``valid=False`` with the reason recorded, so a consumer can tell "unmeasured" from
    "measured zero" (plan 30.12).
    """
    measured = package.observation_quality(fragment_id)
    if measured is None or not measured["values"]:
        reason = ("the package carries no observation-quality block "
                  "(written before the S7 fix)" if not hasattr(package, "observation_quality")
                  else "this fragment's observation carries no OBS_EST quality channel")
        return (np.zeros((1, 1), dtype=np.float32), np.zeros((1, 1), dtype=bool),
                {"available": False, "reason": reason, "channels": []})
    values = np.asarray(measured["values"], dtype=np.float32).reshape(1, -1)
    valid = np.ones(values.shape, dtype=bool)
    return values, valid, {
        "available": True,
        "channels": list(measured["channels"]),
        "n_channels": int(values.shape[1]),
        "asset_id": measured["asset_id"],
        "estimator_version": (measured.get("provenance") or {}).get("estimator_version"),
        "source": (measured.get("provenance") or {}).get("source"),
        "missing_is_not_a_zero_label": True,
    }


def probe_training_package(package_dir: str | Path, *, max_fragments: int = 16,
                           out_path: str | Path | None = None,
                           token_budget: int | None = None) -> dict[str, Any]:
    """Read a real package and build a real batch; never raises, always reports."""
    started = time.time()
    report: dict[str, Any] = {
        "schema": PROBE_SCHEMA,
        "step": "loader_probe",
        "package_dir": str(package_dir),
        "attempts": [],
        "ok": False,
    }

    def attempt(name: str, fn) -> Any:
        t0 = time.time()
        try:
            detail = fn()
            report["attempts"].append({"name": name, "ok": True, "seconds": time.time() - t0,
                                       "detail": _jsonable(detail)})
            return detail
        except Exception as exc:  # noqa: BLE001 - the failure *is* the measurement
            code = getattr(getattr(exc, "code", None), "value", "")
            report["attempts"].append({
                "name": name, "ok": False, "seconds": time.time() - t0,
                "error_code": str(code or type(exc).__name__),
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc()[-1500:],
            })
            if "blocking_attempt" not in report:
                report["blocking_attempt"] = name
            return None

    package = attempt("storage.export.TrainingPackage", lambda: TrainingPackage(package_dir))
    if package is None:
        _finish(report, started, out_path)
        return report

    verify = attempt("package.verify_files", package.verify_files)
    if verify is not None:
        report["files_ok"] = bool(verify["ok"])
        report["files_checked"] = int(verify["files_checked"])
        if not verify["ok"]:
            report["blocking_attempt"] = "package.verify_files"

    relations = attempt("package.relations", package.relations) or []
    queries = attempt("package.queries", package.queries) or []
    report["counts"] = {
        "relations": len(relations),
        "queries": len(queries),
        "relation_kinds": _kind_counts(relations),
    }

    pool = attempt("qc.loader_probe.ExportedRelationPool",
                   lambda: ExportedRelationPool(relations, pool_id=_pool_id(relations)))
    if pool is not None:
        report["relation_pool"] = {"pool_id": pool.pool_id,
                                   "kinds": pool.kind_histogram(),
                                   "r2_closure": pool.r2_closure()}

    fragment_ids = [str(row.get("fragment_id") or _query_fragment(row))
                    for row in queries]
    fragment_ids = [f for f in dict.fromkeys(fragment_ids) if f][: int(max_fragments)]
    candidates = sorted({str(r.get("candidate", "")) for r in relations if r.get("candidate")})
    for candidate in candidates:
        if candidate not in fragment_ids:
            fragment_ids.append(candidate)
    report["batch_fragments"] = len(fragment_ids)
    if not fragment_ids:
        report["error"] = {"code": ErrorCode.INPUT_UNAVAILABLE.value,
                           "message": "the package carries no fragment to build a batch from"}
        _finish(report, started, out_path)
        return report

    payloads = attempt("load_features(local_tokens/geometry/global_rgb)",
                       lambda: load_features(package, fragment_ids, token_budget=token_budget))
    if payloads is None:
        _finish(report, started, out_path)
        return report

    bundle = attempt("training.adapter.FeatureBundle.from_dict",
                     lambda: FeatureBundle.from_dict(payloads, token_budget=token_budget))
    if bundle is None:
        _finish(report, started, out_path)
        return report
    shapes = attempt("training.adapter.FeatureBundle.check_shapes",
                     lambda: _bundle_shapes(bundle.check_shapes()))
    report["feature_shapes"] = shapes
    report["real_denominator"] = {
        "fragments": int(bundle.n_fragments),
        "fragments_with_observation": int(np.count_nonzero(bundle.tokens_total > 0)),
        "fragments_without_observation": int(np.count_nonzero(bundle.tokens_total == 0)),
        "tokens_total": int(np.sum(bundle.tokens_total)),
        "tokens_valid": int(bundle.token_valid.sum()),
        "points_valid": int(bundle.point_valid.sum()),
        "scale_valid_fragments": int(bundle.scale_valid.sum()),
    }

    rows = _batch_rows(relations, fragment_ids, pool)
    report["batch_rows"] = {
        "rows": len(rows),
        "with_positives": sum(1 for r in rows if r.get("positives")),
        "with_negatives": sum(1 for r in rows if r.get("negatives")),
    }
    batch = attempt("training.batch.build_training_batch",
                    lambda: build_training_batch(bundle, pool=pool, rows=rows))
    if batch is None:
        _finish(report, started, out_path)
        return report

    audit = attempt("training.batch.negative_audit", lambda: negative_audit(batch))
    report["batch"] = {
        "shapes": {name: list(np.asarray(getattr(batch, name)).shape)
                   for name in ("pair_index", "pair_valid", "labels_relation", "pos_mask",
                                "neg_mask", "excluded_mask", "exclusion_reason",
                                "quality_target", "corr_weight", "contradiction",
                                "quality_tier", "lineage_cluster", "sample_keys")},
        "pool_id": batch.pool_id,
        "n_queries": int(batch.n_queries),
        "n_candidates": int(batch.n_candidates),
        "positives": int(batch.pos_mask.sum()),
        "negatives": int(batch.neg_mask.sum()),
        "excluded": int(batch.excluded_mask.sum()),
        "effective_queries": int(batch.effective_query_count()),
        "exposure": _jsonable(batch.exposure()),
    }
    report["negative_audit"] = audit
    report["relation_kinds_in_batch"] = _kind_counts_from_codes(
        batch.labels_relation[batch.pair_valid])
    # ``ok`` is the *whole* claim: the package must verify against its own manifest hashes
    # (``package.verify_files``) **and** the batch must pass its negative audit.  Reporting only
    # the audit made a package whose declared hashes do not verify load "ok" -- a loader that
    # accepts tampered bytes is not a loader.
    integrity_ok = bool(report.get("files_ok"))
    report["ok"] = bool(integrity_ok and audit and audit.get("ok"))
    if not integrity_ok:
        report["error"] = {
            "code": ErrorCode.ASSET_HASH_MISMATCH.value,
            "message": ("the package failed its own file-hash check (package.verify_files); a "
                        "loader must refuse a package whose declared hashes do not verify"),
            "problems": (verify or {}).get("problems", []) if isinstance(verify, dict) else [],
        }
        report.setdefault("blocking_attempt", "package.verify_files")
    elif not report["ok"]:
        report["error"] = {"code": ErrorCode.STOP_QA.value,
                           "message": "the batch failed its own negative audit"}
    if batch.pos_mask.sum() == 0:
        report["degenerate"] = {
            "reason": ("no confirmed R2 pair exists in the exported relation table, so the "
                       "batch carries zero positives; the loader is validated but the "
                       "supervision is empty"),
            "kind_histogram": _kind_counts(relations),
        }
    _finish(report, started, out_path)
    return report


def _finish(report: dict[str, Any], started: float, out_path: str | Path | None) -> None:
    report["seconds"] = time.time() - started
    report.setdefault("ok", False)
    report["status"] = "PASS" if report.get("ok") else "FAIL"
    if out_path is not None:
        path = Path(out_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True,
                                   default=str), encoding="utf-8")
        report["report_path"] = str(path)


def _query_fragment(row: Mapping[str, Any]) -> str:
    query_id = str(row.get("query_id", ""))
    return query_id.split("::", 1)[1] if "::" in query_id else query_id


def _pool_id(relations: Sequence[Mapping[str, Any]]) -> str:
    for row in relations:
        value = str(row.get("pool_id", "") or "")
        if value:
            return value
    return "exported"


def _kind_counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in rows:
        key = str(row.get("kind", "UNKNOWN"))
        out[key] = out.get(key, 0) + 1
    return out


def _kind_counts_from_codes(codes: np.ndarray) -> dict[str, int]:
    from ..training.adapter import RELATION_NAMES

    out: dict[str, int] = {}
    for code, count in zip(*np.unique(np.asarray(codes), return_counts=True)):
        out[RELATION_NAMES.get(int(code), f"code_{int(code)}")] = int(count)
    return out


def _bundle_shapes(bundle: FeatureBundle) -> dict[str, Any]:
    return {
        "n_fragments": int(bundle.n_fragments),
        "n_views": int(bundle.n_views),
        "token_budget": int(bundle.token_budget),
        "n_points": int(bundle.n_points),
        "n_regions": int(bundle.n_regions),
        "c_quality": int(bundle.c_quality),
        "c_presence": int(bundle.c_presence),
        "global_rgb": list(bundle.global_rgb.shape),
        "local_tokens": list(bundle.local_tokens.shape),
        "points": list(bundle.points.shape),
        "token_retention": _jsonable(bundle.token_retention()),
        "scale_valid_fraction": float(bundle.scale_valid_fraction),
    }


def _batch_rows(relations: Sequence[Mapping[str, Any]], fragment_ids: Sequence[str],
                pool: ExportedRelationPool | None) -> list[dict[str, Any]]:
    """One row per query: its exported R2 mates as positives, its R1/R0 pairs as negatives.

    The exported table is the authoritative pair list, so this does not re-derive the
    classification; it only splits the rows into positives / legal negatives / excluded, and
    the batch builder re-checks every one of them against the pool.
    """
    known = set(fragment_ids)
    by_query: dict[str, dict[str, list[str]]] = {}
    excluded: dict[str, list[str]] = {}
    for row in relations:
        query = str(row.get("query", ""))
        candidate = str(row.get("candidate", ""))
        if query not in known or candidate not in known or query == candidate:
            continue
        kind = str(row.get("kind", "UNKNOWN"))
        bucket = by_query.setdefault(query, {"positives": [], "negatives": []})
        if kind == "R2" and bool(row.get("valid", False)):
            bucket["positives"].append(candidate)
        elif kind in NEGATIVE_KINDS and bool(row.get("valid", False)) \
                and bool(row.get("loss_mask", False)):
            bucket["negatives"].append(candidate)
        else:
            excluded.setdefault(query, []).append(candidate)
    rows: list[dict[str, Any]] = []
    for query in sorted(set(by_query) | set(excluded)):
        bucket = by_query.get(query, {"positives": [], "negatives": []})
        rows.append({
            "query": query,
            "positives": sorted(dict.fromkeys(bucket["positives"])),
            "negatives": sorted(dict.fromkeys(bucket["negatives"])),
            "excluded": sorted(dict.fromkeys(excluded.get(query, []))),
            "sample_key": f"probe::{query}",
        })
    return rows


def excluded_kind_report(relations: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Kinds that must never be used as an ordinary negative (plan 18.2)."""
    out: dict[str, int] = {}
    for row in relations:
        kind = str(row.get("kind", "UNKNOWN"))
        if kind in EXCLUDED_NEGATIVE_KINDS:
            out[kind] = out.get(kind, 0) + 1
    return out


__all__ = [
    "PROBE_SCHEMA", "FORBIDDEN_PAYLOAD_KEYS", "ExportedRelationPool",
    "load_features", "probe_training_package", "excluded_kind_report", "TOKEN_DIM",
]
