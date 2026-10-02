import sys, collections; sys.path.insert(0,'.')
from synlab.storage.store import AssetStore
st = AssetStore(r"data\a12_trainable\store")
tot = 0; both = 0; one = 0
samples = []
for r in st.list_assets(role="clean_truth", limit=500):
    meta = dict(r.meta or {})
    raw = meta.get("relations")
    if not raw: continue
    pairs = {(str(x.get("a")), str(x.get("b"))) for x in raw}
    for p in pairs:
        if (p[1], p[0]) in pairs: both += 1
        else: one += 1
    tot += len(pairs)
    if len(samples) < 2 and raw:
        samples.append((r.lineage_id, len(raw), raw[0]))
print("clean_truth relation rows (directed) across assets:", tot)
print("  pairs that appear in BOTH directions:", both)
print("  pairs that appear in ONE direction only:", one)
for lin, n, row in samples:
    print("  sample", lin, "rows", n, "->", {k: row.get(k) for k in ("a","b","kind","valid","loss_mask")})
