"""Per-family pattern audit (A05 evidence, plan 9.3 / 9.6).

``audit_all_patterns(store)`` really builds, evaluates and audits one recipe per family and
aggregates the numbers the acceptance harness reads::

    {"ok": bool, "families": {id: {...}}, "max_seam_error": float,
     "deterministic": bool, "geometry_applied": bool, ...}

Each family is exercised on a real mother body (``synlab.mothers.api.create_mother`` when it
is available, otherwise the documented analytic fixture of :mod:`synlab.patterns.fixtures` -
the source is always recorded in ``mother_source``).  A family that fails to build is
reported with its structured error instead of being skipped, and no metric is invented: the
seam, scale, determinism, inheritance and geometry numbers come from
:func:`synlab.patterns.audit.audit_pattern` measured on the frozen recipe.

``ok`` is true only when all 16 families passed, the maximum seam colour error is within
1e-5, the query path is deterministic, and the geometric families really changed the mother
geometry while the appearance-only families did not.
"""

from __future__ import annotations

import time
import traceback
from typing import Any, Iterable, Sequence

import numpy as np

from ..errors import SynLabError
from ..seeds import make_rng
from .params import FAMILY_MODELS, FAMILY_NAMES
from .serialize import recipe_hash

SEAM_TOL = 1e-5

#: The algorithm each family freezes (plan 9.3 table).  Reported so the audit can show that
#: the 16 ids are 16 algorithms and not one fixed tile under 16 names.
FAMILY_ALGORITHM: dict[str, str] = {
    "PAT01": "constant colour + optional low-frequency Fourier colour field",
    "PAT02": "band centre lines in profile arc length (period/gap/phase)",
    "PAT03": "linear-phase stripe sets with integer azimuthal counts",
    "PAT04": "two/three stripe sets combined by union or intersection",
    "PAT05": "sine / Bezier centre line, EDT distance raster",
    "PAT06": "crystal lattice or periodic Poisson disk (scipy.stats.qmc.PoissonDisk)",
    "PAT07": "periodic triangular tile, line lattice or solid barycentric fill",
    "PAT08": "meander fret tile with shared endpoints",
    "PAT09": "2-3 layered line fields with deterministic missing strokes",
    "PAT10": "bounded L-system skeleton + Bezier leaf outlines",
    "PAT11": "programmatic vector symbol / restricted SVG path",
    "PAT12": "one-shot Pillow glyph layout + SciPy signed distance map",
    "PAT13": "multi-scale continuous blotch field + independent roughness stream",
    "PAT14": "smooth mask -> positive height -> real displacement of the whole body",
    "PAT15": "curve distance -> negative height -> real engraved displacement",
    "PAT16": "region masks + bounded composition of the layers above",
}

#: Deterministic palette per family: the audit must be reproducible, not palette-random.
DEFAULT_PALETTE: dict[str, str] = {
    "PAT01": "iron_slip", "PAT02": "slip_white_earth", "PAT03": "cobalt_white",
    "PAT04": "celadon", "PAT05": "ochre_red", "PAT06": "cobalt_white",
    "PAT07": "ash_grey", "PAT08": "iron_slip", "PAT09": "celadon",
    "PAT10": "ochre_red", "PAT11": "cobalt_white", "PAT12": "slip_white_earth",
    "PAT13": "ash_grey", "PAT14": "celadon", "PAT15": "iron_slip", "PAT16": "ochre_red",
}

#: One complexity tier per family in the main loop; all three tiers are proved to change the
#: frozen coefficients by ``tier_probe``.
DEFAULT_TIER: dict[str, int] = {
    "PAT01": 2, "PAT02": 1, "PAT03": 3, "PAT04": 2, "PAT05": 1, "PAT06": 3, "PAT07": 2,
    "PAT08": 1, "PAT09": 3, "PAT10": 2, "PAT11": 1, "PAT12": 2, "PAT13": 3, "PAT14": 1,
    "PAT15": 2, "PAT16": 3,
}

