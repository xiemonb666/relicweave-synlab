import json
d = json.load(open("data/a12_reports/physical_layer/fracture_appearance_run.json", encoding="utf-8"))
r = d["stages"]["prediction"]["rows"][0]
for k in ("ra_mm","measured_dDN_rms","legacy_prediction_roi_grid","legacy_ratio_measured_over_pred",
          "hitpoint_prediction_material_albedo","hitpoint_prediction_render_albedo",
          "hitpoint_ratio_measured_over_pred_render","closing_ratio_measured_over_pred",
          "albedo_channels_material","albedo_channels_render","dDN_factor_material","dDN_factor_render",
          "albedo_factor_ratio_render_over_material","analytic_over_finite_difference_same_points",
          "gradient_rms_roi_grid","gradient_rms_hit_points","gradient_rms_hit_points_finite_difference"):
    print(f"  {k}: {r.get(k)}")
print()
print(r["attribution"]["conclusion"])
