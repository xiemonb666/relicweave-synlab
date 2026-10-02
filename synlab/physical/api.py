"""Physical damage façade: ``apply_damage`` / ``audit_physical`` (plan 12, 30.7, 30.8)."""

from __future__ import annotations

import weakref
from typing import Any

import numpy as np
import trimesh

from ..canonical import hash_json
from ..errors import ErrorCode, SynLabError
from ..roles import (
    FRAME_FRAGMENT,
    SCHEMA_PHYSICAL,
    UNIT_MM,
)
from ..schemas.runtime import PhysicalComponent, PhysicalResult
from . import operators as OPS
from . import sdf as S
from .recipe import APPEARANCE_AXES, P06_VARIANTS, P08_VARIANTS, DamageOutcome, DamageRecipe

#: In-memory source lookup so ``audit_physical(result, clean)`` also works with a CleanTruth
#: (which carries no mesh).  Keyed by the source geometry hash; never serialised.
_SOURCE_MESHES: "weakref.WeakValueDictionary[str, Any]" = weakref.WeakValueDictionary()


def _mesh_of(clean: Any) -> trimesh.Trimesh | None:
    if clean is None:
        return None
    if isinstance(clean, trimesh.Trimesh):
        return clean
    mesh = getattr(clean, "mesh", None)
    if isinstance(mesh, trimesh.Trimesh):
        return mesh
    return None


def _geometry_hash(mesh: trimesh.Trimesh) -> str:
    return hash_json({"vertices": S.geometry_key(mesh), "faces": int(len(mesh.faces)),
                      "area": round(float(mesh.area), 9), "volume": round(float(mesh.volume), 9)})


def register_components(
    parts: list[trimesh.Trimesh],
    *,
    clean_fragment_id: str,
    source_volume_mm3: float,
    min_support_abs_mm3: float = 1e-3,
    min_support_rel: float = 0.005,
    added_bodies: list[tuple[trimesh.Trimesh, str]] | None = None,
) -> tuple[list[PhysicalComponent], dict[str, str], dict[str, Any]]:
    """§30.8 identity policy: keep every connected body, choose one representative.

    The representative is the largest *independently supportable* body; ties are broken by
    the frozen geometry key.  Everything else is kept as ``DEBRIS`` and still enters the
    material ledger; same-ancestor sub-fragments are flagged so they are never used as
    ordinary negatives downstream.
    """
    threshold = max(float(min_support_abs_mm3), float(min_support_rel) * max(float(source_volume_mm3), 0.0))
    entries = []
    for index, part in enumerate(parts):
        volume = float(abs(part.volume))
        entries.append({"mesh": part, "volume": volume, "index": index,
                        "supportable": bool(volume >= threshold), "contamination": False,
                        "key": S.geometry_key(part)})
    for part, material_class in (added_bodies or []):
        volume = float(abs(part.volume))
        entries.append({"mesh": part, "volume": volume, "index": len(entries),
                        "supportable": False, "contamination": True,
                        "material_class": material_class, "key": S.geometry_key(part)})
    supportable = [e for e in entries if e["supportable"]]
    representative_key = None
    if supportable:
        best = sorted(supportable, key=lambda e: (-e["volume"], e["key"]))[0]
        representative_key = (best["index"], best["key"])
    components: list[PhysicalComponent] = []
    representative_map: dict[str, str] = {}
    for entry in sorted(entries, key=lambda e: (-e["volume"], e["key"])):
        component_id = f"{clean_fragment_id}#c{entry['index']}"
        is_representative = (representative_key is not None
                             and entry["index"] == representative_key[0]
                             and entry["key"] == representative_key[1])
        meta = {
            "ancestor": clean_fragment_id,
            "clean_fragment_ancestor": clean_fragment_id,
            "geometry_key": entry["key"],
            "supportable": bool(entry["supportable"]),
            "support_threshold_mm3": threshold,
            "material_class": entry.get("material_class", "ORIGINAL"),
            "is_contamination": bool(entry["contamination"]),
            "same_ancestor_subfragment": not is_representative,
            "not_an_ordinary_negative": not is_representative,
            "source_map": "clean_fragment",
        }
        status = "CORE" if is_representative else "DEBRIS"
        components.append(PhysicalComponent(
            component_id=component_id, clean_fragment_id=clean_fragment_id, mesh=entry["mesh"],
            volume_mm3=float(entry["volume"]), is_representative=bool(is_representative),
            status=status, survivor_patch_ref=None, meta=meta))
        if is_representative:
            representative_map[clean_fragment_id] = component_id
    ledger = {
        "source_volume_mm3": float(source_volume_mm3),
        "component_count": len(entries),
        "original_component_count": int(sum(1 for e in entries if not e["contamination"])),
        "contamination_component_count": int(sum(1 for e in entries if e["contamination"])),
        "damaged_volume_mm3": float(sum(e["volume"] for e in entries if not e["contamination"])),
        "added_volume_mm3": float(sum(e["volume"] for e in entries if e["contamination"])),
        "debris_volume_mm3": float(sum(e["volume"] for e in entries if not e["supportable"])),
        "support_threshold_mm3": threshold,
        "representative_component_id": (representative_map.get(clean_fragment_id)
                                        if representative_map else None),
        "representative_available": bool(representative_map),
        "representative_status": ("PENDING" if representative_map else "INPUT_UNAVAILABLE"),
        "evidence_lost": False,
    }
    ledger["lost_volume_mm3"] = max(
        0.0, ledger["source_volume_mm3"] - ledger["damaged_volume_mm3"])
    ledger["conservation_ok"] = bool(
        abs(ledger["source_volume_mm3"] - ledger["damaged_volume_mm3"] - ledger["lost_volume_mm3"]) <= 1e-6
        * max(ledger["source_volume_mm3"], 1.0))
    if len(entries) > 1 and not ledger["representative_available"]:
        ledger["representative_status"] = "INPUT_UNAVAILABLE"
    return components, representative_map, ledger


