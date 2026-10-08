# PG-Frag source reader review

## Frozen scope

This draft adds a source-only reader and focused A12 tests. It does not change
`forge_chain_audit.py`, producer output, job execution, or any solver/CAD path.
The reader consumes one explicit result directory and the artifacts named in
its `result.json`; it does not walk a package tree.

The public API is:

```python
read_pgfrag_result(
    result_root,
    *,
    expected_result_sha256=None,
    job_path=None,
    expected_job_sha256=None,
    caller_normalized_rows=None,
    include_normalized_rows=False,
) -> dict
```

`expected_result_sha256` and `expected_job_sha256` are only marked verified
after the reader hashes the corresponding bounded source bytes. The result
contains `result_source`, optional `job_source`, `identity`,
`source_binding.components.{points,bonds,components}`, explicit dictionary
binding, cross-table row counts, optional normalized rows, and optional caller
match evidence. A caller mismatch makes the report `FAIL` while retaining the
verified producer-row evidence. No caller-supplied `PASS` is accepted.

## Source checks

- The result JSON is capped at 1 MB and parsed as strict UTF-8 JSON, rejecting
  duplicate keys and non-finite numbers.
- The output manifest is capped at 32 files and 5 MB aggregate declared bytes;
  each output is capped at 2 MB. Paths must be canonical root-relative POSIX
  paths. Traversal, symlink/junction components, absent files, size mismatches,
  and consumed-payload digest mismatches fail closed.
- The reader hashes and parses the explicit data dictionary, points,
  components, bond states, broken bonds, and isolated points. Dictionary column
  sets, dtypes, SI units, and explicit coordinate frames must match the
  supported PG-Frag v1 schema. Values remain in SI units.
- Point IDs must be unique, complete, and equal to component-table point IDs.
  Point component label, mass, and damage must match `components.csv`.
  Bond endpoints must be valid canonical sorted pairs; active degrees must
  match `points.csv`; broken pairs and both lengths must exactly match the
  inactive `bond_states.csv` subset; isolated rows must exactly match graph
  zero-degree points and their point coordinates/masses.
- Header-only `broken_bonds.csv` and `isolated_points.csv` are accepted only if
  the other source tables prove both sets are empty. Empty `points.csv`,
  `components.csv`, or `bond_states.csv` is incomplete.
- `component_partition_validation` stays `UNKNOWN`: the reader cross-checks
  repeated component labels but does not independently recompute graph
  connectivity.

## Qualification boundary

Successful source checks return `PG_DIAGNOSTIC_ONLY`. The report leaves
`physical_fragments`, `crack_surfaces`, `event_history`, and `historical_R2` as
`UNKNOWN`; it emits no fragment count or chain qualification. The legacy
`uniform_box_bar_fixture` context remains visible without converting its
endpoint graph labels into physical-fragment or relation claims.

## Focused test plan

The single test file covers the actual bounded PG-Frag v1 output and negative
cases for: caller-row mismatch, result and table hashes, units, frames,
incomplete/duplicate IDs, orphan endpoints, broken-row length contradictions,
non-finite values, empty main tables, valid header-only zero controls, invalid
header-only broken output, explicit job hash/ID verification, path traversal,
and duplicate JSON keys. It does not invoke solver, CAD, full-batch, recursive
package scans, or the 5 GB bundle.

## Freeze status

Initial source freeze was captured in `freeze_manifest.json`. The main-agent
review authorized one run of this test file against the existing approximately
1.5 MB PG-Frag output; no broader test command is in scope.
