# Appearance-axis finish review

The rank selector now treats every exact-equal-score set as one indivisible group and chooses the cumulative physical-area boundary nearest the requested target. Exact distance ties choose the smaller prefix. A lexicographic score/area sort gives canonical group summation and the helper finishes in `O(N log N)` time without input-order tie splitting. Reports include the realized area error, group count, largest score-group share, quantization flag, and quantization mode. Constant score fields therefore report one group occupying 100% of the area instead of implying precise intermediate coverage.

P05 and P06 validate every texel's RGB, substrate RGB where used, area, positions, roughness, and boolean mask inputs before selecting a subset. P05 unions prior `paint_mask_removed` with the current selection and reports newly removed and cumulative area, so later applications do not restore removed color. P06 keeps `pattern_region` unchanged while reporting original pattern area, cumulative loss, and current visible pattern area. Its visibility reduction uses only current surviving pattern; when none survives, the metric is omitted and details report `NOT_APPLICABLE_NO_SURVIVING_PATTERN`.

P08 paint-coat loss now calls `threshold_for_fraction(..., tail="lower")`, matching the `rank <= threshold` predicate. Verification covers only this variant's zero/full endpoints and threshold direction, not the whole P08 implementation.

The focused test command was:

```text
.\.venv\Scripts\python.exe -m pytest -q tests/a12/operators/test_appearance_continuity_20261003.py
```

Result: 46 passed, exit code 0. `pytest_argv.txt`, `pytest_exit_code.txt`, and `pytest_stdout.txt` preserve the invocation and result.

The real helper CPU benchmark ran three times on each input size. With 10,000 unique scores, median runtime was 0.00847 s; with 100,000 unique scores, median runtime was 0.08137 s. Inputs and timings are recorded in `rank_benchmark.json`; invocation and exit code are in `benchmark_argv.txt` and `benchmark_exit_code.txt`.

The small-box physical-axis probe ran P05→P06 and P06→P05 at levels 1 and 4 and wrote four actual face-appearance output PNGs. All four retained the geometry hash and clean-truth object. The weak P05→P06 chain removed 11/43 mm² of paint; P06 reported visibility against the 32 mm² surviving pattern. The strong chain removed all 43 mm² and P06 correctly reported no surviving pattern. Chain measurements and label details are in `appearance_chains.json`; PNGs show the toy fixture's per-triangle color patches. They do not establish realistic vessel textures, realistic dirt shape, continuous pattern rendering, or production appearance-aging integration.

The source digests for the implementation, tests, and probe inputs are in `source_sha256.json`. No changes to `synlab/degrade/axes.py` were needed in this pass: its existing appearance-array copying and original `clean_truth` reference preservation are exercised by the focused tests.
