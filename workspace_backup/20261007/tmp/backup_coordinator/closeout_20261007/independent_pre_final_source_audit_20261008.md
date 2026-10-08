# Independent pre-final source audit (2026-10-08)

Status: **PRE-FINAL / HISTORICAL INPUT SNAPSHOT / NOT FINAL BACKUP APPROVAL**.

This report freezes read-only evidence gathered against the earlier inventory and manifest pins below. It deliberately records the then-current 806-row ignored-destination blocker; later builder fixes and regenerated manifests must be reviewed separately. It does not authorize inventory execution, copying, staging, commit, push, or post-push verification.

## Pinned review inputs

- Prior inventory: SHA-256 `5afe5b96fb14cf242ec2cce730a802fa8b8ceb32c335de77f1ba55ca9cef14c7`, 25,130,379 bytes.
- Prior action manifest: SHA-256 `49feb8117dac2e44e8f383b35c8a56a3b9e5d1cb62450470db4b479f5ce55814`, 10,479,945 bytes.
- Inventory builder at that review stage: `tmp/backup_coordinator/closeout_20261007/build_closeout_inventory_v2.py`, SHA-256 `ae69f1ab9c0dda710cf1c9875295d185f81eeca9c7b38d0b1db1c6e7e5f5cd14`, 56,155 bytes.
- The report is evidence for that snapshot only. Its input pins are not assertions about the later final inventory.

## Coverage evidence

The pinned inventory contained 24,594 entries and 6,707 copy/stage actions totaling 145,256,308 bytes: PG 1,585 actions, VesselForge 428, SynLab 3,878, and workspace-root external evidence 816. An independent pass rehashed every selected source in that snapshot: 6,707/6,707 matched listed bytes and SHA-256.

The 100 referenced recovery/evidence records were independently rehashed. All matched listed source bytes and hashes. 92 mapped to candidate actions, 7 to unchanged tracked exact-HEAD sources, and 1 to an existing byte-identical recovery alias. The pinned inventory reported no unmatched or unmapped references.

A build/dist/target path scan found 80 files, including 75 code or source-snapshot suffix candidates. All 72 code/source items under `pgfrag/build/lib` were byte-identical to their canonical sources (7 Python modules, 63 vendored Julia files, and 2 patch/fixture scripts). The five other build/lib files (two project manifests, backend provenance JSON, and license) also matched their canonical files. The three `relicweave-synlab/frontend/dist` files were generated HTML/CSS/JS; corresponding frontend source and build configuration were included in the inventory. No unique authored source omission was found in these directories; no `target` files were present.

The required vendored bibliography file `pgfrag/vendor/Peridynamics.jl/docs/src/references.bib` was independently present as an unchanged tracked entry: 8,547 bytes, SHA-256 `bc60345cdd7686900d68a4ff169f6ba5ed5b2c14b52ff747cf8c992cc7cf28e9`, HEAD/worktree blob OID `b48ce660daaacaf2602474496a8376ff6a5baf3c`. This was a vendored dependency reference, not new first-party code.

## Concrete blocker in this snapshot

The manifest had 5,085 rows whose destination policy required exact-path force-add. Of these, 806 were marked `copy_then_stage_exact` without the executor-required force suffix; the remaining 4,279 were marked `stage_existing_exact_force`. The frozen executor rejects ignored destinations unless the operation ends in `_force`, so those 806 rows would fail closed. Four raw-source snapshot actions were among the affected copy rows: three `.gitattributes` pre-change snapshots and the SynLab `docs/a12/HANDOVER.md` snapshot. This is a blocker for this historical manifest, not a claim that a later rebuilt manifest retains it.

## Raw-source, attributes, and supplementary paths

There were 90 raw-source mapping entries and 90 distinct destination actions: 86 were classified as CRLF/LF normalization only and 4 as unresolved content/filter relation. All 90 preserved source/destination bytes and SHA-256 in the reviewed mapping. Their destination attributes were reported as `text=unset`, with `eol` and `filter` unspecified.

For the three repository `.gitattributes` files, each old-byte snapshot matched the current file prefix. The current file was exactly 43 bytes longer, with suffix LF + `/docs/backup/20261007/raw_source/** -text` + LF. The A12 handover snapshot remained a separate raw mapping. No source or repository attributes were changed by this review.

The frozen executor's supplementary export contract allowed only these exact role/path tuples:
- `coverage_export`: `docs/handover/20261007/CODE_COVERAGE.md`
- `source_map`: `workspace_backup/20261007/WORKSPACE_SOURCE_MAP.json`
- `frozen_control_copy`: `docs/backup/20261007/CONTROL_ACTION_MANIFEST.json`

The three corresponding destinations returned `git check-ignore --no-index` rc=1 (no ignore match) in the reviewed state, so supplementary exports did not require force-add. The supplementary parser only accepts ordinary exact-copy/stage operations; recheck the exact final tuples and ignore results against the final manifest before execution.

## Other bounded observations

The final document and QA inputs checked in this pre-final review were:
- `RelicWeave_V1.47.docx`: 779,513 bytes, SHA-256 `41f1254e40a2ecabdcfa1c6583af2fce0ae1b0ab980d5f9179bbaf687b7be64b`.
- Final closeout DOCX: 786,150 bytes, SHA-256 `883c831648d0697f456228f4d862deda8a36ff9740ecd6aadb3a3ebfdfdffc7d`.
- Handover DOCX: 64,641 bytes, SHA-256 `c8b4e57340c7c9d485aeb5c6aa298ba90ac166870c9d8d0a7d414d35051f7fd2`.
- Handover Markdown: 41,396 bytes, SHA-256 `f226a153f8aed2da04e07298f1277cd74071370d52cf74a4967702c2792f7a53`.
- Layout QA reported PASS for 238 pages; authority JSON was 119,386 bytes, SHA-256 `8692754e75ab91e7ef823f7501343bb476731923922c46b4bfa3679edc4b0f52`; QA summary Markdown was 1,446 bytes, SHA-256 `0afa2d5c500a0a01a5b7008673dac2f18d0afb59129bc9a17e1c6da0482fdeb5`. QA JSON inclusion in the backup inventory was still being corrected at this snapshot.

A bounded secret-pattern review of the frozen executor found one AWS access-key-format match in its public-documentation example. Only path/rule/count and fingerprints were recorded; the matching value was not copied into this report. Its line-237 sample fingerprint was SHA-256 `1a5d44a2dca19669d72edf4c4f1c27c4c1ca4b4408fbb17f6ce4ad452d78ddb3`, which root independently confirmed as the public AWS documentation example. This is not the final inventory credential scan.

## Limits

This is a source/inventory review, not a final-main-manifest audit, final supplementary export audit, successful backup execution, or post-push verification. No project code, solver, CAD, provider, or numerical workflow was run. No Git write, source copy, stage, commit, or push was performed. Final regenerated inventory/manifests, credential scan, supplementary tuple pins, and any post-push result remain separate review gates.

