"""Scratch repro: one control-style observation on a committed fragment (not a test).

Reproduces the observe-stage failure of the control leg directly, so the traceback is
visible (the pipeline swallows it into ``error.message``).
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from synlab.config import load_generation_spec  # noqa: E402
from synlab.observe.realism import (LEVEL_IDENTITY, MASK_POLICY_PIPELINE_COC,  # noqa: E402
                                    observe_spec_from_config)
from synlab.observe.routes import resolve_target  # noqa: E402
from synlab.roles import ROLE_FRAGMENT_MESH  # noqa: E402
from synlab.seeds import derive_named_rngs  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402


def main() -> int:
    root = Path(sys.argv[1])
    store = AssetStore(root)
    records = store.list_assets(role=ROLE_FRAGMENT_MESH, limit=50)
    print("fragment assets:", [(r.asset_id, r.lineage_id, r.meta.get("fragment_id"))
                               for r in records])
    record = records[0]
    mesh = store.load_mesh(record.asset_id)
    attrs = dict((mesh.metadata or {}).get("face_attr_arrays") or {})
    print("face attrs:", {k: (v.shape, str(v.dtype)) for k, v in attrs.items()})
    target = resolve_target({"mesh": mesh, "fragment_id": record.meta.get("fragment_id", ""),
                             "face_origin_kind": attrs.get("origin_kind"),
                             "face_interface_id": attrs.get("interface_id")})
    print("target:", target.fragment_id, target.surface_tag.shape,
          sorted(set(int(v) for v in target.surface_tag)))
    spec = load_generation_spec(str(ROOT / "configs" / "a12" / "realistic.yaml"))
    plan = observe_spec_from_config(spec, store_root=ROOT / "data" / "a12_realistic",
                                    lineage_id=record.lineage_id, route="ideal_visible",
                                    renderer="software_rasterizer",
                                    levels={a: LEVEL_IDENTITY for a in
                                            ("I01", "I03", "I04", "I05", "I10")},
                                    distortion_policy=None,
                                    mask_policy=MASK_POLICY_PIPELINE_COC)
    obs_spec = plan.obs_spec
    views = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    obs_spec.view_count = views  # keep the repro cheap; the failure is per-view
    rngs = derive_named_rngs(int(spec.master_seed), record.lineage_id)
    from synlab.observe.api import observe

    try:
        observation = observe(target, None, rngs, route="ideal_visible", spec=obs_spec)
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return 3
    print("ok", observation.route, len(observation.views),
          int(observation.points.shape[0]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
