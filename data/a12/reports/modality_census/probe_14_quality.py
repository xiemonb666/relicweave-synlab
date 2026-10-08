"""Probe 14: obs_result quality vs feature_bundle quality cross-check (READ ONLY)."""
from __future__ import annotations
import json, sqlite3
from pathlib import Path
import numpy as np

ROOT = Path(r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab")
OUT = ROOT / "data" / "a12" / "reports" / "modality_census"

L = []
w = L.append


def main() -> None:
    con = sqlite3.connect(f"file:{(ROOT/'data/a12/metadata.sqlite').as_posix()}?mode=ro&immutable=1",
                          uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute("select asset_id, role, meta_json from assets where role in "
                       "('obs_result','feature_bundle')").fetchall()
    con.close()
    obs, fb = {}, {}
    for r in rows:
        mj = json.loads(r["meta_json"] or "{}")
        oid = mj.get("observation_id")
        if not oid:
            continue
        (obs if r["role"] == "obs_result" else fb)[oid] = (r["asset_id"], mj)
    common = sorted(set(obs) & set(fb))
    w("# probe_14 quality cross-check obs_result <-> feature_bundle")
    w(f"  obs_result with observation_id = {len(obs)}")
    w(f"  feature_bundle with observation_id = {len(fb)}")
    w(f"  common observation_ids = {len(common)}")
    w("")
    for k in common[:3]:
        w(f"--- observation_id {k}")
        w(f"  obs_result   asset={obs[k][0]}")
        w(f"  feat_bundle  asset={fb[k][0]}")
        q = obs[k][1].get("quality") or {}
        fbv, fbn = None, None
        with np.load(ROOT / f"data/a12/assets/{fb[k][0]}/arrays.npz", allow_pickle=False) as z:
            if "quality__names" in z.files:
                fbn = [str(x) for x in z["quality__names"]]
                fbv = [float(x) for x in z["quality__values"]]
        for i, name in enumerate(fbn or []):
            ov = q.get(name)
            w(f"    {name:26s} obs_result={ov!s:26s} feature_bundle={fbv[i]:.6g}" if ov is not None
              else f"    {name:26s} obs_result=<absent>                 feature_bundle={fbv[i]:.6g}")
        w(f"  obs_result quality keys not in feature_bundle: "
          f"{sorted(set(q) - set(fbn or []))}")
    txt = "\n".join(L)
    (OUT / "probe_14_quality_crosscheck.txt").write_text(txt, encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    main()
