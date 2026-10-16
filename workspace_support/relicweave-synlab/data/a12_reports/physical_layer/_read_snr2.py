import json
d = json.load(open("data/a12_reports/physical_layer/fracture_appearance_run.json", encoding="utf-8"))
st = d["stages"]
sn = st["snr_gain"]
print("=== A2 noise vs gain (delivered chain, constant albedo) ===")
print(f"{'gain':>8} {'signal':>8} {'noise':>8} {'SNR':>8} {'bin_frac':>9} {'dn_mean':>8} {'sat':>7}")
for r in sn["rows"]:
    print(f"{r['effective_gain']:8.0f} {r['signal_rms_dn']:8.2f} {r['noise_rms_dn']:8.2f} "
          f"{r['snr']:8.2f} {r['binary_fraction_of_output']:9.3f} {r['dn_mean_delivered']:8.1f} "
          f"{(r['saturated_fraction'] if r['saturated_fraction'] is not None else float('nan')):7.4f}")
print("signal_reference_noise_free", round(sn["signal_reference_noise_free"],3))
print("shipped default snr", round(sn["shipped_default"]["snr"],4), "noise", round(sn["shipped_default"]["noise_rms_dn"],2))
print("required gain for SNR10", sn["required_gain_snr_10"], "ev", sn["required_ev_snr_10"])
print("first row reaching SNR10:", {k: (round(v,4) if isinstance(v,float) else v) for k,v in (sn["first_row_reaching_snr_10"] or {}).items() if k in ("effective_gain","snr","noise_rms_dn","binary_fraction_of_output")})
print("profile default:", {k: (round(v,4) if isinstance(v,float) else v) for k,v in sn["profile_default"].items() if k in ("effective_gain","exposure_ev","noise_rms_dn","signal_rms_dn","snr","denoise","sharpening","upsampled")})
print("texture dn signature:", {k: (round(v,3) if isinstance(v,float) else v) for k,v in (sn["texture_dn_signature"] or {}).items() if k in ("dn_p95_minus_p05","dn_std")})
