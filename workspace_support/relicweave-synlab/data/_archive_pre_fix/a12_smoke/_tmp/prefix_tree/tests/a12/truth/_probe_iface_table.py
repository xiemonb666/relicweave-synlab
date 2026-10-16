"""Debug the interface table construction on the truth fixture (throwaway probe)."""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "a12" / "truth"))

from synlab.schemas.runtime import PhysicalComponent, PhysicalResult  # noqa: E402
from synlab.storage.mesh_io import with_face_attrs  # noqa: E402
from synlab.truth.api import finalize_clean_truth, update_residual_truth  # noqa: E402

from truth_fixtures import CUT, event_with_correspondence  # noqa: E402

mother, event = event_with_correspondence()
clean = finalize_clean_truth(mother, event)
bundle = clean.meta.get("correspondence_bundle")
print("clean meta keys:", sorted(clean.meta))
print("interfaces:", [(p.interface_id, p.fragment_a, p.fragment_b) for p in clean.interfaces])
if bundle is None:
    print("NO BUNDLE")
else:
    print("bundle interface_id:", np.asarray(bundle["interface_id"])[:10],
          "n=", np.asarray(bundle["interface_id"]).shape)
    print("bundle keys:", sorted(bundle))
fragment = event.fragments[0]
mesh = fragment.mesh
origin = np.asarray(fragment.face_origin_kind, dtype=np.uint8)
interface_id = np.full(origin.shape[0], -1, dtype=np.int32)
interface_id[origin == CUT] = 0
with_face_attrs(mesh, origin_kind=origin, interface_id=interface_id)
component = PhysicalComponent(component_id="A#c0", clean_fragment_id="A", mesh=mesh,
                              volume_mm3=float(abs(mesh.volume)), is_representative=True,
                              status="CORE", survivor_patch_ref=None, meta={})
physical = PhysicalResult(
    mother_id=clean.mother_id, clean_ref="fixture", event_id=clean.event_id,
    recipe_id="P03:depth_mm:L1", version=1, components=[component], lost_volume_mm3=0.0,
    lost_volume_ratio=0.0, representative_map={"A": "A#c0"}, physical_truth=None,
    qa={"status": "PASS"},
    meta={"ledger": {"source_volume_mm3": float(abs(mesh.volume)),
                     "damaged_volume_mm3": float(abs(mesh.volume)), "lost_volume_mm3": 0.0,
                     "conservation_ok": True, "clean_fragment_id": "A"},
          "identity": False, "level": 1, "axis_id": "P03", "geometry_changed": True})
truth = update_residual_truth(clean, physical)
print("truth meta iface keys:", sorted(k for k in truth.meta if k.startswith("iface")))
print("iface_new_faces_by_id:", truth.meta.get("iface_new_faces_by_id"))
print("interface_table:", {k: v.tolist() for k, v in truth.meta["interface_table"].items()})
print("origin==CUT faces:", int(np.count_nonzero(origin == CUT)))
print("corr samples:", np.asarray(truth.meta["correspondence_bundle"]["index_a"]).shape)

import tempfile  # noqa: E402

from synlab.roles import ROLE_PHYSICAL_TRUTH  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402
from synlab.truth.api import commit_truth, load_truth  # noqa: E402

with tempfile.TemporaryDirectory() as tmp:
    store = AssetStore(Path(tmp) / "store")
    record = commit_truth(store, truth, role=ROLE_PHYSICAL_TRUTH, lineage_id="lin", split="dev")
    print("record meta iface keys:", sorted(k for k in record.meta if k.startswith("iface")))
    print("record meta interface_table:", type(record.meta.get("interface_table")))
    arrays = store.load_arrays(record.asset_id)
    print("arrays:", sorted(arrays))
    loaded = load_truth(store, record.asset_id, role=ROLE_PHYSICAL_TRUTH)
    print("loaded meta iface keys:", sorted(k for k in loaded.meta if k.startswith("iface")))
    print("loaded interface_table:", {k: np.asarray(v).tolist()
                                      for k, v in (loaded.meta.get("interface_table") or {}).items()})

