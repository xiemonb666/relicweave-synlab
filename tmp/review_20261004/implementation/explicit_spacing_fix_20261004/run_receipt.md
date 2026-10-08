Source: synlab/physical/sdf.py
Original SHA256: 186583014D706CFCC20FBEFDA04A0C68E427F68E3BA7187A48F9A9115DDB827F
Current SHA256: DC54355CBFD17A923E9D52E666FBAAD4B31E08D5A6C1A520F3D8A57DF58C424E
Test argv: .\.venv\Scripts\python.exe -B -m pytest -q tests\a12\degrade\test_axis_routing_audit.py::test_explicit_damage_spacing_is_honoured_verbatim tests\a12\degrade\test_axis_routing_audit.py::test_negative_explicit_spacing_is_refused tests\a12\degrade\test_axis_routing_audit.py::test_choose_spacing_reports_requested_vs_realised
Test exit: 1
Test result: F..; 2 passed, 1 failed.
Failure: test_explicit_damage_spacing_is_honoured_verbatim passed its spacing, basis, budget_limited, and declared_spacing assertions, then spacing_budget_report raised KeyError('request_honoured') because requested_mm was None and the report omitted that field.
Follow-up: stopped after the first failed test as instructed. No boundary benchmark was run.
