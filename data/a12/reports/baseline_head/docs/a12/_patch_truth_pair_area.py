"""One-shot patch: make the R2 area verdict pair-level (see docs/a12/fracture_fix_evidence.md).

Run with the project venv: ``& .venv\\Scripts\\python.exe docs\\a12\\_patch_truth_pair_area.py``.
It rewrites ``synlab/truth/api.py`` through a temp file + atomic replace, because the file is
held open by a concurrent process on this host.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TARGET = REPO / "synlab" / "truth" / "api.py"

OLD_CLASSIFY = '''    if empty or float(patch.area_mm2) <= _EPS:
        kind, valid, loss_mask, reason = RELATION_R1, False, False, "empty_patch"
    elif new_first is not None and new_second is not None \\
            and (new_first <= 0.0 or new_second <= 0.0):
        kind, valid, loss_mask = RELATION_R1, False, False
        reason = "not_a_new_fracture_surface (assembly / outer-surface contact)"
    elif not unique_source:
        kind, valid, loss_mask, reason = RELATION_UNKNOWN, False, False, "no_unique_source"
    elif float(patch.ambiguity_area_ratio) > float(ambiguity_max):
        kind, valid, loss_mask = RELATION_UNKNOWN, False, False
        reason = f"ambiguous_area_ratio>{ambiguity_max}"
    elif inside is not None and inside < MATERIAL_INSIDE_MIN:
        kind, valid, loss_mask = RELATION_UNKNOWN, False, False
        reason = "cavity_adjacency_or_outside_material"
    elif float(patch.area_mm2) < tiny_threshold:
        kind, valid, loss_mask, reason = RELATION_TINY, True, False, "below_tiny_area"
    elif float(patch.area_mm2) < area_threshold:
        kind, valid, loss_mask = RELATION_TINY, True, False
        reason = "below_r2_area_threshold"
    elif float(patch.gap_p95_mm) > float(gap_p95_mm) \\
            or float(patch.normal_angle_p95_deg) > float(normal_p95_deg):
        kind, valid, loss_mask = RELATION_UNKNOWN, False, False
        reason = "shared_surface_geometry_out_of_budget"
    else:
        kind, valid, loss_mask, reason = RELATION_R2, True, True, "shared_new_fracture_surface"
    return {
        "pair": [pair[0], pair[1]],
        "kind": kind, "valid": bool(valid), "loss_mask": bool(loss_mask), "reason": reason,
'''

NEW_CLASSIFY = '''    if empty or float(patch.area_mm2) <= _EPS:
        kind, valid, loss_mask, reason = RELATION_R1, False, False, "empty_patch"
        structural_ok, unknown_reason = False, ""
    elif new_first is not None and new_second is not None \\
            and (new_first <= 0.0 or new_second <= 0.0):
        kind, valid, loss_mask = RELATION_R1, False, False
        reason = "not_a_new_fracture_surface (assembly / outer-surface contact)"
        structural_ok, unknown_reason = False, ""
    elif not unique_source:
        kind, valid, loss_mask, reason = RELATION_UNKNOWN, False, False, "no_unique_source"
        structural_ok, unknown_reason = False, "no_unique_source"
    elif float(patch.ambiguity_area_ratio) > float(ambiguity_max):
        kind, valid, loss_mask = RELATION_UNKNOWN, False, False
        reason = f"ambiguous_area_ratio>{ambiguity_max}"
        structural_ok, unknown_reason = False, reason
    elif inside is not None and inside < MATERIAL_INSIDE_MIN:
        kind, valid, loss_mask = RELATION_UNKNOWN, False, False
        reason = "cavity_adjacency_or_outside_material"
        structural_ok, unknown_reason = False, reason
    elif float(patch.gap_p95_mm) > float(gap_p95_mm) \\
            or float(patch.normal_angle_p95_deg) > float(normal_p95_deg):
        kind, valid, loss_mask = RELATION_UNKNOWN, False, False
        reason = "shared_surface_geometry_out_of_budget"
        structural_ok, unknown_reason = False, reason
    else:
        # Structurally a real cut face.  The *area* verdict is taken per fragment pair: a
        # plan-compliant interface is recorded as several sampling chunks whose individual areas
        # are far below the frozen threshold (measured: one V01 cut recorded as 11 patches, every
        # patch below the 10 mm^2 threshold), so a per-patch area verdict silently turns every R2
        # into TINY_CONTACT and the pipeline reports r2_pairs = 0.
        kind, valid, loss_mask, reason = RELATION_TINY, True, True, "structurally_valid_cut_face"
        structural_ok, unknown_reason = True, ""
    return {
        "pair": [pair[0], pair[1]],
        "kind": kind, "valid": bool(valid), "loss_mask": bool(loss_mask), "reason": reason,
        "structural_ok": bool(structural_ok), "unknown_reason": str(unknown_reason),
'''

OLD_MERGE = '''def _merge_pair_edges(pair: tuple[str, str], patches: Sequence[InterfacePatch],
                      evidence: Mapping[int, dict[str, Any]]) -> RelationEdge:
    """One relation per fragment pair: the strongest measured kind wins, areas are summed."""
    if not patches:
        return RelationEdge(fragment_a=pair[0], fragment_b=pair[1], kind=RELATION_R1,
                            interface_id=None, area_mm2=0.0, valid=False, loss_mask=False,
                            reason="no_direct_fracture_surface (same event, mutually exclusive)")
    measured = [(patch, evidence[int(patch.interface_id)]) for patch in patches
                if int(patch.interface_id) in evidence]
    if not measured:
        return RelationEdge(fragment_a=pair[0], fragment_b=pair[1], kind=RELATION_UNKNOWN,
                            interface_id=None, area_mm2=0.0, valid=False, loss_mask=False,
                            reason="interface_patch_without_measurement")
    kind = min((str(row["kind"]) for _, row in measured),
               key=lambda value: _KIND_PRIORITY.get(value, 9))
    qualifying = [(patch, row) for patch, row in measured if str(row["kind"]) == kind]
    # R2/TINY carry the measured shared area; R1/UNKNOWN report 0 because no valid *fracture*
    # area backs them (the raw measurement stays in ``patch_evidence``)
    area = (float(sum(float(row["area_mm2"]) for _, row in qualifying))
            if kind in (RELATION_R2, RELATION_TINY) else 0.0)
    best_patch, best_row = max(qualifying, key=lambda item: float(item[1]["area_mm2"]))
    reasons = sorted({str(row["reason"]) for _, row in measured})
    return RelationEdge(
        fragment_a=pair[0], fragment_b=pair[1], kind=kind,
        interface_id=int(best_patch.interface_id), area_mm2=area,
        valid=bool(best_row["valid"]), loss_mask=bool(best_row["loss_mask"]),
        reason=";".join(reasons),
    )
'''

NEW_MERGE = '''def _merge_pair_edges(pair: tuple[str, str], patches: Sequence[InterfacePatch],
                      evidence: Mapping[int, dict[str, Any]], area_threshold: float,
                      tiny_threshold: float) -> RelationEdge:
    """One relation per fragment pair, with the **pair-level** area verdict (plan 11.1).

    A fragment pair shares *one* new fracture surface; the interface record splits it into
    sampling chunks, so the R2 threshold has to be applied to the total shared area of the pair
    and never to a single chunk.
    """
    if not patches:
        return RelationEdge(fragment_a=pair[0], fragment_b=pair[1], kind=RELATION_R1,
                            interface_id=None, area_mm2=0.0, valid=False, loss_mask=False,
                            reason="no_direct_fracture_surface (same event, mutually exclusive)")
    measured = [(patch, evidence[int(patch.interface_id)]) for patch in patches
                if int(patch.interface_id) in evidence]
    if not measured:
        return RelationEdge(fragment_a=pair[0], fragment_b=pair[1], kind=RELATION_UNKNOWN,
                            interface_id=None, area_mm2=0.0, valid=False, loss_mask=False,
                            reason="interface_patch_without_measurement")
    structural = [(patch, row) for patch, row in measured if bool(row.get("structural_ok"))]
    eligible_area = float(sum(float(row["area_mm2"]) for _, row in structural))
    failing = [(patch, row) for patch, row in measured if not bool(row.get("structural_ok"))]
    reasons = sorted({str(row["reason"]) for _, row in measured})
    if structural:
        if eligible_area >= float(area_threshold):
            kind, valid, loss_mask = RELATION_R2, True, True
            reason = "shared_new_fracture_surface"
        elif eligible_area >= float(tiny_threshold):
            kind, valid, loss_mask = RELATION_TINY, True, False
            reason = f"below_r2_area_threshold ({eligible_area:.4g} < {float(area_threshold):.4g} mm^2)"
        else:
            kind, valid, loss_mask = RELATION_TINY, True, False
            reason = "below_tiny_area"
        best_patch, _best_row = max(structural, key=lambda item: float(item[1]["area_mm2"]))
        return RelationEdge(
            fragment_a=pair[0], fragment_b=pair[1], kind=kind,
            interface_id=int(best_patch.interface_id), area_mm2=eligible_area,
            valid=valid, loss_mask=loss_mask, reason=";".join([reason] + reasons[:3]),
        )
    unknown_rows = [(patch, row) for patch, row in failing if str(row.get("unknown_reason"))]
    if unknown_rows:
        best_patch, _row = max(unknown_rows, key=lambda item: float(item[1]["area_mm2"]))
        return RelationEdge(
            fragment_a=pair[0], fragment_b=pair[1], kind=RELATION_UNKNOWN,
            interface_id=int(best_patch.interface_id), area_mm2=0.0, valid=False, loss_mask=False,
            reason=";".join(sorted({str(row["unknown_reason"]) for _, row in unknown_rows})),
        )
    return RelationEdge(fragment_a=pair[0], fragment_b=pair[1], kind=RELATION_R1,
                        interface_id=None, area_mm2=0.0, valid=False, loss_mask=False,
                        reason=";".join(reasons))
'''

OLD_CALL = "            relations[pair] = _merge_pair_edges(pair, by_pair.get(pair, []), evidence)"
NEW_CALL = ("            relations[pair] = _merge_pair_edges(pair, by_pair.get(pair, []), evidence,\n"
            "                                              area_threshold, tiny_threshold)")


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")
    for old, new, label in ((OLD_CLASSIFY, NEW_CLASSIFY, "classify"),
                            (OLD_MERGE, NEW_MERGE, "merge"),
                            (OLD_CALL, NEW_CALL, "call")):
        if old not in text:
            print(f"PATCH ABORT: block {label!r} not found (file already patched?)")
            return 2
        text = text.replace(old, new, 1)
    temporary = TARGET.with_suffix(".py.patchtmp")
    temporary.write_text(text, encoding="utf-8")
    try:
        os.replace(temporary, TARGET)
    except OSError:
        shutil.copyfile(temporary, TARGET)
        temporary.unlink()
    print(f"patched {TARGET} ({len(text)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
