import json, numpy as np, sys
sys.path.insert(0, "tests/a12/fracture")
from synlab.fracture.morphology import material_fracture_inputs, HURST_EXPONENT, ROUGHNESS_BANDS, GRAIN_RELIEF_FRACTION, POROSITY_RELIEF_GAIN
from synlab.materials.api import build_material_profile, default_material_params
from synlab.seeds import make_rng
rows=[]
for mid in ("M01","M04","M07"):
    rng = make_rng(20261001, "a12_fracture_implicit", "materials", mid)
    prof = build_material_profile(mid, default_material_params(mid), rng)
    m = material_fracture_inputs(prof)
    lc = float(m.correlation_length_mm); grain=float(m.grain_scale_mm)
    wl = np.array([lc*(2.0**(i-(ROUGHNESS_BANDS-1)/2.0)) for i in range(ROUGHNESS_BANDS)])
    wl = np.clip(wl, 0.20, max(4.0*lc,0.5))
    sigma = max(GRAIN_RELIEF_FRACTION*grain*(1+POROSITY_RELIEF_GAIN*m.porosity),1e-4)
    rows.append(dict(material=mid, grain_mm=grain, lc_mm=lc, porosity=m.porosity,
                     pit_radius_mm=m.pit_radius_mm, glaze_mm=m.glaze_thickness_mm,
                     fiber_p_mm=m.fiber_period_mm, sigma_r0=sigma, wl=[round(float(x),4) for x in wl],
                     lam_min=float(wl.min()), delta_5=float(wl.min()/5), delta_4=float(wl.min()/4)))
print(json.dumps(rows, ensure_ascii=False, indent=1))
for r in rows:
    print(r["material"], "lam_min", round(r["lam_min"],3), "delta5", round(r["delta_5"],3),
          "footprint_cells@d5", round(968.43/r["delta_5"]**2), "tris", 2*round(968.43/r["delta_5"]**2))
