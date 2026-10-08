"""Diversity metrics for the A12 synthetic store.

One module, two consumers:

* :func:`measure` produces the machine-readable ``diversity_*.json`` report for the
  ``before`` (existing stores) and ``after`` (``data/a12_diversity/store``) snapshots;
* :mod:`tests.a12.integration.test_diversity_variables` asserts the *property* that the
  report is meant to prove (no closed value set in any axis), so the claim is re-checkable
  instead of being a number frozen into a document.

Nothing here writes into the stores it reads: every store is opened with
``file:...?mode=ro`` (the same discipline as :class:`synlab.qc.data_quality._RoStore`)
and every metric names its own denominator.

Definitions used by the report
------------------------------
``combo``
    a distinct ``(vessel_id, material_id, pattern_id, layer_combo_id)`` tuple.
``event normal`` (the repetition source this audit was written to find)
    the unit normal of the *cut plane* of one fracture event, measured as the smallest
    singular vector of the interface sample points of that event (``PCA`` on
    ``sample_points_a`` of every :class:`~synlab.schemas.runtime.InterfacePatch`).
    Measured, not reported: the pipeline never records ``FractureSpec.plane_normal``.
``pairwise angular spread``
    for a set of normals ``N``, ``mean`` over all unordered pairs of
    ``arccos(|n_i . n_j|)`` in degrees.  0 means every plane is parallel.
``near-duplicate``
    1 - ``|a - b| / max(|a|, |b|)`` for two scalars: 1.0 is identical.
``asset-level duplicate``
    a blob_hash shared by more than one asset *of the same role*, counted against the
    number of assets of that role (byte-level identity only; two assets may share bytes
    under different interpretations by design, so the per-role denominator is the honest
    one).
"""

from __future__ import annotations

import json
import math
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

REPORT_SCHEMA = "synlab.diversity_report.v1"

#: Stores the ``before`` snapshot scans; every one of them contains real fragments.
BEFORE_STORES: tuple[str, ...] = (
    "data/a12",
    "data/a12_smoke",
    "data/a12_demo",
    "data/a12_demo/store",
    "data/a12_trainable/store",
    "data/a12_campaign/store",
    "data/a12_exports/closed_loop/store",
    "data/a12_exports/cl_fresh/store",
    "data/a12_exports/pilot_gate/store",
    "data/a12_exports/_scratch/store_backup_a12",
    "data/a12_exports/_scratch/gen1",
    "data/a12_exports/_scratch/gen2",
    "data/a12_exports/_scratch/gen3",
    "data/a12_exports/_scratch/gen4",
    "data/a12_exports/_scratch/gen5",
    "data/a12_exports/runid_fix/before_store",
    "data/a12_exports/runid_fix/after_store",
    "data/a12_probe_tmp",
    "data/a12_realistic/control_ideal",
    "data/a12_degrade/_probe_store",
    "data/a12/reports/failure_fix_store",
    "data/a12/reports/l0_after_fix/store",
    "data/a12/reports/l0_after_fix_v2/store",
)

AFTER_STORE = "data/a12_diversity/store"

ROLE_FRAGMENT = "fragment_mesh"
ROLE_MOTHER = "mother_mesh"
ROLE_CLEAN = "clean_truth"
ROLE_OBS = "obs_result"
ROLE_PATTERN = "pattern_recipe"
ROLE_MATERIAL = "material_profile"
ROLE_DEGRADE_VARIANT = "degrade_variant"
ROLE_DEGRADE_MEASUREMENT = "degrade_measurement"


