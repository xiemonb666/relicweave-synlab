import sys; sys.path.insert(0,'.')
from synlab.roles import FORBIDDEN_FEATURE_FIELDS as F
from synlab.storage.export import TRUTH_CRITICAL_FIELDS as T, TRUTH_BEARING_FIELDS as B
cands = ["fragment_id","lineage_id","mother_id","split","event_id","relation","mate_present","historical_R2","object_id","truth_pose","id_map","T_WC","surface_tag","iface_id","corr_point_a","corr_weight","corr_face_a","depth_z","kind","loss_mask","eligible_as_negative"]
for c in cands:
    print(f"  {c:24s} forbidden={c in F}  truth_critical={c in T}  truth_bearing={c in B}")
