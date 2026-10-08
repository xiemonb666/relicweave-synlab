import sys, numpy as np
sys.path.insert(0, ".")
from synlab.observe import fracture_appearance as fa
tex = fa.make_albedo_texture(mm_per_px=0.073, material_albedo=[0.27258, 0.21714, 0.17094],
                             correlation_length_mm=2.6)
d = tex.as_dict()
print("declared:", {k: d[k] for k in ("wavelengths_mm","wavelengths_px","dominant_cycles_per_px",
      "dominant_cycles_per_mm","dominant_over_nyquist","shortest_period_px","nyquist_ok")})
r = fa.texture_spectrum_report(tex, n=512)
print("measured:", {k: round(r[k], 6) for k in ("dominant_cycles_per_px","dominant_cycles_per_mm",
      "dominant_over_nyquist","power_fraction_above_nyquist","modulation_rms","slope_rms_per_mm",
      "anisotropy")})
cons = fa.texture_consistency_report(material_albedo=[0.27258, 0.21714, 0.17094],
                                    correlation_length_mm=2.6,
                                    rungs_mm_per_px=[0.073, 0.0365], n=512)
print("verdict", cons["verdict"], "max dev", round(cons["max_relative_deviation"], 8),
      "nyq ok", cons["nyquist_ok_every_rung"])
for row in cons["rows"]:
    print("  rung", row["mm_per_px"], "wl_mm", [round(x,4) for x in row["wavelengths_mm"]],
          "wl_px", [round(x,2) for x in row["wavelengths_px"]],
          "cyc/mm", round(row["dominant_cycles_per_mm"],6),
          "cyc/px", round(row["dominant_cycles_per_px"],6),
          "nyq", round(row["dominant_over_nyquist"],6),
          "slope/mm", round(row["slope_rms_per_mm"],6),
          "modrms", round(row["modulation_rms"],6))
