"""Step 8 (read-only): assemble the deliverable audit.

Merges the 24 per-vessel part records (``parts/*.json``), the call trace (``s05_trace.json``),
the frozen-batch reproduction (``s04_frozen_repro.json``) and the control-point chain probe
(``s02_chain.json``) into ``data/a12/reports/mother_geometry_audit.json``, and prints the
markdown symptom table used by ``docs/a12/mother_geometry_audit.md``.

Every number in the output is either measured here or quoted from one of those files; the
symptom rules are stated in ``SYMPTOM_RULES`` and are applied mechanically.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # <repo>/data/a12/reports/mother_geometry_audit
REPO = HERE.parents[3]                          # <repo>
sys.path.insert(0, str(HERE))

PARTS = HERE / "parts"
OUT_JSON = REPO / "data" / "a12" / "reports" / "mother_geometry_audit.json"

VESSELS = [f"V{i:02d}" for i in range(1, 25)]

#: builders that call ``common.shell_profile`` (their target is recorded by that function)
SHELL_PROFILE_VESSELS = ("V01", "V02", "V03", "V04", "V05", "V06", "V07", "V08", "V09", "V10",
                         "V11", "V12", "V15", "V16", "V17")
#: builders whose profile ends in a shoulder cone / neck that *decreases* in radius
NECK_FAMILY = ("V06", "V07", "V08", "V09", "V10", "V11", "V16")
#: builders that call ``common.wall_points`` with a rising target radius
WALL_POINTS_FAMILY = SHELL_PROFILE_VESSELS

SYMPTOM_RULES = {
    "S1_profile_truncated": "profile_metrics.z_rim_target_mm - profile_metrics.z_rim > "
                            "max(2.0 mm, 1% of the target)  [shell_profile vessels]",
    "S2_extent_short": "declared z size - measured body z extent > max(2.0 mm, 1% of declared) "
                       "[non-shell_profile vessels]",
    "S3_neck_lost": "an appended shoulder/neck cone exists (monotone filter dropped >0 points) "
                    "and the body radius in its top decile is >= 98% of its own maximum",
    "S4_wall_flat": "wall_points returned r_span == 0 although its target radius R > r_start "
                    "(the wall cannot widen)",
    "S5_floating_part": "a positive vertical gap > 1 mm between consecutive bodies",
    "S6_other_geometry_defect": "defect proven outside the profile helpers (currently V22 only)",
}

ATTRIBUTION = {
    "A1_wall_points_collapse": "contour algorithm defect (a): wall_points clamps every rising "
                               "radius to the first sample",
    "A2_monotone_drops_neck": "contour algorithm defect (a): monotone_radius_control_points "
                              "deletes the shoulder/neck section",
    "A3_stele_bevel_intersection": "geometry algorithm defect (a, independent): V22's bevel is a "
                                   "boolean intersection with a bevel-thick plate",
    "B1_figurine_height_semantics": "parameter/geometry semantics (b): height_mm is not the "
                                    "realised total height",
    "C_design_or_match": "matches its own declaration within tolerance, or the deviation is by "
                         "design (documented per vessel)",
}


def sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True,
                              check=False).stdout.strip()
    except Exception as exc:  # pragma: no cover
        return f"<{type(exc).__name__}: {exc}>"


def load(name: str):
    path = HERE / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def main() -> int:
    parts = {v: json.loads((PARTS / f"{v}.json").read_text(encoding="utf-8")) for v in VESSELS}
    trace = load("s05_trace.json") or {}
    frozen = load("s04_frozen_repro.json") or {}
    chain = load("s02_chain.json") or {}

    for vessel_id, row in parts.items():
        tr = (trace.get(vessel_id) or {}).get("trace") or []
        wall = [t for t in tr if t["helper"] == "wall_points"]
        mono = [t for t in tr if t["helper"] == "monotone_radius_control_points"]
        shell = [t for t in tr if t["helper"] == "shell_profile"]
        row["trace_summary"] = {
            "wall_points_calls": len(wall),
            "wall_points_target_radius_mm": [t["call"]["kwargs"].get("R_mm") for t in wall],
            "wall_points_start_radius_mm": [t["call"]["kwargs"].get("r_start_mm") for t in wall],
            "wall_points_flat_radius_mm": [t["out_r_max"] for t in wall],
            "wall_points_out_r_span_mm": [t["out_r_span"] for t in wall],
            "monotone_in_out": [[t["n_in"], t["n_out"]] for t in mono],
            "monotone_dropped": sum(t["n_dropped"] for t in mono),
            "shell_profile_z_rim_argument_mm": [t["z_rim_mm_argument"] for t in shell],
            "shell_profile_R_argument_mm": [t["R_mm_argument"] for t in shell],
        }

    symptom_table = []
    for vessel_id in VESSELS:
        row = parts[vessel_id]
        body, mesh = row.get("body") or {}, row.get("mesh") or {}
        ts = row["trace_summary"]
        audit = row.get("audit") or {}
        symptoms: list[str] = []
        notes: list[str] = []

        declared = row.get("declared_z_extent_mm")
        tol = max(2.0, 0.01 * abs(float(declared))) if declared else 2.0

        profile_short = body.get("profile_shortfall_mm")
        if profile_short is not None and profile_short > tol:
            symptoms.append("S1_profile_truncated")
        extent_short = body.get("extent_shortfall_mm")
        if vessel_id not in SHELL_PROFILE_VESSELS and extent_short is not None \
                and extent_short > tol:
            symptoms.append("S2_extent_short")

        if ts["monotone_dropped"] > 0:
            top_ratio = body.get("top_over_max_radius_ratio")
            if top_ratio is not None and top_ratio >= 0.98:
                symptoms.append("S3_neck_lost")

        if ts["wall_points_calls"] and any(
                span is not None and span < 1e-9 for span in ts["wall_points_out_r_span_mm"]) \
                and any(target is not None and start is not None and target > start + 1.0
                        for target, start in zip(ts["wall_points_target_radius_mm"],
                                                 ts["wall_points_start_radius_mm"])):
            symptoms.append("S4_wall_flat")

        if float(row.get("max_positive_gap_mm") or 0.0) > 1.0:
            symptoms.append("S5_floating_part")

        if vessel_id == "V22":
            symptoms.append("S6_other_geometry_defect")

        # ---- attribution --------------------------------------------------------------
        attribution: list[str] = []
        if "S4_wall_flat" in symptoms:
            attribution.append("A1_wall_points_collapse")
        if "S3_neck_lost" in symptoms or ("S1_profile_truncated" in symptoms
                                          and vessel_id in NECK_FAMILY):
            attribution.append("A2_monotone_drops_neck")
        if vessel_id == "V22":
            attribution.append("A3_stele_bevel_intersection")
        if vessel_id == "V23" and "S2_extent_short" in symptoms:
            attribution.append("B1_figurine_height_semantics")
        if not attribution:
            attribution.append("C_design_or_match")

        # wall width loss: measured profile r_max against the radius the builder asked for
        declared_r = (ts["shell_profile_R_argument_mm"] or [None])[0]
        measured_r = (body.get("profile_r_max"))
        width_ratio = (float(measured_r) / float(declared_r)
                       if declared_r and measured_r else None)

        if "S4_wall_flat" in symptoms:
            notes.append("wall_points returned a constant radius "
                         f"{ts['wall_points_flat_radius_mm'][0]:.3f} mm although the builder asked "
                         f"for it to run from {ts['wall_points_start_radius_mm'][0]:.3f} mm to "
                         f"{ts['wall_points_target_radius_mm'][0]:.3f} mm")
        if "S3_neck_lost" in symptoms:
            notes.append(f"the monotone filter dropped {ts['monotone_dropped']} control point(s) "
                         "and the body is still at its widest radius at its own top")
        if "S5_floating_part" in symptoms:
            worst = max(row.get("component_gaps") or [], key=lambda g: g["gap_mm"])
            notes.append(f"body top z={worst['lower_z_max']:.2f} mm, next body bottom "
                         f"z={worst['upper_z_min']:.2f} mm -> {worst['gap_mm']:.2f} mm of air")
        if vessel_id == "V23":
            notes.append("realised total height is 0.15*head_h below the ground plane plus "
                         "0.05*head_h short at the crown (see doc)")
        if vessel_id == "V22":
            notes.append("the bevel is a boolean *intersection* with a bevel-thick plate, so the "
                         f"{'38'} mm slab is cut down to the bevel thickness "
                         f"(measured z extent {body.get('z_extent_mm')} mm)")

        symptom_table.append({
            "vessel_id": vessel_id,
            "vessel_name": row.get("vessel_name"),
            "family": row.get("family"),
            "builder": row.get("builder"),
            "status": row.get("status"),
            "declared_z_mm": declared,
            "declared_source": row.get("declared_source"),
            "measured_profile_z_rim_mm": body.get("profile_z_rim"),
            "measured_z_extent_mm": body.get("z_extent_mm"),
            "profile_shortfall_mm": profile_short,
            "extent_shortfall_mm": extent_short,
            "tolerance_mm": tol,
            "n_bodies": mesh.get("n_bodies"),
            "volume_mm3": mesh.get("volume_mm3"),
            "watertight": mesh.get("watertight"),
            "audit_ok": audit.get("ok"),
            "audit_failures": [f.get("check") for f in (audit.get("failures") or [])],
            "thickness_min_mm": audit.get("thickness_min_mm"),
            "max_positive_gap_mm": row.get("max_positive_gap_mm"),
            "top_over_max_radius_ratio": body.get("top_over_max_radius_ratio"),
            "wall_flat_radius_mm": ts["wall_points_flat_radius_mm"] or None,
            "wall_target_radius_mm": ts["wall_points_target_radius_mm"] or None,
            "wall_start_radius_mm": ts["wall_points_start_radius_mm"] or None,
            "profile_r_max_mm": measured_r,
            "profile_r_max_over_declared_radius": width_ratio,
            "monotone_dropped_points": ts["monotone_dropped"],
            "symptoms": symptoms,
            "attribution": attribution,
            "notes": notes,
        })

    a1 = [r["vessel_id"] for r in symptom_table if "A1_wall_points_collapse" in r["attribution"]]
    a2 = [r["vessel_id"] for r in symptom_table if "A2_monotone_drops_neck" in r["attribution"]]
    a3 = [r["vessel_id"] for r in symptom_table if "A3_stele_bevel_intersection" in r["attribution"]]
    b1 = [r["vessel_id"] for r in symptom_table if r["attribution"] == ["B1_figurine_height_semantics"]]
    clean = [r["vessel_id"] for r in symptom_table if r["attribution"] == ["C_design_or_match"]]

    payload = {
        "report": "mother_geometry_audit",
        "scope": "24 registered vessels (V01..V24), one build per vessel through the frozen "
                 "public API, registry prototype parameters, fixed seed",
        "code_state": {
            "git_head": git("rev-parse", "HEAD"),
            "git_head_subject": git("log", "-1", "--pretty=%s"),
            "synlab_mothers_worktree_clean": git("status", "--porcelain", "--",
                                                 "synlab/mothers") == "",
            "file_hashes": {
                "synlab/mothers/vessels/common.py":
                    sha256_file(REPO / "synlab" / "mothers" / "vessels" / "common.py"),
                "synlab/mothers/geometry.py":
                    sha256_file(REPO / "synlab" / "mothers" / "geometry.py"),
            },
            "note": "no file under synlab/** was modified by this audit; it only imports and "
                    "measures",
        },
        "pipeline": {
            "steps": ["s01_find_v10_params.py", "s02_chain_probe.py", "s03_audit_vessel.py",
                      "s04_frozen_repro.py", "s05_trace_helpers.py", "s06_summary.py",
                      "s07_inspect.py", "s08_analyse.py"],
            "per_vessel_parts": "parts/<VID>.json",
            "seed": "make_rng(seed64(0xA12, vessel_id, 'mother_geometry_audit'), vessel_id, 'audit')",
            "audit_settings": "audit_mother(max_thickness_probes=320, run_self_intersection=True)",
        },
        "symptom_rules": SYMPTOM_RULES,
        "attribution_legend": ATTRIBUTION,
        "defects": {
            "A1_wall_points_collapse": {
                "site": "synlab/mothers/vessels/common.py:212-216 (wall_points, final clamp)",
                "mechanism": "for each point, 'if rr > out[-1][0]: rr = out[-1][0]' forces the "
                             "returned radii to be non-increasing. Every call site passes a "
                             "target R that is larger than its start radius, so the first sample "
                             "wins and the whole wall is returned at one constant radius.",
                "evidence": "s05_trace.json: all 15 wall_points call sites return r_span = 0.0",
                "affected": a1,
                "not_a_folding_problem": "PCHIP is a function of the chord parameter, so a rising "
                                         "then falling r(t) cannot fold the curve onto itself; the "
                                         "real fold guards are offset_clearance / curvature_margin "
                                         "inside build_shell_profile.",
            },
            "A2_monotone_drops_neck": {
                "site": "synlab/mothers/vessels/common.py:146-172 (monotone_radius_control_points)",
                "mechanism": "points with 'row[0] < kept[-1][0] - 1e-9' are dropped, so the whole "
                             "shoulder->mouth cone of a necked vessel disappears. The two guards "
                             "are mutually exclusive: wall_points forbids a rise, "
                             "monotone_radius_control_points forbids a fall, and their "
                             "intersection is a constant-radius mid-line.",
                "evidence": "s02_chain.json (V10 control points in/out) and the per-vessel "
                            "monotone_dropped_points column",
                "affected": a2,
            },
            "A3_stele_bevel_intersection": {
                "site": "synlab/mothers/vessels/group_extrude.py:447-454 (V22 bevel)",
                "mechanism": "the chamfer solid is extruded only 'bevel' high at z = thickness - "
                             "bevel and then *intersected* with the full slab, so the slab is cut "
                             "down to the bevel thickness instead of being chamfered.",
                "evidence": "s03 part V22: measured z extent 6.0 mm = bevel_mm, declared 38.0 mm",
                "affected": a3,
            },
        },
        "attribution_counts": {
            "a_contour_algorithm": sorted(set(a1) | set(a2)),
            "a_other_geometry": a3,
            "b_semantics": b1,
            "c_design_or_match": clean,
        },
        "frozen_batch_reproduction": frozen,
        "v10_control_point_chain": chain,
        "vessels": parts,
        "symptom_table": symptom_table,
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True),
                        encoding="utf-8")

    print(f"wrote {OUT_JSON}")
    print(f"a(contour)={sorted(set(a1) | set(a2))}")
    print(f"a(other)={a3}  b={b1}  c={clean}")
    print()
    lines = ["| vessel | family | declared z (mm) | measured (mm) | shortfall (mm) | bodies | "
             "max gap (mm) | top/max r | wall radius flat at (mm) | symptoms | attribution |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for row in symptom_table:
        decl = row["declared_z_mm"]
        meas = (row["measured_profile_z_rim_mm"] if row["measured_profile_z_rim_mm"] is not None
                else row["measured_z_extent_mm"])
        short = (row["profile_shortfall_mm"] if row["profile_shortfall_mm"] is not None
                 else row["extent_shortfall_mm"])
        flat = row["wall_flat_radius_mm"]
        lines.append(
            f"| {row['vessel_id']} {row['vessel_name']} | {row['family']} | "
            f"{'n/a' if decl is None else round(decl, 2)} | "
            f"{'n/a' if meas is None else round(meas, 2)} | "
            f"{'n/a' if short is None else round(short, 2)} | {row['n_bodies']} | "
            f"{round(float(row['max_positive_gap_mm'] or 0.0), 2)} | "
            f"{'n/a' if row['top_over_max_radius_ratio'] is None else round(row['top_over_max_radius_ratio'], 3)} | "
            f"{'n/a' if not flat else round(flat[0], 2)} | "
            f"{', '.join(row['symptoms']) or '-'} | {', '.join(row['attribution'])} |")
    table = "\n".join(lines)
    (HERE / "s08_symptom_table.md").write_text(table + "\n", encoding="utf-8")
    print(table)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
