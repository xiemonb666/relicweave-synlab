Source: synlab/physical/sdf.py
Original SHA256: 186583014D706CFCC20FBEFDA04A0C68E427F68E3BA7187A48F9A9115DDB827F
First implementation SHA256: DC54355CBFD17A923E9D52E666FBAAD4B31E08D5A6C1A520F3D8A57DF58C424E
Final SHA256: FD433876FA4DF84D2316C93DBBE521E1094241829D5FCCF93CEDEEAC02467B1D

Passing target tests (final source):
argv: .\.venv\Scripts\python.exe -B -m pytest -q tests\a12\degrade\test_axis_routing_audit.py::test_explicit_damage_spacing_is_honoured_verbatim tests\a12\degrade\test_axis_routing_audit.py::test_negative_explicit_spacing_is_refused tests\a12\degrade\test_axis_routing_audit.py::test_choose_spacing_reports_requested_vs_realised
exit: 0
result: 3 passed.

Boundary probe v1: exit 1 from a too-strict exact-float check on 0.6/6; preserved as boundary_probe.py and boundary_probe.v1.log.
Boundary probe v2:
argv: .\.venv\Scripts\python.exe -B tmp\review_20261004\implementation\explicit_spacing_fix_20261004\boundary_probe.v2.py
exit: 1
result: auto_no_bbox spacing comparison against literal 0.1 failed because 0.6/6 is 0.09999999999999999. Per instruction, no third run was performed.
