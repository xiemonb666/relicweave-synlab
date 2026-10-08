# Final master visual QA: pages 120–136

Source: RelicWeave_V1.47_A12_VesselForge_PGFrag_Closeout.docx  
Source SHA-256: 9AF0EFE877115200DD99BBCF8F24F3124E2932245D71795FC00252D08E278436  
Render: tmp/closeout_documents_20261007/master_v147_render_v3/page-N.png  
Coverage: 17 pages, each 1547×2002, opened individually at original detail.

**Result: PASS, 17/17.** No overlap, cropped text, unreadable long paths, table collisions or boundary defects, or stranded headings were found. Dense content, readable continuation across pages, and normal token/path wrapping were accepted.

The footer is present on every page. A bottom-region pixel check found the footer content at rows 1925–1948 on all pages, including page 136. Missing running headers on pages 121–122 are within the preserved template allowance.

| Page | Result | Visual notes |
|---:|:---:|---|
| 120 | PASS | References and concluding note; long URLs wrap cleanly; section 25.11 begins with body. |
| 121 | PASS | Reference list ends cleanly with ample lower-page whitespace. |
| 122 | PASS | Appendix G opening; table continues onto 123 with clear boundaries. |
| 123 | PASS | Repeated table header; G2 table continues onto 124. |
| 124 | PASS | G2 table repeats its header; G3 table starts and continues onto 125. |
| 125 | PASS | D06–D24 continuation and G4 table start; continuation onto 126 is clear. |
| 126 | PASS | G4 continuation and G5 opening; no isolated heading. |
| 127 | PASS | Numbered steps and monospaced project tree remain legible. |
| 128 | PASS | Diagram labels/connectors are distinct; G5.2 table continues onto 129. |
| 129 | PASS | G5.2 continuation repeats its header; G5.3/G6 headings have following content. |
| 130 | PASS | Coordinate text, schema table, and G7 opening are clearly separated. |
| 131 | PASS | G7 content and table are readable; headings are not stranded. |
| 132 | PASS | G7.4 continuation repeats its header; G7.5 table borders are clear. |
| 133 | PASS | G7.5/G7.6/G8 continue naturally to the next page. |
| 134 | PASS | G8.1 table fits; G8.3 code continues onto 135. |
| 135 | PASS | Code and prose are legible; final paragraph continues naturally onto 136. |
| 136 | PASS | G8.6–G8.8 are readable; footer confirmed at the bottom, with no clipping. |

Per-page PNG SHA-256 values and inspected=true records are in final_master_120_136.json.