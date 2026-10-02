import sys, json
sys.path.insert(0,".")
from synlab.degrade.registry import AXIS_REGISTRY
ids = AXIS_REGISTRY.ids()
print("registered axes:", len(ids), ids)
print("missing:", AXIS_REGISTRY.missing())
print("has G05:", AXIS_REGISTRY.has("G05"))
try:
    print("entry:", AXIS_REGISTRY.get("G05"))
except Exception as e:
    print("get err", e)
print("dir:", [d for d in dir(AXIS_REGISTRY) if not d.startswith("_")])
