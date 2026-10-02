import sys; sys.path.insert(0,'.')
from synlab.qc.loader_probe import FORBIDDEN_PAYLOAD_KEYS
print("FORBIDDEN_PAYLOAD_KEYS:", sorted(FORBIDDEN_PAYLOAD_KEYS))
from synlab.roles import FORBIDDEN_FEATURE_FIELDS
print()
print("quality_provenance forbidden?", "quality_provenance" in FORBIDDEN_PAYLOAD_KEYS)
from synlab.training.adapter import FeatureBundle
import inspect
src = inspect.getsource(FeatureBundle.from_dict)
print("adapter uses payload.get('quality')" , "payload.get(\"quality\")" in src or "payload['quality']" in src or "quality" in src)
from synlab.observe.features import assert_no_forbidden_features
print("assert_no_forbidden_features imported ok")
