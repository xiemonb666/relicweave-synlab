"""Scratch: does a ZERO offset field already violate the subset check on this body?"""
from __future__ import annotations

import sys

import numpy as np
import trimesh

sys.path.insert(0, r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab")

from synlab.degrade import wear as W  # noqa: E402
from synlab.degrade.wear import WearModel  # noqa: E402
from synlab.physical.api import subset_outside_stats  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402

STORE = r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\data\a12_trainable\store"


def main() -> None:
    store = AssetStore(STORE)
    rec = store.list_assets(role="mother_mesh", limit=1)[0]
    body = store.load_mesh(rec.asset_id)
    zero = np.zeros(len(body.vertices))
    rebuilt = W.NB._offset_body(body, zero)
    print("rebuilt-is-source:", rebuilt is body)
    s = subset_outside_stats(rebuilt, body, n_samples=1200, tol_mm=1e-3, seed=0)
    print("ZERO-OFFSET control: outside=%d max=%.6g" % (s["outside_points"], s["max_outside_mm"]))
    # also: offset only a SINGLE mid-surface vertex, to see if the sign test flips locally
    model = WearModel(material_id="M11")
    wall = W.local_thickness(body)["values_mm"]
    kappa = W.vertex_mean_curvature(body, wall)
    layer, _ = model.effective_layer_mm(wall)
    opening, _ = model.opening_direction(body, wall)
    support, _ = model.support_plane_of(body, opening)
    fields, _g, _b, _d = W._mechanism_fields(body, model, wall, kappa, layer, opening=opening,
                                             support=support, intensity=1.0,
                                             base_seed=int(model.seed))
    total = sum(np.asarray(fields[k]) for k in fields)
    applied = np.minimum(total, 0.30 * np.clip(np.where(np.isfinite(wall), wall, 0.0), 0, None))
    for fraction in (0.0, 1e-4, 1e-3, 1e-2, 1e-1, 0.5, 1.0):
        g = applied * fraction
        dmg = W.NB._offset_body(body, g)
        st = subset_outside_stats(dmg, body, n_samples=1200, tol_mm=1e-3, seed=0)
        print("  fraction %.0e  outside=%3d  max=%.6g  vol_lost=%.3f"
              % (fraction, st["outside_points"], st["max_outside_mm"],
                 abs(body.volume) - abs(dmg.volume)))
        del dmg


if __name__ == "__main__":
    main()