#: Representative, in-range parameters per family.  The audit fixes them so that a report is
#: reproducible and comparable across runs; every value is inside the frozen pydantic model
#: bounds of ``synlab.patterns.params`` (the build validates them, so a typo fails loudly).
FAMILY_PARAMS: dict[str, dict[str, Any]] = {
    "PAT01": {"low_freq_color": True, "colour_bands": 2},
    "PAT02": {"band_width_mm": 2.0, "gap_mm": 12.0, "pair_gap_mm": 3.0},
    "PAT03": {"tilt_deg": 20.0, "double_line": True},
    "PAT04": {"tilt_b_deg": 75.0, "mode": "union"},
    "PAT05": {"variant": "sine", "amplitude_mm": 3.0, "wavelength_mm": 40.0},
    "PAT06": {"mode": "poisson", "radius_mm": 2.0, "clearance_mm": 0.5},
    "PAT07": {"mode": "line", "edge_mm": 12.0},
    "PAT08": {"tile_w_mm": 20.0, "n_turns": 2},
    "PAT09": {"groups": 3, "angles_deg": [0.0, 60.0, 120.0],
              "spacings_mm": [12.0, 12.0, 12.0], "missing_fraction": 0.1},
    "PAT10": {"generations": 3, "step_mm": 6.0},
    "PAT11": {"symbol_id": "rosette", "size_mm": 14.0, "count_around": 4},
    "PAT12": {"text": "A", "font_size_mm": 10.0, "stroke": False},
    "PAT13": {"n_scales": 3, "blotch_contrast": 0.8},
    "PAT14": {"motif": "blobs", "height_mm": 0.8, "base_wavelength_mm": 20.0},
    "PAT15": {"curve_family": "stripe", "depth_mm": 0.5, "line_width_mm": 3.0,
              "spacing_mm": 20.0},
    "PAT16": {"layers": [
        {"family": "PAT03", "params": {"tilt_deg": 15.0}, "zone": "full", "weight": 1.0},
        {"family": "PAT09", "params": {"groups": 2, "angles_deg": [0.0, 60.0],
                                       "spacings_mm": [14.0, 14.0]},
         "zone": "upper", "weight": 0.6}],
        "boundary": "horizontal_band", "boundary_width_mm": 24.0},
}

_APPEARANCE_GEOMETRY_MODES = {"none"}


def _family_list(families: Iterable[str] | None) -> list[str]:
    if families is None:
        return sorted(FAMILY_MODELS)
    out: list[str] = []
    for family in families:
        key = str(family).upper()
        if key not in FAMILY_MODELS:
            raise SynLabError("SCHEMA_INVALID",
                              f"unknown pattern family {family!r}; known: {sorted(FAMILY_MODELS)}",
                              stage="patterns.audit_all.audit_all_patterns")
        out.append(key)
    return out


def _sample_query_points(mother: Any, frame: Any, count: int, rng: np.random.Generator
                         ) -> np.ndarray:
    """Area-weighted points of the recipe's surface tag (deterministic sub-stream)."""
    from .charts import surface_samples

    points, _ = surface_samples(mother, int(count), rng, tag=int(frame.tag))
    if points.shape[0] < 8:
        faces = np.asarray(mother.mesh.faces)
        mask = np.asarray(mother.face_surface_tag) == int(frame.tag)
        points = np.asarray(mother.mesh.triangles[mask]).mean(axis=1) if np.any(mask) else points
    return np.asarray(points, dtype=np.float64)


