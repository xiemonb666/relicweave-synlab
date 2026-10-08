import sys, json, tempfile, os
sys.path.insert(0,'.')
from pathlib import Path
from synlab.storage.export import scan_view_fields, scan_answer_fields, capture_context_keys
pkg = Path(r"data\a12_exports\trainable\next_experiment\training_package")
deploy = pkg / "deploy"
scan = scan_view_fields(deploy)
print("containers scanned:", scan["keys_scanned"], "unique keys:", len(scan["unique_keys"]))
with_keys = capture_context_keys()
res = scan_answer_fields(deploy, capture_keys=with_keys, scan=scan)
print("answer hits:", len(res["answer_hits"]))
import collections
h = collections.Counter(x["field"] for x in res["answer_hits"])
for k,v in h.most_common(30): print(f"   {v:3d}  {k}")
print("capture hits:", len(res["capture_hits"]), collections.Counter(x["field"] for x in res["capture_hits"]))
print()
res0 = scan_answer_fields(deploy, capture_keys=set(), scan=scan)
h0 = collections.Counter(x["field"] for x in res0["answer_hits"])
print("WITHOUT the policy exemption (before):", sum(h0.values()), "hits;", dict(h0))
print("WITH exemption (after):               ", sum(h.values()), "hits")
