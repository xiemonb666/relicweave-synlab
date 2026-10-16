import json, sys
sys.path.insert(0, ".")
from synlab.registry import REGISTRY, load_all
from synlab.canonical import hash_file

reports = load_all()
fp = REGISTRY.fingerprint()
summary = REGISTRY.summary()
out = {
    "registry_fingerprint": fp,
    "registry_counts": {k: {"count": v["count"], "by_status": v["by_status"]} for k, v in summary.items()},
    "load_all_errors": {k: v for k, v in reports.items() if v != "OK"},
    "config_sha256": {
        "configs/a12/realistic.yaml": hash_file("configs/a12/realistic.yaml"),
        "configs/a12/next_experiment.yaml": hash_file("configs/a12/next_experiment.yaml"),
    },
}
print(json.dumps(out, ensure_ascii=False, indent=2))
