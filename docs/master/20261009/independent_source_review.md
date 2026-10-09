# V1.48 Independent Source Review

**Status: PASS for source, contract, package, and render-file integrity; no substantive blocker found.** Visual QA remains a separate pending gate and is not approved by this review.

## Provenance

Root reported that the writer acknowledged modifying these independent review files during the preceding count-correction round. That writer-authored intermediate state is **unaccepted and superseded**. I regenerated this final report from the pinned source and final DOCX bytes/XML, frozen 42-operation plan, authoritative A12 contract files, final receipt and render manifest, actual PNG/PDF files, and the preserved executed-helper byte snapshot. I did not reuse the prior review’s conclusions. Historical review and failed-layout precheck snapshots were rehashed only to confirm that they remain preserved.

## Final pins

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| Final DOCX | 793,363 | `23a42e5f4cca40ef733edc9365c15bd0d5fdff647f8821fddec9c649e52b1455` |
| Final PDF, 228 pages | 8,167,969 | `6afa80c94ff8cfb5096a2a28753f10a5ad8958599d5e2dd9d8def94fe8237922` |
| Final authoring receipt JSON | 214,995 | `ccbf046b82cd85fa53779c34e02c76f8fd869ccd7718958afd33db4394267b3d` |
| Final authoring receipt Markdown | 4,596 | `cc863aa36556109d5c673a69db0ae75543b0eb8aaf2893b722b7761f16bbc572` |
| Final render manifest | 78,384 | `08e06c8ee8e22fdc5ce4853e0dc48db08cc885c2d027eeecec09bed048d553b6` |
| Layout delta JSON / Markdown | 6,094 / 1,925 | `0f5ec02dcc3c29c8e05b647f55e70ac480162ee63b663e8761e3f6d56cf90d31` / `dcdb8665642cd560ae6777d38f95c782913059e5e05789d9b4d44cff09b5c57d` |
| Current helper | 62,963 | `72fed3dca8bf8c986d2c4612e5f8ea3ca3ffbcf85cb86c186f3ff432d72e944e` |
| Executed-helper snapshot | 61,698 | `5a74044e56ea08b61a0ad27675d7abc4364c945ede42bd0741080bc6140310e2` |
| Frozen plan JSON / Markdown | 76,958 / 48,099 | `8c611ffcc443f4d4b6374c8ba0c48c92f2034571f651238c1a7fbc8546606e08` / `022df9010ceaa51da02cfe9ef8dd35300289298db25fb06718dba7a3c48272ca` |

The executed-helper snapshot hash matches the final authoring receipt’s builder hash byte-for-byte. The current helper is a later count-semantics update; the receipt states it was not run to author or rebuild the final DOCX. The pinned Closeout source remains 786,150 bytes / `883c831648d0697f456228f4d862deda8a36ff9740ecd6aadb3a3ebfdfdffc7d`. The protected user original remains 779,513 bytes / `41f1254e40a2ecabdcfa1c6583af2fce0ae1b0ab980d5f9179bbaf687b7be64b`.

## Direct source and plan checks

I rechecked all 38 replacement/fragment source text preimages against the pinned source text and SHA-256 values, then checked all 38 resulting texts in the final DOCX against the frozen plan. The two revision-note paragraphs, new contract heading and intro, all seven MC01–MC07 table rows, appended navigation link, and final AUC static note also match the plan. Of 2,669 source body children, 2,634 unaffected direct subtrees compared semantically equal after accounting for the planned insertions; BODY[5], BODY[6], and source BODY[181]→final BODY[186] remain exact. Final counts are 2,675 body children and 195 tables.

The source has 553 bookmark pairs and 113 internal hyperlinks; the final document has 554 pairs and 114 links. All original bookmark and hyperlink subtrees remain in order, the one new pair is ID `3470` / `RW148_CONTRACT_ALIGNMENT`, every final internal anchor resolves, and `w:sectPr` remains last. BODY[7]’s 33 original navigation links are preserved and BODY[9] has 34. The appended link uses `V1.48合同修订`; its separator is the source ` · ` run with the original run properties. The frozen plan’s separator and old-link-count metadata corrections were limited to these approved implementation details.

