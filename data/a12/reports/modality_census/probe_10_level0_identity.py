"""Probe 10: EMPIRICAL level-0 identity check over all 31 axes (READ ONLY for the repo).

Uses synlab.degrade.api.probe_sources() + operator.apply(...,0,...) and apply_axis(...,0,...)
with a THROWAWAY AssetStore created under the OS temp dir, never inside the repo.
"""
from __future__ import annotations
import hashlib, json, sys, tempfile, collections
from pathlib import Path
import numpy as np

ROOT = Path(r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab")
OUT = ROOT / "data" / "a12" / "reports" / "modality_census"
sys.path.insert(0, str(ROOT))

L = []
w = L.append


def payload_fingerprint(payload: dict) -> str:
    """Independent byte-level fingerprint of every array/mesh value in the payload."""
    h = hashlib.sha256()
    for key in sorted(payload):
        v = payload[key]
        h.update(key.encode())
        if isinstance(v, np.ndarray):
            h.update(str(v.shape).encode())
            h.update(str(v.dtype).encode())
            h.update(np.ascontiguousarray(v).tobytes())
        elif hasattr(v, "vertices") and hasattr(v, "faces"):
            h.update(np.ascontiguousarray(np.asarray(v.vertices)).tobytes())
            h.update(np.ascontiguousarray(np.asarray(v.faces)).tobytes())
        elif isinstance(v, dict):
            h.update(payload_fingerprint(v).encode())
        else:
            h.update(repr(v).encode())
    return h.hexdigest()


def main() -> None:
    from synlab.degrade.api import probe_sources, apply_axis
    from synlab.degrade.registry import AXIS_REGISTRY, basis_rng
    from synlab.storage.store import AssetStore

    probe = probe_sources()
    w("# probe_10 level-0 identity, EMPIRICAL, all 31 axes")
    w(f"  probe families: {sorted(probe)}")
    for k, b in sorted(probe.items()):
        w(f"    family {k}: source_kind={b.source_kind} role={b.role} unit={b.unit} frame={b.frame} "
          f"payload_keys={sorted(b.payload)} meta_keys={sorted(b.meta)}")
    w("")

    FAMILY_OF = {a: a[0] for a in
                 [f"P{i:02d}" for i in range(1, 9)] + [f"I{i:02d}" for i in range(1, 11)]
                 + [f"G{i:02d}" for i in range(1, 9)] + [f"X{i:02d}" for i in range(1, 6)]}
    ROLE_SCHEMA = {"P": ("physical_component", "synlab.physical.v1"),
                   "I": ("obs_view", "synlab.obs.v1"),
                   "G": ("obs_fused_geometry", "synlab.obs.v1"),
                   "X": ("feature_bundle", "a12.obs.v1")}

    tmp = Path(tempfile.mkdtemp(prefix="modality_census_identity_"))
    w(f"  throwaway store (outside the repo): {tmp}")
    store = AssetStore(tmp / "identity_store")
    from synlab.degrade.sources import commit_source, load_source
    stored = {}
    for key, bundle in probe.items():
        role, schema = ROLE_SCHEMA[key]
        rec = commit_source(store, bundle, role=role, schema=schema,
                            lineage_id="census_lineage", split="train")
        re_ = load_source(store, rec.asset_id)
        stored[key] = re_
    before_n = len(store.list_assets(limit=10000))
    w(f"  assets committed for the probe: {before_n}")
    w("")

    w(f"  {'axis':6s} {'op returns source?':19s} {'meas.identity':14s} {'level':6s} "
      f"{'hash equal':11s} {'payload bytes equal':20s} {'measured=={}':13s} {'planned'}")
    n_identity = 0
    n_payload_equal = 0
    n_plan_nonempty = 0
    failures = []
    for axis_id in sorted(FAMILY_OF):
        op = AXIS_REGISTRY.get(axis_id)
        src = stored[FAMILY_OF[axis_id]]
        basis = op.sample_basis(
            {"source": src, "lineage_id": "census", "fragment_id": "census_frag",
             "master_seed": 20261001},
            np.random.default_rng(0), op.default_variant)
        fp_before = payload_fingerprint(src.payload)
        obj = op.apply(src, 0, basis, None)
        returns_source = obj is src
        rec, m = apply_axis(axis_id, 0, src, store, basis=basis, lineage_id="census", split="train")
        fp_after = payload_fingerprint(src.payload)
        payload_equal = (fp_before == fp_after)
        n_identity += 1 if m.identity else 0
        n_payload_equal += 1 if payload_equal else 0
        n_plan_nonempty += 1 if m.planned else 0
        id_match = (getattr(rec, "asset_id", None) == src.asset_id)
        w(f"  {axis_id:6s} {str(returns_source):19s} {str(m.identity):14s} {str(m.level):6s} "
          f"{str(m.result_hash == m.source_hash):11s} {str(payload_equal):20s} "
          f"{str(m.measured == {}):13s} {str(bool(m.planned)):5s} ref_kept={id_match}")
        if not (returns_source and m.identity and payload_equal and m.result_hash == m.source_hash
                and id_match):
            failures.append(axis_id)
    after_n = len(store.list_assets(limit=10000))
    w("")
    w(f"  RESULT: axes declaring identity at level 0 = {n_identity}/31")
    w(f"  RESULT: axes whose payload bytes are unchanged = {n_payload_equal}/31")
    w(f"  RESULT: axes with non-empty planned params at level 0 = {n_plan_nonempty}/31")
    w(f"  RESULT: store asset count before={before_n} after={after_n} "
      f"(delta={after_n-before_n}; level 0 must not commit)")
    w(f"  RESULT: axes failing the full identity contract = {failures if failures else 'NONE'}")

    txt = "\n".join(L)
    (OUT / "probe_10_level0_identity.txt").write_text(txt, encoding="utf-8")
    print(txt)
    print(f"\n(temp store kept at {tmp} -- deliberately outside the repo)")


if __name__ == "__main__":
    main()
