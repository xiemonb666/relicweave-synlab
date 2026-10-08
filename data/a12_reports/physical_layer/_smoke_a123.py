import sys, numpy as np
sys.path.insert(0, ".")
from synlab.observe import fracture_appearance as fa
cfg = fa.load_fracture_appearance_config()
print("config ok; ev", cfg.imaging_exposure_ev, "gain", cfg.imaging_gain,
      "texture", cfg.albedo_texture, cfg.albedo_texture_contrast)
c = fa.choose_contract_light(normal_world=np.array([0.85, 0.276, 0.447]))
print("chosen", c.mode, "score", round(c.response_score, 4))
for r in c.ranking:
    print("  ", r["mode"], round(r["lambert_response"], 4), "usable", round(r["usable_response"], 4))
tex = fa.make_albedo_texture(mm_per_px=0.073, material_albedo=[0.27258, 0.21714, 0.17094])
print("tex", tex.as_dict())
print("report", {k: v for k, v in fa.texture_spectrum_report(tex, n=256).items()
                 if k in ("dominant_cycles_per_px", "dominant_over_nyquist", "modulation_rms",
                          "power_fraction_above_nyquist", "anisotropy")})
cons = fa.texture_consistency_report(material_albedo=[0.27258, 0.21714, 0.17094],
                                    rungs_mm_per_px=[0.073, 0.0365], n=256)
print("verdict", cons["verdict"])
for r in cons["rows"]:
    print("  ", r["mm_per_px"], [round(x, 4) for x in r["wavelengths_mm"]],
          round(r["dominant_cycles_per_mm"], 4), round(r["slope_rms_per_mm"], 5),
          round(r["dominant_over_nyquist"], 4))
