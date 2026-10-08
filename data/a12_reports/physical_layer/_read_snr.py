import json
d = json.load(open("data/a12_reports/physical_layer/fracture_appearance_run.json", encoding="utf-8"))
st = d["stages"]
print("stages:", sorted(st))
sn = st["snr_gain"]
print()
print("=== A2 noise-vs-gain ===")
print(f"{'ev':>4} {'gain':>7} {'signal':>8} {'noise':>8} {'SNR':>7} {'binary_frac':>11} {'sat':>6}")
for r in sn["rows"]:
    print(f"{r['exposure_ev']:4.1f} {r['photon_gain']:7.1f} {r['signal_rms_dn']:8.2f} "
          f"{r['noise_rms_dn']:8.2f} {r['snr']:7.2f} {r['binary_fraction_of_output']:11.3f} "
          f"{r['saturated_fraction']:6.4f}")
print("first gain reaching SNR 10:", sn["first_gain_reaching_snr_10"],
      "ev", sn["first_ev_reaching_snr_10"])
print("shipped default row:", {k: round(v,4) if isinstance(v,float) else v
      for k,v in sn["shipped_default"].items() if k != "note"})
print("profile default:", {k: (round(v,4) if isinstance(v,float) else v)
      for k,v in sn["profile_default"].items() if k not in ("rig_side_justification",)})
