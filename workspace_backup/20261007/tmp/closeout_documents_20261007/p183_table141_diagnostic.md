# P183 table 141 layout diagnostic

Status: one isolated fixed-grid diagnostic was rendered and failed to resolve the overlap. The root master, v3 snapshot, and v3 render remain unchanged. No additional layout variants were tested.

The baseline is `RelicWeave_V1.47_A12_VesselForge_PGFrag_Closeout.docx`, SHA-256 `9af0efe877115200dd99bbcf8f24f3124e2932245d71795fc00252d08e278436`; the exact v3 snapshot remains under `tmp/closeout_documents_20261007/`.

The target is XML table 141, row 6 (zero-based), the TRELLIS.2 data row in the “优势” and “主要限制” columns. Its grid has five equal 1,994-twip columns, while each of its seven rows carries the same cell-width hints `[1757, 1361, 2721, 2665, 2551]`. The table is `autofit` with `tblW=auto:0`. The target row has no fixed height, cell merge/span, `noWrap`, `tcFitText`, direct paragraph spacing/indent, or run spacing/scale/kerning; its runs use Noto Sans CJK SC at 8 pt.

A two-cell `tcW` change to 1,994 twips did not change page 183. One reversible diagnostic candidate then set only table 141 to fixed layout with a 9,970-twip width and normalized all 35 direct cell widths to the unchanged grid. It preserved text, fonts, margins, row heights, and all other tables/package parts. The candidate rendered to 204 pages; all 204 PNG hashes matched v3, including page 183, so the overlap remained and the candidate was not promoted.

The remaining source-level alternatives are table-wide auto-fit/preferred-width behavior and East Asian line-break inheritance. No language, font, or additional width variants were tested. Full machine-readable evidence and hashes are in the adjacent JSON and render-comparison JSON.
