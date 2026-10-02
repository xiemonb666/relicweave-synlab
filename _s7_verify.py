import sys, json
sys.path.insert(0, ".")
from pathlib import Path
import numpy as np
from synlab.storage.export import TrainingPackage
from synlab.qc.loader_probe import load_features, probe_training_package
from synlab.training.adapter import FeatureBundle
pkg_dir = Path(r"data\a12_smallfix\s7_proof\training_package")
pkg = TrainingPackage(pkg_dir)
idx = pkg.observation_index()
fids = sorted((idx.get("rows") or {}))
print("fragments with observation:", fids)
# BEFORE (simulate the old loader)
payloads_new = load_features(pkg, fids, token_budget=256)
print()
print("AFTER (new loader):")
for fid in fids:
    p = payloads_new[fid]
    q = np.asarray(p["quality"]); qv = np.asarray(p["quality_valid"])
    print(f"   {fid}: quality {q.shape} valid_sum={int(qv.sum())} first3={np.round(q.reshape(-1)[:3],4).tolist()}")
b = FeatureBundle.from_dict(payloads_new, token_budget=256).check_shapes()
print("   FeatureBundle.quality:", b.quality.shape, "valid sum:", int(b.quality_valid.sum()),
      "n_regions:", b.n_regions, "c_quality:", b.c_quality)
print()
# BEFORE: emulate the old hard-coded zeros
payloads_old = {fid: {**p, "quality": np.zeros((1,1), np.float32), "quality_valid": np.zeros((1,1), bool)}
                for fid, p in payloads_new.items()}
b_old = FeatureBundle.from_dict(payloads_old, token_budget=256).check_shapes()
print("BEFORE (old hard-coded zeros):")
print("   FeatureBundle.quality:", b_old.quality.shape, "valid sum:", int(b_old.quality_valid.sum()))
print()
res = probe_training_package(pkg_dir, out_path=r"data\a12_reports\s7_loader_probe.json")
print("probe ok:", res.get("ok"), "| files_ok:", res.get("files_ok"))
