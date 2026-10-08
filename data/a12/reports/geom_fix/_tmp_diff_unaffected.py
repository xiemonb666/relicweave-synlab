"""Ad-hoc: compare pre-fix and post-fix part records for the vessels A1/A2 must NOT touch."""
import json
from pathlib import Path

PRE = Path("data/a12/reports/mother_geometry_audit/parts")
POST = Path("data/a12/reports/geom_fix/parts")

for v in ("V13", "V14", "V18", "V19", "V20", "V21", "V22", "V23", "V24"):
    a = json.loads((PRE / f"{v}.json").read_text(encoding="utf-8"))
    b = json.loads((POST / f"{v}.json").read_text(encoding="utf-8"))
    print(f"--- {v}")
    print("  pre  z_max=%9.4f bbox=%s vol=%12.2f faces=%6d sec=%5.2f" % (
        a["mesh"]["z_max"], [round(x, 3) for x in a["mesh"]["bbox_mm"]],
        a["mesh"]["volume_mm3"], a["mesh"]["faces"], a["seconds"]))
    print("  post z_max=%9.4f bbox=%s vol=%12.2f faces=%6d sec=%5.2f" % (
        b["mesh"]["z_max"], [round(x, 3) for x in b["mesh"]["bbox_mm"]],
        b["mesh"]["volume_mm3"], b["mesh"]["faces"], b["seconds"]))
    pa, pb = a["params"], b["params"]
    diff = {k: (pa.get(k), pb.get(k)) for k in set(pa) | set(pb) if pa.get(k) != pb.get(k)}
    print("  params identical:", not diff, diff if diff else "")
    print("  pre  geometry_hash:", a.get("geometry_hash"))
    print("  post geometry_hash:", b.get("geometry_hash"))
    print("  pre  audit ok=%s failures=%s" % (a["audit"]["ok"],
                                              [f.get("check") for f in a["audit"]["failures"]]))
    print("  post audit ok=%s failures=%s" % (b["audit"]["ok"],
                                              [f.get("check") for f in b["audit"]["failures"]]))
    print("  pre  profile_metrics:", json.dumps({k: a["profile_metrics"].get(k) for k in
                                                 sorted(a["profile_metrics"])}, sort_keys=True)[:300])