# ---------------------------------------------------------------------------------------
# store access
# ---------------------------------------------------------------------------------------
class StoreView:
    """Read-only handle on one ``AssetStore`` metadata database."""

    def __init__(self, rel: str, root: Path) -> None:
        self.rel = rel
        self.root = root
        self.db = root / "metadata.sqlite"
        self.conn: sqlite3.Connection | None = None
        self.error: str | None = None
        try:
            self.conn = sqlite3.connect(f"file:{self.db.as_posix()}?mode=ro", uri=True)
            self.conn.row_factory = sqlite3.Row
            names = {r[0] for r in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if "assets" not in names:
                self.error = "no assets table"
        except Exception as exc:  # noqa: BLE001 - an unreadable store is a reported fact
            self.error = f"{type(exc).__name__}: {exc}"

    def close(self) -> None:
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:  # noqa: BLE001
                pass

    @property
    def ok(self) -> bool:
        return self.conn is not None and self.error is None

    def rows(self, role: str | None = None, *, lineage_like: str | None = None
             ) -> list[sqlite3.Row]:
        assert self.conn is not None
        sql = "SELECT * FROM assets"
        where, args = [], []
        if role is not None:
            where.append("role=?")
            args.append(role)
        if lineage_like is not None:
            where.append("lineage_id LIKE ?")
            args.append(lineage_like)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at, asset_id"
        return list(self.conn.execute(sql, args))

    def arrays_path(self, row: Mapping[str, Any]) -> Path | None:
        files = _json(row["files_json"])
        rel = files.get("arrays")
        if not rel:
            return None
        return self.root / Path(*str(rel).split("/"))

    def array_keys(self, row: Mapping[str, Any]) -> list[str]:
        path = self.arrays_path(row)
        if path is None or not path.exists():
            return []
        try:
            with np.load(path, allow_pickle=False) as data:
                return list(data.files)
        except Exception:  # noqa: BLE001
            return []

    def load_arrays(self, row: Mapping[str, Any], keys: Sequence[str]
                    ) -> dict[str, np.ndarray]:
        path = self.arrays_path(row)
        if path is None or not path.exists():
            return {}
        out: dict[str, np.ndarray] = {}
        try:
            with np.load(path, allow_pickle=False) as data:
                for key in keys:
                    if key in data.files:
                        out[key] = data[key]
        except Exception:  # noqa: BLE001
            return {}
        return out


def _json(text: Any) -> dict[str, Any]:
    if not text:
        return {}
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


# ---------------------------------------------------------------------------------------
# small numeric helpers
# ---------------------------------------------------------------------------------------
def plane_normal_of_points(points: np.ndarray) -> np.ndarray | None:
    """Unit normal of the best-fit plane through ``points`` (PCA), or ``None``."""
    pts = np.asarray(points, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[0] < 3 or pts.shape[1] != 3:
        return None
    pts = pts[np.isfinite(pts).all(axis=1)]
    if pts.shape[0] < 3:
        return None
    centred = pts - pts.mean(axis=0)
    try:
        _, _, vt = np.linalg.svd(centred, full_matrices=False)
    except np.linalg.LinAlgError:  # pragma: no cover - non-finite guard above
        return None
    normal = np.asarray(vt[-1], dtype=np.float64)
    norm = float(np.linalg.norm(normal))
    return normal / norm if norm > 1e-12 else None


def angular_spread_deg(normals: Sequence[np.ndarray]) -> dict[str, float]:
    """Mean/max pairwise angle between undirected normals, in degrees."""
    good = [np.asarray(n, dtype=np.float64) for n in normals
            if n is not None and np.isfinite(np.asarray(n, dtype=np.float64)).all()]
    if len(good) < 2:
        return {"pairs": 0, "mean_deg": 0.0, "max_deg": 0.0, "min_deg": 0.0}
    angles: list[float] = []
    for i in range(len(good)):
        for j in range(i + 1, len(good)):
            dot = abs(float(np.dot(good[i], good[j])))
            angles.append(math.degrees(math.acos(max(-1.0, min(1.0, dot)))))
    return {"pairs": len(angles), "mean_deg": float(np.mean(angles)),
            "max_deg": float(np.max(angles)), "min_deg": float(np.min(angles))}


def hash_bucket(values: Sequence[Any], *, ndigits: int = 4) -> dict[str, Any]:
    """Distinct-value census of a scalar sequence (rounded to ``ndigits``)."""
    keyed = Counter()
    for value in values:
        if value is None:
            keyed["<none>"] += 1
        elif isinstance(value, float) and not math.isfinite(value):
            keyed["<nonfinite>"] += 1
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            keyed[repr(round(float(value), ndigits))] += 1
        else:
            keyed[str(value)] += 1
    hist = dict(sorted(keyed.items(), key=lambda kv: (-kv[1], kv[0])))
    return {"n": len(values), "distinct": len(hist), "histogram": hist}


#: The observation pose grid of ``synlab.cameras.viewframes.make_view_frames`` is
#: ``azimuth = 360*k/azimuths``; a view whose measured azimuth sits within this many
#: degrees of such a multiple is counted as *on the canonical grid*.
GRID_TOLERANCE_DEG = 2.0


def angle_grid_census(angles: Sequence[float], *, azimuths: int = 4,
                      tolerance: float = GRID_TOLERANCE_DEG) -> dict[str, Any]:
    """How much of the measured azimuth/elevation set sits on the canonical view grid.

    ``make_view_frames`` places view *k* at ``azimuth = 2*pi*k/azimuths`` and
    ``elevation = -22.5 + 45*layer/(layers-1)`` and then perturbs each frame by a
    ``N(0, 0.35 deg)`` wrist jitter.  If every measured angle is within ``tolerance``
    of that grid, the *view set itself* carries no lineage-level diversity: only the
    sub-degree jitter differs.  This function measures that instead of asserting it.
    """
    good = [float(a) for a in angles if a is not None and math.isfinite(float(a))]
    if not good:
        return {"n": 0}
    target = [360.0 * k / max(int(azimuths), 1) for k in range(max(int(azimuths), 1))]
    on_grid = 0
    residues: list[float] = []
    for value in good:
        residue = min(min(abs((value - t + 180.0) % 360.0 - 180.0) for t in target),
                      360.0)
        residues.append(residue)
        if residue <= tolerance:
            on_grid += 1
    arr = np.asarray(residues, dtype=np.float64)
    return {
        "n": len(good),
        "grid_azimuths": int(azimuths),
        "tolerance_deg": float(tolerance),
        "on_grid": on_grid,
        "on_grid_fraction": on_grid / len(good),
        "residue_deg": {"median": float(np.median(arr)), "p95": float(np.percentile(arr, 95)),
                        "max": float(arr.max())},
    }



def quantile_summary(values: Sequence[float]) -> dict[str, Any]:
    arr = np.asarray([v for v in values if v is not None and math.isfinite(float(v))],
                     dtype=np.float64)
    if arr.size == 0:
        return {"n": 0}
    qs = np.percentile(arr, [0, 5, 25, 50, 75, 95, 100])
    return {
        "n": int(arr.size), "min": float(qs[0]), "p05": float(qs[1]), "p25": float(qs[2]),
        "median": float(qs[3]), "p75": float(qs[4]), "p95": float(qs[5]), "max": float(qs[6]),
        "mean": float(arr.mean()), "std": float(arr.std()),
        "distinct_rounded_4": int(np.unique(np.round(arr, 4)).size),
    }


def closest_pair(values: Sequence[float], labels: Sequence[str] | None = None
                 ) -> dict[str, Any]:
    """Closest pair of scalars under the relative-difference metric.

    ``rel_diff = |a-b| / max(|a|,|b|)`` and ``similarity = 1 - rel_diff``; a pair whose
    larger member is 0 has similarity 1.0 by definition (both are exactly zero).
    """
    items = [(float(v), (labels[i] if labels else str(i)))
             for i, v in enumerate(values) if v is not None and math.isfinite(float(v))]
    if len(items) < 2:
        return {"pairs": 0}
    order = sorted(range(len(items)), key=lambda i: items[i][0])
    best = None
    for a, b in zip(order, order[1:]):
        va, la = items[a]
        vb, lb = items[b]
        scale = max(abs(va), abs(vb))
        rel = 0.0 if scale == 0.0 else abs(va - vb) / scale
        if best is None or rel < best["rel_diff"]:
            best = {"rel_diff": float(rel), "similarity": float(1.0 - rel),
                    "a": va, "b": vb, "label_a": la, "label_b": lb}
    # the adjacent-in-sorted-order pair is the exact minimiser of |a-b|; the metric is
    # monotone in |a-b| on a fixed scale only, so also check the global minimum of the
    # relative metric over a bounded sample of pairs when the list is small.
    if len(items) <= 400:
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                va, la = items[i]
                vb, lb = items[j]
                scale = max(abs(va), abs(vb))
                rel = 0.0 if scale == 0.0 else abs(va - vb) / scale
                if rel < best["rel_diff"]:
                    best = {"rel_diff": float(rel), "similarity": float(1.0 - rel),
                            "a": va, "b": vb, "label_a": la, "label_b": lb}
    best["pairs_compared"] = len(items) * (len(items) - 1) // 2
    return best


def descriptor_distance(a: Mapping[str, Any], b: Mapping[str, Any]) -> float:
    """L1 distance between two image descriptors (0.0 = identical)."""
    total = 0.0
    total += abs(float(a["w"]) - float(b["w"])) / 1024.0
    total += abs(float(a["h"]) - float(b["h"])) / 1024.0
    total += abs(float(a["mean"]) - float(b["mean"])) / 255.0
    total += abs(float(a["std"]) - float(b["std"])) / 255.0
    ha = np.asarray(a["hist"], dtype=np.float64)
    hb = np.asarray(b["hist"], dtype=np.float64)
    total += float(np.abs(ha - hb).sum()) / max(ha.sum(), 1.0)
    return float(total)


# ---------------------------------------------------------------------------------------
# layer extractors
# ---------------------------------------------------------------------------------------
def _planning_layer(lineages: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    combos = Counter()
    for lin in lineages:
        combos[(lin["vessel_id"], lin["material_id"], lin["pattern_id"],
                lin["layer_combo_id"])] += 1
    return {
        "lineages": len(lineages),
        "distinct_vessel_material_pattern_layer_combos": len(combos),
        "combos_per_lineage": (len(combos) / len(lineages)) if lineages else 0.0,
        "vessel": hash_bucket([lin["vessel_id"] for lin in lineages]),
        "material": hash_bucket([lin["material_id"] for lin in lineages]),
        "pattern": hash_bucket([lin["pattern_id"] for lin in lineages]),
        "layer_combo": hash_bucket([lin["layer_combo_id"] for lin in lineages]),
        "split": hash_bucket([lin["split"] for lin in lineages]),
        "combo_multiplicity": hash_bucket(list(combos.values())),
    }


def _event_layer(lineages: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    normals: list[np.ndarray] = []
    offsets: list[float] = []
    per_group: dict[tuple[str, str], list[np.ndarray]] = defaultdict(list)
    frag_counts, event_counts, backends, tiny_counts = [], [], Counter(), []
    for lin in lineages:
        for event in lin["events"]:
            if event.get("normal") is not None:
                normal = np.asarray(event["normal"], dtype=np.float64)
                normals.append(normal)
                per_group[(lin["vessel_id"], lin["material_id"])].append(normal)
            if event.get("offset_bbox_units") is not None:
                offsets.append(float(event["offset_bbox_units"]))
            backends[event.get("backend") or "<none>"] += 1
        frag_counts.append(lin["fragments"])
        tiny_counts.append(lin["tiny_fragments"])
        event_counts.append(lin["event_count"])
    groups: dict[str, Any] = {}
    for (vessel, material), group_normals in sorted(per_group.items()):
        spread = angular_spread_deg(group_normals)
        groups[f"{vessel}|{material}"] = {
            "lineages": len(group_normals),
            "distinct_normals_rounded_3dp": len({
                tuple(np.round(n, 3).tolist()) for n in group_normals}),
            **spread,
        }
    overall = angular_spread_deg(normals)
    return {
        "events_total": int(sum(event_counts)),
        "events_per_lineage": hash_bucket(event_counts),
        "fragments_per_lineage": hash_bucket(frag_counts),
        "tiny_fragments_per_lineage": hash_bucket(tiny_counts),
        "backend": dict(backends),
        "normal_set_size": len(normals),
        "normal_set_size_distinct_3dp": len({tuple(np.round(n, 3).tolist()) for n in normals}),
        "normal_set_size_distinct_2dp": len({tuple(np.round(n, 2).tolist()) for n in normals}),
        "normal_pairwise_spread_overall": overall,
        "normal_spread_within_vessel_material": groups,
        "witness_normal": None if not normals else [float(x) for x in normals[0]],
        "offset_bbox_units": quantile_summary(offsets),
        "offset_distinct_4dp": len({round(v, 4) for v in offsets}),
        "planes_null_in_spec": sum(1 for lin in lineages for e in lin["events"]
                                   if e.get("plane_explicit") is False),
    }


DEFAULT_PARAM_KEYS = ("diameter_mm", "wall_mm", "base_mm", "warp_amplitude",
                      "warp_eccentricity_mm", "warp_lobes")


def _parameter_layer(lineages: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    keys: Counter = Counter()
    per_key: dict[str, list[float]] = defaultdict(list)
    constant_keys: dict[str, Any] = {}
    for lin in lineages:
        for key, value in (lin["params"] or {}).items():
            keys[key] += 1
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)) and math.isfinite(float(value)):
                per_key[key].append(float(value))
            else:
                constant_keys.setdefault(key, value)
    out: dict[str, Any] = {"param_keys_seen": dict(sorted(keys.items())),
                           "non_numeric_keys": dict(sorted(constant_keys.items())),
                           "per_key": {}}
    for key, values in sorted(per_key.items()):
        summary = quantile_summary(values)
        summary["distinct_values"] = len(set(values))
        out["per_key"][key] = summary
    # parameters pinned at a value that also appears as the vessel model's own default
    out["per_vessel_default_check"] = _vessel_default_check(lineages)
    return out


def _vessel_default_check(lineages: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Fraction of lineages whose parameter equals the vessel model's own field default."""
    out: dict[str, Any] = {}
    try:
        from synlab.mothers.api import params_model
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}
    for vessel in sorted({lin["vessel_id"] for lin in lineages}):
        try:
            model = params_model(vessel)
            fields = getattr(model, "model_fields", {}) or {}
        except Exception:  # noqa: BLE001
            continue
        rows = [lin for lin in lineages if lin["vessel_id"] == vessel]
        entry: dict[str, Any] = {"lineages": len(rows), "fields": {}}
        for name, field in fields.items():
            default = getattr(field, "default", None)
            if default is None or not isinstance(default, (int, float)):
                continue
            values = [lin["params"].get(name) for lin in rows if name in (lin["params"] or {})]
            if not values:
                continue
            at_default = sum(1 for v in values if isinstance(v, (int, float))
                             and abs(float(v) - float(default)) < 1e-9)
            entry["fields"][name] = {
                "model_default": float(default), "lineages_with_key": len(values),
                "at_default": at_default,
                "at_default_fraction": at_default / len(values),
            }
        out[vessel] = entry
    return out


def _material_pattern_layer(lineages: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    families = Counter()
    footprints, amplitudes, phases = [], [], []
    palettes: Counter = Counter()
    directions: Counter = Counter()
    recipe_hashes: Counter = Counter()
    param_keys: Counter = Counter()
    numeric: dict[str, list[float]] = defaultdict(list)
    non_numeric: dict[str, Counter] = defaultdict(Counter)
    for lin in lineages:
        pattern = lin["pattern"] or {}
        if not pattern:
            continue
        families[pattern.get("family_id") or "<none>"] += 1
        if pattern.get("footprint_mm") is not None:
            footprints.append(float(pattern["footprint_mm"]))
        if pattern.get("height_amplitude_mm") is not None:
            amplitudes.append(float(pattern["height_amplitude_mm"]))
        if pattern.get("recipe_hash"):
            recipe_hashes[str(pattern["recipe_hash"])] += 1
        for key, value in (pattern.get("frozen_params") or {}).items():
            param_keys[key] += 1
            if isinstance(value, bool):
                non_numeric[key][str(value)] += 1
            elif isinstance(value, (int, float)) and math.isfinite(float(value)):
                numeric[key].append(float(value))
            elif isinstance(value, (list, tuple)) and value and all(
                    isinstance(v, (int, float)) for v in value):
                numeric[key].append(float(sum(value) / len(value)))
            else:
                non_numeric[key][str(value)] += 1
        for key in ("phase_deg", "phase", "phase_s_mm"):
            if pattern.get(key) is not None:
                phases.append(float(pattern[key]))
        palette = pattern.get("palette_id") or pattern.get("palette")
        palettes[str(palette)] += 1
        direction = pattern.get("direction_deg") or pattern.get("orientation_deg")
        directions[str(direction)] += 1
    materials = Counter(str(lin["material_id"]) for lin in lineages)
    mat_stats: dict[str, Any] = defaultdict(list)
    for lin in lineages:
        for key, value in (lin["material_stats"] or {}).items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                mat_stats[key].append(float(value))
    return {
        "material_distribution": dict(sorted(materials.items())),
        "pattern_family_distribution": dict(sorted(families.items())),
        "pattern_recipe_hash": {
            "lineages_with_recipe": int(sum(recipe_hashes.values())),
            "distinct_recipe_hashes": len(recipe_hashes),
            "multiplicity": hash_bucket(list(recipe_hashes.values())),
            "note": ("identical hash = byte-identical frozen recipe; the hash covers the "
                     "whole recipe dict, so two lineages sharing one built the same pattern"),
        },
        "pattern_frozen_param_keys": dict(sorted(param_keys.items())),
        "pattern_frozen_numeric": {k: quantile_summary(v) for k, v in sorted(numeric.items())},
        "pattern_frozen_categorical": {k: dict(sorted(v.items()))
                                       for k, v in sorted(non_numeric.items())},
        "pattern_footprint_mm": quantile_summary(footprints),
        "pattern_height_amplitude_mm": quantile_summary(amplitudes),
        "pattern_phase_values": hash_bucket(phases),
        "pattern_palette": dict(sorted(palettes.items())),
        "pattern_direction": dict(sorted(directions.items())),
        "material_stat_keys": {k: quantile_summary(v) for k, v in sorted(mat_stats.items())},
    }



def _observation_layer(lineages: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    profile_ids, tiers, wds, sizes, view_counts = Counter(), Counter(), [], [], []
    azimuths, elevations, focus_settings = [], [], Counter()
    keyed: dict[str, list[float]] = defaultdict(list)
    for lin in lineages:
        for obs in lin["observations"]:
            if obs.get("profile_id"):
                profile_ids[str(obs["profile_id"])] += 1
            if obs.get("tier"):
                tiers[str(obs["tier"])] += 1
            if obs.get("working_distance_mm") is not None:
                wds.append(float(obs["working_distance_mm"]))
            if obs.get("views"):
                view_counts.append(int(obs["views"]))
            if obs.get("image_size"):
                sizes.append(tuple(int(x) for x in obs["image_size"]))
            if obs.get("focus_setting"):
                focus_settings[str(obs["focus_setting"])] += 1
            azimuths.extend(obs.get("azimuths_deg") or [])
            elevations.extend(obs.get("elevations_deg") or [])
            for key in ("exposure_ev", "defocus_sigma_px", "read_noise_sigma",
                        "effective_gain", "bit_depth"):
                value = (obs.get("imaging") or {}).get(key)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    keyed[key].append(float(value))
    light_modes = Counter()
    for lin in lineages:
        if lin.get("light_mode"):
            light_modes[str(lin["light_mode"])] += 1
    return {
        "profile_id": dict(sorted(profile_ids.items())),
        "tier": dict(sorted(tiers.items())),
        "working_distance_mm": quantile_summary(wds),
        "working_distance_distinct": len({round(v, 3) for v in wds}),
        "image_size": hash_bucket([f"{w}x{h}" for w, h in sizes]),
        "views_per_observation": hash_bucket(view_counts),
        "focus_setting": dict(sorted(focus_settings.items())),
        "azimuth_deg": hash_bucket(azimuths, ndigits=2),
        "elevation_deg": hash_bucket(elevations, ndigits=2),
        "azimuth_on_canonical_grid": angle_grid_census(azimuths, azimuths=4),
        "light_mode": dict(sorted(light_modes.items())),
        "imaging": {k: quantile_summary(v) for k, v in sorted(keyed.items())},
    }


def _degradation_layer(lineages: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    axis_sets = Counter()
    axis_levels = Counter()
    combos = Counter()
    per_lineage: list[dict[str, Any]] = []
    for lin in lineages:
        entries = lin.get("degrade") or []
        axes = tuple(sorted({str(e.get("axis_id")) for e in entries}))
        axis_sets[axes] += 1
        for entry in entries:
            axis_levels[(str(entry.get("axis_id")), int(entry.get("level", -1)))] += 1
        combos[tuple(sorted((str(e.get("axis_id")), int(e.get("level", -1)))
                            for e in entries))] += 1
        per_lineage.append({"lineage_id": lin["lineage_id"], "axes": list(axes),
                            "levels": [int(e.get("level", -1)) for e in entries]})
    return {
        "lineages_with_variants": sum(1 for lin in lineages if lin.get("degrade")),
        "distinct_axis_subsets": len(axis_sets),
        "axis_subset_histogram": {"+".join(k) if k else "<none>": v
                                  for k, v in sorted(axis_sets.items(), key=lambda kv: -kv[1])},
        "distinct_axis_level_combos": len(combos),
        "axis_level_pairs": len(axis_levels),
        "axis_level_histogram": {f"{a}:L{l}": n for (a, l), n in sorted(axis_levels.items())},
        "per_lineage": per_lineage,
    }


def _repetition_layer(stores: Sequence[StoreView]) -> dict[str, Any]:
    per_role_total: Counter = Counter()
    per_role_dup_assets: Counter = Counter()
    per_role_dup_groups: Counter = Counter()
    seen_assets: dict[str, str] = {}
    cross_store_aliases: Counter = Counter()
    for store in stores:
        assert store.conn is not None
        for row in store.conn.execute("SELECT asset_id FROM assets"):
            asset_id = str(row["asset_id"])
            previous = seen_assets.setdefault(asset_id, store.rel)
            if previous != store.rel:
                cross_store_aliases[previous] += 1
        for row in store.conn.execute(
                "SELECT role, blob_hash, COUNT(*) n FROM assets GROUP BY role, blob_hash"):
            per_role_total[row["role"]] += int(row["n"])
            if int(row["n"]) > 1:
                per_role_dup_assets[row["role"]] += int(row["n"])
                per_role_dup_groups[row["role"]] += 1
    rows = []
    for role in sorted(per_role_total):
        total = per_role_total[role]
        dup = per_role_dup_assets[role]
        rows.append({
            "role": role, "assets": total, "duplicate_group_count": per_role_dup_groups[role],
            "assets_sharing_bytes_with_another_asset_of_the_same_role": dup,
            "duplicate_asset_fraction": (dup / total) if total else 0.0,
        })
    return {
        "per_role": rows,
        "assets_total": int(sum(per_role_total.values())),
        "assets_sharing_bytes_total": int(sum(per_role_dup_assets.values())),
        "distinct_asset_ids": len(seen_assets),
        "cross_store_asset_aliases": dict(sorted(cross_store_aliases.items())),
        "note": ("a duplicate is a blob_hash shared by >1 asset of the same role *inside one "
                 "store*; assets_total sums over stores, so a store copied on disk inflates "
                 "the denominator - distinct_asset_ids removes that aliasing"),
    }


def _geometry_layer(stores: Sequence[StoreView]) -> dict[str, Any]:
    """Fragment geometry census, in-store and deduplicated across stores.

    ``within_store`` is the honest repetition measurement (two fragments in the same
    store); ``deduplicated`` drops store copies by first-seen ``asset_id`` so a backup
    directory does not masquerade as a second identical fragment.
    """
    volumes_a, areas_a, diag_a, labels_a = [], [], [], []
    volumes_b, areas_b, diag_b, labels_b = [], [], [], []
    seen: set[str] = set()
    for store in stores:
        for row in store.rows(ROLE_FRAGMENT):
            meta = _json(row["meta_json"])
            fragment_id = meta.get("fragment_id") or row["asset_id"]
            volume = meta.get("volume_mm3")
            area = meta.get("area_mm2")
            arrays = store.load_arrays(row, ("mesh.vertices",))
            verts = arrays.get("mesh.vertices")
            diagonal = None
            if verts is not None and np.asarray(verts).size:
                pts = np.asarray(verts, dtype=np.float64)
                diagonal = float(np.linalg.norm(pts.max(axis=0) - pts.min(axis=0)))
            label = f"{store.rel}:{fragment_id}"
            if isinstance(volume, (int, float)):
                volumes_a.append(float(volume))
                labels_a.append(label)
            if isinstance(area, (int, float)):
                areas_a.append(float(area))
            if diagonal is not None:
                diag_a.append(diagonal)
            asset_id = str(row["asset_id"])
            if asset_id in seen:
                continue
            seen.add(asset_id)
            if isinstance(volume, (int, float)):
                volumes_b.append(float(volume))
                labels_b.append(label)
            if isinstance(area, (int, float)):
                areas_b.append(float(area))
            if diagonal is not None:
                diag_b.append(diagonal)
    return {
        "fragments": len(volumes_a),
        "fragments_deduplicated": len(volumes_b),
        "volume_mm3": quantile_summary(volumes_b),
        "area_mm2": quantile_summary(areas_b),
        "bbox_diagonal_mm": quantile_summary(diag_b),
        "closest_volume_pair": closest_pair(volumes_b, labels_b),
        "closest_area_pair": closest_pair(areas_b, labels_b),
        "within_store": {
            "fragments": len(volumes_a),
            "closest_volume_pair": closest_pair(volumes_a, labels_a),
            "closest_area_pair": closest_pair(areas_a, labels_a),
        },
    }



def _image_layer(stores: Sequence[StoreView], *, max_assets: int = 24) -> dict[str, Any]:
    """Image-level near-duplicate check on real 8-bit RGB tiles (bounded sample).

    One image per observation asset: the first ``*.rgb`` array it stores (``obs_result``
    keeps them as ``v000.rgb``, ``obs_view`` as ``payload.frames.0.rgb``).  The descriptor
    is ``(w, h, mean, std, 16-bin grey histogram)`` and the distance is the L1 metric
    documented in the report; a pair of *identical* images has distance 0.
    """
    descriptors: list[dict[str, Any]] = []
    seen_sizes: Counter = Counter()
    scanned = 0
    for role in (ROLE_OBS, "obs_view"):
        for store in stores:
            for row in store.rows(role):
                if len(descriptors) >= max_assets:
                    break
                keys = [k for k in store.array_keys(row)
                        if k.endswith(".rgb") or k == "rgb"]
                if not keys:
                    continue
                arrays = store.load_arrays(row, [sorted(keys)[0]])
                rgb = arrays.get(sorted(keys)[0])
                if rgb is None:
                    continue
                arr = np.asarray(rgb)
                if arr.ndim == 4:
                    arr = arr[0]
                if arr.ndim != 3 or arr.shape[0] < 2:
                    continue
                scanned += 1
                seen_sizes[f"{arr.shape[1]}x{arr.shape[0]}"] += 1
                grey = arr.astype(np.float32).mean(axis=2)
                hist, _ = np.histogram(grey, bins=16, range=(0.0, 255.0))
                meta = _json(row["meta_json"])
                descriptors.append({
                    "label": f"{store.rel}:{role}:{meta.get('fragment_id') or row['asset_id']}",
                    "w": int(arr.shape[1]), "h": int(arr.shape[0]),
                    "mean": float(grey.mean()), "std": float(grey.std()),
                    "hist": [float(x) for x in hist],
                })
            if len(descriptors) >= max_assets:
                break
    best = None
    for i in range(len(descriptors)):
        for j in range(i + 1, len(descriptors)):
            dist = descriptor_distance(descriptors[i], descriptors[j])
            # the L1 budget is 1 (w) + 1 (h) + 1 (mean) + 1 (std) + 2 (hist) = 6
            similarity = max(0.0, 1.0 - dist / 6.0)
            if best is None or dist < best["distance"]:
                best = {"distance": float(dist), "similarity": float(similarity),
                        "label_a": descriptors[i]["label"], "label_b": descriptors[j]["label"],
                        "mean_a": descriptors[i]["mean"], "mean_b": descriptors[j]["mean"]}
    distances = []
    for i in range(min(len(descriptors), 12)):
        for j in range(i + 1, min(len(descriptors), 12)):
            distances.append(descriptor_distance(descriptors[i], descriptors[j]))
    return {
        "assets_scanned": scanned,
        "descriptors": len(descriptors),
        "image_size_histogram": dict(sorted(seen_sizes.items())),
        "closest_pair": best,
        "pairwise_distance": quantile_summary(distances),
        "metric": ("L1(|w1-w2|/1024 + |h1-h2|/1024 + |mean1-mean2|/255 + |std1-std2|/255 "
                   "+ sum|hist1-hist2|/n_pixels); similarity = max(0, 1 - distance/6)"),
    }


def _relation_layer(lineages: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    kinds = Counter()
    r2_per_lineage, r1_per_lineage, unknown_per_lineage = [], [], []
    shared_areas: list[float] = []
    for lin in lineages:
        clean = lin.get("clean") or {}
        relations = clean.get("relations") or []
        local = Counter()
        for rel in relations:
            kind = str(rel.get("kind") or "<none>")
            kinds[kind] += 1
            local[kind] += 1
            if isinstance(rel.get("area_mm2"), (int, float)) and float(rel["area_mm2"]) > 0:
                shared_areas.append(float(rel["area_mm2"]))
        r2_per_lineage.append(local.get("R2", 0))
        r1_per_lineage.append(local.get("R1", 0))
        unknown_per_lineage.append(local.get("UNKNOWN", 0))
    def _census(values: Sequence[int]) -> dict[str, Any]:
        counter = Counter(int(v) for v in values)
        return {"n": len(values), "distinct": len(counter),
                "histogram": {str(k): v for k, v in sorted(counter.items())}}
    return {
        "relation_kinds": dict(sorted(kinds.items())),
        "r2_pairs_per_lineage": _census(r2_per_lineage),
        "r1_pairs_per_lineage": _census(r1_per_lineage),
        "unknown_pairs_per_lineage": _census(unknown_per_lineage),
        "shared_area_mm2": quantile_summary(shared_areas),
        "closest_shared_area_pair": closest_pair(shared_areas),
    }


# ---------------------------------------------------------------------------------------
# lineage extraction
# ---------------------------------------------------------------------------------------
def _parse_lineage_id(lineage_id: str) -> dict[str, Any]:
    """``LIN0003_V01_M04_PAT01`` -> its parts (empty on a non-conforming id)."""
    parts = str(lineage_id or "").split("_")
    out: dict[str, Any] = {"index": None, "vessel_id": None, "material_id": None,
                           "pattern_id": None}
    if parts and parts[0].startswith("LIN") and parts[0][3:].isdigit():
        out["index"] = int(parts[0][3:])
    for part in parts[1:]:
        if part.startswith("V") and part[1:].isdigit():
            out["vessel_id"] = part
        elif part.startswith("M") and part[1:].isdigit():
            out["material_id"] = part
        elif part.startswith("PAT"):
            out["pattern_id"] = part
    return out


def collect_lineages(stores: Sequence[StoreView]) -> list[dict[str, Any]]:
    """One record per ``lineage_id`` across every store handed in."""
    per_lineage: dict[str, dict[str, Any]] = {}
    for store in stores:
        if not store.ok:
            continue
        for row in store.rows():
            lineage_id = row["lineage_id"]
            if not lineage_id:
                continue
            entry = per_lineage.setdefault(str(lineage_id), _new_lineage(str(lineage_id)))
            entry["stores"].add(store.rel)
            _absorb(entry, store, row)
    out = []
    for lineage_id in sorted(per_lineage, key=lambda k: (per_lineage[k]["order"], k)):
        entry = per_lineage[lineage_id]
        entry["stores"] = sorted(entry["stores"])
        entry["event_count"] = len(entry["events"])
        out.append(entry)
    return out


def _new_lineage(lineage_id: str) -> dict[str, Any]:
    parsed = _parse_lineage_id(lineage_id)
    return {
        "lineage_id": lineage_id, "stores": set(), "order": 10 ** 9,
        "split": None, "layer_combo_id": None, "run_ids": set(),
        "vessel_id": parsed["vessel_id"], "material_id": parsed["material_id"],
        "pattern_id": parsed["pattern_id"], "index": parsed["index"],
        "params": {}, "events": [], "fragments": 0, "tiny_fragments": 0,
        "observations": [], "light_mode": None, "degrade": [], "pattern": {},
        "material_stats": {}, "clean": {}, "roles": Counter(),
    }


def _absorb(entry: dict[str, Any], store: StoreView, row: Mapping[str, Any]) -> None:
    role = str(row["role"])
    entry["roles"][role] += 1
    meta = _json(row["meta_json"])
    if entry["index"] is None and meta.get("mother_index") is not None:
        entry["index"] = int(meta["mother_index"])
    if entry["order"] == 10 ** 9:
        entry["order"] = int(entry["index"] if entry["index"] is not None else 10 ** 8)
    if entry["split"] is None and row["split"]:
        entry["split"] = str(row["split"])
    if meta.get("layer_combo_id") and entry["layer_combo_id"] is None:
        entry["layer_combo_id"] = str(meta["layer_combo_id"])
    if meta.get("run_id"):
        entry["run_ids"].add(str(meta["run_id"]))

    if role == ROLE_MOTHER:
        if not entry["params"]:
            entry["params"] = dict(meta.get("params") or {})
        if not entry["vessel_id"]:
            entry["vessel_id"] = meta.get("vessel_id")
        if not entry["material_id"]:
            entry["material_id"] = meta.get("material_id")
    elif role == ROLE_FRAGMENT:
        entry["fragments"] += 1
        if meta.get("is_tiny"):
            entry["tiny_fragments"] += 1
    elif role == ROLE_CLEAN:
        _absorb_clean(entry, store, row, meta)
    elif role == ROLE_OBS:
        _absorb_observation(entry, row, meta)
    elif role in (ROLE_DEGRADE_VARIANT, ROLE_DEGRADE_MEASUREMENT):
        entry["degrade"].append({"axis_id": meta.get("axis_id"), "level": meta.get("level"),
                                 "variant": meta.get("variant")})
    elif role == ROLE_PATTERN:
        _absorb_pattern(entry, meta)
    elif role == ROLE_MATERIAL:
        stats = meta.get("stats")
        if isinstance(stats, dict):
            entry["material_stats"] = {k: v for k, v in stats.items()
                                       if isinstance(v, (int, float))
                                       and not isinstance(v, bool)}


def _absorb_clean(entry: dict[str, Any], store: StoreView, row: Mapping[str, Any],
                  meta: Mapping[str, Any]) -> None:
    """Recover the cut plane of one event from its own interface samples."""
    if meta.get("event_id") and any(e["event_id"] == meta["event_id"] for e in entry["events"]):
        return
    arrays = store.load_arrays(row, ("iface_points_a", "iface_normals_a", "iface_offset",
                                     "iface_area_mm2"))
    points = arrays.get("iface_points_a")
    normal = plane_normal_of_points(points) if points is not None else None
    if normal is None:
        normals = arrays.get("iface_normals_a")
        if normals is not None and np.asarray(normals).size:
            mean_normal = np.asarray(normals, dtype=np.float64).mean(axis=0)
            norm = float(np.linalg.norm(mean_normal))
            normal = mean_normal / norm if norm > 1e-12 else None
    params = entry.get("params") or {}
    diameter = params.get("diameter_mm")
    offset_units = None
    if points is not None and np.asarray(points).size and diameter:
        centre = np.asarray(points, dtype=np.float64).mean(axis=0)
        if normal is not None:
            offset_units = float(np.dot(centre, normal) / float(diameter))
    entry["events"].append({
        "event_id": meta.get("event_id"),
        "backend": meta.get("backend"),
        "normal": None if normal is None else [float(x) for x in normal],
        "offset_bbox_units": offset_units,
        "plane_explicit": meta.get("plane_explicit"),
        "fragment_ids": list(meta.get("fragment_ids") or []),
        "interfaces": meta.get("interface_count"),
        "truth_hash": meta.get("truth_hash"),
    })
    relations = meta.get("relations")
    if relations is None:
        relations_json = meta.get("relations_json")
        if relations_json:
            try:
                relations = json.loads(relations_json)
            except (TypeError, ValueError):
                relations = None
    if entry["clean"].get("relations") is None:
        entry["clean"] = {
            "relations": relations or [],
            "r2_count": meta.get("r2_count"),
            "relation_count": meta.get("relation_count"),
            "mother_area_mm2": meta.get("mother_area_mm2"),
            "truth_hash": meta.get("truth_hash"),
        }


def _absorb_observation(entry: dict[str, Any], row: Mapping[str, Any],
                        meta: Mapping[str, Any]) -> None:
    views = meta.get("views") or []
    first = views[0] if views else {}
    azimuths: list[float] = []
    elevations: list[float] = []
    for view in views:
        view_meta = (view.get("meta") or {}).get("view_meta") or {}
        matrix = view_meta.get("T_WS")
        if matrix is None:
            continue
        rot = np.asarray(matrix, dtype=np.float64)[:3, :3]
        axis = rot @ np.array([0.0, 0.0, -1.0])
        norm = float(np.linalg.norm(axis))
        if norm < 1e-12:
            continue
        axis = axis / norm
        elevations.append(math.degrees(math.asin(max(-1.0, min(1.0, float(axis[2]))))))
        azimuths.append(math.degrees(math.atan2(float(axis[1]), float(axis[0]))) % 360.0)
    obs_spec = (meta.get("meta") or {}).get("obs_spec") or {}
    stages = ((first.get("meta") or {}).get("imaging_stages") or [])
    imaging: dict[str, Any] = {}
    for stage in stages:
        if not isinstance(stage, dict):
            continue
        for key in ("exposure_ev", "effective_gain", "read_noise_sigma", "bit_depth"):
            if stage.get(key) is not None:
                imaging[key] = stage[key]
    for stage in stages:
        if isinstance(stage, dict) and stage.get("op") == "gaussian_psf":
            imaging["defocus_sigma_px"] = stage.get("sigma_px")
    entry["observations"].append({
        "observation_id": meta.get("observation_id"),
        "fragment_id": meta.get("fragment_id"),
        "route": meta.get("route"),
        "profile_id": first.get("profile_id"),
        "tier": first.get("tier"),
        "working_distance_mm": first.get("working_distance_mm"),
        "u_position_mm": first.get("u_position_mm"),
        "focus_setting": first.get("focus_setting"),
        "image_size": first.get("image_size") or obs_spec.get("delivered_size"),
        "views": len(views),
        "azimuths_deg": azimuths,
        "elevations_deg": elevations,
        "imaging": imaging,
        "light_mode": first.get("light_mode"),
        "n_points": meta.get("n_points"),
    })
    backend = meta.get("backend_report") or {}
    light = (backend.get("degradations") or {}).get("light") or {}
    if light.get("mode") and entry["light_mode"] is None:
        entry["light_mode"] = str(light["mode"])


def _absorb_pattern(entry: dict[str, Any], meta: Mapping[str, Any]) -> None:
    recipe = meta.get("recipe") or {}
    height = recipe.get("height") or {}
    bands = ((recipe.get("meta") or {}).get("bands") or {})
    basis = bands.get("basis") or {}
    params = recipe.get("params") or {}
    frozen = {k: v for k, v in params.items()
              if k not in ("measured", "region_sample_report", "footprint", "bands")}
    try:
        recipe_hash = _sha256_json(recipe)
    except (TypeError, ValueError):
        recipe_hash = None
    entry["pattern"] = {
        "family_id": meta.get("family_id"),
        "module_version": meta.get("module_version"),
        "footprint_mm": recipe.get("footprint_mm"),
        "height_amplitude_mm": height.get("amplitude_mm"),
        "height_mode": height.get("mode"),
        "palette_id": (recipe.get("palette") or {}).get("palette_id")
        if isinstance(recipe.get("palette"), dict) else recipe.get("palette_id"),
        "phase_s_mm": frozen.get("phase_s_mm"),
        "orientation_deg": frozen.get("orientation_deg") or frozen.get("tilt_deg"),
        "band_count": len(basis.get("bands") or []),
        "frozen_params": frozen,
        "recipe_hash": recipe_hash,
        "bands": [
            {"band": b.get("band"), "wavelength_x_mm_min": b.get("wavelength_x_mm_min"),
             "energy": b.get("energy")}
            for b in (basis.get("bands") or [])
        ],
    }


def _sha256_json(value: Any) -> str:
    import hashlib

    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()



# ---------------------------------------------------------------------------------------
# top level
# ---------------------------------------------------------------------------------------
def measure(store_rels: Iterable[str], *, label: str, repo: Path | None = None,
            image_sample: int = 24) -> dict[str, Any]:
    repo = repo or REPO_ROOT
    stores: list[StoreView] = []
    skipped: list[dict[str, str]] = []
    for rel in store_rels:
        root = repo / Path(*rel.split("/"))
        if not (root / "metadata.sqlite").exists():
            skipped.append({"store": rel, "reason": "no metadata.sqlite"})
            continue
        view = StoreView(rel, root)
        if not view.ok:
            skipped.append({"store": rel, "reason": view.error or "unreadable"})
            view.close()
            continue
        stores.append(view)
    try:
        lineages = collect_lineages(stores)
        report = {
            "schema": REPORT_SCHEMA,
            "label": label,
            "stores_scanned": [s.rel for s in stores],
            "stores_skipped": skipped,
            "lineages": len(lineages),
            "fragments": int(sum(lin["fragments"] for lin in lineages)),
            "planning_layer": _planning_layer(lineages),
            "event_layer": _event_layer(lineages),
            "parameter_layer": _parameter_layer(lineages),
            "material_pattern_layer": _material_pattern_layer(lineages),
            "observation_layer": _observation_layer(lineages),
            "degradation_layer": _degradation_layer(lineages),
            "repetition_layer": {
                "assets": _repetition_layer(stores),
                "geometry": _geometry_layer(stores),
                "imagery": _image_layer(stores, max_assets=image_sample),
                "relations": _relation_layer(lineages),
            },
            "per_lineage": [
                {
                    "lineage_id": lin["lineage_id"], "stores": lin["stores"],
                    "split": lin["split"], "vessel_id": lin["vessel_id"],
                    "material_id": lin["material_id"], "pattern_id": lin["pattern_id"],
                    "layer_combo_id": lin["layer_combo_id"],
                    "fragments": lin["fragments"], "observations": len(lin["observations"]),
                    "events": lin["event_count"],
                    "params": lin["params"],
                    "truth_hash": (lin["clean"] or {}).get("truth_hash"),
                    "degrade_axes": sorted({str(d.get("axis_id")) for d in lin["degrade"]}),
                }
                for lin in lineages
            ],
        }
        return report
    finally:
        for store in stores:
            store.close()


def compact(report: Mapping[str, Any]) -> dict[str, Any]:
    """The before/after comparison table, reduced to the numbers a reader needs."""
    event = report["event_layer"]
    repeat = report["repetition_layer"]
    return {
        "lineages": report["lineages"],
        "fragments": report["fragments"],
        "combos": report["planning_layer"]["distinct_vessel_material_pattern_layer_combos"],
        "event_normal_set_size": event["normal_set_size"],
        "event_normal_set_size_distinct_2dp": event["normal_set_size_distinct_2dp"],
        "event_normal_spread_mean_deg": event["normal_pairwise_spread_overall"]["mean_deg"],
        "event_normal_spread_max_deg": event["normal_pairwise_spread_overall"]["max_deg"],
        "events_per_lineage_distinct": event["events_per_lineage"]["distinct"],
        "fragments_per_lineage_distinct": event["fragments_per_lineage"]["distinct"],
        "fragment_count_histogram": event["fragments_per_lineage"]["histogram"],
        "observation_working_distance_distinct": report["observation_layer"][
            "working_distance_distinct"],
        "observation_profile_ids": len(report["observation_layer"]["profile_id"]),
        "observation_light_modes": len(report["observation_layer"]["light_mode"]),
        "observation_azimuth_values": report["observation_layer"]["azimuth_deg"]["distinct"],
        "observation_views_distinct": report["observation_layer"]["views_per_observation"][
            "distinct"],
        "degrade_axis_subsets": report["degradation_layer"]["distinct_axis_subsets"],
        "degrade_axis_level_combos": report["degradation_layer"]["distinct_axis_level_combos"],
        "asset_duplicate_fraction": _role_fraction(repeat["assets"], "fragment_mesh"),
        "asset_duplicate_fraction_all": (
            repeat["assets"]["assets_sharing_bytes_total"] / repeat["assets"]["assets_total"]
            if repeat["assets"]["assets_total"] else 0.0),
        "closest_fragment_volume_similarity": (
            (repeat["geometry"]["closest_volume_pair"] or {}).get("similarity")),
        "closest_image_similarity": (
            (repeat["imagery"]["closest_pair"] or {}).get("similarity")),
        "closest_shared_area_similarity": (
            (repeat["relations"]["closest_shared_area_pair"] or {}).get("similarity")),
        "r2_pair_kinds": report["repetition_layer"]["relations"]["relation_kinds"],
    }


def _role_fraction(assets: Mapping[str, Any], role: str) -> float | None:
    for row in assets.get("per_role") or []:
        if row["role"] == role:
            return float(row["duplicate_asset_fraction"])
    return None


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    label = "before"
    out_path = REPO_ROOT / "data" / "a12" / "reports" / "diversity_before.json"
    rels = list(BEFORE_STORES)
    image_sample = 24
    i = 0
    while i < len(argv):
        token = argv[i]
        if token == "--label":
            label = argv[i + 1]
            i += 2
        elif token == "--out":
            out_path = Path(argv[i + 1])
            i += 2
        elif token == "--store":
            if rels is BEFORE_STORES:
                rels = []
            rels.append(argv[i + 1])
            i += 2
        elif token == "--after":
            rels = [AFTER_STORE]
            label = "after"
            i += 1
        elif token == "--image-sample":
            image_sample = int(argv[i + 1])
            i += 2
        else:
            raise SystemExit(f"unknown argument {token!r}")
    report = measure(rels, label=label, image_sample=image_sample)
    report["compact"] = compact(report)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str),
                        encoding="utf-8")
    print(json.dumps(report["compact"], ensure_ascii=False, indent=1, default=str))
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
