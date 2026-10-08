import sys, json; sys.path.insert(0,'.')
from synlab.qc.data_quality import check_store
rep = check_store(r"data\a12_trainable\store")
checks = rep.get("checks") or []
for c in checks:
    if str(c.get("id","")).startswith("semantics"):
        print(f"{c['id']:34s} {c['status']:5s} hits={c.get('hits')}/{c.get('denominator')}  {str(c.get('detail'))[:150]}")
print()
print("overall:", rep.get("status"), "| failed:", [c["id"] for c in checks if c.get("status")=="FAIL"][:10])
