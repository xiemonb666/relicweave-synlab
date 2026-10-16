"""Failure class 3: which fragment the physical recipe is applied to.

The batch answered ``NA_NOT_APPLICABLE`` ("fragment carries no interface face attribute") on
``LIN0004_V10_M06_PAT03`` although the event *does* have a new surface: the untouched V10 lid
(394 820 mm^3, measured) is bigger than every cut piece, so the "largest non-tiny fragment"
rule selected a body that has no fracture interface at all.  Every P recipe of this plan
declares ``ROI = {"kind": "interface"}`` (``synlab.degrade.axes``), so the target must be a
fragment that can host that ROI.  The tests below pin the rule, the honest fallback and the
V10 lid-skirt placement bug that produced a second, stray body.
"""

from __future__ import annotations

import types

import numpy as np
import pytest

from synlab.errors import SynLabError
from synlab.fracture.api import fracture_event
from synlab.mothers.vessels.group_composite import _lid_part
from synlab.pipeline import _fragment_interface_faces, _pick_fragment
from synlab.schemas.runtime import ORIGIN_INTERFACE, ORIGIN_MOTHER_SURFACE

#: the parameters the batch really used for ``LIN0004_V10_M06_PAT03`` (committed mother asset
#: ``asset_d6a31345d892ead78e4e``): the mother is a three-body assembly, the lid floats above
#: the body and the cut never touches it
LIN0004_V10_M06_PAT03_PARAMS = {
    "base_mm": 10.649771173028173,
    "belly_ratio": 0.68991973127168,
    "diameter_mm": 222.77854733012697,
    "height_mm": 352.12756141776987,
    "knob_diameter_mm": 64.43440084462063,
    "lid_height_ratio": 0.568826035425881,
    "lid_seat_mm": 3.3710449924909853,
    "mouth_ratio": 0.30098125744230925,
    "wall_mm": 2.8443414248422236,
    "warp_amplitude": 0.016873063698682116,
    "warp_eccentricity_mm": 1.848518300460957,
    "warp_lobes": 2,
}


def _fake_fragment(fragment_id: str, volume_mm3: float, *, interface_faces: int = 0,
                   origin_interface_faces: int = 0, faces: int | None = None,
                   is_tiny: bool = False) -> types.SimpleNamespace:
    n = int(faces if faces is not None else max(interface_faces, origin_interface_faces, 1) * 2 + 4)
    ids = np.full(n, -1, dtype=np.int32)
    if interface_faces:
        ids[:interface_faces] = 0
    origin = np.full(n, ORIGIN_MOTHER_SURFACE, dtype=np.uint8)
    if origin_interface_faces:
        origin[:origin_interface_faces] = ORIGIN_INTERFACE
    return types.SimpleNamespace(fragment_id=fragment_id, volume_mm3=float(volume_mm3),
                                 is_tiny=bool(is_tiny), face_interface_id=ids,
                                 face_origin_kind=origin, face_side=np.zeros(n, dtype=np.int8))


def test_interface_face_counts_read_both_channels():
    fragment = _fake_fragment("f", 1.0, interface_faces=5, origin_interface_faces=9)
    assert _fragment_interface_faces(fragment) == (5, 9)
    assert _fragment_interface_faces(_fake_fragment("g", 1.0)) == (0, 0)


def test_pick_fragment_prefers_the_largest_fragment_that_can_host_the_interface_roi():
    untouched = _fake_fragment("lid", 394820.4, faces=768)
    cut_small = _fake_fragment("cut-minus", 113646.8, interface_faces=335,
                               origin_interface_faces=666, faces=1768)
    cut_large = _fake_fragment("cut-plus", 178117.3, interface_faces=329,
                               origin_interface_faces=686, faces=4076)
    fracture = types.SimpleNamespace(fragments=[untouched, cut_large, cut_small])
    assert _pick_fragment(fracture).fragment_id == "cut-plus"
    # the rule is about the interface, not about the volume: the untouched body is the biggest
    assert max(fracture.fragments, key=lambda f: f.volume_mm3).fragment_id == "lid"
    # a fragment whose faces only carry origin_kind (no paired patch) is still eligible,
    # because roi_faces falls back to face_origin_kind
    origin_only = _fake_fragment("origin-only", 5000.0, origin_interface_faces=42, faces=100)
    fracture = types.SimpleNamespace(fragments=[untouched, origin_only])
    assert _pick_fragment(fracture).fragment_id == "origin-only"


