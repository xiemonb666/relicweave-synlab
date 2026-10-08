import sys
sys.path.insert(0, "tests/a12/degrade")
from _probe_axis_routing_audit import _RouteSpy
from synlab.degrade.api import probe_sources, apply_axis
from synlab.degrade import axes as A
src = probe_sources()
with _RouteSpy() as spy:
    _r, m = apply_axis("I01", 1, src["I"], None, lineage_id="lin_probe")
    print("records:", spy.records)
print("I01._apply is _BaseAxis._apply ?", A.I01.__dict__.get("_apply") is A._BaseAxis._apply)
print("I01._apply:", A.I01.__dict__.get("_apply"))
print("mro:", [c.__name__ for c in A.I01.__mro__])
