# Layout-final visual QA coverage

**Status: `BLOCKED_MISMATCHES`.** This report covers the frozen layout-final candidate only after all 13 visual QA groups were ready, root accepted the content review, and root gave the separate QA GO.

Layout-final candidate SHA-256: `883c831648d0697f456228f4d862deda8a36ff9740ecd6aadb3a3ebfdfdffc7d`. Rendered pages: 225/225; page PNG SHA matches: 225; clean pass pages: 225.

Each page group was inspected individually and bound to the layout-final source SHA. Every page PNG hash was checked against the actual render file. See the JSON companion for per-page hashes and report identities.

Semantic qualification is inherited from the reviewed 70aa base. The frozen independent layout static proof binds both source DOCX files and verifies all 18,217 ordered text tokens, eight status paragraphs, bookmarks/internal links, the 23-part package, and exactly the declared layout deltas. The proof and root content review identities are recorded in the JSON companion.

The frozen handover DOCX/Markdown and 13 page PNGs were checked against their existing two reports and page 5 correction addendum. No handover rerender was performed.

The previous baseline 086-102 QA report overwrite remains unrecoverable; its addendum is retained as written and the lost report is not reconstructed. Two known temporary-helper loss/overwrite records are retained by count only; missing helper contents are not fabricated.

Integrity findings:

- layout_master_019_036.json has no integer counts.issues
- layout_master_019_036.json pass count does not equal its page range
- layout_master_019_036.json range/source page-count metadata does not match the frozen render
- layout_master_037_054.json has no integer counts.issues
- layout_master_037_054.json pass count does not equal its page range
- layout_master_037_054.json range/source page-count metadata does not match the frozen render
- layout_master_055_072.json has no integer counts.issues
- layout_master_055_072.json pass count does not equal its page range
- layout_master_055_072.json range/source page-count metadata does not match the frozen render
- layout_master_073_090.json has no integer counts.issues
- layout_master_073_090.json pass count does not equal its page range
- layout_master_073_090.json range/source page-count metadata does not match the frozen render
- layout_master_091_108.json has no integer counts.issues
- layout_master_091_108.json pass count does not equal its page range
- layout_master_091_108.json range/source page-count metadata does not match the frozen render
- layout_master_109_126.json has no integer counts.issues
- layout_master_109_126.json pass count does not equal its page range
- layout_master_109_126.json range/source page-count metadata does not match the frozen render
- layout_master_127_144.json has no integer counts.issues
- layout_master_127_144.json pass count does not equal its page range
- layout_master_127_144.json range/source page-count metadata does not match the frozen render
- layout_master_145_162.json has no integer counts.issues
- layout_master_145_162.json pass count does not equal its page range
- layout_master_145_162.json range/source page-count metadata does not match the frozen render
- layout_master_163_180.json has no integer counts.issues
- layout_master_163_180.json pass count does not equal its page range
- layout_master_163_180.json range/source page-count metadata does not match the frozen render
- layout_master_181_198.json has no integer counts.issues
- layout_master_181_198.json pass count does not equal its page range
- layout_master_181_198.json range/source page-count metadata does not match the frozen render
- layout_master_199_216.json has no integer counts.issues
- layout_master_199_216.json pass count does not equal its page range
- layout_master_199_216.json range/source page-count metadata does not match the frozen render
- layout_master_217_225.json has no integer counts.issues
- layout_master_217_225.json pass count does not equal its page range
- layout_master_217_225.json range/source page-count metadata does not match the frozen render