def apply_damage(clean_truth: Any, fragment: Any, recipe: DamageRecipe,
                 rng: np.random.Generator | None = None) -> PhysicalResult:
    """Apply one physical damage level to one clean fragment (plan 12.1, 30.7).

    Level 0 (``recipe.is_identity``) returns the *source asset reference and bytes*: the
    component mesh is the very same object as ``fragment.mesh`` and no resampling,
    re-meshing or re-writing happens.
    """
    mesh = _mesh_of(fragment)
    if mesh is None:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "apply_damage needs a fragment carrying a mesh",
                          stage="physical.apply_damage")
    if not isinstance(recipe, DamageRecipe):
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"recipe must be a DamageRecipe, got {type(recipe)!r}",
                          stage="physical.apply_damage")
    clean_fragment_id = str(getattr(fragment, "fragment_id", "") or recipe.meta.get("fragment_id", "fragment"))
    mother_id = str(getattr(clean_truth, "mother_id", "") or recipe.meta.get("mother_id", ""))
    event_id = str(getattr(clean_truth, "event_id", "") or recipe.meta.get("event_id", ""))
    version = int(getattr(clean_truth, "version", 0) or 0)
    clean_ref = f"{mother_id}:{event_id}:v{version}"
    source_volume = float(abs(mesh.volume))
    _SOURCE_MESHES[_geometry_hash(mesh)] = mesh

    declared = recipe.declared()
    if recipe.is_identity:
        ledger_components, representative_map, ledger = register_components(
            [mesh], clean_fragment_id=clean_fragment_id, source_volume_mm3=source_volume)
        for component in ledger_components:
            component.meta["identity"] = True
            component.meta["source_object_is_shared"] = True
        qa = {
            "status": "PASS", "identity": True, "level": 0,
            "source_geometry_hash": _geometry_hash(mesh),
            "result_geometry_hash": _geometry_hash(ledger_components[0].mesh),
            "bytes_identical": True, "resampled": False,
            "note": "level 0 returns the source asset reference/bytes without resampling",
        }
        return PhysicalResult(
            mother_id=mother_id, clean_ref=clean_ref, event_id=event_id,
            recipe_id=recipe.recipe_id or f"{recipe.axis_id}:{recipe.variant}:L0", version=1,
            components=ledger_components, lost_volume_mm3=0.0, lost_volume_ratio=0.0,
            representative_map=representative_map, physical_truth=None, qa=qa,
            meta={"declared": declared, "identity": True, "ledger": ledger,
                  "source_geometry_hash": _geometry_hash(mesh), "axis_id": recipe.axis_id,
                  "variant": recipe.variant, "level": int(recipe.level),
                  "geometry_changed": False, "frozen": recipe.frozen()},
        )

    outcome = OPS.run_damage(mesh, recipe, fragment=fragment)
    geometry_changed = outcome.mesh is not None and outcome.mesh is not mesh and recipe.touches_geometry
    damaged_mesh = outcome.mesh if outcome.mesh is not None else mesh
    if recipe.touches_geometry:
        parts = S.component_split(damaged_mesh) if geometry_changed else [mesh]
    else:
        parts = [mesh]
    components, representative_map, ledger = register_components(
        parts, clean_fragment_id=clean_fragment_id, source_volume_mm3=source_volume,
        min_support_rel=float(recipe.meta.get("min_representative_ratio", 0.005)),
        added_bodies=[(body, "CONTAMINATION") for body in outcome.added_bodies])
    lost_volume = float(ledger["lost_volume_mm3"])
    qa = {
        "status": "PASS" if outcome.realized else "FAIL",
        "identity": False, "level": int(recipe.level), "realized": bool(outcome.realized),
        "geometry_changed": bool(geometry_changed),
        "source_geometry_hash": _geometry_hash(mesh),
        "result_geometry_hash": _geometry_hash(damaged_mesh),
        "geometry_hash_unchanged": bool(_geometry_hash(damaged_mesh) == _geometry_hash(mesh)),
        "component_count": len(components),
        "ledger": ledger,
        "sdf_pipeline": outcome.details.get("sdf_pipeline", {}),
        "failure_code": outcome.failure_code,
    }
    if not outcome.realized:
        qa["failure_code"] = qa.get("failure_code") or ErrorCode.OPERATOR_NOT_REALIZED.value
    result = PhysicalResult(
        mother_id=mother_id, clean_ref=clean_ref, event_id=event_id,
        recipe_id=recipe.recipe_id or f"{recipe.axis_id}:{recipe.variant}:L{recipe.level}",
        version=1, components=components, lost_volume_mm3=lost_volume,
        lost_volume_ratio=float(lost_volume / max(source_volume, 1e-12)),
        representative_map=representative_map, physical_truth=None, qa=qa,
        meta={
            "declared": declared, "identity": False, "ledger": ledger,
            "axis_id": recipe.axis_id, "variant": recipe.variant, "level": int(recipe.level),
            "geometry_changed": bool(geometry_changed), "frozen": recipe.frozen(),
            "source_geometry_hash": _geometry_hash(mesh),
            "measured": dict(outcome.measurements),
            "measurement_units": dict(outcome.units),
            "details": outcome.details,
            "appearance": outcome.appearance,
            "appearance_updated": bool(outcome.appearance),
        },
    )
    if outcome.mesh is not None and geometry_changed:
        # face-level provenance of the new surface: SDF-born faces carry no clean barycentric id
        from ..storage.mesh_io import with_face_attrs

        for component in components:
            if component.meta.get("is_contamination"):
                origin = np.full(len(component.mesh.faces), 2, dtype=np.uint8)
            else:
                origin = np.full(len(component.mesh.faces), 2, dtype=np.uint8)
            with_face_attrs(component.mesh, origin_kind=origin)
    _attach_physical_truth(result, clean_truth)
    return result