def test_pick_fragment_keeps_the_volume_rule_when_no_fragment_has_an_interface():
    """No fabricated attributes: an interface-free event still gets its honest answer."""
    small = _fake_fragment("tiny-body", 10.0, faces=12, is_tiny=True)
    big = _fake_fragment("untouched-large", 900.0, faces=64)
    tiny = _fake_fragment("too-small", 0.5, faces=6)
    fracture = types.SimpleNamespace(fragments=[big, small, tiny])
    assert _pick_fragment(fracture).fragment_id == "untouched-large"


def test_lid_skirt_is_placed_in_the_lids_own_frame():
    """The V10 skirt used to stay at the world origin and became a stray body under the pot."""
    part = _lid_part(r_mouth=40.0, lid_height_mm=30.0, seat_mm=4.0, knob_r=8.0, t_wall=4.0,
                     z_lid_base=200.0)
    z_min = float(np.asarray(part.mesh.bounds)[0, 2])
    z_max = float(np.asarray(part.mesh.bounds)[1, 2])
    # the collar spans [-1.5*seat, +0.5*seat] around the lid's base plane (measured on
    # V10/M06 LIN0004_V10_M06_PAT03: [349.02, 355.77] for z_lid_base=354.08, seat=3.371)
    assert z_min == pytest.approx(200.0 - 1.5 * 4.0, abs=1e-6), f"skirt at z_min={z_min}"
    assert z_min > 190.0
    assert z_max > 200.0
    # and the caller that keeps the lid at the origin is unaffected
    origin_part = _lid_part(r_mouth=40.0, lid_height_mm=30.0, seat_mm=4.0, knob_r=8.0,
                            t_wall=4.0, z_lid_base=0.0)
    assert float(np.asarray(origin_part.mesh.bounds)[0, 2]) == pytest.approx(-1.5 * 4.0, abs=1e-6)


def test_real_v10_mother_gets_an_interface_capable_target():
    """The lineage that answered ``NA_NOT_APPLICABLE`` now has a usable P-axis target.

    Costs one mother build plus one shared cut (~60 s); it exercises the real builder, the real
    ``plane_shared_cut`` backend and the real ``roi_faces`` acceptance rule.
    """
    from synlab.fracture.fragment import split_components
    from synlab.mothers.api import create_mother
    from synlab.physical.fields import roi_faces
    from synlab.seeds import make_rng

    mother = create_mother("V10", "M06", dict(LIN0004_V10_M06_PAT03_PARAMS),
                           make_rng(20261001, "shape", "class3"), mother_id="class3-V10")
    assert bool(mother.mesh.is_watertight)
    assert len(split_components(mother.mesh)) == 3
    fracture = fracture_event(mother, {"backend": "plane_shared_cut"}, 
                              make_rng(20261001, "cut", "class3"), event_id="class3-V10_E01")
    fragments = list(fracture.fragments)
    assert len(fragments) >= 4
    untouched = [f for f in fragments if not any(_fragment_interface_faces(f))]
    assert untouched, "the untouched assembly body is the case this test protects"
    target = _pick_fragment(fracture)
    assert any(count > 0 for count in _fragment_interface_faces(target))
    ids, info = roi_faces(target.mesh, target, {"kind": "interface"})
    assert len(ids) > 0
    assert info["roi_kind"] == "interface"
    # the body the old rule picked really is not applicable - the honest NA stays reachable
    biggest = max([f for f in fragments if not f.is_tiny], key=lambda f: f.volume_mm3)
    if not any(_fragment_interface_faces(biggest)):
        with pytest.raises(SynLabError) as info_exc:
            roi_faces(biggest.mesh, biggest, {"kind": "interface"})
        assert str(info_exc.value.code) == "ErrorCode.NA_NOT_APPLICABLE"