## Package and approved layout delta

The final DOCX contains 23 ZIP parts with the source/e22 part order. Relative to e22, only `word/document.xml` differs; the other 22 uncompressed part payloads are byte-identical. The final document XML tree equals e22 after normalizing only the six approved `w:gridCol/@w:w` value changes. All `w:t` values and field codes are unchanged from e22, as are every table-cell `tcW` and row-height setting.

| Target table | Shape | Grid widths, before → after | Changed values |
|---|---:|---|---:|
| Evidence-channel metric table, BODY[1277] | 8 × 5 | [798, 2299, 2298, 2298, 2299] → [2100, 2299, 1500, 1794, 2299] | 3 |
| 3D-feature metric table, BODY[1296] | 7 × 5 | [798, 2299, 2298, 2298, 2299] → [2300, 1548, 1547, 2298, 2299] | 3 |

Each table keeps fixed `tblW=9994` twips and the existing 9992-twip grid sum. The two-twip difference is inherited from e22. Five grid slots per table were inspected/replayed; six values changed across both tables.

Against the pinned Closeout source, exactly five parts differ: `word/document.xml`, `docProps/core.xml`, `word/header2.xml`, `word/footer2.xml`, and `word/footer3.xml`. The other 18 parts are byte-identical. The only approved core-field changes read back as title `RelicWeave V1.48 Contract Aligned Master Plan`, subject `2026-10-09 contract alignment and qualification gates`, version `1.48`, and modified time `2026-10-08T19:34:08Z`. Header/footer version strings read V1.48 / 2026-10-09. After restoring only the authorized property/text values, their XML trees equal the source; field codes, cached field text, run formatting, and section formatting remain intact.

## Contract alignment and qualification boundary

The final text reflects only physical relation classes R0/R1/R2 while retaining stored codes R0=0, R1=1, R2=2, TINY_CONTACT=3, UNKNOWN=4. The inner `GenerationSpec` version remains distinct from outer job schema versions; member schema/API/asset-role migration is pending and undeclared fields remain rejected. Typed relation head and calibrated abstention are explicitly unimplemented.

Member positives derive from the independent confirmed object-membership manifest intersected with frozen G and excluding q. Confirmed same-object identity remains positive when pair adjacency is unknown; member closure and direct-R2 neighbor closure are independent. Empty-set semantics, object-macro aggregation, within-object query weighting, source-cluster intervals, and GT isolation remain requirements. B1 remains an R2 scalar ablation. Oracle-R2 is an offline privileged diagnostic, not a strict upper bound or deployable claim, and requires matched pool/context/budget with controls. MC01–MC07 remain `SPECIFIED / NOT_RUN`. The AUC valid/loss-mask issue is only registered as a static gap; no source change or metric rerun is claimed.

The preserved E8 phrase calling perfect-adjacency Oracle a theoretical upper-limit diagnostic remains inside its dated historical record. Current A6.20 text states Oracle-R2 is not a strict performance upper bound. No active contradiction was found; historical experiment results and verdicts were not removed.

The authorities re-read were `contract_alignment_20261009.md/json`, `data_contract.md` §8, and `interfaces.md` §5. Their current byte/SHA pins are in the accompanying JSON report.

## Render integrity and limits

The receipt and manifest agree with the actual final PDF hash and 228-page count. I rehashed all 228 PNGs; actual byte lengths and SHA-256 values match both receipt and manifest, page numbers are continuous, and the manifest reports `PASS` with no integrity errors. Visual QA remains `WAITING_FOR_ROOT_FINAL_QA`. The receipt identifies current verified layout tables at pages 118 and 120; its 42-operation page map is explicitly historical pre-layout and is not used here as current page evidence.

No tests, application CLI, solver, training, renderer, or Git operation was run by this review.