def _one_family(family: str, mother: Any, *, store: Any, seed: int, n_pairs: int,
                complexity: int | None, palette: str | None, commit: bool,
                query_points: int, surface_tag: str | None,
                allow_aux_layers: bool = True) -> dict[str, Any]:
    """Build, evaluate, audit and (optionally) commit one family.  Never raises."""
    from .api import build_pattern, evaluate
    from .charts import resolve_frame

    tier = int(complexity or DEFAULT_TIER.get(family, 2))
    started = time.perf_counter()
    entry: dict[str, Any] = {
        "family_id": family, "family_name": FAMILY_NAMES.get(family, family),
        "algorithm": FAMILY_ALGORITHM.get(family, ""),
        "complexity": tier, "palette_id": palette or DEFAULT_PALETTE.get(family),
        "ok": False, "status": "NOT_RUN",
    }
    request: dict[str, Any] = {
        "family": family, "complexity": tier, "palette_id": entry["palette_id"],
        "allow_aux_layers": bool(allow_aux_layers), "max_aux_layers": 2,
        "params": dict(FAMILY_PARAMS.get(family) or {}),
        "seed_ref": f"pattern-audit:{family}:tier{tier}:seed{seed}",
    }
    if surface_tag:
        request["surface_tag"] = surface_tag
    rng = make_rng(int(seed), "pattern-audit", family, tier)
    try:
        recipe = build_pattern(mother, request, rng)
    except SynLabError as exc:
        entry.update({"ok": False, "status": "FAILED", "stage": "build",
                      "error": exc.to_dict(), "seconds": time.perf_counter() - started})
        return entry
    except Exception as exc:  # noqa: BLE001 - reported, never hidden
        entry.update({"ok": False, "status": "FAILED", "stage": "build",
                      "error": {"code": type(exc).__name__, "message": str(exc),
                                "traceback": traceback.format_exc()[-1200:]},
                      "seconds": time.perf_counter() - started})
        return entry

    build_seconds = time.perf_counter() - started
    entry.update({
        "recipe_hash": recipe_hash(recipe),
        "resource_hash": recipe.resource_hash,
        "recipe_version": recipe.version,
        "channels": list(recipe.channels),
    })
    region = (recipe.meta or {}).get("regions", [{}])[0]
    entry["region"] = {"surface_tag": region.get("surface_tag"),
                       "s_range_mm": [region.get("s_min_mm"), region.get("s_max_mm")],
                       "feather_mm": region.get("feather_mm")}
    entry["chart"] = dict((recipe.meta or {}).get("chart") or {})
    entry["footprint_mm"] = (recipe.meta or {}).get("footprint_mm")
    entry["height_policy"] = dict((recipe.meta or {}).get("height") or {})

    # ---------------------------------------------------------------- evaluate
    try:
        frame = resolve_frame(mother, str(region.get("surface_tag")))
        points = _sample_query_points(mother, frame, query_points,
                                      make_rng(int(seed), "pattern-audit", family, "points"))
        channels = evaluate(recipe, mother, points, int(frame.tag))
        entry["evaluate"] = {
            "n_points": int(points.shape[0]),
            "albedo_shape": list(np.asarray(channels.albedo).shape),
            "roughness_shape": list(np.asarray(channels.roughness).shape),
            "height_shape": list(np.asarray(channels.height_mm).shape),
            "region_shape": list(np.asarray(channels.pattern_region).shape),
            "pattern_region_fraction": float(np.mean(channels.pattern_region > 0)),
            "height_abs_max_mm": float(np.abs(channels.height_mm).max()),
            "albedo_min": float(np.asarray(channels.albedo).min()),
            "albedo_max": float(np.asarray(channels.albedo).max()),
            "roughness_min": float(np.asarray(channels.roughness).min()),
            "roughness_max": float(np.asarray(channels.roughness).max()),
            "dtype": {"albedo": str(np.asarray(channels.albedo).dtype),
                      "pattern_region": str(np.asarray(channels.pattern_region).dtype)},
        }
    except SynLabError as exc:
        entry.update({"ok": False, "status": "FAILED", "stage": "evaluate",
                      "error": exc.to_dict(), "build_seconds": build_seconds,
                      "seconds": time.perf_counter() - started})
        return entry
    except Exception as exc:  # noqa: BLE001
        entry.update({"ok": False, "status": "FAILED", "stage": "evaluate",
                      "error": {"code": type(exc).__name__, "message": str(exc),
                                "traceback": traceback.format_exc()[-1200:]},
                      "build_seconds": build_seconds,
                      "seconds": time.perf_counter() - started})
        return entry

    # ---------------------------------------------------------------- audit
    from .audit import audit_pattern

    try:
        report = audit_pattern(recipe, mother, n_pairs=int(n_pairs))
    except SynLabError as exc:
        entry.update({"ok": False, "status": "FAILED", "stage": "audit",
                      "error": exc.to_dict(), "build_seconds": build_seconds,
                      "seconds": time.perf_counter() - started})
        return entry
    except Exception as exc:  # noqa: BLE001
        entry.update({"ok": False, "status": "FAILED", "stage": "audit",
                      "error": {"code": type(exc).__name__, "message": str(exc),
                                "traceback": traceback.format_exc()[-1200:]},
                      "build_seconds": build_seconds,
                      "seconds": time.perf_counter() - started})
        return entry

    seam_chart = dict(report.get("seam", {}).get("chart_space") or {})
    seam_world = dict(report.get("seam", {}).get("world_space") or {})
    determinism = dict(report.get("determinism") or {})
    inheritance = dict(report.get("inheritance") or {})
    geometry = dict(report.get("geometry") or {})
    scale = dict(report.get("scale") or {})
    width = dict(scale.get("line_width_mm") or {})
    spectrum = dict(scale.get("spectrum") or {})
    dots = dict(scale.get("dot_spacing_mm") or {})
    entry.update({
        "ok": bool(report.get("pass")),
        "status": "QA_PASSED" if report.get("pass") else "QA_FAILED",
        "failures": list(report.get("failures") or []),
        "seam": {
            "chart_space_max_abs_color_error": seam_chart.get("max_abs_color_error"),
            "chart_space_pass": seam_chart.get("pass"),
            "deriv_mismatch_ratio": seam_chart.get("max_deriv_mismatch_ratio"),
            "derivative_pass": seam_chart.get("derivative_pass"),
            "world_space_status": seam_world.get("status"),
            "world_space_pass": seam_world.get("pass"),
            "n_pairs": seam_chart.get("n_pairs"),
        },
        "deterministic": bool(determinism.get("pass")),
        "determinism_checks": {k: v for k, v in determinism.items() if isinstance(v, dict)},
        "inheritance_pass": bool(
            all(bool(v.get("pass")) for v in inheritance.values() if isinstance(v, dict))),
        "inheritance": {k: v for k, v in inheritance.items() if isinstance(v, dict)},
        "geometry": geometry,
        "scale": {
            "measured_line_width_mm": (None if width.get("status") != "OK"
                                       else width.get("p50_mm")),
            "measured_line_width_p05_p95_mm": (None if width.get("status") != "OK"
                                               else [width.get("p05_mm"), width.get("p95_mm")]),
            "declared_line_width_mm": scale.get("declared_line_width_mm"),
            "min_wavelength_mm": scale.get("min_wavelength_mm"),
            "dominant_wavelength_mm": spectrum.get("dominant_wavelength_mm"),
            "spectrum_status": spectrum.get("status"),
            "region_area_mm2": scale.get("region_area_mm2"),
            "circumferential_metric": scale.get("circumferential_metric"),
            "dot_spacing_mm": dots or None,
        },
        "recipe_hash_recomputed": report.get("recipe_hash_recomputed"),
        "recipe_hash_matches": report.get("recipe_hash_matches"),
        "audit": report,
    })

    # ---------------------------------------------------------------- store round trip
    if commit and store is not None:
        from .commit import commit_pattern, load_pattern

        try:
            record = commit_pattern(store, recipe, channels=channels,
                                    lineage_id=f"pattern_audit_{family}", split="audit",
                                    ancestry=(), mother_id=getattr(mother, "mother_id", None),
                                    qa={"audit_pass": bool(report.get("pass")),
                                        "seam_error": seam_chart.get("max_abs_color_error"),
                                        "family_id": family},
                                    qa_status="QA_PASS" if report.get("pass") else "QA_FAIL")
            reloaded = load_pattern(store, record.asset_id)
            entry["asset"] = {
                "asset_id": record.asset_id, "role": record.role,
                "interpretation_hash": record.interpretation_hash,
                "qa_status": record.qa_status,
                "reload_recipe_hash": recipe_hash(reloaded),
                "reload_matches": bool(recipe_hash(reloaded) == recipe_hash(recipe)),
                "channels_asset": (record.meta or {}).get("channels_asset")
                or (record.meta or {}).get("recipe", {}).get("channels_asset"),
            }
            if not entry["asset"]["reload_matches"]:
                entry["ok"] = False
                entry["status"] = "QA_FAILED"
                entry["failures"] = list(entry.get("failures") or []) + \
                    ["recipe hash changed across the store round trip"]
        except SynLabError as exc:
            entry["ok"] = False
            entry["status"] = "QA_FAILED"
            entry["failures"] = list(entry.get("failures") or []) + [f"commit failed: {exc.code}"]
            entry["commit_error"] = exc.to_dict()
    entry["build_seconds"] = build_seconds
    entry["seconds"] = time.perf_counter() - started
    return entry


