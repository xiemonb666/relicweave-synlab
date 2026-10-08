# RMS calibration core v3 review pack — 2026-10-04

V3 applies only the reviewed contract changes: every UNKNOWN path returns the raw field as `calibrated_field_mm`, and Python/NumPy booleans are rejected as targets instead of being converted to `1.0`. The subnormal-scale regression now verifies `UNKNOWN_SCALE_UNREPRESENTABLE`, no fabricated factor, raw field/hash preservation, and that the returned actual RMS remains the raw positive RMS rather than a modified candidate. The zero-target partial-data branch also restores raw values before returning UNKNOWN, so the field/status contract is consistent.

The v2 source and diff remain frozen under `baseline_v2/`; v3 is diffed only against that snapshot in `v3.diff`. `v3_freeze.json` records the pre-v3 baseline; `v3_pretest_freeze.json` records the exact v3 source, test, diff and fixture immediately before the only v3 test invocation.

Verification command argv is recorded in `pytest_v3.run.json`. It ran once from `C:\\Users\\xiemo\\Desktop\\ShardForge\\relicweave-synlab` and exited 0: **11 passed in 0.22s**. Full stdout/stderr are `pytest_v3.stdout.txt` and `pytest_v3.stderr.txt`; the JUnit XML is `pytest_v3.junit.xml` (11 tests, 0 failures, 0 errors, 0 skipped). The initial v1 8-PASS receipt remains unchanged in `baseline_v1/` and the original `pytest.*` files.

This work still does not integrate G01 and does not claim real-phone noise calibration.
