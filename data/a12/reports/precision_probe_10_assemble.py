"""precision audit probe 10 - assemble data/a12/reports/precision_audit.json.

Reads the raw probe outputs produced by precision_probe_00..09 and emits the machine
readable audit: 8 dimensions x {rig spec, synthetic status, gap, fix, priority} plus a
summary table, the TOP 5 shortfalls and the missing-metric list.

Read only with respect to code/configs/existing data; writes only the one JSON report.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
REP = ROOT / "data" / "a12" / "reports"


def load(name: str):
    p = REP / name
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def sha256_file(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def evidence(rel: str) -> dict:
    p = ROOT / rel
    return {"path": rel, "exists": p.exists(),
            "sha256": (sha256_file(p) if p.exists() and p.stat().st_size < 40_000_000 else None),
            "bytes": (p.stat().st_size if p.exists() else None)}


def main() -> int:
    contract = json.loads((ROOT / "configs/a12/capture_contract.json").read_text(encoding="utf-8"))
    inv = None  # precision_probe_00_inventory.txt is written by PowerShell with a BOM; unused
    obs_main = load("precision_probe_02_observation.json")
    obs_camp = load("precision_probe_02b_campaign.json")
    post = load("precision_probe_03_postfix.json")
    cal = load("precision_probe_04_calib_tokens.json")
    geo_final = load("precision_probe_05_geometry.json")
    geo_main = load("precision_probe_05_geometry_main.json")
    card = load("precision_probe_06_datacard_cl_v2.json")
    deg_audit = load("precision_probe_07_degrade_audit.json")
    deg_err = load("precision_probe_09_degrade_error.json")
    masks = {s: load(f"precision_probe_08_masks_{s}.json") for s in
             ("data_a12", "data_a12_final_store", "data_a12_campaign_store")}

    def agg(rep):
        return (rep or {}).get("roles", {}).get("obs_result", {}).get("aggregate")

    a_main, a_camp = agg(obs_main), agg(obs_camp)

    def pkgs_by_name():
        out = {}
        for p in (cal or {}).get("packages", []):
            out[p["package"]] = p
        return out

    P = pkgs_by_name()
    newest = P.get("data/a12_exports/trainable/next_experiment/training_package", {})
    old_nx = P.get("data/a12_exports/next_experiment/training_package", {})
    old_cl = P.get("data/a12_exports/closed_loop/training_package", {})

    def tok_summary(pkg):
        rows = pkg.get("tokens_detail") or []
        if not rows:
            return None
        return {"n_sampled": len(rows),
                "sv1_over_sv0_min": min(r["sv1_over_sv0"] for r in rows),
                "sv1_over_sv0_max": max(r["sv1_over_sv0"] for r in rows),
                "rank_1e-3_values": sorted({r["rank_1e-3"] for r in rows}),
                "n_sv_values": sorted({r["n_sv"] for r in rows}),
                "rank_1e-1_range": [min(r["rank_1e-1"] for r in rows),
                                    max(r["rank_1e-1"] for r in rows)]}

    deg_sum = (deg_err or {}).get("summary", {})

    dims = [
        {
            "id": 1, "key": "imaging",
            "title_zh": "成像精度：mm/px 档位 vs 合成渲染的实际采样密度",
            "rig_spec": {
                "resolution_table_mm_per_px": {
                    str(r["distance_mm"]): r["mm_per_px"]
                    for r in contract["working_distance_and_resolution"]["resolution_table"]["rows"]},
                "acceptance_distances_cm": contract["working_distance_and_resolution"][
                    "acceptance_distances_cm"]["spec"],
                "structure_pilot_start": contract["working_distance_and_resolution"][
                    "structure_sampling_targets"]["pilot_start"]["spec"],
                "structure_detail_goal": contract["working_distance_and_resolution"][
                    "structure_sampling_targets"]["detail_goal"]["spec"],
                "sources": {"resolution_table": "t051", "formula": "p0518",
                            "sampling_targets": "p0517", "must_report": "p0515",
                            "acceptance_distances": "p0511"},
                "confidence": {"pilot_start": "documented_candidate",
                               "detail_goal": "documented_candidate",
                               "resolution_table": "documented"},
            },
            "documented_ladder_recomputed": (cal or {}).get("documented_ladder", {}).get("rows"),
            "synthetic_now": {
                "store_data_a12": {k: a_main.get(k) for k in (
                    "n_views", "working_distance_mm_median", "mm_per_px_median", "px_per_mm_median",
                    "resolvable_4px_mm_median", "resolvable_8px_mm_median")} if a_main else None,
                "store_a12_campaign": {k: a_camp.get(k) for k in (
                    "n_views", "working_distance_mm_median", "mm_per_px_median", "px_per_mm_median",
                    "resolvable_4px_mm_median", "resolvable_8px_mm_median")} if a_camp else None,
                "px_for_0p2mm_at_campaign_median": (
                    0.2 / a_camp["mm_per_px_median"] if a_camp else None),
                "profile_implied_mm_per_px": {
                    "GLOBAL_V1": 320.0 / 1024, "MID_V1": 250.0 / 1024, "LOCAL_V1": 180.0 / 1024},
                "r_eff_mm_producers": (post or {}).get("data/a12", {}).get(
                    "meta_key_presence", {}).get("r_eff_mm"),
                "px_per_mm_meta_hits_data_a12": (post or {}).get("data/a12", {}).get(
                    "meta_key_presence", {}).get("px_per_mm"),
            },
            "gap": ("0.2 mm structure occupies 0.74 px at the median working distance "
                    "(190.5 mm) and 0.68 px in the main store (203.3 mm); the 4 px pilot start "
                    "needs 1.088 mm features. r_eff_mm has 0 producers in the whole repository; "
                    "the three resolution profiles do not align with t051's mm/px ladder."),
            "z_max_mm_for_0p2mm_4px": {
                "native_2304_wide": 0.2 / 4.0 * 1279.4256170832302,
                "delivered_768_wide": 0.2 / 4.0 * 700.6315789473684,
                "delivered_256_wide": 0.2 / 4.0 * 233.5438596491228,
                "note": ("z_max = (0.2 mm / 4 px) * f_px; the contract's 10-25 cm acceptance "
                         "distances and the 0.2 mm>=4 px target cannot both hold on the "
                         "delivered grids"),
            },
            "fix": [
                "configs/a12/camera_profiles.json: add the five distances 50/100/150/200/250 mm "
                "aligned to t051 and add px_per_mm / r_eff_mm / dof_cover_mm / effective_roi",
                "write z_max = 0.2/4*f_px as an explicit gate so the 0.2 mm target is either "
                "reachable or explicitly declared unreachable",
                "add one producer for r_eff_mm (contract p0515 requires it reported separately)",
            ],
            "priority": "P1",
            "evidence": [evidence("data/a12/reports/precision_probe_04_calib_tokens.json"),
                         evidence("data/a12/reports/precision_probe_02_observation.json"),
                         evidence("data/a12/reports/precision_probe_02b_campaign.json")],
            "recompute": [
                "& .venv\\Scripts\\python.exe data\\a12\\reports\\precision_probe_04_calib_tokens.py",
                "& .venv\\Scripts\\python.exe data\\a12\\reports\\precision_probe_02_observation.py --store data/a12 --out data\\a12\\reports\\precision_probe_02_observation.json",
                "& .venv\\Scripts\\python.exe data\\a12\\reports\\precision_probe_02_observation.py --store data/a12_campaign/store --out data\\a12\\reports\\precision_probe_02b_campaign.json",
            ],
        },
        {
            "id": 2, "key": "geometry",
            "title_zh": "几何精度：网格最小特征、断面间隙、法向一致性",
            "rig_spec": {
                "repeat_position_error_p95_mm": contract["mechanics"]["repeat_position_error_p95_mm"]["spec"],
                "repeat_position_error_confidence": "documented_candidate",
                "restated_in_H4": contract["mechanics"]["repeat_position_error_p95_mm"]["restated_in_H4"]["spec"],
                "clearance_mm": contract["mechanics"]["clearance_mm"]["spec"],
                "zero_return_test": contract["mechanics"]["zero_return_test"]["spec"],
                "no_encoder_rule": contract["mechanics"]["no_encoder"]["spec"],
                "engineering_section_gate": {"A06_shared_distance_p95_mm": 0.02,
                                             "A06_normal_reverse_angle_p95_deg": 2.0,
                                             "source": "configs/a12/qa_protocol_v1.json"},
                "sources": {"p0533": "p0533", "p1796": "p1796", "p0531": "p0531"},
            },
            "synthetic_now": {
                "data_a12_clean_truth": (geo_main or {}).get("clean_truth", {}),
                "data_a12_final_clean_truth": (geo_final or {}).get("clean_truth", {}),
                "data_a12_meshes": {r: {k: v for k, v in (geo_main or {}).get(r, {}).items()
                                        if k != "per_asset_head"}
                                    for r in ("fragment_mesh", "mother_mesh", "physical_component")},
                "data_a12_final_meshes": {r: {k: v for k, v in (geo_final or {}).get(r, {}).items()
                                              if k != "per_asset_head"}
                                          for r in ("fragment_mesh", "mother_mesh", "physical_component")},
            },
            "gap": ("iface_gap_p95 (n=573) = 1.0094e-06 mm, max = 1.1641e-05 mm, normal p95 = "
                    "3.487e-04 deg -- 3 to 9 orders of magnitude tighter than the 0.5 mm / 2.0 deg "
                    "candidates, so the candidate gates are NOT the bottleneck and the synthetic "
                    "geometry is not evidence of real reconstruction accuracy. The real risk is "
                    "degenerate mesh slivers: physical_component min edge 3.725e-09 mm, "
                    "fragment_mesh 0.258% of edges below 1e-3 mm in the pre-fix store."),
            "fix": [
                "regenerate the main store geometry (the post-fix store already measures 0.0% "
                "edges below 1e-3 mm, so this is new bytes, not a new algorithm)",
                "add A31_degenerate_edge_frac_max and A31_min_edge_mm to qa_protocol_v1.json and "
                "report frac_edge_below_1e-3mm in audit_mother / physical_result QC",
                "record the 0.5 mm P95 as 'missing' for the synthetic side: the synthetic side has "
                "no repeated positioning concept (T_WC is constructed per view)",
            ],
            "priority": "P0",
            "evidence": [evidence("data/a12/reports/precision_probe_05_geometry.json"),
                         evidence("data/a12/reports/precision_probe_05_geometry_main.json")],
            "recompute": [
                "& .venv\\Scripts\\python.exe data\\a12\\reports\\precision_probe_05_geometry.py --store data/a12_final/store",
                "& .venv\\Scripts\\python.exe data\\a12\\reports\\precision_probe_05_geometry.py --store data/a12 --out data\\a12\\reports\\precision_probe_05_geometry_main.json",
            ],
        },
        {
            "id": 3, "key": "observation",
            "title_zh": "观测精度：深度误差、CoC/mark-out、掩码覆盖率、Blender vs CPU",
            "rig_spec": {
                "depth_channel_rule": contract["ledger"]["full_data_chain"]["items"][5],
                "dof_mm": contract["working_distance_and_resolution"]["depth_of_field_mm"]["spec"],
                "dof_confidence": "unspecified",
                "q2_equivalent_3d_floor": contract["mask_and_quality"]["quality_3d_floor_q2_equivalent"],
                "bright_wall_rule": contract["mask_and_quality"]["bright_wall_depth_shortage"]["spec"],
                "sources": {"depth_chain": "p0459/t104", "dof_unspecified": "p0504/p0511/p0515/p0518/p0533/p0579",
                            "dof_qualitative": "p1159", "q2_floor": "unspecified_exact"},
            },
            "synthetic_now": {
                "depth_error_reference": {
                    "blender_median_mm": [0.074, 0.134], "blender_p999_mm": [0.87, 4.13],
                    "rasterizer_median_mm": [0.004, 0.013], "rasterizer_max_mm": [17.7, 48.6],
                    "analytic_plane_mm": 0.0,
                    "source": "docs/a12/observe_evidence.md section 8 item 4 (cited, not re-run)",
                },
                "blender_vs_cpu": {
                    "classification_channels_bit_identical": True,
                    "classification_channels_differing_elements": 1,
                    "classification_channels_fraction": 1.1e-07,
                    "depth_valid_pixels_compared": 356968,
                    "depth_pixels_over_0p001mm": 1,
                    "depth_max_abs_diff_mm": 214.25,
                    "depth_p99_abs_diff_mm": 3.05e-05,
                    "depth_median_abs_diff_mm": 0.0,
                    "rgb_linear_elements_over_0p01": 20,
                    "rgb_linear_total_elements": 28311552,
                    "source": "docs/a12/gpu_acceleration.md section 3.6 (cited, not re-run)",
                },
                "mask_and_coc": {k: (v or {}).get("aggregate") for k, v in masks.items()},
                "mask_semantics_values": sorted({
                    s for k, v in masks.items() for s in
                    ((v or {}).get("aggregate", {}).get("mask_semantics_values") or [])}),
            },
            "gap": ("the main store (894 assets, 412 views) still carries the pre-fix mask/CoC "
                    "bytes: mask/object 52.24%, uncertain/object 45.71%, CoC<2px only 4.85%; the "
                    "post-fix data/a12_final measures mask/object 99.27% and uncertain 0.072%. "
                    "mask_semantics is None in all three stores, so the CoC instrument cannot be "
                    "proven from the products. The rasterizer tail error (17.7-48.6 mm) is the "
                    "production default in 114/114 observations."),
            "fix": [
                "regenerate the main store observations, or recompute deployment_mask / "
                "uncertain_mask on the same depth_z with the coc_units_v2 instrument (proven "
                "bit-identical in docs/a12/data_semantics_versions.md 1.4)",
                "write meta.mask_semantics in observe/routes.py (surface_tag_pixels is already "
                "written at the same point in data/a12_final)",
                "compare per-view depth error against sigma<=0.2 mm (Q2-equivalent) instead of "
                "quoting an interval; the current evidence has no per-view values on disk",
            ],
            "priority": "P0",
            "evidence": [evidence("data/a12/reports/precision_probe_08_masks_data_a12.json"),
                         evidence("data/a12/reports/precision_probe_08_masks_data_a12_final_store.json"),
                         evidence("data/a12/reports/precision_probe_08_masks_data_a12_campaign_store.json")],
            "recompute": [
                "& .venv\\Scripts\\python.exe data\\a12\\reports\\precision_probe_08_masks.py --store data/a12 --out data\\a12\\reports\\precision_probe_08_masks_data_a12.json",
                "& .venv\\Scripts\\python.exe data\\a12\\reports\\precision_probe_08_masks.py --store data/a12_final/store --out data\\a12\\reports\\precision_probe_08_masks_data_a12_final_store.json",
                "& .venv\\Scripts\\python.exe data\\a12\\reports\\precision_probe_08_masks.py --store data/a12_campaign/store --out data\\a12\\reports\\precision_probe_08_masks_data_a12_campaign_store.json",
            ],
        },
        {
            "id": 4, "key": "calibration",
            "title_zh": "标定精度：候选值 vs 实测值",
            "rig_spec": {
                "intrinsics_fields": contract["calibration"]["intrinsics"]["spec"],
                "per_stable_condition": contract["calibration"]["per_stable_condition"]["spec"],
                "px_per_mm": contract["calibration"]["px_per_mm"]["spec"],
                "working_distance_mm": contract["calibration"]["working_distance_mm"]["spec"],
                "three_position_classes": contract["calibration"][
                    "u_cmd_mm_u_scale_read_mm_u_encoder_mm"]["spec"],
                "scale_reference": contract["calibration"]["scale_reference"]["spec"],
                "scale_drift_metric": contract["calibration"]["scale_drift_metric"]["spec"],
                "calibration_rev_rule": contract["mechanics"]["calibration_rev_rule"]["spec"],
                "sources": {"intrinsics": "p1163", "px_per_mm": "p0579/p0515",
                            "working_distance": "p0511", "three_positions": "p0591",
                            "scale_reference": "p1163", "scale_drift": "t097",
                            "rig_calibration_rev": "p0531", "calibration_id": "p0427/t045"},
            },
            "synthetic_now": {
                "documented_ladder_meta": {k: (cal or {}).get("documented_ladder", {}).get(k)
                                           for k in ("focal_length_mm", "focal_px", "pixel_pitch_mm",
                                                     "px_per_mm_sensor", "fov_h_deg", "f_number",
                                                     "f_number_provenance", "line_time_us",
                                                     "line_time_provenance")},
                "camera_profiles": {"n": 3, "calibrated_false": 3, "calibration_refs_empty": 3,
                                    "status": "STRESS_UNCALIBRATED",
                                    "source": "configs/a12/camera_profiles.json (read directly)"},
                "meta_key_hits": {store: (post or {}).get(store, {}).get("meta_key_presence")
                                  for store in ("data/a12", "data/a12_final/store",
                                                "data/a12_campaign/store",
                                                "data/a12_trainable/store")},
                "g06_g07_injection_accuracy": {
                    "note": ("G07 focal 0-3% and G06 ratio 0-5% are DEGRADATION INJECTION "
                             "magnitudes, not real calibration accuracy; the audit measures how "
                             "accurately the operator applies the declared injection"),
                    "G07_abs_error_max": 8.413408858487514e-17,
                    "G06_abs_error_max": 1.0668549377257364e-16,
                    "G07_side_effect": {"reprojection_p95_radius_px": [24.460823181775904,
                                                                      25.069301370377303],
                                        "depth_deviation_mean_mm": [1.4735003965563882,
                                                                    1.5611680314640415],
                                        "depth_deviation_p95_mm": [2.4836528765887214,
                                                                   2.637434999219359]},
                },
            },
            "gap": ("every calibration axis is a candidate or a derivation: f = 3.12520 mm "
                    "(DERIVED from FOV and sensor format; the contract fallback says 3.6 mm and "
                    "decision D6 derives 2.77 mm -- three values coexist, none measured); f/2.0 "
                    "and line_time 8.9 us are CANDIDATE; 3/3 profiles have calibrated=false; "
                    "calibration_id / rig_calibration_rev / intrinsics_profile_id / scale_drift / "
                    "r_eff_mm each have 0 hits across 894 + 30 + 167 + 463 assets."),
            "fix": [
                "physical calibration: print a known checkerboard/AprilTag, capture 10-20 frames "
                "at 10/15/20/25 cm per condition, solve fx/fy/cx/cy + k1,k2,p1,p2; accept only if "
                "reprojection RMS <= 0.2 px, 3-repeat fx spread <= 0.2%, (cx,cy) spread <= 0.5 px",
                "put a traceable scale reference in every formal capture and report scale drift; "
                "the synthetic side can first place a VIRTUAL coded target to validate the drift "
                "algorithm itself (p1164: coded targets must not enter learning/matching inputs)",
                "add calibration_rev / rig_calibration_rev / intrinsics_profile_id to asset meta; "
                "keep calibrated=false until the real measurement exists and forbid any "
                "px_per_mm-based accuracy claim meanwhile",
            ],
            "priority": "P0",
            "evidence": [evidence("data/a12/reports/precision_probe_04_calib_tokens.json"),
                         evidence("data/a12/reports/precision_probe_03_postfix.json"),
                         evidence("data/a12/reports/precision_probe_09_degrade_error.json")],
            "recompute": [
                "& .venv\\Scripts\\python.exe data\\a12\\reports\\precision_probe_04_calib_tokens.py",
                "& .venv\\Scripts\\python.exe data\\a12\\reports\\precision_probe_03_postfix.py --out data\\a12\\reports\\precision_probe_03_postfix.json",
            ],
        },
        {
            "id": 5, "key": "degradation",
            "title_zh": "退化精度：31 轴各档的施加量 vs 声明量",
            "rig_spec": {
                "axes": "31 axes (P01-P08, I01-I10, G01-G08, X01-X05)",
                "pilot_rule": "two axes per family first",
                "degradation_vector_D_14": contract["mask_and_quality"]["degradation_vector_D"]["spec"],
                "D_rule": contract["mask_and_quality"]["degradation_vector_D"]["rule"],
                "engineering_gate": {"A10_min_independent_mothers_per_axis": 20,
                                     "source": "configs/a12/qa_protocol_v1.json"},
                "sources": {"axes": "t109", "vector_D": "p0365"},
            },
            "synthetic_now": {
                "denominators": (deg_audit or {}).get("denominators"),
                "limits": (deg_audit or {}).get("limits"),
                "level0": {"n": deg_sum.get("level0_n"),
                           "identity_all_true": deg_sum.get("level0_identity_all_true"),
                           "source_hash_equals_result_hash_all": deg_sum.get("level0_hash_equal_all"),
                           "failures": deg_sum.get("level0_failures")},
                "paired_planned_vs_measured": {
                    "n_levels": deg_sum.get("n_levels"),
                    "n_levels_with_paired_quantity": deg_sum.get("n_levels_with_paired_quantity"),
                    "n_axes_with_paired_quantity": deg_sum.get("n_axes_with_paired_quantity"),
                    "max_abs_error": deg_sum.get("max_abs_error"),
                    "max_rel_error": deg_sum.get("max_rel_error"),
                    "n_rel_error_gt_1pct": deg_sum.get("n_rel_error_gt_1pct"),
                    "unpaired_axes": (deg_err or {}).get("unpaired_axes"),
                    "worst_abs_error_rows": (deg_err or {}).get("worst_abs_error"),
                    "pair_definition": deg_sum.get("pair_definition"),
                },
                "headline_axes": {
                    "P03_applied_depth_mm": [0.05, 0.05, 0.10, 0.10, 0.25, 0.25, 0.50, 0.50],
                    "P04_achieved_contact_loss": [0.10003155569580313, 0.25023666771852315,
                                                  0.5001577784790154, 0.8002524455664247],
                    "P04_max_abs_error": 2.5244556642467497e-04,
                    "P04_budget": 0.02,
                    "G01_applied_over_target": [1.13057684046434703, 1.12225652359213177,
                                                1.11119858968387031, 1.08141297402033931],
                    "G08_rel_error": [0.11561000306077818, 0.06059655801936362,
                                      0.2020740528335655, 0.12931896694378653],
                    "P08_rel_error": [0.11076049226885404, 0.03502682234143267,
                                      0.0034711265383399748, 0.0013674134848005541],
                },
            },
            "gap": ("155/155 levels PASS and level-0 identity holds 31/31 (hash equal), but only "
                    "36 levels / 9 axes have a paired declared-vs-verified quantity; 22 axes have "
                    "no independent verification of the injected magnitude (P01/P05/P06 do not "
                    "even carry planned_* keys). Among the paired ones G08 reaches 20.2% relative "
                    "error and G01 is systematically 8-13% high. "
                    "independent_mothers_observed = 1 against a required 20."),
            "fix": [
                "extend the P02/P03/P04 pattern (an independent verification quantity per axis, "
                "see docs/a12/degrade_axes.md section 7) to the remaining axes so that "
                "n_axes_with_paired_quantity goes 9 -> 31",
                "G01: add a measured-RMS rescale step (measured applied/target mean = 1.1195)",
                "G08: add measured_spurious_height_mm so the declared height and the verified "
                "max displacement are the same object",
                "run audit_all_axes on a real mother library so the independence denominator is "
                ">=20 instead of 1",
            ],
            "priority": "P0",
            "evidence": [evidence("data/a12/reports/precision_probe_07_degrade_audit.json"),
                         evidence("data/a12/reports/precision_probe_09_degrade_error.json")],
            "recompute": [
                "& .venv\\Scripts\\python.exe -c \"import sys,json;sys.path.insert(0,'.');from synlab.degrade import api as D;open('data/a12/reports/precision_probe_07_degrade_audit.json','w',encoding='utf-8').write(json.dumps(D.audit_all_axes(None,levels=[0,1,2,3,4]),indent=2,ensure_ascii=False,default=str))\"",
                "& .venv\\Scripts\\python.exe data\\a12\\reports\\precision_probe_09_degrade_error.py",
            ],
        },
        {
            "id": 6, "key": "features_labels",
            "title_zh": "特征/标签精度：loss_mask 语义、tokens 有效秩、frame_id、view_pos",
            "rig_spec": {
                "loss_mask_authority": "decision record D10: loss_mask is the only supervision "
                                       "gate; valid is a derived alias; "
                                       "eligible_as_negative = kind in {R1,R0} and loss_mask",
                "quality_vector_storage": contract["mask_and_quality"]["quality_vector_8"]["storage"]["spec"],
                "truth_layers": "clean / physical / visible, see roles.py",
                "deploy_whitelist": contract["ledger"]["file_classes"]["fields"][4],
                "sources": {"loss_mask": "D10", "truth": "t042", "quality_storage": "t104",
                            "deploy_whitelist": "t044/t104"},
            },
            "synthetic_now": {
                "relations_by_package": {k: (v.get("relations") if v else None)
                                         for k, v in P.items()},
                "tokens_by_package": {k: tok_summary(v) for k, v in P.items()},
                "frame_id_by_package": {k: {"index_block": (v or {}).get("frame_id_index_block"),
                                            "row_counter_matches": (v or {}).get("frame_id")}
                                        for k, v in P.items()},
                "view_pos_by_package": {k: (v or {}).get("obs", {}).get("shards")
                                        for k, v in P.items()},
                "newest_package": newest.get("package"),
                "newest_frame_id_match_fraction": (newest.get("frame_id_index_block") or {}).get(
                    "measured", {}).get("match_fraction"),
                "closed_loop_v2_frame_id_match_fraction": (
                    P.get("data/a12_exports/closed_loop/training_package_v2", {})
                    .get("frame_id_index_block") or {}).get("measured", {}).get("match_fraction"),
            },
            "gap": ("the newest package (1721 relation rows) has loss_mask != valid on 3 rows "
                    "(TINY_CONTACT: valid=True, loss_mask=False) and eligible_as_negative = 1560 "
                    "(first non-zero supply), so the D10 wording 'valid is a derived alias' no "
                    "longer matches the bytes. tokens effective rank is now 256/256 and "
                    "sv[1]/sv[0] rose from ~4e-09 to 0.132-0.869, frame_id match fraction is "
                    "0.9875 (97.9% reproduced on closed_loop v2), view_pos is 100% non-zero and "
                    "equals T_WC[0,3] so its error against truth is 0.0 mm by construction -- but "
                    "the error against a MEASURED slide position is missing (no encoder)."),
            "fix": [
                "either make valid a strict alias of loss_mask again (one writer line) or update "
                "D10 and docs/a12/export_guide.md 2.7 to say 'weak alias: valid may be True while "
                "loss_mask is False'; leaving both unchanged makes 3 rows mis-supervised downstream",
                "push iface_* down into physical_truth / visible_labels (data/a12_final already does)",
                "adjudicate the u_position ceiling: the package reaches 127.12 mm while "
                "camera_profiles.json declares max_travel_mm = 120",
            ],
            "priority": "P0",
            "evidence": [evidence("data/a12/reports/precision_probe_04_calib_tokens.json")],
            "recompute": [
                "& .venv\\Scripts\\python.exe data\\a12\\reports\\precision_probe_04_calib_tokens.py",
            ],
        },
        {
            "id": 7, "key": "interface_visibility",
            "title_zh": "断面可分辨性：2D 像素数与占物体像素比",
            "rig_spec": {
                "fracture_local_2d": contract["capture_checklist"]["fracture_local_2d"]["spec"],
                "effective_directions_per_fracture": contract["capture_checklist"][
                    "fracture_local_2d"]["effective_directions_per_fracture"],
                "count_confidence": contract["capture_checklist"]["fracture_local_2d"]["count_confidence"],
                "fail_rule": contract["capture_checklist"]["fracture_local_2d"]["fail_rule"],
                "region_mask_rule": contract["mask_and_quality"]["region_mask"]["render_rule"]["spec"],
                "sources": {"fracture_local_2d": "t042/p0431/p0881",
                            "region_mask": "t101(D09)/t117/p1481"},
            },
            "synthetic_now": {
                "pre_fix": {
                    "store": "data/a12",
                    "tag_px_total": a_main.get("tag_px_total") if a_main else None,
                    "rim_px_total": a_main.get("rim_px_total") if a_main else None,
                    "n_views_with_rim": a_main.get("n_views_with_rim") if a_main else None,
                    "label_bundle_rim_px": (obs_main or {}).get("roles", {}).get(
                        "label_bundle", {}).get("rim_px_total"),
                    "label_bundle_tag_px": (obs_main or {}).get("roles", {}).get(
                        "label_bundle", {}).get("tag_px_total"),
                    "physical_component_with_interface_id": (post or {}).get("data/a12", {}).get(
                        "physical_component", {}).get("has_interface_id"),
                    "physical_component_n": (post or {}).get("data/a12", {}).get(
                        "physical_component", {}).get("n"),
                },
                "post_fix": {
                    "data/a12_campaign/store": {k: (post or {}).get("data/a12_campaign/store", {}).get("rim", {}).get(k)
                                                for k in ("rim_px", "object_px", "rim_frac_of_object",
                                                          "rim_frac_of_frame", "n_assets_with_rim",
                                                          "n_assets_scanned")},
                    "data/a12_final/store": {k: (post or {}).get("data/a12_final/store", {}).get("rim", {}).get(k)
                                             for k in ("rim_px", "object_px", "rim_frac_of_object",
                                                       "n_assets_with_rim", "n_assets_scanned")},
                    "data/a12_iface/store": {k: (post or {}).get("data/a12_iface/store", {}).get("rim", {}).get(k)
                                             for k in ("rim_px", "object_px", "rim_frac_of_object",
                                                       "n_assets_with_rim", "n_assets_scanned")},
                    "physical_component_with_interface_id": {
                        s: f"{(post or {}).get(s, {}).get('physical_component', {}).get('has_interface_id')}"
                           f"/{(post or {}).get(s, {}).get('physical_component', {}).get('n')}"
                        for s in ("data/a12", "data/a12_final/store", "data/a12_campaign/store",
                                  "data/a12_iface/store")},
                },
                "area_share_reference": {
                    "three_d_area_share_pct": [6.32, 2.83, 3.04],
                    "forward_projected_share_pct": [4.176, 2.194],
                    "rim_px_over_object_px_pct_small_grid": 1.83,
                    "rim_px_over_object_px_pct_campaign": (post or {}).get(
                        "data/a12_campaign/store", {}).get("rim", {}).get("rim_frac_of_object"),
                    "source": "docs/a12/fracture_surface_signal.md section 5 (cited for the 3D "
                              "and projected shares; the campaign rim share is measured here)",
                },
            },
            "gap": ("pre-fix rim pixels are exactly 0 in 312 213 504 tag pixels (and 0 in "
                    "313 786 368 label_bundle pixels) while the code fix already exists in HEAD; "
                    "post-fix stores measure 1.83% (256x192), 5.32% (campaign, 288 views) and "
                    "6.67% (final) rim per object pixel. The strict ratio against the 3D area "
                    "share needs the three shares computed on ONE lineage batch; the campaign "
                    "ratio of 1.75 mixes asset sets and must not be read as label inflation."),
            "fix": [
                "regenerate the main store observations and components (post-fix stores measure "
                "pc_interfaces 1/1, 2/2, 6/9 while the main store is 0/55)",
                "compute the three shares (3D area, forward-projected, rim pixels) on one lineage "
                "batch and write them into reports/",
                "add the fracture_local view ring (+-10/20/30/40 deg) so each fracture gets 3-6 "
                "effective directions instead of a single all-round 4-view ring",
            ],
            "priority": "P0",
            "evidence": [evidence("data/a12/reports/precision_probe_03_postfix.json"),
                         evidence("data/a12/reports/precision_probe_02_observation.json"),
                         evidence("data/a12/reports/precision_probe_02b_campaign.json")],
            "recompute": [
                "& .venv\\Scripts\\python.exe data\\a12\\reports\\precision_probe_03_postfix.py --out data\\a12\\reports\\precision_probe_03_postfix.json",
                "& .venv\\Scripts\\python.exe data\\a12\\reports\\precision_probe_02_observation.py --store data/a12_campaign/store --out data\\a12\\reports\\precision_probe_02b_campaign.json",
            ],
        },
        {
            "id": 8, "key": "training_package",
            "title_zh": "训练包精度：数据卡逐列/逐通道 min/max/缺失率抽查",
            "rig_spec": {
                "ledger_rule": contract["ledger"]["file_classes"]["note"],
                "gt_isolation": contract["ledger"]["gt_isolation"]["spec"],
                "deploy_whitelist_semantics": "only RGB + deployment mask + camera u position may "
                                              "enter the model input",
                "sources": {"ledger": "t044", "gt_isolation": "p0626", "whitelist": "t044/t104"},
            },
            "synthetic_now": {
                "card_checked_package": (card or {}).get("package"),
                "n_checks": (card or {}).get("n_checks"),
                "n_match": (card or {}).get("n_match"),
                "n_mismatch": (card or {}).get("n_mismatch"),
                "honest_boundaries": (card or {}).get("honest_boundaries"),
                "mismatch_rows": [c for c in (card or {}).get("checks", []) if not c["match"]],
                "packages_without_card": [
                    "data/a12_exports/trainable/next_experiment/training_package",
                    "data/a12_exports/next_experiment/training_package",
                    "data/a12_exports/closed_loop/training_package",
                ],
            },
            "gap": ("the one package that ships dataset_card.json (closed_loop/training_package_v2) "
                    "recomputes 328/328 (58 file sha256, 90+ missing rates, 90+ unique counts, "
                    "30+ numeric min/max/mean, 40+ channel statistics, 3 effective ranks). But the "
                    "newest package (trainable/next_experiment, 1721 relation rows, 256-dim "
                    "tokens, 98.75% frame_id) has NO data card, and v2's deploy/obs/index.json "
                    "replaced the hard forbidden_channels list with an 8-channel caveat list "
                    "(forbidden_channels = null) which the card itself marks "
                    "deploy_view_answer_field_hit = defect_present."),
            "fix": [
                "generate the missing data card: python tools/load_package.py --package "
                "data/a12_exports/trainable/next_experiment/training_package --write-card "
                "(existing tool; NOT executed here because it writes into the package)",
                "restore a hard forbidden_channels list and actually stop writing those channels, "
                "or record the relaxation as a decision with an adjudication id instead of "
                "defect_present -- the current state is neither",
                "raise --max-arrays past the 12-per-family cap and wire precision_probe_06 into "
                "tools/check_data_quality.py so every package gets a card-consistency report",
            ],
            "priority": "P0",
            "evidence": [evidence("data/a12/reports/precision_probe_06_datacard_cl_v2.json")],
            "recompute": [
                "& .venv\\Scripts\\python.exe data\\a12\\reports\\precision_probe_06_datacard.py --package data/a12_exports/closed_loop/training_package_v2 --out data\\a12\\reports\\precision_probe_06_datacard_cl_v2.json",
            ],
        },
    ]

    top5 = [
        {
            "rank": 1, "priority": "P0",
            "title": "主库 data/a12 是修复前的一代：断面 2D 像素 = 0、掩码/CoC 是 v1 口径、构件面来源 100% 丢失",
            "measured": {"rim_px": 0, "tag_px": 312213504, "physical_component_all_ambiguous": 3446247,
                         "mask_over_object": 0.5223534631975766, "uncertain_over_object": 0.4571242908225175,
                         "coc_below_markout": 0.04848366040524432},
            "post_fix_reference": {"data/a12_final": {"rim_assets": "7/7",
                                                      "mask_over_object": 0.9927082731096039,
                                                      "uncertain_over_object": 0.000721076289750482}},
            "min_fix": "用新字节替换旧字节（代码已在 HEAD）：重新生成主库观测与构件；mask/CoC 可在同一批 "
                       "depth_z 上纯重算，不必重渲染",
            "acceptance": "precision_probe_03_postfix.py 对 data/a12 报 rim_px > 0 且 "
                          "pc_interfaces = 55/55；precision_probe_08_masks.py 报 "
                          "uncertain_frac_of_object_mean < 0.01",
            "needs_new_algorithm": False,
        },
        {
            "rank": 2, "priority": "P0",
            "title": "标定轴全部是候选/推导值，calibration_* / rig_calibration_rev / scale_drift / r_eff_mm 全仓 0 命中",
            "measured": {"focal_length_mm": 3.1252012858255296, "focal_provenance": "DERIVED",
                         "f_number": 2.0, "f_number_provenance": "CANDIDATE",
                         "line_time_us": 8.9, "line_time_provenance": "CANDIDATE",
                         "profiles_calibrated_false": "3/3",
                         "calibration_id_hits": 0, "rig_calibration_rev_hits": 0,
                         "intrinsics_profile_id_hits": 0, "scale_drift_hits": 0, "r_eff_mm_hits": 0},
            "min_fix": "这需要真实测量：标定板逐距离解算（残差 <=0.2 px）→ 画面放可追溯尺度基准并自动查漂移 "
                       "→ meta 补 calibration_rev/rig_calibration_rev/intrinsics_profile_id",
            "acceptance": "3/3 profile calibrated=true 且 calibration_refs 非空；reports/ 每次采集出 "
                          "scale_drift 行",
            "needs_new_algorithm": True,
        },
        {
            "rank": 3, "priority": "P0",
            "title": "22/31 退化轴没有声明→验证配对量；G08 20.2%、G01 系统性 8-13% 被 PASS 掩盖",
            "measured": {"n_levels_with_paired_quantity": 36, "n_axes_with_paired_quantity": 9,
                         "max_abs_error": 0.2845017272763304, "max_rel_error": 0.2020740528335655,
                         "n_rel_error_gt_1pct": 10,
                         "independent_mothers_observed": 1, "required": 20},
            "min_fix": "把 P02/P03/P04 的『独立通道复核』模式推广到 24 个轴；G01 加实测 RMS 反解尺度；"
                       "G08 补 measured_spurious_height_mm；真实母体库上跑 audit_all_axes",
            "acceptance": "precision_probe_09 的 n_axes_with_paired_quantity = 31 且 "
                          "n_rel_error_gt_1pct = 0",
            "needs_new_algorithm": False,
        },
        {
            "rank": 4, "priority": "P0",
            "title": "最新训练包没有数据卡；且部署视图出现答案侧字段（deploy_view_answer_field_hit = defect_present）",
            "measured": {"card_checked": "closed_loop/training_package_v2", "n_checks": 328,
                         "n_match": 328, "n_mismatch": 0,
                         "newest_package_has_card": False,
                         "deploy_view_answer_field_hit": "defect_present",
                         "forbidden_channels_in_v2": None},
            "min_fix": "① --write-card 给最新包生成数据卡；② 恢复硬 forbidden_channels 或把放开写成裁决"
                       "（当前两边都不是）；③ 去掉 --max-arrays 上限并挂进 check_data_quality.py",
            "acceptance": "reports/ 里每个包都有一份 card-consistency 报告且 n_mismatch = 0；"
                          "deploy/obs/index.json 的 forbidden_channels 非 null 或带裁决编号",
            "needs_new_algorithm": False,
        },
        {
            "rank": 5, "priority": "P1",
            "title": "成像档位与『0.2 mm >=4 px』在交付网格上不可同时成立；r_eff_mm 全仓 0 生产者",
            "measured": {"mm_per_px_median_campaign": 0.27192564136706865,
                         "px_for_0p2mm": 0.7355, "resolvable_4px_mm": 1.0877025654682746,
                         "profile_implied_mm_per_px": {"GLOBAL_V1": 0.3125, "MID_V1": 0.244140625,
                                                       "LOCAL_V1": 0.17578125},
                         "z_max_mm": {"native_2304": 63.97128085416151,
                                      "delivered_768": 35.03157894736842,
                                      "delivered_256": 11.677192982456139}},
            "min_fix": "profile 加 50/100/150/200/250 mm 五档并对齐 t051；补 px_per_mm/r_eff_mm/"
                       "dof_cover_mm/effective_roi；把 z_max = 0.2/4*f_px 写成显式门",
            "acceptance": "configs/a12/camera_profiles.json 有五档且每档 px_per_mm 与 t051 的偏差 "
                          "<=2%；reports/ 有 r_eff_mm 产物",
            "needs_new_algorithm": False,
        },
    ]

    missing = [
        {"metric": "real camera intrinsics calibration accuracy (fx/fy/cx/cy + distortion residuals)",
         "why": "no real camera on this host; 3/3 profiles calibrated=false; contract camera.lens is "
                "unspecified with a fallback assumption",
         "who": "checkerboard/AprilTag experiment after the rig exists"},
        {"metric": "absolute scale drift (t097 requires it on every capture)",
         "why": "no scale reference in frame; scale_valid=true is constructed by the renderer",
         "who": "traceable scale reference in frame / virtual coded target to validate the algorithm"},
        {"metric": "optical working distance measurement method",
         "why": "contract p0511 requires the method be stated; the synthetic side constructs the "
                "distance and has no method",
         "who": "caliper or calibration-board back-solve on the rig"},
        {"metric": "measured P95 repeat position error (0.5 mm candidate)",
         "why": "every synthetic T_WC is constructed; there is no repeated-positioning concept",
         "who": "ten-cycle zero-return test per axis (p0533)"},
        {"metric": "difference between view_pos and a MEASURED slide position",
         "why": "contract mechanics.no_encoder: the measured position field is null without an encoder",
         "who": "encoder or dial readout (p0563/p0591)"},
        {"metric": "r_eff_mm (resolvable structure size)",
         "why": "0 producers in the whole repository; p0515 requires it reported separately",
         "who": "one producer in the implementation (definition proposed in audit section 1.3)"},
        {"metric": "frame depth of field number vs the contract",
         "why": "the contract's DoF is unspecified (decision D6 cannot close it without an aperture)",
         "who": "measure the aperture then recompute per D6's c = 2.0 px x mm_per_px"},
        {"metric": "strict three-share ratio for the fracture surface on one lineage batch",
         "why": "the main store has rim = 0 and the campaign 3D area share is not the same asset set",
         "who": "re-run the fracture_surface_signal section 5 experiment on one batch"},
        {"metric": "per-view depth error against sigma <= 0.2 mm (Q2 equivalent)",
         "why": "only an interval is on disk (median 0.074-0.134 mm, p99.9 0.87-4.13 mm)",
         "who": "write the per-view errors from blender/1024_12 into reports/"},
        {"metric": "injection accuracy of 22 of the 31 degradation axes",
         "why": "no paired measured_* quantity in the audit table",
         "who": "add one independent verification quantity per axis"},
        {"metric": "REAL_CAPTURE photographs",
         "why": "REAL_CAPTURE:PENDING; the document states this cannot be filled by synthesis",
         "who": "the scan rig"},
        {"metric": "degradation_vector_D (14 dims) products",
         "why": "depth_noise / curvature_noise have 0 hits in synlab/degrade/api.py",
         "who": "implement the 14-dim D with units, seed and operation order"},
    ]

    out = {
        "schema": "synlab.a12.precision_audit.v1",
        "title": "A12 全链精度审计（扫描台契约 × 合成数据）",
        "read_only": True,
        "code_state": {
            "git_head": subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                                       capture_output=True, text=True).stdout.strip(),
            "git_status_porcelain": subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                                                   capture_output=True, text=True).stdout.splitlines(),
            "modified_tracked_files": [
                line[3:] for line in subprocess.run(
                    ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True,
                    text=True).stdout.splitlines() if line[:2].strip() == "M"],
            "note": ("this audit changed no code, no config and no existing data; the working tree "
                     "carries concurrent writes from other agents (see modified_tracked_files), so "
                     "every number here is a byte snapshot of one moment"),
        },
        "contract_source": {
            "file": "configs/a12/capture_contract.json",
            "source_pointer_convention": contract["source_pointer_convention"],
            "confidence_vocabulary": contract["confidence_vocabulary"],
        },
        "store_generations": {
            "pre_fix": ["data/a12", "data/a12_exports/next_experiment/training_package",
                        "data/a12_exports/closed_loop/training_package"],
            "post_fix": ["data/a12_campaign/store", "data/a12_final/store", "data/a12_iface/store",
                         "data/a12_exports/closed_loop/training_package_v2",
                         "data/a12_exports/trainable/next_experiment/training_package"],
            "identifier": "rim pixels > 0, physical_component face__interface_id present, "
                          "tokens effective rank 256, view_pos non-zero",
        },
        "dimensions": dims,
        "top5_shortfalls": top5,
        "missing_metrics": missing,
        "probe_scripts": sorted(p.name for p in REP.glob("precision_probe_*.py")),
        "probe_outputs": sorted(p.name for p in REP.glob("precision_probe_*")
                                if p.suffix in (".json", ".txt")),
    }
    outp = REP / "precision_audit.json"
    outp.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print("wrote", outp.relative_to(ROOT).as_posix(), outp.stat().st_size, "bytes")
    print("dimensions:", len(dims), "top5:", len(top5), "missing:", len(missing))
    print("modified tracked files (NOT this audit):", out["code_state"]["modified_tracked_files"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
