"""Compare the pre-fix audit parts with the post-fix sweep parts (read-only)."""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
PRE = REPO / "data/a12/reports/mother_geometry_audit/parts"
POST = REPO / "data/a12/reports/geom_fix/parts"

rows = []
for i in range(1, 25):
    vid = f"V{i:02d}"
    pre = json.loads((PRE / f"{vid}.json").read_text(encoding="utf-8"))
    post = json.loads((POST / f"{vid}.json").read_text(encoding="utf-8"))

    def g(d, *keys, default=None):
        cur = d
        for k in keys:
            if not isinstance(cur, dict) or k not in cur:
                return default
            cur = cur[k]
        return cur

    def pz(d):
        v = g(d, "profile_metrics", "z_rim")
        if v is None:
            v = g(d, "body", "profile_z_rim")
        return v

    rows.append({
        "vessel_id": vid,
        "pre_status": pre.get("status"),
        "post_status": post.get("status"),
        "pre_params_src": pre.get("params_source"),
        "post_params_src": post.get("params_source"),
        "pre_z_rim": pz(pre),
        "post_z_rim": pz(post),
        "pre_r_max": g(pre, "profile_metrics", "r_max"),
        "post_r_max": g(post, "profile_metrics", "r_max"),
        "pre_zmax": g(pre, "mesh", "z_max"),
        "post_zmax": g(post, "mesh", "z_max"),
        "pre_vol": g(pre, "mesh", "volume_mm3"),
        "post_vol": g(post, "mesh", "volume_mm3"),
        "pre_nbodies": g(pre, "mesh", "n_bodies"),
        "post_nbodies": g(post, "mesh", "n_bodies"),
        "pre_audit_ok": g(pre, "audit", "ok"),
        "post_audit_ok": g(post, "audit", "ok"),
        "pre_hash": pre.get("geometry_hash"),
        "post_hash": post.get("geometry_hash"),
        "pre_gap": pre.get("max_positive_gap_mm"),
        "post_gap": post.get("max_positive_gap_mm"),
        "pre_ver": pre.get("registry_version"),
        "post_ver": post.get("registry_version"),
    })

hdr = f"{'vid':4} {'pre':>4} {'post':>5} {'zrim_pre':>10} {'zrim_post':>10} {'rmax_pre':>9} {'rmax_post':>9} {'vol_d%':>8} {'nb':>5} {'ok':>7} {'ver':>7}"
print(hdr)
for r in rows:
    def f(v, fmt="{:.2f}"):
        return fmt.format(v) if isinstance(v, (int, float)) else str(v)
    dv = None
    if isinstance(r["pre_vol"], (int, float)) and isinstance(r["post_vol"], (int, float)) and r["pre_vol"]:
        dv = 100.0 * (r["post_vol"] - r["pre_vol"]) / r["pre_vol"]
    print(f"{r['vessel_id']:4} {r['pre_status'][:4]:>4} {r['post_status'][:5]:>5} "
          f"{f(r['pre_z_rim']):>10} {f(r['post_z_rim']):>10} "
          f"{f(r['pre_r_max']):>9} {f(r['post_r_max']):>9} {f(dv):>8} "
          f"{str(r['pre_nbodies'])+'->'+str(r['post_nbodies']):>5} "
          f"{str(r['pre_audit_ok'])+'->'+str(r['post_audit_ok']):>7} "
          f"{str(r['pre_ver'])+'->'+str(r['post_ver']):>7}")

out = Path(__file__).resolve().parent / "_s15_prepost.json"
out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
print("wrote", out)
