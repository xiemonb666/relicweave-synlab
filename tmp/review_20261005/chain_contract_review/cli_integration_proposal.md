# Minimal `forge_chain_audit` CLI source-reader integration proposal

This is a proposal only. It makes no production-source change. The PG adapter and tests have been separately assigned and should stabilize their return contract before any caller integration starts.

## Caller schema

The present `relicweave.chain.audit.input.v1` carries `references.native_job` and `references.native_result`, but no declaration that a source-specific reader should load output payloads. Keep old v1 meaning conservative. Add a versioned v2 input with an explicit section such as:

```json
{
  "schema": "relicweave.chain.audit.input.v2",
  "source_readers": {
    "native_result": {
      "reader_id": "pgfrag.result.v1",
      "job_reference": "native_job",
      "mode": "read_producer_rows"
    }
  }
}
```

`source_readers.native_result` selects an installed reader; `job_reference` must resolve to the already explicit `references.native_job`. It does not supply copied normalized rows as evidence. If legacy v1 has no reader declaration, source binding remains UNKNOWN. If a producer format or required table is unsupported, empty, omitted, or unhashable, return UNKNOWN/INCOMPLETE; do not treat it as a valid empty dataset. If the caller also supplies a normalized claim for fields that the producer actually emits, compare the canonical forms field-by-field and return FAIL on a mismatch.

## Minimal API and call point

After `audit_chain` has loaded and hash-checked explicit metadata references at `synlab/qa/forge_chain_audit.py:281-300`, but before it evaluates event/job relationships at `:368-423`, dispatch the declared reader through an allowlisted registry. Initial API proposal:

```python
read_pgfrag_result(
    root: Path,
    result_reference: Mapping[str, Any],
    job_document: Mapping[str, Any],
) -> SourceReadResult
```

`SourceReadResult` should return bounded summary metadata, canonical point/component/bond rows or their canonical digests and ID sets, per-component status, and explicit UNKNOWN/FAIL reasons. It should not place bulky rows into the final report. The existing CLI reaches this call naturally through `main()` → `audit_chain(document, root)` at `:916-943`; it should not rely on a producer invoking the standalone audit.

The PG reader should resolve `outputs[].path` relative to the already resolved `result.json` parent; reject traversal/symlinks and undeclared files; verify every enumerated artifact's bytes and SHA-256; load and verify `data_dictionary.json`; validate units/frame declarations; verify the point ID set and table joins; and compare `result.input.job_sha256`, `result.job_id`, and the named job reference. `result.json` itself remains verified by the existing explicit reference hash because its output manifest excludes itself to avoid recursive hashing.

## Status boundaries

For the present PG run, return a payload-level verified status only for tables that pass source checks. The fixture says `initial_condition.kind=uniform_box_bar_fixture`, so `source_binding.fragments`, `crack_surfaces`, `historical_relations`, and the VF→PG point map must stay UNKNOWN. A list of intact graph components or inactive bonds is not a fragment or paired fracture-surface label. `science_qualification.physics_qualified` and `pretrain_qualified` remain false.

The reader integration updates only chain-audit report semantics. It does not enter model forward or make ground-truth rows available to inference. A later A12 reader must separately verify the legacy export's actual query/index/table metadata, feature-versus-label separation, per-lineage split assignment, and degradation measurements. A later VF reader must verify manifest-declared geometry payloads and source frame. Keep their implementation files/tests separate so they can run concurrently without touching the CLI-owned files.

## Focused acceptance checks

The eventual narrow tests should cover: valid real PG source subset; bad/missing declared output hash; path escape or symlink; missing/empty output table; duplicate/missing/orphan point IDs; invalid bond endpoints or duplicate pairs; incorrect job ID/hash; incorrect units/frame; unsupported schema returns UNKNOWN; a `uniform_box_bar_fixture` never populates fragment/surface/R2 rows; and caller-normalized claims that differ from producer rows fail. These do not justify a full suite, data generation, or eligibility claim.