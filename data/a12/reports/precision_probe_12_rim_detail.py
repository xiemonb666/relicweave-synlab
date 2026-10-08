import json
import pathlib

d = json.loads(pathlib.Path("data/a12/reports/precision_probe_03_postfix.json").read_text(encoding="utf-8"))
pa = [a for a in d["data/a12_campaign/store"]["rim"]["per_asset"]
      if a.get("role") == "obs_result" and a.get("object_px")]
fr = sorted((a["rim_px"] / a["object_px"], a["rim_px"], a["object_px"]) for a in pa)
print("n obs_result rows in per_asset:", len(pa))
for f, r_, o_ in fr:
    print("  frac %.4f  rim %d / object %d" % (f, r_, o_))
print("min", "%.5f" % fr[0][0], "max", "%.5f" % fr[-1][0])
mid = fr[len(fr) // 2][0]
print("median %.5f" % mid)
