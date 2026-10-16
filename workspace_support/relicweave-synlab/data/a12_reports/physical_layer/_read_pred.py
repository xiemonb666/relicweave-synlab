import json
d = json.load(open("data/a12_reports/physical_layer/fracture_appearance_run.json", encoding="utf-8"))
rows = d["stages"]["prediction"]["rows"]
for r in rows:
    print("Ra", r["ra_mm"], "measured dDN", round(r["measured_dDN_rms"], 3))
    print("   legacy ROI-grid pred", round(r["legacy_prediction_roi_grid"], 3),
          "ratio", round(r["legacy_ratio_measured_over_pred"], 4))
    print("   hit-point   pred    ", round(r["hitpoint_prediction"], 3),
          "ratio", round(r["hitpoint_ratio_measured_over_pred"], 4))
    print("   grad RMS roi-grid", round(r["gradient_rms_roi_grid"], 5),
          " hit-points", round(r["gradient_rms_hit_points"], 5),
          " hit-points FD", round(r["gradient_rms_hit_points_finite_difference"], 5))
    print("   radii p50 grid", round(r["grid_radius_p50_mm"], 2),
          " hit", round(r["hit_radius_p50_mm"], 2),
          " frac>10mm grid", round(r["grid_fraction_beyond_10mm"], 3),
          " hit", round(r["hit_fraction_beyond_10mm"], 3))
