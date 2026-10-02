"""**The one truth source for negative eligibility** (decision D10, tightened by the Lead ruling).

Why this module exists
----------------------
``docs/a12/relation_negatives.md`` §9.1.1 recorded a real divergence between the four parallel
relation-pool readers: three of them decided whether a measured pair could serve as an *ordinary
negative* by looking at the pair's **kind** alone, so 24 ``R1`` rows (48 directed pairs) that the
truth layer had **withdrawn** -- ``valid=False``, ``loss_mask=False``,
``reason="no_direct_fracture_surface"`` -- were still supplied as negatives by
``relations.gallery.RelationPool``, ``training.sampler.PoolIndex[exported]`` and
``training.sampler.PoolIndex[gallery]``, while ``qc.loader_probe.ExportedRelationPool`` and
``training.smoke.TrainingPoolView`` refused them.

Following rule **R2** (make the property hold by construction) the fix is not "call the other
method": it is that eligibility has exactly **one** definition and every implementation
**consumes** it.  That definition is :func:`resolve_negative_eligibility`::

    eligible_as_negative := kind in {R0, R1} and valid and loss_mask

A reader never derives it from the kind again.  It reads the three inputs from its own truth layer
(an exported table row, a stored relation edge, an implicit-``R0`` construction) and hands them to
this function, which is the only place the rule lives.  The result carries the refusal **reason**
so a consumer can say *why* a candidate was not offered instead of silently dropping it.

Missing fields are a **refusal**, never an assumption
-----------------------------------------------------
An input that does not carry the flags cannot confirm the gate, and *"cannot confirm"* must never
become *"supply it anyway"*: that is exactly the recomputation the ruling forbids.  A missing flag
is therefore reported as :data:`MISSING_FLAGS` and refuses.  The one documented exception is the
**kind-only row** (a row with *no* flag vocabulary at all: no ``valid``, no ``loss_mask``, no
``eligible_as_negative``), which is a synthetic/pre-contract row rather than a withdrawn
measurement; it is resolved from the kind alone and labelled :data:`KIND_ONLY_ROW` so no report
can mistake it for a flag-bearing measurement.  Every real exported table carries the flags.

The frozen gate is also *cross-checked*: when a row carries ``eligible_as_negative`` and it
contradicts the gate computed from ``(kind, valid, loss_mask)``, that row is a table defect and the
resolution refuses it (:data:`FLAG_CONFLICT`) instead of quietly preferring one side.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

__all__ = [
    "NEGATIVE_KINDS", "NegativeEligibility", "resolve_negative_eligibility", "flags_from_row",
    "adjacency_eligibility", "ELIGIBLE", "KIND_NOT_NEGATIVE", "ROW_INVALID", "LOSS_MASK_OFF",
    "FLAG_CONFLICT", "MISSING_FLAGS", "NOT_A_MEMBER", "SELF_PAIR", "KIND_ONLY_ROW",
    "MISSING", "FROZEN_GATE", "ELIGIBILITY_SOURCE",
]

#: Relation kinds an ordinary negative may carry (``storage.export.NEGATIVE_KINDS``).
NEGATIVE_KINDS: tuple[str, ...] = ("R1", "R0")

#: The frozen gate, as one string, for reports (``storage.export`` decision D10).
FROZEN_GATE = "eligible_as_negative == (kind in {R0,R1} and valid and loss_mask)"

#: Where eligibility comes from: the exported row's own extracted flags.  Reported by every
#: consumer so a reader that resolved it differently is visible instead of assumed.
ELIGIBILITY_SOURCE = "truth_row_flags(valid,loss_mask,eligible_as_negative)"

# ---- reason codes (machine readable, stable; the human sentence is ``detail``) ------------
ELIGIBLE = "eligible"
KIND_NOT_NEGATIVE = "kind_not_a_negative_kind"
ROW_INVALID = "row_valid_false"
LOSS_MASK_OFF = "loss_mask_false"
FLAG_CONFLICT = "eligible_as_negative_conflicts_with_the_gate"
MISSING_FLAGS = "row_carries_no_valid_loss_mask_flags"
KIND_ONLY_ROW = "kind_only_row_without_flag_vocabulary"
NOT_A_MEMBER = "fragment_not_a_pool_member"
SELF_PAIR = "query_is_its_own_candidate"

#: Sentinel for "this input does not carry the field" (distinct from a stored ``False``).
MISSING: Any = object()


@dataclass(frozen=True)
class NegativeEligibility:
    """The resolved answer for one directed pair under the frozen gate."""

    eligible: bool
    reason: str
    detail: str = ""
    kind: str = ""
    valid: bool | None = None
    loss_mask: bool | None = None
    source: str = ELIGIBILITY_SOURCE

    def as_dict(self) -> dict[str, Any]:
        return {"eligible": bool(self.eligible), "reason": self.reason, "detail": self.detail,
                "kind": self.kind, "valid": self.valid, "loss_mask": self.loss_mask,
                "source": self.source}


def _flag(value: Any) -> bool | None:
    return None if value is None or value is MISSING else bool(value)


def resolve_negative_eligibility(kind: Any, valid: Any = MISSING, loss_mask: Any = MISSING, *,
                                 eligible_as_negative: Any = MISSING, reason: str = "",
                                 source: str = ELIGIBILITY_SOURCE) -> NegativeEligibility:
    """The **only** place the ordinary-negative gate is decided.

    Parameters
    ----------
    kind
        The measured relation kind of the directed pair (``R0``/``R1``/``R2``/``TINY_CONTACT``/
        ``UNKNOWN``).
    valid, loss_mask
        The row's own extracted flags.  :data:`MISSING` (or ``None``) means *"this input does not
        carry the field"* -- which refuses, unless the *whole* flag vocabulary is absent (the
        kind-only row case).
    eligible_as_negative
        The row's frozen eligibility flag, when the truth layer wrote one.  It is a
        **cross-check**, not an override: a contradiction refuses the row.
    """
    kind = str(kind or "")
    has_flags = not (valid is MISSING or valid is None) or not (loss_mask is MISSING
                                                               or loss_mask is None)
    explicit = _flag(eligible_as_negative) if eligible_as_negative is not MISSING else None
    valid_b, mask_b = _flag(valid), _flag(loss_mask)
    if not has_flags and explicit is None:
        # a synthetic/pre-contract row: no flag vocabulary at all.  Resolved from the kind so
        # such a fixture keeps working, and *labelled* so no report mistakes it for a measurement.
        eligible = kind in NEGATIVE_KINDS
        return NegativeEligibility(
            eligible, KIND_ONLY_ROW if eligible else KIND_NOT_NEGATIVE,
            f"{kind} row without valid/loss_mask/eligible_as_negative: resolved from the kind "
            f"alone ({ELIGIBILITY_SOURCE} unavailable)", kind, None, None, source)
    if not has_flags:
        return NegativeEligibility(
            False, MISSING_FLAGS,
            f"{kind} row carries neither valid nor loss_mask, so the gate "
            f"(kind in {list(NEGATIVE_KINDS)} and valid and loss_mask) cannot be confirmed: "
            f"refused (no supply without confirmation)", kind, valid_b, mask_b, source)
    gate = bool(kind in NEGATIVE_KINDS and valid_b is True and mask_b is True)
    if explicit is not None and bool(explicit) != gate:
        return NegativeEligibility(
            False, FLAG_CONFLICT,
            f"{kind} row says eligible_as_negative={bool(explicit)} but its own flags resolve to "
            f"{gate} (valid={valid_b}, loss_mask={mask_b}): contradicting table, refused",
            kind, valid_b, mask_b, source)
    if kind not in NEGATIVE_KINDS:
        return NegativeEligibility(False, KIND_NOT_NEGATIVE,
                                   f"{kind} is not an ordinary-negative kind "
                                   f"({list(NEGATIVE_KINDS)} only)", kind, valid_b, mask_b, source)
    if valid_b is not True:
        return NegativeEligibility(False, ROW_INVALID,
                                   f"the {kind} row is not usable (valid=False)"
                                   + (f": {reason}" if reason else ""),
                                   kind, valid_b, mask_b, source)
    if mask_b is not True:
        return NegativeEligibility(False, LOSS_MASK_OFF,
                                   f"the {kind} row is outside the supervised set "
                                   f"(loss_mask=False)" + (f": {reason}" if reason else ""),
                                   kind, valid_b, mask_b, source)
    return NegativeEligibility(True, ELIGIBLE,
                               f"{kind} row with valid=True and loss_mask=True", kind, True, True,
                               source)


def adjacency_eligibility(kind: Any, valid: Any = MISSING, *, reason: str = "",
                          source: str = ELIGIBILITY_SOURCE) -> NegativeEligibility:
    """Usable-*measurement* reading (``valid`` only), for historical mate sets.

    A mate set is not a negative set: ``kind == R2 and valid``.  The same rule applies to a missing
    flag (refuse, never assume) except for the kind-only row, for which the kind alone decides.
    """
    kind = str(kind or "")
    if (valid is MISSING or valid is None):
        eligible = kind == "R2"
        return NegativeEligibility(eligible, KIND_ONLY_ROW if eligible else ROW_INVALID,
                                   f"{kind} row without a valid flag: resolved from the kind alone",
                                   kind, None, None, source)
    ok = bool(kind == "R2" and bool(valid))
    return NegativeEligibility(ok, ELIGIBLE if ok else (ROW_INVALID if kind == "R2"
                                                        else KIND_NOT_NEGATIVE),
                               f"{kind} row with valid={bool(valid)}"
                               + (f": {reason}" if reason else ""),
                               kind, bool(valid), None, source)


def flags_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """The three eligibility inputs of a table row, with :data:`MISSING` for absent fields.

    Handing the *sentinel* through (instead of defaulting to ``False``) is what lets
    :func:`resolve_negative_eligibility` tell "the row says no" from "the row says nothing".
    """
    return {"kind": row.get("kind", MISSING) if row.get("kind") is not None else MISSING,
            "valid": row.get("valid", MISSING),
            "loss_mask": row.get("loss_mask", MISSING),
            "eligible_as_negative": row.get("eligible_as_negative", MISSING),
            "reason": str(row.get("reason", "") or "")}
