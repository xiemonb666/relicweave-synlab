# Final QA coverage record — oldbase

**Status: `base_review_complete_pending_v4`.** This record aggregates the oldbase page reviews only. The reviewed master source is `RelicWeave_V1.47_A12_VesselForge_PGFrag_Closeout.docx`, SHA-256 `9af0efe877115200dd99bbcf8f24f3124e2932245d71795fc00252d08e278436`. No V147 innovations are merged or accepted here, and this is not a final merged-master PASS.

The 12 `final_master` JSON reports cover pages 1–204 exactly once. All 204 corresponding page PNGs exist in `master_v147_render_v3`; each page entry says it was inspected, each report documents individual original-detail image inspection, all PNG hashes match the actual files, and all 12 source SHA bindings match both the expected hash and the current source DOCX. The images are 1547 × 2002 pixels. Coverage has 203 pass pages and one issue page.

Page 183 remains open. Its v3 image SHA-256 is `50e85088f89e0127552e67a74034d3f06ffa5872d3fe8920c59d441f8c9ff28f`. The review records text overprinting across the divider in the TRELLIS.2 row of the upper I3 candidate-method table. A v4 narrow correction and root v4 review are still pending, so the oldbase record must not be called a final master PASS.

The two final handover JSON reports cover pages 1–13 exactly once, and their page PNG hashes and source bindings match the saved files. The original page 1–7 JSON records a page 5 clipping issue. The actual page 5 correction addendum reopens the same PNG at original detail, confirms the table header and footer are complete, and records final visual QA as PASS with zero issues. After applying that addendum, handover pages 1–13 have complete reviewed coverage and zero remaining visual issues; the original report and addendum remain separate records.

I read the actual baseline overwrite addendum and did not reconstruct the lost report. It states that the prior baseline QA report contents were overwritten and are unrecoverable from the retained evidence. The baseline DOCX (735,943 bytes, SHA-256 `7b15f365545d05538cddcd10801c90c9d10cfc741fa4a391bdc33706ea545fe0`) matches the actual file; the addendum says its 203-page PNG render remains retained. The current `final_master_086_102.md/json` copies are byte-identical to the current `master_086_102.md/json` files, as recorded by the addendum and confirmed by byte comparison.

The earlier independent content review files were not modified during this supplemental pass. Their current byte identities are recorded in the JSON companion. This coverage record is frozen before the final backup inventory.

| Master page range | QA JSON SHA-256 | Pages | Source SHA bound | PNG SHA checks | Individual inspection evidence |
|---|---|---:|---|---:|---|
| 001–017 | `7527f1aef405887fd63c5fec280091debcd9c36cac1e6a23e68919b9dceb9ded` | 17 | match | 17/17 | each page inspected at original detail |
| 018–034 | `4fec173cdeae1bcd73d2a35d8e5f196d3432fe833bf758ff018ee87e469bffec` | 17 | match | 17/17 | each page inspected at original detail |
| 035–051 | `b5680e7935be139844e64a88ca6c6414599440bd2175781f78a7a4681d39968c` | 17 | match | 17/17 | 17 individual PNGs inspected |
| 052–068 | `2cefdc8b1263cca54f81441a0de57ddd2fa9dc85dc20ca2512642f17e07cd4d4` | 17 | match | 17/17 | each PNG individually inspected |
| 069–085 | `0bbc5d8505b76466a75e4ddc541c6e75f62f9f06540b3ae3046796cf3fad4806` | 17 | match | 17/17 | each page viewed at original detail |
| 086–102 | `0e8c74e6c99a75efa9c1c2816bd27a15e78615ba9e6b84314105c39eb47f7f5e` | 17 | match | 17/17 | each PNG inspected individually at original detail |
| 103–119 | `b8ce822516b4e77ec2eb226a371be0bc06c22663e3c7853fece9ec410bcad8dc` | 17 | match | 17/17 | each page individually inspected at original detail |
| 120–136 | `9280fa2a9406d556c9e1592b57670be01f2fe2f670a930362d831b88fd5494ff` | 17 | match | 17/17 | each original PNG individually inspected |
| 137–153 | `4b3c93af58dd8af2bf4f49b47d4b63c6c64a732cc10bfdaaf898d7e4fe999264` | 17 | match | 17/17 | each page PNG individually viewed at original detail |
| 154–170 | `4b214d73f63a91e9a691c6df41fd6b8fecc8d58786d26ba14b0c6e99b2494ed5` | 17 | match | 17/17 | each page PNG individually viewed at original detail |
| 171–187 | `baddb85717ede8571d0f2d18fcaca87b6f572c27203c75e2f9ebb1d2c1764ea9` | 17 | match | 17/17 | each PNG individually inspected at original detail |
| 188–204 | `8390fff415f4723a8a0d1ffc8cf1186c691c04739015456ec223015816637f8f` | 17 | match | 17/17 | each page individually inspected at original detail |

No solver, CAD, tests, Git writes, or document source edits were part of this coverage check.
