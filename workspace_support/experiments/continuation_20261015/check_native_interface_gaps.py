"""Measure actual native paired-side separation in the current facet normal."""
import json
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT/"pgfrag/data/continuation_20261015"


def measure(name):
    root = DATA/("cohesive_"+name)
    initial = np.load(root/"initial_state.npz", allow_pickle=False)
    nodes = np.load(root/"history/node_state.npy", mmap_mode="r")
    steps = np.load(root/"history/node_saved_steps.npy")
    time = np.load(root/"history/ledger.npy", mmap_mode="r")[:, 0]
    rest = initial["rest_nodes_m"]; pairs = initial["cohesive_pairs"]
    lineage = json.loads((root/"lineage.json").read_text())
    tets = initial["tets"]
    sign = np.asarray([1 if rest[tets[p["post_insertion_bulk_parent_rows"][1]], 0].mean() > 0 else -1
                       for p in lineage["parent_facets"]])
    bary = np.asarray([[2/3, 1/6, 1/6], [1/6, 2/3, 1/6], [1/6, 1/6, 2/3]])
    records = []
    for i, step in enumerate(steps):
        current = rest+nodes[i, :, 0, :]
        a, b = current[pairs[:, 0]], current[pairs[:, 1]]
        mid = .5*(a+b)
        normal = np.cross(mid[:, 1]-mid[:, 0], mid[:, 2]-mid[:, 0])
        normal *= np.where(normal[:, :1] >= 0, 1, -1)
        normal /= np.linalg.norm(normal, axis=1, keepdims=True)
        jump = sign[:, None, None]*(b-a)
        qp_jump = np.einsum("qi,fij->fqj", bary, jump)
        gap = np.einsum("fqi,fi->fq", qp_jump, normal)
        records.append({"step": int(step), "time_s": float(time[step]), "min_qp_current_normal_gap_m": float(gap.min()),
                        "max_qp_current_normal_gap_m": float(gap.max()), "qps_with_gap_below_minus_1nm": int((gap < -1e-9).sum())})
    return {"case": name, "method": "ancestor-matched native sides, degree-2 Tri3 qp jump dotted with current mean-surface normal oriented toward +x; side order determined by parent tetrahedron",
            "sample_stride": int(steps[1]-steps[0]),
            "minimum_sampled_gap_m": min(r["min_qp_current_normal_gap_m"] for r in records), "records": records}


def main():
    out = ROOT/"pgfrag/experiments/cohesive_vessel_20261015/current_gap_diagnosis_v1.json"
    if out.exists():
        raise FileExistsError(out)
    results = [measure(n) for n in ("bonded_cohesive_control_v1", "weak_seam_v4")]
    out.write_text(json.dumps({"results": results}, indent=2)+"\n", encoding="utf-8")
    print(json.dumps([{k: v for k, v in r.items() if k != "records"} | {"last": r["records"][-1]} for r in results], indent=2))


if __name__ == "__main__":
    main()
