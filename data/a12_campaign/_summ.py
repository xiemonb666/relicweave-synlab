import json
d = json.load(open("data/a12_campaign/two_endpoint_check.json", encoding="utf-8"))
print("sampled:", d["sampled_lineage"])
for lid, v in d["per_lineage"].items():
    obs = v["observations"]
    facts = {}
    for o in obs:
        f = o.get("observation_facts") or {}
        facts[str(f.get("role"))] = facts.get(str(f.get("role")), 0) + 1
    r2 = v["r2_pairs"]
    print(f"{lid}: assets={v['assets']} obs={len(obs)} roles={facts} label_bundles={len(v['label_bundles'])} r2={len(r2)} both_ends={[p.get('both_ends_observed') for p in r2]} kinds={v['relation_kinds']}")