def _attach_physical_truth(result: PhysicalResult, clean_truth: Any) -> None:
    """Recompute residual truth through ``synlab.truth.api`` when that module is available."""
    try:  # dependency under parallel development: absence is reported, never faked
        from ..truth.api import update_residual_truth  # type: ignore
    except Exception as exc:  # pragma: no cover - parallel-development dependency
        result.meta["physical_truth_status"] = "PENDING_DEPENDENCY"
        result.meta["physical_truth_dependency"] = f"{type(exc).__name__}: {exc}"
        return
    try:
        result.physical_truth = update_residual_truth(clean_truth, result)
        result.meta["physical_truth_status"] = "UPDATED"
    except Exception as exc:  # pragma: no cover - reported honestly
        result.meta["physical_truth_status"] = "FAILED"
        result.meta["physical_truth_dependency"] = f"{type(exc).__name__}: {exc}"


# ---------------------------------------------------------------------------- audit


def _resolve_clean(result: PhysicalResult, clean: Any) -> tuple[trimesh.Trimesh | None, str]:
    mesh = _mesh_of(clean)
    if mesh is not None:
        return mesh, "explicit"
    source_hash = (result.meta or {}).get("source_geometry_hash")
    if source_hash and source_hash in _SOURCE_MESHES:
        return _SOURCE_MESHES[source_hash], "registry"
    if clean is None:
        return None, "missing"
    return None, "unresolvable"


