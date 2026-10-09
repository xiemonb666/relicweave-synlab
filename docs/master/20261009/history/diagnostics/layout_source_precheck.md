# V1.48 layout source precheck

**Static source/XML result: PASS. Publication status: PENDING layout render and visual QA.** The earlier `independent_source_review.md/json` remains a prefinal review and was not overwritten. This report does not claim a final PDF or visual PASS.

The candidate DOCX is `164b65c96aa7701a0ad6036fc25c6402dc8bf86c8581c35d258c42eb17fc5a2d` (793425 bytes). Its pinned e22 pre-layout snapshot is `e22e15c52aff6b4590a5fba298d13516c27b37b944d3b3e779d82124b1ffc1f2`. The layout delta JSON/Markdown pins are `2ff9ffa8f3bbc356aa86bb2d5e3c13bed0b1aea46ffee85ae017487253ae2309` and `0edae996557c1081b7885df65d9e078f85d2fbec451bafc7ec4003a230dbf46b`; the reviewed builder is `7674b99d78395a56228c410b586d631d81613361bb87a4c4b5a6e7f6a13f3436`.

The candidate has the same 23-part ZIP order as e22. Relative to e22, only `word/document.xml` changed; the other 22 package parts, including `docProps/core.xml` and all headers/footers, are raw-byte identical. The document XML is well-formed. After masking only the two target tables’ `w:gridCol/@w:w` and `w:tcW/@w:w` values, its complete XML structure equals e22. All `w:t` values and attributes, field codes/instructions, body child tags, bookmarks, hyperlinks, and non-target text remain identical.

Both frozen-table cells remain aligned to their grid columns. Table 95 (`body[1277]`, evidence-channel metrics) remains 8×5; widths change from `[798, 2299, 2298, 2298, 2299]` to `[2100, 2299, 1500, 1794, 2299]` twips. Table 99 (`body[1296]`, 3D-feature metrics) remains 7×5; widths change to `[2300, 1548, 1547, 2298, 2299]` twips. Row heights did not change, and both tables already had fixed `tblLayout`. The 42-operation frozen plan still passes its 42 source-text/hash checks and 38 actual replacement checks; its inserted note, contract section/table, navigation link, and later insertion remain exact.

One inherited geometry detail is unchanged: each table’s fixed `w:tblW` is 9,994 twips while its grid and cell-column sum is 9,992 twips, a 2-twip (0.1 pt) difference already present in e22. The width patch preserves that gap and keeps each row’s cell widths equal to the grid; it did not introduce the mismatch.

The latest `final_render_layout` directory contains no PDF and the last `render.log` entry is `RENDER_EXIT_CODE=1`. This reviewer did not rerun LibreOffice or alter the DOCX. A successful layout render and its separate visual QA are still required before final delivery approval.
