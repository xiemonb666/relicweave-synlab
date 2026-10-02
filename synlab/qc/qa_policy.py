"""Versioned QA policy: the layer that turns a *recorded* check into a *failure code* (N9).

The gap this module closes
--------------------------
``synlab.physical.api.audit_physical`` measures the out-of-ROI drift of a delivered body and
records it::

    checks["roi_external_drift"] = {"max_mm": <drift>, "pass": bool(drift <= 1e-3)}

but it **never appends a failure code** for it.  A body whose extracted geometry drifted
**0.354 mm** outside the ROI therefore shipped with ``audit status = PASS`` and
``failure_codes = []`` (``docs/a12/smallfixes_report.md`` §S11, measured on the P03 global-SDF
path; the narrowband path measures ``0.000348 mm`` and passes).  A check that cannot fail is not
a check.

``synlab/physical/**`` is outside this task's write scope, so the tightening is implemented
**here**, as an explicit, versioned QA policy that consumes a produced audit and re-derives the
verdict from it.  Nothing is re-measured and nothing is inferred: the policy reads the measured
``pass`` flag (or the measured value against the audit's own threshold) and only ever **adds**
failure codes.  It can never turn a ``FAIL`` into a ``PASS``.

Versioning (engineering policy R5: "any threshold change needs a version plus a recorded reason")
------------------------------------------------------------------------------------------------
:data:`QA_POLICY_VERSION` is the policy in force; :data:`QA_POLICY_HISTORY` records every version
with its change, its reason and its measured evidence.  An audit that has been through this layer
carries a ``qa_policy`` block naming the version that produced its verdict, so a stored verdict is
always attributable to a policy -- and an audit *without* that block is a pre-policy (v1) record,
which is exactly how the already-produced artifacts are recognised and labelled (they are **not**
rewritten; see ``tools/a12_n9_qa_tighten.py``).

What this layer deliberately does **not** do
--------------------------------------------
* it does not re-measure anything, and it does not need the geometry;
* it does not lower a threshold, drop a failure code or upgrade a status;
* it does not modify the frozen producer: an audit written by ``audit_physical`` is still a v1
  audit until this layer is applied to it.  Stamping the version at the commit boundary belongs
  in ``synlab/physical/api.py`` (out of scope here) -- recorded as a residual gap, not hidden.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

#: The QA policy in force.  Bump it whenever a clause below changes.
QA_POLICY_VERSION = "a12.qa.v2"

#: Every version this repository has applied, with the measured reason for the change.
QA_POLICY_HISTORY: tuple[dict[str, Any], ...] = (
    {
        "version": "a12.qa.v1",
        "status": "superseded",
        "change": "baseline: audit_physical records checks['roi_external_drift'] with a pass flag "
                  "but no failure code",
        "effect": ("a delivered body with 0.354 mm out-of-ROI drift reports status=PASS with "
                   "failure_codes=[] on the global SDF path"),
        "evidence": ["docs/a12/smallfixes_report.md §S11",
                     "data/a12_reports/s11_p03_drift.json"],
    },
    {
        "version": "a12.qa.v2",
        "status": "current",
        "change": ("a failed roi_external_drift check joins failure_codes as "
                   f"{'ROI_EXTERNAL_DRIFT_EXCEEDED'} and the status becomes FAIL"),
        "reason": ("the check is measured against a real threshold (1e-3 mm) and the frozen "
                   "producer already computes pass=false; not using it was the only reason a "
                   "0.354 mm drift shipped as PASS"),
        "effect": ("every audit whose measured drift exceeds the recorded threshold flips from "
                   "PASS to FAIL; the narrowband path (0.000348 mm) still passes"),
        "policy": "R5 (no relaxation): the change only adds failure codes",
        "evidence": ["data/a12_reports/n9_qa_v2.json"],
    },
)

#: Failure code the v2 policy adds.
DRIFT_FAILURE_CODE = "ROI_EXTERNAL_DRIFT_EXCEEDED"

#: The check name in ``audit_physical``'s ``checks`` block.
DRIFT_CHECK = "roi_external_drift"

#: The frozen threshold the producer itself used (``physical/api.py``: ``drift <= 1e-3``).
DRIFT_MAX_MM_DEFAULT = 1e-3

#: Audit keys that carry the identity of the audited thing (copied into the flip record).
_IDENTITY_KEYS = ("axis_id", "variant", "level", "recipe_id", "fragment_id", "component_id",
                  "asset_id", "run_id", "source")


def qa_policy_version(audit: Mapping[str, Any] | None) -> str:
    """The policy version an audit's verdict was produced by.

    ``a12.qa.v1`` when the record carries no ``qa_policy`` block (i.e. it was written before this
    layer existed) -- that is the label the already-produced artifacts are handled with.
    """
    block = (audit or {}).get("qa_policy")
    if isinstance(block, Mapping) and block.get("version"):
        return str(block["version"])
    return "a12.qa.v1"


def drift_reading(audit: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The measured drift check of an audit, or ``None`` when the audit does not carry one."""
    check = ((audit or {}).get("checks") or {}).get(DRIFT_CHECK)
    if not isinstance(check, Mapping):
        return None
    value = check.get("max_mm", check.get("drift_mm"))
    threshold = check.get("threshold_mm", check.get("max_allowed_mm", DRIFT_MAX_MM_DEFAULT))
    passed = check.get("pass")
    if passed is None and value is not None:
        # the producer's own rule, re-derived only when the producer did not record a verdict
        passed = bool(float(value) <= float(threshold))
    return {"max_mm": None if value is None else float(value),
            "threshold_mm": float(threshold), "pass": None if passed is None else bool(passed),
            "declared_pass": check.get("pass")}