def audit_physical(result: PhysicalResult, clean: Any = None) -> dict[str, Any]:
    """QA for one physical damage result (plan 12.4).

    Checks ``damaged ⊆ clean``, watertightness, positive volume, minimum thickness, lost
    volume/area, source residue and out-of-ROI drift, and refuses to report success when a
    declared change was not measured (``OPERATOR_NOT_REALIZED`` / ``DAMAGE_EFFECT_MISSING``).
    The audit never repairs or re-meshes anything: geometry hashes are compared before and
    after the audit to prove it.
    """
    clean_mesh, clean_source = _resolve_clean(result, clean)
    declared = dict((result.meta or {}).get("declared") or {})
    axis_id = str(declared.get("axis_id", (result.meta or {}).get("axis_id", "")))
    variant = str(declared.get("variant", (result.meta or {}).get("variant", "")))
    level = int(declared.get("level", (result.meta or {}).get("level", 0)) or 0)
    touches_geometry = bool(declared.get("touches_geometry", True))
    measured = dict((result.meta or {}).get("measured") or {})
    appearance_axes = axis_id in APPEARANCE_AXES or (
        axis_id == "P08" and P08_VARIANTS.get(variant) == "APPEARANCE")
    checks: dict[str, Any] = {}
    failures: list[str] = []
    warnings: list[str] = []
    metrics: dict[str, float] = {}

    hashes_before = [hash_json({"k": S.geometry_key(c.mesh), "v": float(abs(c.mesh.volume))})
                     for c in result.components]
    clean_hash_before = _geometry_hash(clean_mesh) if clean_mesh is not None else None

    if clean_mesh is None:
        return {
            "status": "NA", "axis_id": axis_id, "variant": variant, "level": level,
            "clean_source": clean_source, "checks": checks, "failure_codes": ["INPUT_UNAVAILABLE"],
            "reason": "clean source geometry unavailable for the subset/watertight audit",
            "measured": metrics, "no_auto_repair": {"geometry_hashes_unchanged": None},
        }

    source_volume = float(abs(clean_mesh.volume))
    damaged_volume = float(sum(c.volume_mm3 for c in result.components if not c.meta.get("is_contamination")))
    added_volume = float(sum(c.volume_mm3 for c in result.components if c.meta.get("is_contamination")))
    metrics.update({
        "source_volume_mm3": source_volume, "damaged_volume_mm3": damaged_volume,
        "added_volume_mm3": added_volume, "lost_volume_mm3": result.lost_volume_mm3,
        "lost_volume_ratio": result.lost_volume_ratio,
        "component_count": float(len(result.components)),
        "declared_level": float(level),
    })

    # ---- damaged ⊆ clean (measured on the damaged surface, tolerance disclosed)
    tol_mm = float((result.qa.get("ledger", {}) or {}).get("outside_tol_mm", 1e-3))
    outside_stats = []
    for component in result.components:
        if component.meta.get("is_contamination"):
            continue
        stats = S.outside_fraction(component.mesh, clean_mesh, n_samples=1200, tol_mm=tol_mm,
                                   seed=len(outside_stats))
        outside_stats.append(stats)
    worst_outside = max((s["max_outside_mm"] for s in outside_stats), default=0.0)
    worst_fraction = max((s["outside_fraction"] for s in outside_stats), default=0.0)
    checks["damaged_subset_clean"] = {
        "tol_mm": tol_mm, "max_outside_mm": worst_outside, "outside_fraction": worst_fraction,
        "samples": int(sum(s["samples"] for s in outside_stats)),
        "pass": bool(worst_outside <= max(tol_mm, 5e-4)),
    }
    metrics["max_outside_mm"] = worst_outside
    if not checks["damaged_subset_clean"]["pass"]:
        failures.append("DAMAGED_NOT_SUBSET_OF_CLEAN")

    # ---- watertight / positive volume / winding
    reports = [(c.component_id, S.watertight_report(c.mesh)) for c in result.components]
    non_watertight = [cid for cid, report in reports if not report["watertight"]]
    non_positive = [cid for cid, report in reports if not report["positive_volume"]]
    checks["watertight"] = {"non_watertight": non_watertight,
                            "pass": bool(not non_watertight or not touches_geometry),
                            "per_component": {cid: report["watertight"] for cid, report in reports}}
    checks["positive_volume"] = {"non_positive": non_positive, "pass": bool(not non_positive)}
    if non_watertight and touches_geometry:
        failures.append("NOT_WATERTIGHT")
    if non_positive:
        failures.append("NON_POSITIVE_VOLUME")

    # ---- thickness
    thickness_rows = []
    for component in result.components:
        if len(component.mesh.faces) < 4:
            continue
        thickness_rows.append((component.component_id,
                               S.ray_thickness(component.mesh, n_samples=200, seed=17)))
    min_thickness = min((row[1]["min_mm"] for row in thickness_rows), default=0.0)
    guard = (result.meta or {}).get("min_wall_thickness_mm")
    checks["min_thickness"] = {"min_mm": min_thickness,
                               "guard_mm": guard,
                               "pass": bool(guard is None or min_thickness >= float(guard) * 0.999),
                               "per_component": {cid: row["min_mm"] for cid, row in thickness_rows}}
    metrics["min_thickness_mm"] = min_thickness
    if guard is not None and min_thickness < float(guard) * 0.999:
        failures.append("THICKNESS_GUARD_VIOLATED")

    # ---- loss bookkeeping
    ledger = dict((result.meta or {}).get("ledger") or {})
    measured_lost = max(0.0, source_volume - damaged_volume)
    loss_error = abs(measured_lost - float(result.lost_volume_mm3))
    checks["loss_accounting"] = {
        "measured_lost_volume_mm3": measured_lost,
        "declared_lost_volume_mm3": float(result.lost_volume_mm3),
        "absolute_error_mm3": loss_error,
        "relative_error": float(loss_error / max(source_volume, 1e-12)),
        "passed = ledger_conservation": bool(ledger.get("conservation_ok", True)),
        "pass": bool(loss_error <= max(1e-6 * source_volume, 1e-6)),
    }
    metrics["measured_lost_volume_mm3"] = measured_lost
    if not checks["loss_accounting"]["pass"]:
        failures.append("LOSS_ACCOUNTING_MISMATCH")

    # ---- source residue and out-of-ROI drift (geometry axes with an interface ROI)
    residue = None
    drift = measured.get("roi_external_drift_mm")
    if touches_geometry and not appearance_axes:
        try:
            from .operators import SdfContext

            ctx = SdfContext(clean_mesh, DamageRecipe(axis_id=axis_id, variant=variant, level=level,
                                                      roi=(result.meta.get("declared", {}) or {}).get("roi")
                                                      or {"kind": "interface"},
                                                      grid={"spacing_mm": None},
                                                      meta={"shortest_structure_mm": None})
                             if False else _context_recipe(result, axis_id, variant, level))
            residue = ctx.contact_state(result.components[0].mesh)
        except Exception as exc:
            residue = {"unavailable": f"{type(exc).__name__}: {exc}"}
    if residue is not None and "unavailable" not in residue:
        metrics["source_residue_fraction"] = float(residue["residual_fraction"])
        checks["source_residue"] = {"residual_fraction": float(residue["residual_fraction"]),
                                    "residual_area_mm2": float(residue["residual_area_mm2"]),
                                    "lost_area_mm2": float(residue["lost_area_mm2"]),
                                    "measured": True}
    elif residue is not None:
        checks["source_residue"] = {"measured": False, "reason": residue["unavailable"]}
    if drift is not None:
        metrics["roi_external_drift_mm"] = float(drift)
        checks["roi_external_drift"] = {"max_mm": float(drift),
                                        "pass": bool(float(drift) <= 1e-3)}

    # ---- appearance axes must not change geometry
    if appearance_axes:
        source_hash = (result.meta or {}).get("source_geometry_hash")
        result_hashes = {_geometry_hash(c.mesh) for c in result.components}
        unchanged = bool(source_hash in result_hashes)
        checks["geometry_hash_unchanged"] = {"source_hash": source_hash,
                                             "component_hashes": sorted(result_hashes),
                                             "pass": unchanged}
        appearance = (result.meta or {}).get("appearance") or {}
        changed_texels = float(np.sum(np.any(
            np.asarray(appearance.get("texel_albedo")) != 0, axis=-1))) if appearance.get("texel_albedo") is not None else 0.0
        metrics["appearance_arrays"] = float(len(appearance))
        metrics["appearance_texels_touched"] = changed_texels
        checks["appearance_effect"] = {"arrays": sorted(appearance), "pass": bool(appearance)}
        if not unchanged:
            failures.append("APPEARANCE_CHANGED_GEOMETRY")
        if level > 0 and not appearance:
            failures.append(ErrorCode.OPERATOR_NOT_REALIZED.value)

    # ---- declared change must be measured
    declared_effect = dict((result.meta or {}).get("declared", {}).get("expected") or {})
    if level > 0:
        effect_present = True
        if appearance_axes:
            effect_present = bool((result.meta or {}).get("appearance"))
        elif touches_geometry:
            effect_present = bool(measured_lost > 1e-12 or added_volume > 1e-12)
        checks["declared_effect_measured"] = {
            "effect_present": effect_present,
            "geometry_changed": bool((result.meta or {}).get("geometry_changed", False)),
            "declared_expectation": declared_effect or None,
            "pass": effect_present,
        }
        if not effect_present:
            failures.append(ErrorCode.OPERATOR_NOT_REALIZED.value)
        target = declared_effect.get("target")
        realized_value = declared_effect.get("realized_key")
        if target is not None and realized_value and realized_value in measured:
            tol = float(declared_effect.get("tolerance", 0.01))
            achieved = float(measured[realized_value])
            deviation = abs(achieved - float(target))
            checks["declared_effect_target"] = {"target": float(target), "achieved": achieved,
                                                "tolerance": tol, "deviation": deviation,
                                                "pass": bool(deviation <= tol)}
            if deviation > tol:
                failures.append(ErrorCode.DAMAGE_EFFECT_MISSING.value)
    else:
        identity_ok = all(c.meta.get("identity", False) for c in result.components)
        checks["identity_level"] = {"pass": bool(identity_ok), "level": level}

    # ---- the audit must not have modified anything
    hashes_after = [hash_json({"k": S.geometry_key(c.mesh), "v": float(abs(c.mesh.volume))})
                    for c in result.components]
    clean_hash_after = _geometry_hash(clean_mesh) if clean_mesh is not None else None
    no_repair = {
        "geometry_hashes_unchanged": bool(hashes_before == hashes_after),
        "clean_hash_unchanged": bool(clean_hash_before == clean_hash_after),
        "repair_applied": False,
    }
    if not no_repair["geometry_hashes_unchanged"] or not no_repair["clean_hash_unchanged"]:
        failures.append("AUDIT_MUTATED_GEOMETRY")

    status = "PASS" if not failures else "FAIL"
    if level > 0 and not measured and not appearance_axes:
        status = "FAIL"
        failures.append(ErrorCode.OPERATOR_NOT_REALIZED.value)
    return {
        "status": status, "axis_id": axis_id, "variant": variant, "level": level,
        "clean_source": clean_source, "checks": checks, "failure_codes": sorted(set(failures)),
        "warnings": warnings, "measured": metrics, "declared": declared,
        "ledger": ledger, "no_auto_repair": no_repair,
        "representative_map": dict(result.representative_map),
        "components": [{"component_id": c.component_id, "status": c.status,
                        "volume_mm3": c.volume_mm3, "is_representative": c.is_representative,
                        "ancestor": c.meta.get("clean_fragment_ancestor"),
                        "same_ancestor_subfragment": c.meta.get("same_ancestor_subfragment", False)}
                       for c in result.components],
    }


