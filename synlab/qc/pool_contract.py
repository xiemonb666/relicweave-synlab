"""The relation-pool **protocol**: one contract, every implementation, one suite.

Why this module exists
----------------------
The repository contains four parallel readers of the same relation data:

======================================  ====================================================
implementation                          where
======================================  ====================================================
``qc.loader_probe.ExportedRelationPool`` the offline reader over an exported ``relations.parquet``
``training.sampler.PoolIndex``           the sampler/pool adapter ``synlab.training`` consumes
``training.smoke.TrainingPoolView``      the training-side view over the same exported table
``relations.gallery.RelationPool``       the live gallery pool built from the asset store
======================================  ====================================================

They are duck-typed against each other, so nothing in the type system keeps them honest.  The
last time they diverged, ``ExportedRelationPool.neighbours()`` returned the confirmed **R1/R0**
set while ``training.batch`` reads ``neighbours(q)`` as the **historical R2 mate set**; every
legal negative then looked like a mate, ``assert_legal_negative`` refused all of them
(``every_legal_negative_is_a_pool_neighbour = true`` for 55/55 queries) and the ``rank`` task
**never started** while every individual component reported success
(``docs/a12/relation_negatives.md`` §1, defect (B); ``docs/a12/engineering_policy.md`` §3 row 5).

Following rule **R2** (make the property hold *by construction*, not by convention) the protocol
is fixed here as a **single constructive contract**: one row set goes in, every implementation is
instantiated from it, and every implementation is run through **the same assertion battery**
(:data:`ASSERTIONS`).  Expected values are derived by :func:`reference_mates` / the row set
itself -- never by one of the implementations under test -- so a shared misreading cannot make
the suite green.  Any implementation that does not satisfy the battery fails the suite; the
failure names the assertion, the pool and the offending fragment.

The protocol (what every pool must provide)
-------------------------------------------
``relation(a, b) -> str``
    Symmetric.  ``a == b`` is never an adjacency.  A pair named by a measured row reads that
    row's kind; a pair with **no** measured row may only read ``R0`` (implicit non-adjacency)
    or ``UNKNOWN`` (not measured) -- it may never claim ``R1``/``R2``/``TINY_CONTACT``.
``mates(q) -> set[str]``
    The **historical R2 mate set**: exactly the confirmed ``R2`` adjacency of ``q`` in this pool,
    ``q`` excluded.
``neighbours(q) -> set[str]``
    **The same set as** :meth:`mates`.  This is the reading ``training.batch`` relies on; a pool
    that answers with its negative neighbours here is the ``rank`` defect and fails the suite.
``legal_pool(q) -> list[str]`` / ``legal_negatives(q) -> set[str]``
    The *ordinary negative* candidates: **confirmed ``R1``/``R0`` only**, never ``q``, never a
    mate of ``q``, never ``R2``/``TINY_CONTACT``/``UNKNOWN``.  The two spellings must agree.
``history_exclusions(q) -> set[str]``
    Fragments that may **never** be an ordinary negative of ``q`` under this pool's reading.
    The battery requires the two properties that make the name meaningful: it is a **superset of
    the mate set** and it is **disjoint from the legal set**.  Implementations may exclude more
    (``PoolIndex`` also excludes ``q`` itself and every ``UNKNOWN``/``TINY``/grey-zone candidate);
    excluding *less* than the mates is the mismatch this pins.
``confirmed(a, b) -> bool``
    ``True`` for a measured adjacency (``R0``/``R1``/``R2`` under a reader that can see all of
    them, ``R0``/``R1`` under the deliberately conservative exported reader).
``negative_eligibility(a, b)``
    The **one truth source** of the ordinary-negative gate, consumed by every implementation
    (``relations.legal_negative.resolve_negative_eligibility``): a frozen result carrying
    ``eligible`` plus the machine-readable ``reason`` and a human ``detail``.  A reader supplies
    the inputs from its own truth layer (an exported table row's ``valid``/``loss_mask``, a stored
    relation edge, an implicit-``R0`` construction) and **never** re-derives eligibility from the
    pair's kind; a row the truth layer withdrew (``valid=False`` / ``loss_mask=False``) is refused
    by every reader, and an input that carries no eligibility evidence refuses too.  This is the
    clause ``eligibility_follows_extracted_flags`` asserts.
``assert_legal_negative(q, c) -> None``
    Raises for ``c == q``, for a mate of ``q``, for ``R2``/``TINY_CONTACT``/``UNKNOWN`` and for an
    unconfirmed candidate; accepts every candidate of ``legal_pool(q)``.
``candidate_ids(q) -> list[str]``
    The pool's universe minus ``q`` (the query is never its own candidate).
``lineup``
    The pool's fragment universe (``PoolIndex.lineage`` reads it through ``lineup`` /
    ``fragment_ids``).

The battery is *safety-shaped*: it never asserts that two implementations know the same amount
(the exported reader deliberately knows less -- a pair that is absent from the table is
``UNKNOWN`` and unconfirmed), it asserts that **neither of them ever claims a legal negative it
cannot justify**.  The "same amount" side is measured separately by :func:`check_agreement`,
which reports the divergence between implementations instead of hiding it.

Failure injection
-----------------
:data:`FAILURE_INJECTIONS` wraps one implementation and breaks exactly one protocol clause; each
injection must be *caught* by the named assertion.  That is the reproducible proof that the
suite can fail -- a contract test that cannot fail is a convention, not a contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, MutableMapping, Sequence

from ..errors import ErrorCode, SynLabError
from ..schemas.runtime import (
    RELATION_R0,
    RELATION_R1,
    RELATION_R2,
    RELATION_TINY,
    RELATION_UNKNOWN,
    GallerySpec,
)
from ..storage.export import NEGATIVE_KINDS

#: Version of the protocol contract itself (bump when an assertion is added/strengthened).
POOL_PROTOCOL_VERSION = "relations.pool_protocol.v1"

#: Relation kinds a *measured* row may carry.
MEASURED_KINDS: tuple[str, ...] = (RELATION_R2, RELATION_R1, RELATION_R0, RELATION_TINY,
                                   RELATION_UNKNOWN)

#: Kinds that may never be an ordinary negative (positive adjacency, contact artefact, unknown).
FORBIDDEN_NEGATIVE_KINDS: tuple[str, ...] = (RELATION_R2, RELATION_TINY, RELATION_UNKNOWN)

#: Kinds a pair with **no** measured row may read (implicit non-adjacency, or not measured).
UNMEASURED_KINDS: tuple[str, ...] = (RELATION_R0, RELATION_UNKNOWN)

#: Non-adjacency readings that are legal for ``relation(a, a)`` / out-of-universe fragments.
NON_ADJACENCY_READINGS: tuple[str, ...] = ("SELF", "ABSENT", RELATION_UNKNOWN)

#: Methods the protocol requires every pool to expose.
PROTOCOL_METHODS: tuple[str, ...] = (
    "relation", "mates", "neighbours", "legal_pool", "legal_negatives", "confirmed",
    "history_exclusions", "candidate_ids", "assert_legal_negative", "negative_eligibility",
)

#: The four parallel implementations, by dotted path (for the report).
IMPLEMENTATIONS: tuple[str, ...] = (
    "synlab.qc.loader_probe.ExportedRelationPool",
    "synlab.training.sampler.PoolIndex",
    "synlab.training.smoke.TrainingPoolView",
    "synlab.relations.gallery.RelationPool",
)

_QUERY_KEYS: tuple[str, ...] = ("query", "a", "fragment_a")
_CANDIDATE_KEYS: tuple[str, ...] = ("candidate", "b", "fragment_b")

#: Reason code the injected kind-recomputation stamps on its answers (report-only).
KIND_RECOMPUTED = "eligibility_recomputed_from_the_kind"


class PoolContractError(SynLabError):
    """A pool implementation does not satisfy the protocol contract."""

    def __init__(self, message: str, *, label: str, failures: Sequence[str],
                 stage: str = "qc.pool_contract") -> None:
        super().__init__(ErrorCode.SCHEMA_INVALID, message, stage=stage,
                         evidence_refs=[f"{label}:{f}" for f in list(failures)[:32]])
        self.label = str(label)
        self.failures = list(failures)


# --------------------------------------------------------------------------------------
# the context: one row set + the reference reading derived from it
# --------------------------------------------------------------------------------------
def row_endpoints(row: Mapping[str, Any]) -> tuple[str, str]:
    """``(query, candidate)`` of a directed relation row, whatever spelling it uses."""
    query = next((str(row[k]) for k in _QUERY_KEYS if row.get(k)), "")
    candidate = next((str(row[k]) for k in _CANDIDATE_KEYS if row.get(k)), "")
    return query, candidate


def reference_rows(rows: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    """The contract's own reading of the rows: ``{(a, b): {kind, valid, ...}}`` per unordered pair.

    Deliberately trivial and independent of every implementation under test: a pair's kind is
    the kind of the row that measured it.  Two rows naming the same unordered pair with
    different kinds are a **table defect** and are reported by :meth:`ProtocolContext.duplicate_pairs`
    (the exported reader keeps one direction per row, so such a table cannot be read
    symmetrically by construction).
    """
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        query, candidate = row_endpoints(row)
        if not query or not candidate or query == candidate:
            continue
        key = (query, candidate) if query <= candidate else (candidate, query)
        entry = out.setdefault(key, {"kinds": [], "valid": [], "rows": 0})
        entry["kinds"].append(str(row.get("kind", RELATION_UNKNOWN)))
        entry["valid"].append(bool(row.get("valid", False)))
        entry["rows"] += 1
    return out


def reference_mates(rows: Iterable[Mapping[str, Any]], *,
                    valid_only: bool = True) -> dict[str, set[str]]:
    """``{fragment: {confirmed R2 mates}}`` -- the contract's own mate reading.

    ``valid_only=True`` (the meaning ``training.batch`` and ``relations.mate_absent`` use) counts
    an ``R2`` row only when the measurement is usable.
    """
    mates: MutableMapping[str, set[str]] = {}
    for row in rows:
        if str(row.get("kind")) != RELATION_R2:
            continue
        if valid_only and not bool(row.get("valid", False)):
            continue
        query, candidate = row_endpoints(row)
        if not query or not candidate or query == candidate:
            continue
        mates.setdefault(query, set()).add(candidate)
        mates.setdefault(candidate, set()).add(query)
    return {fid: set(values) for fid, values in mates.items()}


@dataclass(frozen=True)
class ProtocolContext:
    """One protocol reading: the row set, the fragment universe and the reference derivation."""

    name: str
    lineup: tuple[str, ...]
    rows: tuple[Mapping[str, Any], ...]
    source: str = ""
    #: pairs the pool is asked about; defaults to every ordered pair of :attr:`lineup`
    pairs: tuple[tuple[str, str], ...] = ()
    notes: Mapping[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------ derivation
    def universe(self) -> tuple[str, ...]:
        return tuple(self.lineup)

    def _reference(self) -> dict[tuple[str, str], dict[str, Any]]:
        cached = self.__dict__.get("_reference_cache")
        if cached is None:
            cached = reference_rows(self.rows)
            object.__setattr__(self, "_reference_cache", cached)
        return cached

    def reference_kind(self, a: str, b: str) -> str | None:
        """The measured kind of ``(a, b)``, or ``None`` when no row names the pair."""
        a, b = str(a), str(b)
        if a == b:
            return None
        entry = self._reference().get((a, b) if a <= b else (b, a))
        if entry is None:
            return None
        kinds = sorted(set(entry["kinds"]))
        if len(kinds) != 1:
            return None                      # conflicting rows: reported, never guessed
        return kinds[0]

    def reference_valid(self, a: str, b: str) -> bool:
        a, b = str(a), str(b)
        entry = self._reference().get((a, b) if a <= b else (b, a))
        return bool(entry and any(entry["valid"])) if entry else False

    def mates(self) -> dict[str, set[str]]:
        return reference_mates(self.rows)

    def duplicate_pairs(self) -> list[dict[str, Any]]:
        """Unordered pairs named by rows with **conflicting** kinds (a table defect)."""
        out: list[dict[str, Any]] = []
        for (a, b), entry in sorted(self._reference().items()):
            kinds = sorted(set(entry["kinds"]))
            if len(kinds) > 1:
                out.append({"query": a, "candidate": b, "kinds": kinds, "rows": entry["rows"]})
        return out

    def mate_set(self, fragment_id: str) -> set[str]:
        return set(self.mates().get(str(fragment_id), set()))

    def ordered_pairs(self) -> tuple[tuple[str, str], ...]:
        if self.pairs:
            return tuple(self.pairs)
        return tuple((a, b) for a in self.lineup for b in self.lineup)


# --------------------------------------------------------------------------------------
# the assertion battery
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Assertion:
    """One protocol clause: ``fn(pool, ctx) -> [violation, ...]`` (empty list means satisfied)."""

    name: str
    clause: str
    fn: Callable[[Any, ProtocolContext], list[str]]

    def run(self, pool: Any, ctx: ProtocolContext) -> list[str]:
        try:
            return [str(item) for item in (self.fn(pool, ctx) or [])]
        except Exception as exc:  # noqa: BLE001 - an implementation that raises *fails* the clause
            return [f"raised {type(exc).__name__}: {exc}"]


def _has(pool: Any, name: str) -> bool:
    return callable(getattr(pool, name, None))


def _interface_present(pool: Any, ctx: ProtocolContext) -> list[str]:
    missing = [name for name in PROTOCOL_METHODS if not _has(pool, name)]
    out = [f"missing protocol method {name}()" for name in missing]
    if missing:
        return out
    # The universe is checked *behaviourally* (does the pool name candidates at all?) rather than
    # by sniffing attribute names: ``PoolIndex`` answers it through the carrier's ``lineup`` and
    # exposes no ``lineup`` of its own.
    if not any(pool.candidate_ids(fid) for fid in ctx.universe()):
        out.append("candidate_ids() is empty for every fragment: the pool exposes no candidate "
                   "universe (lineup/fragment_ids is empty for every fragment)")
    return out


def _relation_value_domain(pool: Any, ctx: ProtocolContext) -> list[str]:
    out: list[str] = []
    for a, b in ctx.ordered_pairs():
        kind = str(pool.relation(a, b))
        if a == b:
            if kind not in NON_ADJACENCY_READINGS and kind not in (RELATION_R0,):
                out.append(f"relation({a}, {a}) = {kind!r}: a fragment is never its own adjacency")
            continue
        if kind not in MEASURED_KINDS and kind not in NON_ADJACENCY_READINGS:
            out.append(f"relation({a}, {b}) = {kind!r} is outside the protocol vocabulary")
            continue
        measured = ctx.reference_kind(a, b)
        if measured is None:
            if kind not in UNMEASURED_KINDS:
                out.append(f"relation({a}, {b}) = {kind!r} but no measured row names the pair "
                           f"(only {UNMEASURED_KINDS} are allowed)")
        elif kind != measured:
            out.append(f"relation({a}, {b}) = {kind!r} but the measured row says {measured!r}")
    return out


def _relation_symmetry(pool: Any, ctx: ProtocolContext) -> list[str]:
    out: list[str] = []
    for a, b in ctx.ordered_pairs():
        if a > b:
            continue
        forward, backward = str(pool.relation(a, b)), str(pool.relation(b, a))
        if forward != backward:
            out.append(f"relation({a}, {b}) = {forward!r} but relation({b}, {a}) = {backward!r}")
    return out


def _mates_match_measured_r2(pool: Any, ctx: ProtocolContext) -> list[str]:
    out: list[str] = []
    expected = ctx.mates()
    for fid in ctx.universe():
        got = {str(x) for x in pool.mates(fid)}
        want = set(expected.get(str(fid), set()))
        if fid in got:
            out.append(f"mates({fid}) contains the fragment itself")
            got = got - {fid}
        if got != want:
            out.append(f"mates({fid}) = {sorted(got)} but the measured R2 rows say "
                       f"{sorted(want)}")
    return out


def _neighbours_are_mates(pool: Any, ctx: ProtocolContext) -> list[str]:
    """The ``rank`` clause: ``neighbours()`` **is** the historical R2 mate set."""
    out: list[str] = []
    for fid in ctx.universe():
        mates = {str(x) for x in pool.mates(fid)}
        neighbours = {str(x) for x in pool.neighbours(fid)}
        if neighbours != mates:
            out.append(f"neighbours({fid}) = {sorted(neighbours)} but mates({fid}) = "
                       f"{sorted(mates)}")
    return out


def _legal_set_only_confirmed_negatives(pool: Any, ctx: ProtocolContext) -> list[str]:
    out: list[str] = []
    for fid in ctx.universe():
        legal = {str(x) for x in pool.legal_pool(fid)}
        for candidate in sorted(legal):
            kind = str(pool.relation(fid, candidate))
            if kind not in NEGATIVE_KINDS:
                out.append(f"legal_pool({fid}) offers {candidate} with kind {kind!r} "
                           f"(ordinary negatives are {sorted(NEGATIVE_KINDS)} only)")
            if not bool(pool.confirmed(fid, candidate)):
                out.append(f"legal_pool({fid}) offers unconfirmed {candidate} ({kind!r})")
    return out


def _legal_set_excludes_self(pool: Any, ctx: ProtocolContext) -> list[str]:
    out: list[str] = []
    for fid in ctx.universe():
        if str(fid) in {str(x) for x in pool.legal_pool(fid)}:
            out.append(f"legal_pool({fid}) contains the query itself")
        if str(fid) in {str(x) for x in pool.legal_negatives(fid)}:
            out.append(f"legal_negatives({fid}) contains the query itself")
        if str(fid) in {str(x) for x in pool.candidate_ids(fid)}:
            out.append(f"candidate_ids({fid}) contains the query itself")
    return out


def _legal_set_excludes_mates(pool: Any, ctx: ProtocolContext) -> list[str]:
    """A legal negative may never be a mate of its query (the supervision-leak clause)."""
    out: list[str] = []
    for fid in ctx.universe():
        mates = {str(x) for x in pool.mates(fid)}
        for name, values in (("legal_pool", pool.legal_pool(fid)),
                             ("legal_negatives", pool.legal_negatives(fid))):
            leak = sorted(mates & {str(x) for x in values})
            if leak:
                out.append(f"{name}({fid}) offers the mate(s) {leak}")
        neighbour_leak = sorted({str(x) for x in pool.neighbours(fid)}
                                & {str(x) for x in pool.legal_pool(fid)})
        if neighbour_leak:
            out.append(f"legal_pool({fid}) offers the neighbour(s) {neighbour_leak}")
    return out


def _legal_pool_equals_legal_negatives(pool: Any, ctx: ProtocolContext) -> list[str]:
    out: list[str] = []
    for fid in ctx.universe():
        left = {str(x) for x in pool.legal_pool(fid)}
        right = {str(x) for x in pool.legal_negatives(fid)}
        if left != right:
            out.append(f"legal_pool({fid}) = {sorted(left)} but legal_negatives({fid}) = "
                       f"{sorted(right)}")
    return out


def _history_exclusions_superset_of_mates(pool: Any, ctx: ProtocolContext) -> list[str]:
    out: list[str] = []
    for fid in ctx.universe():
        history = {str(x) for x in pool.history_exclusions(fid)}
        missing = sorted({str(x) for x in pool.mates(fid)} - history)
        if missing:
            out.append(f"history_exclusions({fid}) omits the mate(s) {missing}")
    return out


def _history_exclusions_disjoint_from_legal(pool: Any, ctx: ProtocolContext) -> list[str]:
    out: list[str] = []
    for fid in ctx.universe():
        history = {str(x) for x in pool.history_exclusions(fid)}
        overlap = sorted(history & {str(x) for x in pool.legal_pool(fid)})
        if overlap:
            out.append(f"legal_pool({fid}) offers {overlap}, which history_exclusions({fid}) "
                       f"forbids")
    return out


def _assert_legal_negative_accepts_the_legal_set(pool: Any, ctx: ProtocolContext) -> list[str]:
    out: list[str] = []
    for fid in ctx.universe():
        for candidate in sorted({str(x) for x in pool.legal_pool(fid)}):
            try:
                pool.assert_legal_negative(fid, candidate)
            except Exception as exc:  # noqa: BLE001 - the refusal is the measurement
                out.append(f"assert_legal_negative({fid}, {candidate}) refuses a candidate of "
                           f"legal_pool: {type(exc).__name__}: {exc}")
    return out


def _assert_legal_negative_refuses_illegal(pool: Any, ctx: ProtocolContext) -> list[str]:
    out: list[str] = []
    for fid in ctx.universe():
        # the query itself
        try:
            pool.assert_legal_negative(fid, fid)
            out.append(f"assert_legal_negative({fid}, {fid}) accepted the query itself")
        except Exception:  # noqa: BLE001 - expected refusal
            pass
        for candidate in sorted({str(x) for x in pool.mates(fid)}):
            try:
                pool.assert_legal_negative(fid, candidate)
                out.append(f"assert_legal_negative({fid}, {candidate}) accepted a historical "
                           f"R2 mate")
            except Exception:  # noqa: BLE001 - expected refusal
                pass
        for candidate in sorted(set(ctx.universe()) - {str(fid)}):
            kind = str(pool.relation(fid, candidate))
            if kind not in FORBIDDEN_NEGATIVE_KINDS and kind not in NON_ADJACENCY_READINGS:
                continue
            try:
                pool.assert_legal_negative(fid, candidate)
                out.append(f"assert_legal_negative({fid}, {candidate}) accepted a {kind!r} "
                           f"candidate")
            except Exception:  # noqa: BLE001 - expected refusal
                pass
    return out


def _ineligible_directions(ctx: ProtocolContext) -> dict[tuple[str, str], dict[str, Any]]:
    """``{(query, candidate): row}`` for every direction the **row set** marks ineligible.

    Derived from the rows alone (the contract's own reading, ``reference_rows``), never from an
    implementation: a direction is listed when the row names it, its kind is an
    ordinary-negative kind, and the row is withdrawn -- ``valid=False`` or ``loss_mask=False``.
    Its ``eligible_as_negative`` flag must agree with that gate; a row where it does not is a
    table defect and is reported by this assertion as well, because no reader may supply it.
    """
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for (a, b), entry in ctx._reference().items():
        kinds = sorted(set(entry["kinds"]))
        if len(kinds) != 1 or kinds[0] not in NEGATIVE_KINDS:
            continue
        row = next((r for r in ctx.rows
                    if {str(r.get("query")), str(r.get("candidate"))} == {a, b}), {})
        valid = row.get("valid", None)
        loss_mask = row.get("loss_mask", None)
        declared = row.get("eligible_as_negative", None)
        if valid is None and loss_mask is None and declared is None:
            continue                          # no flag vocabulary: nothing is withdrawn
        flag_gate = bool(valid is True and loss_mask is True)
        ineligible = (declared is False) or not flag_gate
        if not ineligible:
            continue                          # eligible under the frozen gate: not a finding
        out[(a, b)] = {"kind": kinds[0], "valid": bool(valid), "loss_mask": bool(loss_mask),
                       "eligible_as_negative": declared, "reason": str(row.get("reason", "") or "")}
        out[(b, a)] = out[(a, b)]             # relations are symmetric: both directions
    return out


def _eligibility_follows_extracted_flags(pool: Any, ctx: ProtocolContext) -> list[str]:
    """**The eligibility clause**: eligibility follows the extracted flags, never the kind.

    ``docs/a12/relation_negatives.md`` §9.1.1: 24 ``R1`` rows (48 directed pairs) carry
    ``valid=False``/``loss_mask=False`` and were supplied as ordinary negatives by
    ``relations.gallery.RelationPool``, ``PoolIndex[exported]`` and ``PoolIndex[gallery]`` while
    ``ExportedRelationPool``/``TrainingPoolView`` refused them.  The frozen gate is
    ``eligible_as_negative := (kind in {R0,R1}) and valid and loss_mask``, so a withdrawn row must
    be refused by **every** implementation, in four places at once -- the legal set, the guard, the
    ``confirmed``/``negative_eligibility`` reading, and the exclusion list -- and the refusal must
    carry a reason.  A reader that recomputes eligibility from the kind fails this clause.
    """
    out: list[str] = []
    rows = _ineligible_directions(ctx)
    for (query, candidate), row in sorted(rows.items()):
        where = f"({query}, {candidate}) [{row['kind']} valid={row['valid']} " \
                f"loss_mask={row['loss_mask']}]"
        if candidate in {str(x) for x in pool.legal_pool(query)}:
            out.append(f"legal_pool{where} offers a row the extracted flags withdraw")
        if candidate in {str(x) for x in pool.legal_negatives(query)}:
            out.append(f"legal_negatives{where} offers a row the extracted flags withdraw")
        if str(pool.relation(query, candidate)) in NEGATIVE_KINDS \
                and bool(pool.confirmed(query, candidate)):
            out.append(f"confirmed{where} returns True for a row the extracted flags withdraw")
        resolution = None
        accessor = getattr(pool, "negative_eligibility", None)
        if callable(accessor):
            try:
                resolution = accessor(query, candidate)
            except Exception as exc:  # noqa: BLE001 - an accessor that raises fails the clause
                out.append(f"negative_eligibility{where} raised {type(exc).__name__}: {exc}")
        if resolution is None:
            continue
        if bool(getattr(resolution, "eligible", True)):
            out.append(f"negative_eligibility{where} says eligible=True: {resolution!r}")
        if not str(getattr(resolution, "reason", "") or ""):
            out.append(f"negative_eligibility{where} refuses without a reason")
    # the same clause for the mate/exclusion side: a withdrawn candidate must not be *implied*
    # legal by an exclusion list that stays silent about it while the legal set is filtered
    for fid in ctx.universe():
        legal = {str(x) for x in pool.legal_pool(fid)}
        for (query, candidate) in rows:
            if query != str(fid) or candidate in legal:
                continue
            try:
                pool.assert_legal_negative(fid, candidate)
                out.append(f"assert_legal_negative({fid}, {candidate}) accepted a row the "
                           f"extracted flags withdraw")
            except Exception:  # noqa: BLE001 - expected refusal
                pass
    return out


#: The battery, in report order.  Every implementation must satisfy **every** clause.
ASSERTIONS: tuple[Assertion, ...] = (
    Assertion("interface_present",
              "the pool exposes every protocol method and a non-empty candidate universe",
              _interface_present),
    Assertion("relation_value_domain",
              "relation(a,b) is symmetric, never an adjacency for a==b, equals the measured "
              "row's kind, and never invents an adjacency for an unmeasured pair",
              _relation_value_domain),
    Assertion("relation_symmetry",
              "relation(a,b) == relation(b,a) for every pair of the universe",
              _relation_symmetry),
    Assertion("mates_match_measured_r2",
              "mates(q) is exactly the confirmed R2 adjacency of q (q excluded)",
              _mates_match_measured_r2),
    Assertion("neighbours_are_mates",
              "neighbours(q) == mates(q) -- the clause whose divergence made rank never start",
              _neighbours_are_mates),
    Assertion("legal_set_only_confirmed_negatives",
              "legal_pool()/legal_negatives() contain confirmed R0/R1 candidates only",
              _legal_set_only_confirmed_negatives),
    Assertion("legal_set_excludes_self",
              "no legal candidate and no candidate_ids entry is the query itself",
              _legal_set_excludes_self),
    Assertion("legal_set_excludes_mates",
              "a legal negative is never a mate (or a neighbour) of its query",
              _legal_set_excludes_mates),
    Assertion("legal_pool_equals_legal_negatives",
              "the two spellings of the legal set agree",
              _legal_pool_equals_legal_negatives),
    Assertion("history_exclusions_superset_of_mates",
              "history_exclusions(q) contains every mate of q",
              _history_exclusions_superset_of_mates),
    Assertion("history_exclusions_disjoint_from_legal",
              "nothing history_exclusions(q) forbids is offered by legal_pool(q)",
              _history_exclusions_disjoint_from_legal),
    Assertion("assert_legal_negative_accepts_the_legal_set",
              "the guard accepts every candidate the pool calls legal",
              _assert_legal_negative_accepts_the_legal_set),
    Assertion("assert_legal_negative_refuses_illegal",
              "the guard refuses q itself, its mates and every R2/TINY/UNKNOWN candidate",
              _assert_legal_negative_refuses_illegal),
    Assertion("eligibility_follows_extracted_flags",
              "a row the truth layer withdrew (valid=False / loss_mask=False) is refused by every "
              "implementation -- legal set, guard, confirmed()/negative_eligibility() and history "
              "exclusions alike: eligibility is consumed, never recomputed from the kind",
              _eligibility_follows_extracted_flags),
)

ASSERTION_NAMES: tuple[str, ...] = tuple(a.name for a in ASSERTIONS)


# --------------------------------------------------------------------------------------
# running the battery
# --------------------------------------------------------------------------------------
def check_pool(pool: Any, ctx: ProtocolContext, *, label: str | None = None) -> dict[str, Any]:
    """Run the whole battery against one pool; never raises (the failure *is* the report)."""
    name = str(label or getattr(pool, "pool_id", "") or type(pool).__name__)
    results: list[dict[str, Any]] = []
    failures: list[str] = []
    for assertion in ASSERTIONS:
        problems = assertion.run(pool, ctx)
        results.append({"name": assertion.name, "clause": assertion.clause,
                        "ok": not problems, "failures": problems[:12],
                        "failure_count": len(problems)})
        failures.extend(f"{assertion.name}: {item}" for item in problems)
    kinds = {}
    for fid in ctx.universe():
        kinds[str(pool.relation(fid, fid))] = kinds.get(str(pool.relation(fid, fid)), 0) + 1
    return {
        "schema": "synlab.qc.pool_contract.result.v1",
        "protocol_version": POOL_PROTOCOL_VERSION,
        "label": name,
        "context": ctx.name,
        "implementation": f"{type(pool).__module__}.{type(pool).__name__}",
        "pool_id": str(getattr(pool, "pool_id", "") or ""),
        "universe": len(ctx.universe()),
        "rows": len(ctx.rows),
        "ok": not failures,
        "assertions": results,
        "failed_assertions": sorted({item.split(":", 1)[0] for item in failures}),
        "failures": failures[:64],
        "failure_count": len(failures),
        "self_relation_readings": kinds,
    }


def assert_pool_contract(pool: Any, ctx: ProtocolContext, *, label: str | None = None) -> dict:
    """Run the battery and raise :class:`PoolContractError` when any clause fails."""
    report = check_pool(pool, ctx, label=label)
    if not report["ok"]:
        raise PoolContractError(
            f"{report['label']} ({report['implementation']}) violates the pool protocol "
            f"{POOL_PROTOCOL_VERSION}: {len(report['failed_assertions'])} clause(s) failed "
            f"({', '.join(report['failed_assertions'])})",
            label=report["label"], failures=report["failures"])
    return report


def check_agreement(pools: Mapping[str, Any], ctx: ProtocolContext, *,
                    readings: Sequence[str] = ("mates", "neighbours", "legal_pool"),
                    ) -> dict[str, Any]:
    """Compare implementations on the same context: report every disagreement, hide nothing.

    The contract battery is safety-shaped (each implementation must justify every legal negative
    it offers).  This function measures the *other* half: where the implementations read the same
    thing differently.  A disagreement is reported, never averaged away.

    Two readings are deliberately **not** compared for equality, because the protocol does not
    make them equal:

    * ``history_exclusions`` -- implementations may exclude *more* than the mates (``PoolIndex``
      also excludes ``q`` itself and every ``UNKNOWN``/``TINY``/grey-zone candidate).  The
      battery asserts the two properties that make the name meaningful (superset of the mates,
      disjoint from the legal set) instead.
    * ``relation(a, a)`` -- ``SELF``, ``ABSENT`` and ``UNKNOWN`` are all legal non-adjacency
      readings; only the reading of a **measured kind** has to agree.
    """
    out: dict[str, Any] = {"schema": "synlab.qc.pool_contract.agreement.v1",
                           "protocol_version": POOL_PROTOCOL_VERSION, "context": ctx.name,
                           "readings": list(readings), "disagreements": [], "ok": True}
    labels = sorted(pools)
    for fid in ctx.universe():
        for reading in readings:
            values: dict[str, Any] = {}
            for label in labels:
                fn = getattr(pools[label], reading, None)
                if not callable(fn):
                    values[label] = None
                    continue
                value = fn(fid)
                values[label] = sorted(str(x) for x in value)
            distinct = {tuple(v) for v in values.values() if v is not None}
            if len(distinct) > 1:
                out["disagreements"].append({"fragment": str(fid), "reading": reading,
                                             "values": values})
    for a, b in ctx.ordered_pairs():
        if a >= b:
            continue
        values = {label: str(pools[label].relation(a, b)) for label in labels}
        # a non-adjacency reading is a non-adjacency reading: SELF/ABSENT/UNKNOWN are all legal
        # for a pair that is not a measured adjacency, and the protocol does not choose between
        # them.  A measured kind (R0/R1/R2/TINY_CONTACT/UNKNOWN) is compared verbatim.
        keys = {label: (value if value in MEASURED_KINDS else "<non-adjacency>")
                for label, value in values.items()}
        if len(set(keys.values())) > 1:
            out["disagreements"].append({"pair": [a, b], "reading": "relation", "values": values})
    out["ok"] = not out["disagreements"]
    out["disagreement_count"] = len(out["disagreements"])
    out["disagreements"] = out["disagreements"][:64]
    return out


def classify_divergence(pools: Mapping[str, Any], ctx: ProtocolContext) -> dict[str, Any]:
    """Split the measured divergence into *conservative gaps*, *eligibility findings* and
    *conflicts*, and deduplicate the readers that read identically.

    * **conservative gap** -- a disagreement about a pair **no measured row names**: the exported
      reader answers ``UNKNOWN`` (the table does not name it) while the gallery answers ``R0``
      (``R0`` is implicit for two verified members).  Documented behaviour of the two readers,
      neither of which offers an unjustified legal negative; counted, never hidden, not a failure.
    * **eligibility finding** -- the readers agree on the pair's *kind* but not on whether it may
      be an ordinary negative (one reads the row as usable, the other does not).  This is the
      frozen ``eligible_as_negative := kind in {R0,R1} and valid and loss_mask`` gate
      (``storage.export``, decision D10) being applied by some readers and not others; it is
      reported as a finding with the exact rows, because changing it is a data/eligibility
      decision, not a contract detail.
    * **conflict** -- the readers disagree about the **kind** of a pair a measured row names, or
      about a mate set.  That is the defect class this contract exists for, and it fails the run.

    Readers whose readings are identical are grouped, so one divergence is never counted once per
    pair of labels.
    """
    labels = sorted(pools)

    def _group(values: Mapping[str, Any]) -> dict[str, list[str]]:
        groups: dict[str, list[str]] = {}
        for label, value in values.items():
            groups.setdefault(repr(value), []).append(label)
        return groups

    conflicts: list[dict[str, Any]] = []
    eligibility: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    mate_conflicts: list[dict[str, Any]] = []
    eligibility_keys: set[tuple[str, str]] = set()
    for fid in ctx.universe():
        for reading in ("mates", "neighbours"):
            values = {label: tuple(sorted(str(x) for x in getattr(pools[label], reading)(fid)))
                      for label in labels}
            groups = _group(values)
            if len(groups) > 1:
                mate_conflicts.append({"fragment": str(fid), "reading": reading,
                                       "groups": {key: sorted(val) for key, val in groups.items()}})
        legal = {label: frozenset(str(x) for x in pools[label].legal_pool(fid)) for label in labels}
        groups = _group(legal)
        if len(groups) == 1:
            continue
        group_keys = list(groups)
        for index, left_key in enumerate(group_keys):
            for right_key in group_keys[index + 1:]:
                left = set(legal[groups[left_key][0]])
                right = set(legal[groups[right_key][0]])
                pair = {"fragment": str(fid), "readers": [groups[left_key], groups[right_key]]}
                gap_candidates = []
                eligibility_candidates = []
                kind_candidates = []
                for candidate in sorted(left ^ right):
                    measured = ctx.reference_kind(fid, candidate)
                    if measured is None:
                        gap_candidates.append(candidate)
                        continue
                    kinds = {label: str(pools[label].relation(fid, candidate)) for label in labels}
                    if len(set(kinds.values())) > 1:
                        kind_candidates.append({"candidate": candidate, "measured_kind": measured,
                                                "kinds": kinds})
                    else:
                        eligibility_candidates.append({
                            "candidate": candidate, "measured_kind": measured,
                            "offered_by": groups[left_key] if candidate in left
                            else groups[right_key],
                            "refused_by": groups[right_key] if candidate in left
                            else groups[left_key],
                            "row_valid": ctx.reference_valid(fid, candidate)})
                if gap_candidates:
                    gaps.append({**pair, "reading": "legal_pool", "count": len(gap_candidates),
                                 "examples": gap_candidates[:5],
                                 "reason": ("pairs no measured row names: the exported table is "
                                            "not complete over this universe, so the exported "
                                            "reader answers UNKNOWN and the gallery answers the "
                                            "implicit R0")})
                if eligibility_candidates:
                    for example in eligibility_candidates:
                        eligibility_keys.add((str(fid), str(example["candidate"])))
                    eligibility.append({**pair, "reading": "legal_pool",
                                        "count": len(eligibility_candidates),
                                        "examples": eligibility_candidates[:5],
                                        "reason": ("the readers agree on the kind and disagree "
                                                   "on eligibility: the frozen gate is "
                                                   "eligible_as_negative == (kind in {R0,R1} "
                                                   "and valid and loss_mask)")})
                if kind_candidates:
                    conflicts.append({**pair, "reading": "legal_pool",
                                      "count": len(kind_candidates),
                                      "examples": kind_candidates[:5]})
    conflict_pairs: list[dict[str, Any]] = []
    for a, b in ctx.ordered_pairs():
        if a >= b:
            continue
        values = {label: str(pools[label].relation(a, b)) for label in labels}
        keys = {label: (value if value in MEASURED_KINDS else "<non-adjacency>")
                for label, value in values.items()}
        if len(set(keys.values())) <= 1:
            continue
        item = {"pair": [a, b], "reading": "relation", "values": values,
                "measured_kind": ctx.reference_kind(a, b)}
        if ctx.reference_kind(a, b) is None:
            gaps.append({**item, "count": 1})
        else:
            conflict_pairs.append(item)
    return {
        "schema": "synlab.qc.pool_contract.divergence.v1",
        "protocol_version": POOL_PROTOCOL_VERSION,
        "context": ctx.name,
        "readers": labels,
        "conservative_gaps": len(gaps),
        "eligibility_findings": len(eligibility),
        # distinct (query, candidate) directions behind the findings: a fragment is compared once
        # per pair of *distinct readings*, so the raw item count is not the number of affected
        # pairs -- both are reported.
        "eligibility_pairs": len(eligibility_keys),
        "eligibility_queries": len({key[0] for key in eligibility_keys}),
        "conflicts": len(conflicts) + len(mate_conflicts) + len(conflict_pairs),
        "conflict_examples": (conflicts + mate_conflicts + conflict_pairs)[:16],
        "eligibility_examples": eligibility[:8],
        "gap_examples": gaps[:8],
        "ok": not (conflicts or mate_conflicts or conflict_pairs),
        "note": ("conservative gap = a pair no row names (exported UNKNOWN vs implicit R0); "
                 "eligibility finding = same kind, different eligibility reading (`valid`/"
                 "`loss_mask`); conflict = different kind for the same pair, or a different mate "
                 "set.  Only a conflict fails the run."),
    }


def eligibility_finding(pools: Mapping[str, Any], ctx: ProtocolContext) -> dict[str, Any]:
    """The exact rows behind the eligibility divergence (the finding, stated with real rows).

    A pair is listed when the readers **agree on its kind** but disagree on whether it may be an
    ordinary negative, and the row's own frozen eligibility flag says it may not.  That is the
    ``eligible_as_negative := kind in {R0,R1} and valid and loss_mask`` gate of decision D10
    being applied by some readers and ignored by others.
    """
    labels = sorted(pools)
    directed: dict[tuple[str, str], dict[str, Any]] = {}
    for fid in ctx.universe():
        for candidate in sorted(set(ctx.universe()) - {str(fid)}):
            measured = ctx.reference_kind(fid, candidate)
            if measured not in NEGATIVE_KINDS:
                continue
            row = next((r for r in ctx.rows
                        if {str(r.get("query")), str(r.get("candidate"))}
                        == {str(fid), str(candidate)}), {})
            if bool(row.get("valid", False)):
                continue                      # eligible under every reading: not a finding
            offered = [label for label in labels
                       if candidate in {str(x) for x in pools[label].legal_pool(fid)}]
            refused = [label for label in labels if label not in offered]
            if not offered or not refused:
                continue
            directed[(str(fid), candidate)] = {
                "query": str(fid), "candidate": candidate, "measured_kind": measured,
                "row_valid": bool(row.get("valid", False)),
                "row_loss_mask": bool(row.get("loss_mask", False)),
                "row_eligible_as_negative": row.get("eligible_as_negative"),
                "row_reason": str(row.get("reason", "") or ""),
                "offered_by": offered, "refused_by": refused}
    offered_by: dict[str, int] = {}
    for item in directed.values():
        for label in item["offered_by"]:
            offered_by[label] = offered_by.get(label, 0) + 1
    unordered = {tuple(sorted(key)) for key in directed}
    return {
        "schema": "synlab.qc.pool_contract.eligibility_finding.v1",
        "protocol_version": POOL_PROTOCOL_VERSION,
        "context": ctx.name,
        "directed_pairs": len(directed),
        "unordered_pairs": len(unordered),
        "kinds": sorted({item["measured_kind"] for item in directed.values()}),
        "all_rows_valid_false": bool(directed) and all(not item["row_valid"]
                                                       for item in directed.values()),
        "all_rows_loss_mask_false": bool(directed) and all(not item["row_loss_mask"]
                                                           for item in directed.values()),
        "offered_by_counts": dict(sorted(offered_by.items())),
        "examples": [directed[key] for key in sorted(directed)[:6]],
        "frozen_gate": "eligible_as_negative == (kind in {R0,R1} and valid and loss_mask)",
        "mechanism": ("training.sampler.PoolIndex.confirmed() recomputes confirmation from "
                      "relation() alone (rel in {R0,R1,R2}) instead of asking the carrier's "
                      "confirmed(); relations.gallery.RelationsIndex.confirmed() accepts an "
                      "explicit edge regardless of its valid flag.  So the live pool and the "
                      "sampler's adapter offer rows the exported reader refuses."),
        "one_line_fix": ("RelationsIndex.confirmed(): return False when the stored edge exists "
                         "with valid=False; PoolIndex.confirmed(): return "
                         "self.pool.confirmed(a, b) when the carrier exposes it"),
        "decision": ("reported, not applied: changing either method changes which candidates "
                     "the live sampler draws, i.e. the training data -- a Lead decision, not a "
                     "contract detail (docs/a12/relation_negatives.md)"),
    }


# --------------------------------------------------------------------------------------
# building the four implementations from one context
# --------------------------------------------------------------------------------------
def _lineup_for(ctx: ProtocolContext) -> list[str]:
    if ctx.lineup:
        return [str(f) for f in ctx.lineup]
    seen: list[str] = []
    for row in ctx.rows:
        query, candidate = row_endpoints(row)
        for fid in (query, candidate):
            if fid and fid not in seen:
                seen.append(fid)
    return sorted(seen)


def exported_pool(ctx: ProtocolContext) -> Any:
    from .loader_probe import ExportedRelationPool

    return ExportedRelationPool(list(ctx.rows), pool_id=f"contract::{ctx.name}")


def training_pool_view(ctx: ProtocolContext) -> Any:
    from ..training.smoke import TrainingPoolView

    return TrainingPoolView(list(ctx.rows), lineup=_lineup_for(ctx),
                            pool_id=f"contract::{ctx.name}")


def pool_index(ctx: ProtocolContext, *, carrier: str = "exported") -> Any:
    """``PoolIndex`` over one of the two row-carrier families (the sampler's own reading)."""
    from ..training.sampler import PoolIndex

    base = exported_pool(ctx) if carrier == "exported" else gallery_pool(ctx)
    return PoolIndex(base)


def gallery_pool(ctx: ProtocolContext, *, fragments: Mapping[str, Any] | None = None) -> Any:
    """A real :class:`~synlab.relations.gallery.RelationPool` over the same rows.

    The gallery reading is the one the live pipeline uses: ``R0`` is **implicit** (a pair with no
    explicit edge and two verified members is a confirmed non-adjacency), ``R2``/``R1``/
    ``TINY_CONTACT``/``UNKNOWN`` edges are explicit.  This is why the gallery can offer more legal
    negatives than the conservative exported reader -- the difference is measured by
    :func:`check_agreement`, never assumed away.
    """
    from ..relations.gallery import FragmentRecord, RelationPool, RelationsIndex

    lineup = _lineup_for(ctx)
    index = RelationsIndex()
    index.set_members(lineup)
    for row in ctx.rows:
        query, candidate = row_endpoints(row)
        if not query or not candidate or query == candidate:
            continue
        if query not in lineup or candidate not in lineup:
            continue
        kind = str(row.get("kind", RELATION_R0))
        # Every row of the context goes in, ``R0`` included: an explicit ``R0`` row is a measured
        # non-adjacency and it is what carries that row's ``valid``/``loss_mask`` eligibility flags
        # (``relations.legal_negative``).  Skipping it would make the gallery read the pair as an
        # *implicit* R0 -- i.e. eligible by construction -- which is a different row reading, not
        # the same one.
        index.add(query, candidate, kind,
                  area_mm2=float(row.get("area_mm2") or 0.0),
                  valid=bool(row.get("valid", True)),
                  loss_mask=bool(row.get("loss_mask", True)),
                  reason=str(row.get("reason", "") or ""))
    records: dict[str, FragmentRecord] = dict(fragments or {})
    for fid in lineup:
        records.setdefault(fid, FragmentRecord(fragment_id=fid, lineage_id="", mother_id="",
                                               event_id="", split=""))
    gallery = GallerySpec(pool_id=f"contract::{ctx.name}", gallery_version=POOL_PROTOCOL_VERSION,
                          scope="FULL", lineage_ids=[], fragment_ids=list(lineup),
                          size_target=len(lineup), split="dev",
                          hash=f"sha256:pool-contract:{ctx.name}",
                          meta={"source": "qc.pool_contract", "context": ctx.name})
    return RelationPool(gallery=gallery, fragments=records, index=index, roster=[],
                        historical_neighbours={fid: list(index.neighbours(fid))
                                               for fid in lineup},
                        features={}, gallery_distractor_only=set(),
                        meta={"context": ctx.name})


def build_implementations(ctx: ProtocolContext, *,
                          fragments: Mapping[str, Any] | None = None,
                          index_carriers: Sequence[str] = ("exported", "gallery"),
                          ) -> dict[str, Any]:
    """Instantiate every registered implementation on the **same** context.

    ``PoolIndex`` is a wrapper, so it is instantiated over each carrier family: over the exported
    reader and over the gallery pool.  The result is the list the suite runs the battery against.
    """
    pools: dict[str, Any] = {
        "qc.loader_probe.ExportedRelationPool": exported_pool(ctx),
        "training.smoke.TrainingPoolView": training_pool_view(ctx),
        "relations.gallery.RelationPool": gallery_pool(ctx, fragments=fragments),
    }
    for carrier in index_carriers:
        pools[f"training.sampler.PoolIndex[{carrier}]"] = pool_index(ctx, carrier=carrier)
    return pools


def run_contract_suite(pools: Mapping[str, Any], ctx: ProtocolContext, *,
                       agreement: bool = True) -> dict[str, Any]:
    """Run the battery against every pool and (optionally) the cross-implementation agreement."""
    results = {label: check_pool(pool, ctx, label=label) for label, pool in sorted(pools.items())}
    payload: dict[str, Any] = {
        "schema": "synlab.qc.pool_contract.suite.v1",
        "protocol_version": POOL_PROTOCOL_VERSION,
        "context": {"name": ctx.name, "source": ctx.source, "universe": len(ctx.universe()),
                    "rows": len(ctx.rows), "assertions": list(ASSERTION_NAMES),
                    "duplicate_pairs": ctx.duplicate_pairs(),
                    "notes": dict(ctx.notes)},
        "pools": results,
        "ok": all(item["ok"] for item in results.values()),
        "failed_pools": sorted(label for label, item in results.items() if not item["ok"]),
    }
    if agreement:
        payload["agreement"] = check_agreement(pools, ctx)
        payload["ok"] = bool(payload["ok"] and payload["agreement"]["ok"])
    return payload


# --------------------------------------------------------------------------------------
# failure injection: proof that the suite can fail
# --------------------------------------------------------------------------------------
class _InjectedPool:
    """Base wrapper: delegates everything, breaks exactly one protocol clause."""

    #: assertion that must catch this injection
    expected_assertion = ""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.injection = f"{type(self).__module__}.{type(self).__name__}"

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    @property
    def pool_id(self) -> str:
        return f"injected::{getattr(self.inner, 'pool_id', 'pool')}"


class NeighboursReturnTheNegativeSet(_InjectedPool):
    """Defect (B), verbatim: ``neighbours()`` answers with the confirmed R1/R0 set."""

    expected_assertion = "neighbours_are_mates"

    def neighbours(self, fragment_id: str) -> set[str]:
        return {str(x) for x in self.inner.legal_negatives(fragment_id)}


class HistoryExclusionsDropTheMates(_InjectedPool):
    """``history_exclusions()`` forgets the mates -- the exclusion list that guards sampling."""

    expected_assertion = "history_exclusions_superset_of_mates"

    def history_exclusions(self, fragment_id: str) -> set[str]:
        return set()


class LegalSetOffersAMate(_InjectedPool):
    """``legal_pool()`` offers the query's own mate as an ordinary negative."""

    expected_assertion = "legal_set_excludes_mates"

    def legal_pool(self, fragment_id: str, *, relation: str | None = None) -> list[str]:
        out = [str(x) for x in self.inner.legal_pool(fragment_id, relation=relation)]
        return sorted(set(out) | {str(x) for x in self.inner.mates(fragment_id)})

    def legal_negatives(self, fragment_id: str) -> set[str]:
        return {str(x) for x in self.legal_pool(fragment_id)}


class LegalSetOffersUnknown(_InjectedPool):
    """``legal_pool()`` offers a candidate the pool itself cannot confirm."""

    expected_assertion = "legal_set_only_confirmed_negatives"

    def legal_pool(self, fragment_id: str, *, relation: str | None = None) -> list[str]:
        known = [str(x) for x in self.inner.candidate_ids(fragment_id)]
        unknown = [c for c in known if str(self.inner.relation(fragment_id, c))
                   in (RELATION_UNKNOWN, RELATION_TINY)]
        out = [str(x) for x in self.inner.legal_pool(fragment_id, relation=relation)]
        return sorted(set(out) | set(unknown))

    def legal_negatives(self, fragment_id: str) -> set[str]:
        return {str(x) for x in self.legal_pool(fragment_id)}


class RelationIsAsymmetric(_InjectedPool):
    """``relation(a, b)`` claims R2 in one direction and R0 in the other."""

    expected_assertion = "relation_symmetry"

    def relation(self, a: str, b: str) -> str:
        if str(a) < str(b):
            return RELATION_R2
        return RELATION_R0


class GuardAcceptsAMate(_InjectedPool):
    """``assert_legal_negative()`` stops refusing the query's own mate."""

    expected_assertion = "assert_legal_negative_refuses_illegal"

    def assert_legal_negative(self, query_id: str, candidate_id: str) -> None:
        if str(query_id) == str(candidate_id):
            raise SynLabError(ErrorCode.LEAKAGE_DETECTED, "query as its own negative",
                              stage="qc.pool_contract.injection")
        return None


class EligibilityRecomputedFromTheKind(_InjectedPool):
    """The 9.1.1 defect, verbatim: eligibility recomputed from the **kind** again.

    Both readings the divergence had are injected at once -- ``confirmed()`` answers
    ``relation() in {R0,R1,R2}`` (the ``PoolIndex`` mechanism) and ``legal_pool()`` offers every
    ``R0``/``R1`` candidate the row set withdrew (the ``RelationPool`` mechanism, which never
    looked at ``valid`` for an explicit edge).  ``assert_legal_negative`` is deliberately left
    untouched: the clause must be caught by the eligibility assertion, not by the guard.
    """

    expected_assertion = "eligibility_follows_extracted_flags"

    def negative_eligibility(self, a: str, b: str) -> Any:
        from ..relations.legal_negative import NegativeEligibility

        kind = str(self.inner.relation(a, b))
        return NegativeEligibility(kind in ("R0", "R1", "R2"), KIND_RECOMPUTED,
                                   f"{kind} recomputed from the kind alone", kind)

    def confirmed(self, a: str, b: str) -> bool:
        return str(self.inner.relation(a, b)) in ("R0", "R1", "R2")

    def legal_pool(self, fragment_id: str, *, relation: str | None = None) -> list[str]:
        kind_wanted = None if relation is None else str(relation)
        out = [str(x) for x in self.inner.legal_pool(fragment_id, relation=None)]
        for candidate in self.inner.candidate_ids(fragment_id):
            candidate = str(candidate)
            kind = str(self.inner.relation(fragment_id, candidate))
            if kind not in NEGATIVE_KINDS or candidate in out:
                continue
            if kind_wanted is not None and kind != kind_wanted:
                continue
            out.append(candidate)
        return sorted(dict.fromkeys(out))

    def legal_negatives(self, fragment_id: str) -> set[str]:
        return {str(x) for x in self.legal_pool(fragment_id)}


#: ``{injection name: (wrapper, assertion that must catch it)}``.
FAILURE_INJECTIONS: dict[str, type[_InjectedPool]] = {
    "neighbours_return_the_negative_set": NeighboursReturnTheNegativeSet,
    "history_exclusions_drop_the_mates": HistoryExclusionsDropTheMates,
    "legal_set_offers_a_mate": LegalSetOffersAMate,
    "legal_set_offers_unknown": LegalSetOffersUnknown,
    "relation_is_asymmetric": RelationIsAsymmetric,
    "guard_accepts_a_mate": GuardAcceptsAMate,
    "eligibility_recomputed_from_the_kind": EligibilityRecomputedFromTheKind,
}


def run_failure_injections(ctx: ProtocolContext, *, base: Any | None = None,
                           label: str = "relations.gallery.RelationPool") -> dict[str, Any]:
    """Break one clause at a time and prove the battery catches every injection."""
    inner = base if base is not None else gallery_pool(ctx)
    baseline = check_pool(inner, ctx, label=label)
    out: dict[str, Any] = {
        "schema": "synlab.qc.pool_contract.injection.v1",
        "protocol_version": POOL_PROTOCOL_VERSION,
        "context": ctx.name,
        "base": {"label": label, "ok": baseline["ok"],
                 "failed_assertions": baseline["failed_assertions"]},
        "injections": [],
        "ok": bool(baseline["ok"]),
    }
    for name, wrapper in FAILURE_INJECTIONS.items():
        broken = wrapper(inner)
        report = check_pool(broken, ctx, label=f"injected::{name}")
        caught = wrapper.expected_assertion in report["failed_assertions"]
        out["injections"].append({
            "name": name, "wrapper": f"{wrapper.__module__}.{wrapper.__name__}",
            "expected_assertion": wrapper.expected_assertion,
            "caught": bool(not report["ok"] and caught),
            "failed_assertions": report["failed_assertions"],
            "first_failure": (report["failures"] or [""])[0],
        })
        out["ok"] = bool(out["ok"] and not report["ok"] and caught)
    out["caught"] = sum(1 for item in out["injections"] if item["caught"])
    out["total"] = len(out["injections"])
    return out


# --------------------------------------------------------------------------------------
# the canonical context (the fixture every implementation is instantiated from)
# --------------------------------------------------------------------------------------
#: Fragments of the canonical context: two event chains (mates), one mate-absent event (the legal
#: negative supply) and one isolated distractor, plus the tiny/unknown edges the protocol must
#: refuse.  Small enough to reason about, complete enough that every clause of the battery fires.
CANONICAL_FRAGMENTS: tuple[str, ...] = (
    "a0-m", "a0-p",                                        # event A: mates
    "a1-m", "a1-p",                                        # event A, second pair: mates
    "b0-m", "b0-p", "b1-m", "b1-p",                        # event B: two mate pairs
    "n0", "n1", "n2",                                      # mate-absent negative supply
    "t0",                                                  # tiny-contact fragment
    "u0",                                                  # unknown-edge fragment
    "d0", "d1",                                            # distractor pair (mates, other event)
)


def canonical_rows() -> list[dict[str, Any]]:
    """The canonical relation rows: one row per unordered pair, **complete** over the universe.

    Completeness matters: an explicit ``R0`` row for every non-adjacent pair is what lets the
    conservative exported reader and the implicit-``R0`` gallery reader agree, so the agreement
    check is a real comparison instead of a measurement of how much each reader knows.  The real
    package's table is *not* complete, and that gap is reported separately
    (``tools/a12_n13_pool_contract.py --step real``) rather than hidden by the fixture.
    """
    mates = [("a0-m", "a0-p"), ("a1-m", "a1-p"), ("b0-m", "b0-p"), ("b1-m", "b1-p"),
             ("d0", "d1")]
    r1 = [("a0-p", "b0-m"), ("a1-m", "b0-p"), ("b1-m", "d0")]
    tiny = [("t0", "n0"), ("t0", "a0-m")]
    unknown = [("u0", "n1"), ("u0", "b0-m")]
    rows: list[dict[str, Any]] = []
    for a, b in mates:
        rows.append({"query": a, "candidate": b, "kind": RELATION_R2, "valid": True,
                     "loss_mask": True, "area_mm2": 12.5, "eligible_as_negative": False,
                     "reason": "", "pool_id": "canonical", "split": "dev"})
    for a, b in r1:
        rows.append({"query": a, "candidate": b, "kind": RELATION_R1, "valid": True,
                     "loss_mask": False, "area_mm2": 1.5, "eligible_as_negative": False,
                     "reason": "r1_no_direct_fracture_surface", "pool_id": "canonical",
                     "split": "dev"})
    for a, b in tiny:
        rows.append({"query": a, "candidate": b, "kind": RELATION_TINY, "valid": True,
                     "loss_mask": False, "area_mm2": 0.02, "eligible_as_negative": False,
                     "reason": "tiny_contact", "pool_id": "canonical", "split": "dev"})
    for a, b in unknown:
        rows.append({"query": a, "candidate": b, "kind": RELATION_UNKNOWN, "valid": False,
                     "loss_mask": False, "area_mm2": 0.0, "eligible_as_negative": False,
                     "reason": "unmeasured_pair", "pool_id": "canonical", "split": "dev"})
    named = {tuple(sorted(pair)) for pair in mates + r1 + tiny + unknown}
    for index, a in enumerate(CANONICAL_FRAGMENTS):
        for b in CANONICAL_FRAGMENTS[index + 1:]:
            if tuple(sorted((a, b))) in named:
                continue
            rows.append({"query": a, "candidate": b, "kind": RELATION_R0, "valid": True,
                         "loss_mask": True, "area_mm2": 0.0, "eligible_as_negative": True,
                         "reason": "", "pool_id": "canonical", "split": "dev"})
    return rows


def canonical_context() -> ProtocolContext:
    """The canonical context: everything the battery needs, in one deterministic row set."""
    return ProtocolContext(
        name="canonical",
        lineup=CANONICAL_FRAGMENTS,
        rows=tuple(canonical_rows()),
        source="synlab.qc.pool_contract.canonical_rows()",
        notes={"mates": [["a0-m", "a0-p"], ["a1-m", "a1-p"], ["b0-m", "b0-p"],
                         ["b1-m", "b1-p"], ["d0", "d1"]],
               "mate_absent_fragments": ["n0", "n1", "n2"],
               "complete_over_the_universe": True,
               "role": "the fixture every implementation is instantiated from"})


__all__ = [
    "POOL_PROTOCOL_VERSION", "IMPLEMENTATIONS", "PROTOCOL_METHODS", "MEASURED_KINDS",
    "FORBIDDEN_NEGATIVE_KINDS", "UNMEASURED_KINDS", "NON_ADJACENCY_READINGS",
    "PoolContractError", "ProtocolContext", "Assertion", "ASSERTIONS", "ASSERTION_NAMES",
    "row_endpoints", "reference_rows", "reference_mates",
    "check_pool", "assert_pool_contract", "check_agreement", "classify_divergence",
    "eligibility_finding", "run_contract_suite",
    "exported_pool", "training_pool_view", "pool_index", "gallery_pool", "build_implementations",
    "FAILURE_INJECTIONS", "run_failure_injections",
    "CANONICAL_FRAGMENTS", "canonical_rows", "canonical_context",
]
