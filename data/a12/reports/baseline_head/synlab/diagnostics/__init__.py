"""Degradation diagnostics: frozen metrics, clustered statistics and report artifacts.

Public entry points:

``synlab.diagnostics.api``
    :func:`run_diagnosis`, :func:`pool_metrics`, :func:`paired_bootstrap`,
    :func:`risk_upper_bound`.
``synlab.diagnostics.fixtures``
    :func:`run_fixtures` -- hand-computed metric/statistics expectation fixtures.
"""

from __future__ import annotations

from .api import (
    API_VERSION,
    paired_bootstrap,
    pool_metrics,
    risk_upper_bound,
    run_diagnosis,
    run_from_config,
)
from .fixtures import run_fixtures
from .metrics import (
    DEFAULT_TOP_K,
    accept_set,
    aggregate_metrics,
    any_at_m,
    conditional_cov,
    cov_recall_at_k,
    effective_cov_at_k,
    effective_hit_at_k,
    hit_at_k,
    per_query_table,
    pool_cov_at_m,
    query_metrics,
    risk_events,
)
from .runner import (
    CallableScorer,
    CheckpointScorer,
    ClassicalScorer,
    DiagnosticRunner,
    write_reports,
)
from .stats import (
    BOOTSTRAP_UNIT,
    clopper_pearson_upper,
    holm_correction,
    n90,
    paired_bootstrap_ci,
    power_approx,
    risk_bound_table,
    zeron_event_units,
)

__all__ = [
    "API_VERSION", "run_diagnosis", "run_from_config", "pool_metrics", "paired_bootstrap",
    "risk_upper_bound", "run_fixtures", "DEFAULT_TOP_K", "hit_at_k", "cov_recall_at_k",
    "any_at_m", "pool_cov_at_m", "conditional_cov", "accept_set", "effective_hit_at_k",
    "effective_cov_at_k", "risk_events", "query_metrics", "aggregate_metrics",
    "per_query_table", "DiagnosticRunner", "CallableScorer", "ClassicalScorer",
    "CheckpointScorer", "write_reports", "BOOTSTRAP_UNIT", "paired_bootstrap_ci",
    "holm_correction", "clopper_pearson_upper", "zeron_event_units", "risk_bound_table",
    "power_approx", "n90",
]
