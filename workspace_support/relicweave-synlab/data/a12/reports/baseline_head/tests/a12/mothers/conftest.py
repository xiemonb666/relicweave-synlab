"""Shared fixtures for the A12 mother tests (plan 7).

One mother per registered vessel is built and audited once per session; the per-vessel
parameter-influence checks reuse the same default parameter set.  Nothing here substitutes a
fixture for a failed build: a vessel that cannot produce a real mother fails the test that
asked for it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:  # pragma: no cover - import guard for direct execution
    sys.path.insert(0, str(REPO_ROOT))

from synlab.mothers.api import (audit_mother, canonical_params, create_mother,  # noqa: E402
                                default_params, vessel_ids)
from synlab.seeds import make_rng  # noqa: E402

#: Seed used for the deterministic replay checks.
SEED_A = 20240517
SEED_B = 991
#: Test-time audit budget: the full audit (including the complete self-intersection scan) is
#: exercised for the vessels the QA tests select; the session fixture keeps a smaller probe
#: count so the whole suite stays inside the CPU budget of this host.  Both are real runs of
#: ``synlab.mothers.audit``, only ``max_thickness_probes`` differs.
FIXTURE_THICKNESS_PROBES = 96


@pytest.fixture(scope="session")
def registered_vessels() -> list[str]:
    ids = vessel_ids()
    assert ids, "no vessel is registered"
    return ids


@pytest.fixture(scope="session")
def mother_case(registered_vessels):
    """``{vessel_id: (mother, audit_report, params)}`` for every registered vessel."""

    cases: dict[str, tuple] = {}
    failures: list[str] = []
    for index, vessel_id in enumerate(registered_vessels):
        params = default_params(vessel_id)
        try:
            mother = create_mother(vessel_id, "M01", params, make_rng(SEED_A, "shape"),
                                   mother_id=f"{vessel_id}-fixture")
            report = audit_mother(mother, max_thickness_probes=FIXTURE_THICKNESS_PROBES)
        except Exception as exc:  # noqa: BLE001 - reported as a test failure, not hidden
            failures.append(f"{vessel_id}: {type(exc).__name__}: {exc}")
            continue
        cases[vessel_id] = (mother, report, params)
    if failures:
        pytest.fail("vessels that could not produce an audited mother:\n" + "\n".join(failures))
    return cases


def perturbed_params(vessel_id: str, params: dict, field: str) -> dict:
    """A parameter dict with ``field`` moved to the far end of its registered range."""
    from synlab.mothers.api import sampler_spec

    spec = sampler_spec(vessel_id)
    info = spec.get(field)
    out = dict(params)
    if info is None:
        # a field that is not sampled (a construction switch): flip it instead of skipping,
        # so "at least three real shape parameters" is checked on the *declared* list only
        current = params.get(field)
        if isinstance(current, bool):
            out[field] = not current
        else:
            raise AssertionError(f"{vessel_id}: {field!r} has no registered range to vary")
        return canonical_params(vessel_id, out)
    current = float(params[field])
    low, high = float(info["low"]), float(info["high"])
    target = high if abs(current - low) < abs(current - high) else low
    if info["int"]:
        target = float(int(round(target)))
    out[field] = int(round(target)) if info["int"] else float(target)
    return canonical_params(vessel_id, out)


__all__ = ["SEED_A", "SEED_B", "FIXTURE_THICKNESS_PROBES", "perturbed_params"]
