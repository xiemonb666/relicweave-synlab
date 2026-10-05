# `forge_chain_audit` source-reader dispatch (2026-10-05)

`forge_chain_audit` keeps `relicweave.chain.audit.input.v1` behavior: it reads and hashes only explicitly named JSON references and does not dispatch a producer-payload reader. Input v2 opts into one fixed diagnostic reader:

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

The v2 declaration is an exact allowlist. Unknown keys, reader IDs, references, modes, or additional reader entries remain `UNKNOWN`; the audit never imports a caller-selected module. It dispatches only after `references.native_result` and `references.native_job` both pass the existing schema and SHA-256 checks. The PG reader receives the verified hashes, the resolved job file, and the parent directory of the explicitly referenced `result.json`. That directory is its output boundary. It checks the result and bounded output files itself before parsing their bytes.

The report puts this evidence at `producer_diagnostics.pgfrag`. `SOURCE_VERIFIED` there means only that the named result/job identity and supported `points`, `components`, and bond-state tables were read and cross-checked. The reader does not return bulk normalized rows to the audit report. If `chain.pgfrag_normalized_rows` is supplied, it must be a typed mapping and the reader compares the `points`, `components`, `bonds`, and `broken_bonds` projection against source rows; an explicit `null`, incomplete claim, or mismatch fails the dispatch. Caller rows do not establish producer evidence by themselves.

The report distinguishes `reader_dispatched`, `reader_result_metadata_read`, and `producer_payload_byte_evidence` (`COMPLETE`, `PARTIAL`, `UNKNOWN`, or `NOT_DISPATCHED`). Table-byte evidence is derived only from `source_binding.components[*].files` entries that report both `bytes_verified=true` and `sha256_verified=true`. If the reader ran and read `result.json` but returned no verified table-file evidence, payload-byte evidence stays `UNKNOWN`; the audit serializes the higher-level payload-read and JSON-only flags as `null` rather than inferring them from result-metadata bytes.

Dispatch outcomes are deliberately separate from whole-chain acceptance:

| Condition | `producer_diagnostics.pgfrag.status` | Chain audit status |
| --- | --- | --- |
| Supported reader verifies result, job, dictionary, and tables | `SOURCE_VERIFIED` | Remains `INCOMPLETE` until all other chain evidence is complete |
| Reader rejects payload or a supplied normalized-row claim | `FAIL` | `FAIL` |
| Declaration absent/unsupported, metadata reference unverified, or bounded reader reports incomplete input | `UNKNOWN` | `INCOMPLETE` |

The overall `source_binding.status` remains `UNKNOWN` because this adapter does not bind the full VF→PG→fragment→surface→observation chain. Only the PG diagnostic table components are marked `SOURCE_VERIFIED` inside `producer_diagnostics.pgfrag`. In particular, an endpoint `uniform_box_bar_fixture`, intact-bond component, or broken bond never becomes a physical fragment, paired crack surface, event history, or historical `R2` row. Historical archaeology remains a separate source. Physics and pretraining qualification stay false, and ground-truth fields remain outside inference features.

This is a report-only audit input path. The reader is reached through the existing CLI call `main()` → `audit_chain(document, root)`; it does not connect to A12 export, model inference, or training. Narrow dispatch tests live in `tests/a12/qa/test_forge_chain_source_dispatch_20261005.py`; this change does not claim complete packages, alter the prior 30-gap audit record, or qualify the current chain.
