"""Statistics for A12 diagnostics: clustered bootstrap, Holm, Clopper-Pearson, power (plan 19.4, 30.15).

Every number is computed from the supplied measurements; no curve is smoothed and no
interval is claimed without its unit.  The primary statistical unit is the independent
**shape lineage** cluster -- fragments, views, quality levels and seeds are repeats *inside*
a cluster and may never be counted as independent ``n``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

#: Frozen statistical unit (plan 19.4 / ``DiagnosticStatistics.unit``).
BOOTSTRAP_UNIT = "shape_lineage"

DEFAULT_REPLICATES = 10000
DEFAULT_CONFIDENCE = 0.95


# --------------------------------------------------------------------------------------
# paired clustered bootstrap
# --------------------------------------------------------------------------------------
def _clusters(paired: Any) -> dict[str, list[float]]:
    """Normalise accepted inputs into ``{cluster: [values]}`` (paired within a cluster)."""
    out: dict[str, list[float]] = {}
    if isinstance(paired, Mapping):
        for key, value in paired.items():
            if isinstance(value, (int, float, np.floating, np.integer)):
                out.setdefault(str(key), []).append(float(value))
            else:
                out.setdefault(str(key), []).extend(float(v) for v in value)
        return out
    for item in paired or []:
        if isinstance(item, Mapping):
            key = str(item.get("cluster", item.get("lineage_cluster", "UNKNOWN")))
            out.setdefault(key, []).append(float(item.get("delta", item.get("value", 0.0))))
        elif isinstance(item, (tuple, list)) and len(item) >= 2:
            out.setdefault(str(item[0]), []).append(float(item[1]))
        else:
            out.setdefault("UNKNOWN", []).append(float(item))
    return out


def paired_bootstrap_ci(paired: Any, *, unit: str = BOOTSTRAP_UNIT,
                        replicates: int = DEFAULT_REPLICATES,
                        confidence: float = DEFAULT_CONFIDENCE,
                        alpha: float | None = None,
                        rng: np.random.Generator | None = None,
                        statistic: str = "mean",
                        null_delta: float = 0.0,
                        seed: int = 20261001) -> dict[str, Any]:
    """Cluster bootstrap of the paired difference (default 10000 resamples).

    Resampling happens **at the lineage-cluster level**: a cluster is drawn whole, so the
    within-cluster repeats (fragments, views, quality levels, seeds) keep their real
    correlation and never inflate ``n``.
    """
    clusters = _clusters(paired)
    per_cluster = {key: float(np.mean(values)) for key, values in clusters.items() if values}
    values_all = [v for values in clusters.values() for v in values]
    n_clusters = len(per_cluster)
    keys = sorted(per_cluster)
    point = float(np.mean([per_cluster[k] for k in keys])) if keys else None
    conf = float(confidence if alpha is None else 1.0 - float(alpha))
    report: dict[str, Any] = {
        "unit": str(unit),
        "requested_unit": str(unit),
        "unit_is_shape_lineage": str(unit) == BOOTSTRAP_UNIT,
        "replicates": int(replicates),
        "confidence": conf,
        "n_clusters": n_clusters,
        "n_observations": len(values_all),
        "mean_delta": point,
        "null_delta": float(null_delta),
        "per_cluster_mean": per_cluster,
        "statistic": str(statistic),
        "degenerate": None,
        "ok": True,
    }
    if n_clusters == 0:
        report.update({"ok": False, "ci_low": None, "ci_high": None, "degenerate":
                       "no paired observations"})
        return report
    if n_clusters == 1:
        report.update({"ci_low": None, "ci_high": None, "degenerate":
                       "single cluster: the bootstrap cannot estimate between-cluster variance",
                       "ok": False})
        return report
    rng = rng if rng is not None else np.random.default_rng(int(seed))
    values = np.asarray([per_cluster[k] for k in keys], dtype=np.float64)
    draws = rng.integers(0, n_clusters, size=(int(replicates), n_clusters))
    samples = values[draws]
    stats = samples.mean(axis=1) if statistic == "mean" else np.median(samples, axis=1)
    lo_q = 100.0 * (1.0 - conf) / 2.0
    hi_q = 100.0 * (1.0 + conf) / 2.0
    ci_low, ci_high = np.percentile(stats, [lo_q, hi_q])
    report.update({
        "ci_low": float(ci_low),
        "ci_high": float(ci_high),
        "bootstrap_sd": float(np.std(stats, ddof=1)) if stats.size > 1 else 0.0,
        "excludes_null": bool(float(ci_low) > float(null_delta)
                              or float(ci_high) < float(null_delta)),
        "direction": ("positive" if point is not None and point > null_delta else
                      ("negative" if point is not None and point < null_delta else "zero")),
    })
    return report


def macro_mean_by_stratum(rows: Sequence[Mapping[str, Any]], *, value_key: str,
                          stratum_key: str) -> dict[str, Any]:
    """Macro average over strata plus the worst stratum (plan 19.4 requirement)."""
    strata: dict[str, list[float]] = {}
    for row in rows:
        value = row.get(value_key)
        if value is None:
            continue
        strata.setdefault(str(row.get(stratum_key, "UNKNOWN")), []).append(float(value))
    means = {key: float(np.mean(values)) for key, values in strata.items() if values}
    if not means:
        return {"ok": False, "macro_mean": None, "worst_stratum": None, "strata": {}}
    worst = min(means, key=lambda k: means[k])
    return {"ok": True, "macro_mean": float(np.mean(list(means.values()))),
            "worst_stratum": {"name": worst, "value": means[worst]}, "strata": means,
            "n_strata": len(means)}


# --------------------------------------------------------------------------------------
# multiple testing
# --------------------------------------------------------------------------------------
def holm_correction(pvalues: Mapping[str, float] | Sequence[float], *, alpha: float = 0.05,
                    labels: Sequence[str] | None = None) -> dict[str, Any]:
    """Holm step-down correction; returns adjusted p-values and per-comparison verdicts."""
    if isinstance(pvalues, Mapping):
        items = [(str(k), float(v)) for k, v in pvalues.items()]
    else:
        names = list(labels) if labels is not None else [f"h{i}" for i in range(len(pvalues))]
        items = list(zip(names, [float(v) for v in pvalues]))
    m = len(items)
    if m == 0:
        return {"ok": False, "method": "holm", "alpha": float(alpha), "adjusted": {},
                "rejected": {}, "reason": "no comparisons"}
    ordered = sorted(items, key=lambda kv: kv[1])
    adjusted: dict[str, float] = {}
    running = 0.0
    for rank, (name, p) in enumerate(ordered):
        factor = m - rank
        value = min(1.0, max(running, p * factor))
        running = value
        adjusted[name] = value
    rejected = {name: bool(adjusted[name] <= alpha) for name, _ in items}
    return {"ok": True, "method": "holm", "alpha": float(alpha), "m": m,
            "adjusted": adjusted, "rejected": rejected,
            "n_rejected": int(sum(rejected.values())),
            "note": "family-wise correction for the registered comparisons only"}


# --------------------------------------------------------------------------------------
# Clopper-Pearson risk upper bound
# --------------------------------------------------------------------------------------
def clopper_pearson_upper(events: int, n: int, alpha: float = 0.05) -> float:
    """One-sided ``1 - alpha`` Clopper-Pearson upper bound for a binomial event rate.

    ``e = 0`` uses the closed form ``1 - alpha**(1/n)`` (plan 30.15: n=20 -> ~13.9 %,
    n=29 -> ~9.8 %); ``e > 0`` uses ``scipy.stats.beta.ppf(1-alpha, e+1, n-e)`` and ``e = n``
    gives exactly 1.  The bound is only meaningful under the frozen binomial event model
    (independent conservative lineage clusters, identical per-mother query/trajectory counts,
    fixed policy) -- it is not a licence to claim overall safety.
    """
    events = int(events)
    n = int(n)
    alpha = float(alpha)
    if n < 1:
        raise ValueError("Clopper-Pearson requires n >= 1")
    if events < 0 or events > n:
        raise ValueError(f"events must satisfy 0 <= e <= n, got e={events}, n={n}")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be in (0, 1)")
    if events == 0:
        return float(1.0 - alpha ** (1.0 / n))
    if events >= n:
        return 1.0
    from scipy.stats import beta

    return float(beta.ppf(1.0 - alpha, events + 1, n - events))


def zeron_event_units(target_rate: float, alpha: float = 0.05) -> int:
    """Independent zero-event units needed for a one-sided ``1-alpha`` bound <= target."""
    if not 0.0 < target_rate < 1.0:
        raise ValueError("target_rate must be in (0, 1)")
    n = math.log(alpha) / math.log(1.0 - target_rate)
    return int(math.ceil(n))


def risk_bound_table(alpha: float = 0.05, targets: Sequence[float] = (0.10, 0.05, 0.01)
                     ) -> dict[str, Any]:
    """The frozen zero-event table (plan 30.15: 10 % -> 29, 5 % -> 59, 1 % -> 299)."""
    return {"alpha": float(alpha),
            "units": {f"{t:.0%}": zeron_event_units(t, alpha) for t in targets}}


# --------------------------------------------------------------------------------------
# power / sample size
# --------------------------------------------------------------------------------------
def power_approx(sigma: float, delta: float, alpha: float = 0.05, power: float = 0.8) -> int:
    """Normal-approximation cluster count ``n ~ ((z_{1-a/2} + z_power) sigma / delta)^2``.

    A scenario calculation only: pilot cluster variance is unstable and the real sample size
    must be confirmed by simulation or a proper model (plan 30.15).
    """
    from scipy.stats import norm

    sigma = float(sigma)
    delta = float(delta)
    if sigma <= 0 or delta <= 0:
        raise ValueError("sigma and delta must be positive")
    z_alpha = float(norm.ppf(1.0 - float(alpha) / 2.0))
    z_power = float(norm.ppf(float(power)))
    return int(math.ceil(((z_alpha + z_power) * sigma / delta) ** 2))


def achieved_power(n: int, sigma: float, delta: float, alpha: float = 0.05) -> float:
    """Power actually reached by ``n`` clusters for the paired macro difference."""
    from scipy.stats import norm

    if n < 1:
        raise ValueError("n must be >= 1")
    z_alpha = float(norm.ppf(1.0 - float(alpha) / 2.0))
    se = float(sigma) / math.sqrt(float(n))
    if se <= 0:
        return 1.0
    return float(1.0 - norm.cdf(z_alpha - abs(float(delta)) / se))


def power_report(sigma: float, delta: float, alpha: float = 0.05, power: float = 0.8,
                 *, pilot_clusters: int | None = None) -> dict[str, Any]:
    """Power block required by plan 30.15 (all fields, sensitivities included)."""
    n = power_approx(sigma, delta, alpha=alpha, power=power)
    return {
        "primary_metric": "macro CovRecall@10",
        "paired_estimand": "per-lineage paired mean difference (treated - control)",
        "null_delta": 0.0,
        "target_delta": float(delta),
        "alpha": float(alpha),
        "power": float(power),
        "pilot_cluster_sd": float(sigma),
        "n_approx": n,
        "n_sensitivity": {f"{factor:g}x_sd": power_approx(sigma * factor, delta, alpha=alpha,
                                                          power=power)
                          for factor in (0.75, 1.0, 1.5, 2.0)},
        "achieved_power_at_n": achieved_power(n, sigma, delta, alpha=alpha),
        "pilot_clusters": pilot_clusters,
        "note": "scenario calculation from an unstable pilot variance; confirm with simulation "
                "or a proper model before freezing a sample size",
        "ci_rule": "mean_delta >= target_delta and CI_lower > null_delta for a directional claim; "
                   "CI_lower >= target_delta to claim the effect is at least the target",
    }


def n90(points: Sequence[tuple[float, float]] | Sequence[Mapping[str, Any]], *,
        fraction: float = 0.9, higher_is_better: bool = True, metric: str = "",
        reference: float | None = None) -> dict[str, Any]:
    """Sample size at which the **measured** curve reaches ``fraction`` of its plateau.

    ``reference`` is the frozen saturation reference measured for the specified model, domain
    and budget (plan 19.5).  Without it the largest measured value is used, which can only
    ever bracket *inside* the measured range.  Only measured points are used and the answer is
    bracketed by two measured ``N`` values: a curve that never reaches the fraction inside the
    measured range is reported as ``NOT_REACHED`` and **no value is extrapolated**.
    """
    series: list[tuple[float, float]] = []
    for item in points:
        if isinstance(item, Mapping):
            series.append((float(item.get("n")), float(item.get("value"))))
        else:
            series.append((float(item[0]), float(item[1])))
    series = sorted(series)
    report: dict[str, Any] = {"metric": str(metric), "fraction": float(fraction),
                              "n_points": len(series), "measured_points": series,
                              "extrapolated": False,
                              "reference_source": ("external_saturation_reference"
                                                   if reference is not None
                                                   else "max_measured_value")}
    if len(series) < 2:
        report.update({"n90": None, "status": "INSUFFICIENT_POINTS",
                       "reason": "at least two measured gallery sizes are required"})
        return report
    values = [v for _n, v in series]
    if reference is None:
        plateau = max(values) if higher_is_better else min(values)
    else:
        plateau = float(reference)
    target = float(fraction) * plateau if higher_is_better else \
        plateau + (1.0 - float(fraction)) * (max(values) - plateau)
    report["reference_value"] = float(plateau)
    report["target_value"] = float(target)
    hit_index = None
    for index, (_n, value) in enumerate(series):
        reached = value >= target if higher_is_better else value <= target
        if reached:
            hit_index = index
            break
    if hit_index is None:
        report.update({"n90": None, "status": "NOT_REACHED",
                       "reason": f"the measured curve never reaches {target:.4g} within the "
                                 f"measured range; no extrapolation is performed"})
        return report
    if hit_index == 0:
        report.update({"n90": series[0][0], "status": "BRACKETED",
                       "bracket": [None, series[0][0]],
                       "reason": "the smallest measured size already reaches the target"})
        return report
    n_lo, v_lo = series[hit_index - 1]
    n_hi, v_hi = series[hit_index]
    if v_hi == v_lo:
        n_est = n_hi
    else:
        weight = (target - v_lo) / (v_hi - v_lo)
        n_est = n_lo + weight * (n_hi - n_lo)
    report.update({"n90": float(n_est), "status": "BRACKETED", "bracket": [n_lo, n_hi],
                   "at_n": {"lo": {"n": n_lo, "value": v_lo}, "hi": {"n": n_hi, "value": v_hi}},
                   "reason": "linear interpolation strictly between two measured points"})
    return report


@dataclass
class RiskEvidence:
    """Zero/non-zero event evidence for one frozen risk event."""

    events: int
    units: int
    alpha: float = 0.05

    @property
    def upper(self) -> float:
        return clopper_pearson_upper(self.events, self.units, self.alpha)

    def as_dict(self, *, target: float | None = None) -> dict[str, Any]:
        return {"events": self.events, "units": self.units, "alpha": self.alpha,
                "upper_bound": self.upper,
                "target": target,
                "meets_target": (None if target is None else bool(self.upper <= target)),
                "model": "binomial, independent conservative lineage clusters"}


def summarise_risk_events(events: int, units: int, *, alpha: float = 0.05,
                          target: float = 0.10) -> dict[str, Any]:
    """Risk block for the report: the CP bound plus the frozen zero-event requirement."""
    required = zeron_event_units(target, alpha)
    if int(units) < 1:
        return {
            "events": int(events), "units": 0, "alpha": float(alpha), "upper_bound": None,
            "target": float(target), "meets_target": None, "verdict": "NA",
            "model": "binomial, independent conservative lineage clusters",
            "zero_event_units_required": required, "zero_event_units_present": 0,
            "reason": "no mate-absent unit exists in this frozen roster: the risk event model "
                      "does not apply, so no bound is reported",
            "caveat": "an all-zero bootstrap may not be used to claim a risk gate is met; the "
                      "binomial unit model must actually hold",
        }
    evidence = RiskEvidence(int(events), int(units), alpha).as_dict(target=target)
    evidence.update({
        "zero_event_units_required": required,
        "zero_event_units_present": int(units) if int(events) == 0 else 0,
        "verdict": ("PASS" if evidence["upper_bound"] <= target else "NOT_ESTABLISHED"),
        "caveat": "an all-zero bootstrap may not be used to claim a risk gate is met; the "
                  "binomial unit model must actually hold",
    })
    return evidence


__all__ = [
    "BOOTSTRAP_UNIT", "DEFAULT_REPLICATES", "DEFAULT_CONFIDENCE", "paired_bootstrap_ci",
    "macro_mean_by_stratum", "holm_correction", "clopper_pearson_upper", "zeron_event_units",
    "risk_bound_table", "power_approx", "achieved_power", "power_report", "n90",
    "RiskEvidence", "summarise_risk_events",
]
