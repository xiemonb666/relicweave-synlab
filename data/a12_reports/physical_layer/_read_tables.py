"""Compact reader: print the measured tables of the appearance run as markdown."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
path = ROOT / "data/a12_reports/physical_layer/fracture_appearance_run.json"
d = json.loads(path.read_text(encoding="utf-8"))
stages = d.get("stages", {})
print("## run")
print("specimen:", d["specimen_entry"]["vessel"], d["specimen_entry"]["material"],
      "roi:", d["roi_frame"]["roi_id"], "lit:", round(d["roi_frame"].get("lit_score", float("nan")), 3))
print("timing:", {k: round(v, 1) for k, v in d.get("timing", {}).items()})

s = stages.get("sweep")
if s:
    f = s["relief_field"]
    print("\n## relief field")
    print("material:", s["material_parameters"]["material_id"],
          "sigma_r0", round(f["sigma_r0_mm"], 4), "lambda_min", f["lambda_min_mm"],
          "Ra_unit", round(f["ra_at_unit_mm"], 4), "slope_rms_unit",
          round(f["slope_rms_at_unit_scale"], 4), "scale", round(f["amplitude_scale"], 4),
          "glaze_strip", bool(f["glaze_strip"]))
    print("bands", f["band_wavelengths_mm"], [round(x, 4) for x in f["band_amplitudes_mm"]])
    print("wall", {k: round(v, 3) if isinstance(v, (int, float)) else v
                   for k, v in (f["meta"]["wall_thickness"] or {}).items()})
    print("\n## dDN table (shading channel; difference = relief_on - relief_off)")
    print("| mm/px | L px | ss | off dN p95-p05 | facet edge DN | interior DN | "
          "Ra mm | dDN rms | dDN p95 | changed>=1 | changed>=2 | pred dDN |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for row in s["rows"]:
        if row.get("status") != "OK":
            print("|", row.get("mm_per_px_target"), "| UNREACHABLE |", "|" * 10)
            continue
        off = row["relief_off"]
        for a in row["amplitudes"]:
            df, ch = a["difference"], a["changed_code_values"]
            print(f"| {row['mm_per_px_measured']:.4f} | {row['long_edge_px']} | "
                  f"{row['supersample']} | {off['dn']['dn_p95_minus_p05']:.1f} | "
                  f"{off['facet']['facet_edge_dn_step']:.2f} | "
                  f"{off['facet']['interior_dn_step']:.3f} | {a['ra_realized_mm']:.4f} | "
                  f"{df['dDN_rms']:.2f} | {df['dDN_p95_abs']:.2f} | "
                  f"{ch['fraction_above_1_dn']:.3f} | {ch['fraction_above_2_dn']:.3f} | "
                  f"{a['prediction']['dDN_from_measured_slope']:.2f} |")
    nc = s.get("noise_control")
    if nc:
        print("\nnoise control (same render, different imaging seed): shading",
              round(nc["difference_shading"]["dDN_rms"], 4), "| quantised",
              round(nc["difference_shading_quantised"]["dDN_rms"], 4), "| shipped gain",
              round(nc["difference_delivered"]["dDN_rms"], 2))
    u = s.get("unlit_control")
    if u:
        print("unlit control:", u.get("vessel_id"), u.get("roi_id"),
              "lit", round(u.get("lit_score", 0), 3),
              "unlit_frac", (u.get("lambert") or {}).get("unlit_fraction"),
              "dDN rms", round((u.get("difference") or {}).get("dDN_rms", -1), 4),
              "changed>=1", round((u.get("difference") or {}).get("fraction_above_1_dn", -1), 4))
    sp = s.get("spectrum") or {}
    print("spectrum: psd slope", round(sp.get("psd_slope_loglog", 0), 3),
          "corr_len", round(sp.get("correlation_length_1e_mm", 0), 2),
          "expected", sp.get("expected_correlation_length_mm"))

fac = stages.get("facets")
if fac:
    print("\n## facets (mm/px", round(fac["mm_per_px_measured"], 5), ")")
    print("| mode | facet edge DN | interior DN | ratio | median face px | dN p95-p05 |")
    print("|---|---|---|---|---|---|")
    for k, v in fac["variants"].items():
        m = v["measured"]
        print(f"| {k} | {m['facet']['facet_edge_dn_step']:.2f} | "
              f"{m['facet']['interior_dn_step']:.3f} | {m['facet']['facet_contrast_ratio']:.1f} | "
              f"{m['facet']['median_face_area_px']:.0f} | {m['dn']['dn_p95_minus_p05']:.1f} |")
    md = fac["mesh_density"]
    print("geometry unchanged:", fac["geometry_unchanged"],
          "in every variant:", fac["geometry_unchanged_in_every_variant"])
    print("patch edges: median", round(md["patch_edges"]["edge_median_mm"], 4), "mm,",
          "p05", round(md["patch_edges"]["edge_p05_mm"], 4),
          "area", round(md["patch_edges"]["area_mm2"], 2), "mm2",
          "faces", md["patch_edges"]["n_faces"])
    inv = md["inverse_solve"]
    print("inverse solve: lambda_min", inv["lambda_min_mm"], "-> edge",
          round(inv["required_edge_mm"], 4), "mm, triangles", round(inv["required_triangles"]),
          "cells", round(inv["required_cells_equivalent"]), "factor",
          round(inv["density_factor"], 1))
    print("required edge in px:", {k: (round(v, 3) if isinstance(v, float) else v)
                                   for k, v in md["required_edge_in_px"].items()})
    print("current edge in px:", {k: (round(v, 3) if isinstance(v, float) else v)
                                  for k, v in md["current_edge_in_px"].items()})

mat = stages.get("materials")
if mat:
    print("\n## materials on the same fracture geometry (mm/px",
          round(mat["mm_per_px_measured"], 5), ")")
    print("| id | grain mm | porosity | sigma_r0 mm | lam_min mm | fiber mm | trans | glaze mm |"
          " Ra realized mm | dN p95-p05 | dDN rms | aniso | median blob px | facets edge DN |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for mid, row in mat["materials"].items():
        p = row["parameters"]
        on = row["relief_on"]
        print(f"| {mid} | {p['grain_scale_mm']:.2f} | {p['porosity']:.4f} | {p['sigma_r0_mm']:.4f} | "
              f"{p['lambda_min_mm']:.3f} | {p['fiber_period_mm']:.2f} | {p['transmission']:.2f} | "
              f"{p['glaze_thickness_mm']:.2f} | {row['relief_field']['realized_ra_mm']:.4f} | "
              f"{on['dn']['dn_p95_minus_p05']:.1f} | "
              f"{row['difference_relief_on_minus_off']['dDN_rms']:.2f} | "
              f"{on['direction']['anisotropy']:.3f} | "
              f"{on['grain'].get('median_blob_px', float('nan')):.0f} | "
              f"{on['facet']['facet_edge_dn_step']:.2f} |")
    print("image:", mat.get("image"))

gl = stages.get("glaze")
if gl:
    print("\n## glaze")
    print("asset channels:", gl["asset_channels"]["keys"],
          "has layer channel:", gl["asset_channels"]["has_layer_channel"])
    if gl.get("measured_layer_shell"):
        m = gl["measured_layer_shell"]
        print("measured L01 shell thickness p05/median/max:",
              {k: round(v, 3) for k, v in m["thickness_mm"].items()}, "volume",
              round(m["volume_mm3"], 1))
    if gl.get("measured_layer_shell_error"):
        print("layer shell error:", gl["measured_layer_shell_error"][:160])
    st = gl.get("relief_damping_strip")
    if st:
        print("relief damping strip: material", st["material"], "glaze",
              st["glaze_thickness_mm"], "kind", st["glaze_kind"], "strip",
              round(st["strip_width_mm"], 3), "mm =", round(st["strip_width_px"], 1), "px, ratio",
              st["ratio"])
        print("  dDN rms", round(st["difference"]["dDN_rms"], 3), "changed px fraction",
              round(st["changed_pixel_fraction"], 4))
    print("step table rows:", len(gl["step_table"]["rows"]))
    for r in gl["step_table"]["rows"][:6]:
        print("  t", round(r["thickness_mm"], 3), "mm/px", round(r["mm_per_px"], 5),
              "band", round(r["band_width_px"], 2), "px resolvable", r["laterally_resolvable_2px"],
              "albedo step DN", round(r["albedo_step_face_dn"], 2),
              "step wall DN", round(r["step_wall_dn"], 2))

im = stages.get("images")
if im:
    print("\n## A/B images")
    for v in im["views"]:
        print(f"- {v['path']}  L={v['long_edge_px']} mm/px={v['mm_per_px_measured']:.5f} "
              f"Ra={v['ra_mm']} ss={v['supersample']} dDN rms={v['dDN']['dDN_rms']:.2f} "
              f"p95={v['dDN']['dDN_p95_abs']:.2f} "
              f"facet edge off/on/smooth={v['facet_edge_step_relief_off']:.2f}/"
              f"{v['facet_edge_step_relief_on']:.2f}/{v['facet_edge_step_smooth']:.2f}")