def apply_qa_policy(audit: Mapping[str, Any], *, version: str = QA_POLICY_VERSION,
                    ) -> dict[str, Any]:
    """Return ``audit`` under the current QA policy (a copy; the input is never mutated).

    Only additions: ``failure_codes`` gains :data:`DRIFT_FAILURE_CODE` when the measured drift
    check failed, ``status`` becomes ``FAIL`` in that case, and the verdict is stamped with the
    policy version and the clauses that fired.  Idempotent.
    """
    out = dict(audit)
    checks = dict(out.get("checks") or {})
    codes = [str(code) for code in (out.get("failure_codes") or [])]
    previous = qa_policy_version(out)
    applied: list[dict[str, Any]] = []

    reading = drift_reading(out)
    if reading is not None and reading["pass"] is False and DRIFT_FAILURE_CODE not in codes:
        codes.append(DRIFT_FAILURE_CODE)
        applied.append({
            "clause": "roi_external_drift_must_fail_the_audit",
            "failure_code": DRIFT_FAILURE_CODE,
            "measured_mm": reading["max_mm"],
            "threshold_mm": reading["threshold_mm"],
            "reason": ("the producer measured the drift and computed pass=false, but recorded no "
                       "failure code; the policy turns the recorded verdict into a failure code"),
        })

    out["failure_codes"] = codes
    out["checks"] = checks
    if applied:
        out["status"] = "FAIL"
    out["qa_policy"] = {
        "version": str(version),
        "previous_version": previous,
        "applied": applied,
        "clauses": [str(item["clause"]) for item in applied],
        "history": [dict(item) for item in QA_POLICY_HISTORY],
        "changelog": ("drift checks that the frozen producer marks as failed now join "
                      "failure_codes; no code is removed and no status is upgraded"),
    }
    return out


def tighten_audits(audits: Iterable[Mapping[str, Any]], **kwargs: Any) -> list[dict[str, Any]]:
    """Apply the policy to a stream of audits (a list comprehension with the semantics named)."""
    return [apply_qa_policy(audit, **kwargs) for audit in audits]


def audit_verdict(audit: Mapping[str, Any]) -> dict[str, Any]:
    """``{path-level facts}`` of one audit, before and after the policy (for a flip list)."""
    before_status = str(audit.get("status", "") or _status_from_codes(audit))
    tightened = apply_qa_policy(audit)
    after_status = str(tightened.get("status", "") or _status_from_codes(tightened))
    reading = drift_reading(audit)
    return {
        "qa_policy_before": qa_policy_version(audit),
        "qa_policy_after": qa_policy_version(tightened),
        "status_before": before_status,
        "status_after": after_status,
        "failure_codes_before": [str(c) for c in (audit.get("failure_codes") or [])],
        "failure_codes_after": [str(c) for c in (tightened.get("failure_codes") or [])],
        "added_failure_codes": sorted(set(str(c) for c in (tightened.get("failure_codes") or []))
                                      - set(str(c) for c in (audit.get("failure_codes") or []))),
        "flips": bool(before_status.upper() == "PASS" and after_status.upper() == "FAIL"),
        "drift_mm": None if reading is None else reading["max_mm"],
        "drift_pass": None if reading is None else reading["pass"],
        "threshold_mm": None if reading is None else reading["threshold_mm"],
        "identity": {key: audit[key] for key in _IDENTITY_KEYS if key in audit},
    }


def _status_from_codes(audit: Mapping[str, Any]) -> str:
    codes = list(audit.get("failure_codes") or [])
    if codes:
        return "FAIL"
    return "PASS" if "checks" in audit else "UNKNOWN"


def looks_like_audit(value: Any) -> bool:
    """Heuristic the scanner uses: a dict carrying a ``checks`` block and a verdict-shaped key."""
    return (isinstance(value, Mapping) and isinstance(value.get("checks"), Mapping)
            and any(key in value for key in ("status", "failure_codes", "axis_id", "measured")))


__all__ = [
    "QA_POLICY_VERSION", "QA_POLICY_HISTORY", "DRIFT_FAILURE_CODE", "DRIFT_CHECK",
    "DRIFT_MAX_MM_DEFAULT", "qa_policy_version", "drift_reading", "apply_qa_policy",
    "tighten_audits", "audit_verdict", "looks_like_audit",
]