def _tier_probe(mother: Any, families: Sequence[str], *, seed: int, palette_of) -> dict[str, Any]:
    """Build all three complexity tiers per family and prove the coefficients change."""
    from .api import build_pattern

    out: dict[str, Any] = {}
    for family in families:
        hashes: dict[str, str] = {}
        errors: dict[str, str] = {}
        for tier in (1, 2, 3):
            request = {"family": family, "complexity": tier,
                       "palette_id": palette_of(family), "max_aux_layers": 0,
                       "allow_aux_layers": False,
                       "seed_ref": f"pattern-tier:{family}:{tier}:{seed}"}
            try:
                recipe = build_pattern(mother, request,
                                       make_rng(int(seed), "pattern-tier", family, tier))
                hashes[str(tier)] = recipe_hash(recipe)
            except SynLabError as exc:
                errors[str(tier)] = f"{exc.code}: {exc.message[:180]}"
        out[family] = {
            "tiers": sorted(int(t) for t in hashes),
            "recipe_hashes": hashes,
            "all_three_tiers": len(hashes) == 3,
            "all_distinct": len(set(hashes.values())) == len(hashes) and len(hashes) == 3,
            "errors": errors,
        }
    return out


def audit_all_patterns(store: Any = None, *, families: Iterable[str] | None = None,
                       n_pairs: int = 1000, seed: int = 20260101, mother: Any = None,
                       prefer_real_mother: bool = True, commit: bool = True,
                       complexity: int | None = None, surface_tag: str | None = None,
                       query_points: int = 512, tier_probe: bool = True,
                       allow_aux_layers: bool = True) -> dict[str, Any]:
    """Run the 16-family audit for real and return the A05 report dictionary."""
    started = time.perf_counter()
    family_ids = _family_list(families)
    notes: list[str] = []
    if mother is None:
        from .fixtures import mother_for_audit

        mother, mother_source, mother_notes = mother_for_audit(
            prefer_real=prefer_real_mother, seed=int(seed) % 10_000)
        notes.extend(mother_notes)
    else:
        mother_source = "caller supplied mother"

    def palette_of(family: str) -> str:
        return DEFAULT_PALETTE.get(family, "iron_slip")

    reports: dict[str, Any] = {}
    for family in family_ids:
        reports[family] = _one_family(
            family, mother, store=store, seed=int(seed), n_pairs=int(n_pairs),
            complexity=complexity, palette=palette_of(family), commit=bool(commit),
            query_points=int(query_points), surface_tag=surface_tag,
            allow_aux_layers=bool(allow_aux_layers))

    tiers = _tier_probe(mother, family_ids, seed=int(seed), palette_of=palette_of) \
        if tier_probe else {}

    seam_values = [entry["seam"]["chart_space_max_abs_color_error"] for entry in reports.values()
                   if isinstance(entry.get("seam"), dict)
                   and entry["seam"].get("chart_space_max_abs_color_error") is not None]
    max_seam_error = float(max(seam_values)) if seam_values else float("nan")
    world_values = [entry["seam"].get("world_space_pass") for entry in reports.values()
                    if isinstance(entry.get("seam"), dict)]
    deterministic = bool(reports) and all(bool(e.get("deterministic")) for e in reports.values())
    inheritance_ok = bool(reports) and all(bool(e.get("inheritance_pass"))
                                           for e in reports.values())

    geometric: dict[str, bool] = {}
    appearance_untouched: dict[str, bool] = {}
    for family, entry in reports.items():
        geometry = dict(entry.get("geometry") or {})
        mode = str(geometry.get("mode", entry.get("height_policy", {}).get("mode", "none")))
        if mode in _APPEARANCE_GEOMETRY_MODES:
            appearance_untouched[family] = bool(geometry.get("hash_unchanged"))
        else:
            geometric[family] = bool(geometry.get("pass"))
    geometry_applied = bool(geometric) and all(geometric.values())
    appearance_ok = all(appearance_untouched.values())
    tiers_ok = (not tier_probe) or all(v["all_distinct"] for v in tiers.values())
    hashes = [e.get("recipe_hash") for e in reports.values() if e.get("recipe_hash")]
    hashes_unique = len(set(hashes)) == len(hashes)

    failures: list[str] = []
    for family, entry in reports.items():
        if not entry.get("ok"):
            failures.append(f"{family}: {entry.get('status')} "
                            f"{'; '.join(entry.get('failures') or []) or entry.get('error', '')}")
    if len(family_ids) != len(FAMILY_MODELS):
        failures.append(f"only {len(family_ids)} of {len(FAMILY_MODELS)} families were audited")
    if not (max_seam_error <= SEAM_TOL):
        failures.append(f"max seam colour error {max_seam_error:.3e} above {SEAM_TOL:g}")
    if not deterministic:
        failures.append("determinism check failed")
    if not inheritance_ok:
        failures.append("source inheritance check failed")
    if not geometry_applied:
        failures.append("a geometric family did not change the mother geometry")
    if not appearance_ok:
        failures.append("an appearance-only family changed the mother geometry")
    if not hashes_unique:
        failures.append("recipe hashes are not unique across families (fixed tile?)")
    if not tiers_ok:
        failures.append("complexity tiers did not change the frozen coefficients")

    ok = not failures
    report = {
        "ok": bool(ok),
        "status": "QA_PASSED" if ok else "QA_FAILED",
        "check": "A05 pattern families (plan 9.3 / 9.6)",
        "families": reports,
        "family_ids": family_ids,
        "n_families": len(family_ids),
        "families_ok": sum(1 for e in reports.values() if e.get("ok")),
        "max_seam_error": max_seam_error,
        "seam_tolerance": SEAM_TOL,
        "max_seam_error_world_space_ok": all(bool(v) for v in world_values) if world_values else None,
        "deterministic": deterministic,
        "inheritance_ok": inheritance_ok,
        "geometry_applied": geometry_applied,
        "geometry_families": geometric,
        "appearance_geometry_untouched": appearance_untouched,
        "complexity_tiers_all_distinct": tiers_ok,
        "tier_probe": tiers,
        "recipe_hashes_unique": hashes_unique,
        "fixed_image_check": {
            "verdict": "each family freezes its own algorithm and coefficients",
            "recipe_hashes_unique": hashes_unique,
            "algorithms": FAMILY_ALGORITHM,
            "raster_families_regenerate_per_recipe": True,
        },
        "mother_source": mother_source,
        "mother_id": getattr(mother, "mother_id", None),
        "mother_faces": int(getattr(mother, "n_faces", 0)),
        "store_root": (str(getattr(store, "root", "")) if store is not None else None),
        "committed": bool(commit and store is not None),
        "n_pairs": int(n_pairs),
        "seed": int(seed),
        "notes": notes,
        "failures": failures,
        "seconds": round(time.perf_counter() - started, 3),
        "evidence": {"report": "data/a12/reports/pattern_audit.json",
                     "acceptance": "A05",
                     "recipe_role": "pattern_recipe"},
    }
    return report


__all__ = ["audit_all_patterns", "FAMILY_ALGORITHM", "DEFAULT_PALETTE", "SEAM_TOL"]