def _context_recipe(result: PhysicalResult, axis_id: str, variant: str, level: int) -> DamageRecipe:
    declared = (result.meta or {}).get("declared") or {}
    return DamageRecipe(axis_id=axis_id, variant=variant, level=level,
                        roi=dict(declared.get("roi") or {"kind": "interface"}),
                        params=dict(declared.get("params") or {}),
                        grid={"spacing_mm": None},
                        meta={"shortest_structure_mm": None})


def commit_physical(store: Any, result: PhysicalResult, *, lineage_id: str | None = None,
                    split: str | None = None, component_index: int = 0) -> Any:
    """Commit the representative component mesh as a physical asset (role from roles.py)."""
    if not result.components:
        raise SynLabError(ErrorCode.DAMAGE_EFFECT_MISSING, "physical result has no components",
                          stage="physical.commit")
    representative = None
    for component in result.components:
        if component.is_representative:
            representative = component
            break
    component = representative or result.components[int(component_index)]
    from ..storage.mesh_io import mesh_arrays

    payload = dict(mesh_arrays(component.mesh))
    return store.commit_asset(
        role="physical_component", schema=SCHEMA_PHYSICAL, unit=UNIT_MM, frame=FRAME_FRAGMENT,
        payload=payload,
        meta={"component_id": component.component_id, "volume_mm3": component.volume_mm3,
              "is_representative": component.is_representative, "status": component.status,
              "ancestor": component.meta.get("clean_fragment_ancestor"),
              "recipe_id": result.recipe_id, "clean_ref": result.clean_ref,
              "axis_id": result.meta.get("axis_id"), "level": result.meta.get("level")},
        qa=dict(result.qa), lineage_id=lineage_id, split=split,
        ancestry=[result.clean_ref] if result.clean_ref else [],
    )


__all__ = ["apply_damage", "audit_physical", "register_components", "commit_physical",
           "DamageRecipe", "DamageOutcome"]
