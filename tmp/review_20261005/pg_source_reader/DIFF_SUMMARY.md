# Source reader change and validation record

## Current source delta

- Added `synlab/qa/source_readers/` with `read_pgfrag_result`, a bounded
  source-backed PG-Frag v1 reader. It hashes consumed result artifacts, parses
  typed CSV rows, checks explicit units/frames, reconciles point/component
  rows, bonds, inactive subsets, and isolated points, and can source-verify a
  named job file and optional external result digest.
- Added a 1-based point-roster check that first requires
  `declared_point_count == len(points.csv rows)`. It never allocates a set or
  range sized from untrusted result metadata.
- Added 19 focused A12 test cases and moved their source input to the tracked,
  byte-preserved fixture in `tests/fixtures/pgfrag/result_v1_toy_endpoint/`.
  The fixture README marks the data as a toy endpoint diagnostic without
  physical-fragment, R2, or chain qualification.
- No existing production module or chain audit was edited. No Git operation or
  `.gitattributes` edit was made in this task.

## Validation history

The original 18-case run against the first source draft had 17 passes and one
test-harness failure: that negative test changed the CSV byte length, so the
reader correctly returned `outputs.bytes` before reaching its SHA mismatch
check. The test mutation was changed to a same-length valid numeric value, and
that node passed on its authorized retry. The bounded-count fix then added one
large-declaration negative case; that node passed against the updated reader.

After moving the source to the portable fixture, the one authorized full-file
run collected 19 cases and had 18 passes plus one stale test assertion that
still referenced a removed local variable. The assertion now reads the fixture
`result.json` byte length directly; the single authorized retry of that node
passed. The retry changed only the test file; the reader SHA and fixture hashes
are unchanged. These separate receipts are retained, and are not presented as
one full-file run with 19 passes.

The named actual-source probe reads the existing PG-Frag output and matching
`job.json` using frozen external digests. Its report remains
`PG_DIAGNOSTIC_ONLY`; `job_source` is `SOURCE_VERIFIED`, caller match remains
`UNKNOWN`, and physical fragments, crack surfaces, event history, historical
R2, and independent component-graph validation remain `UNKNOWN`.
