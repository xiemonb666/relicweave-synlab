import time, sys
sys.path.insert(0, ".")
from synlab.storage.store import AssetStore
t0=time.time()
from tools.a12_corr_token_map import relations_with_truth_assets, observation_map, project
st = AssetStore(r"data\a12_trainable\store")
t=time.time(); obs = observation_map(st); print("observation_map: %.2fs -> %d fragments" % (time.time()-t, len(obs)), flush=True)
t=time.time(); rels = relations_with_truth_assets(st); print("relations_with_truth_assets: %.2fs -> %d rows" % (time.time()-t, len(rels)), flush=True)
print("  supervised rows:", sum(1 for r in rels if r.get("valid") and r.get("loss_mask")), flush=True)
t=time.time(); rows, prov = project(st); print("project: %.2fs -> %d rows, mapped %d" % (time.time()-t, len(rows), prov.get("samples_mapped")), flush=True)
print("total %.1fs" % (time.time()-t0))
