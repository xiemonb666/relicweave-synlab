# Independent static review of merged V1.47 candidate

**Status: static pass with reviewed scope exceptions.** This result applies to the final candidate hash below. It is a static review; rendering remains a separate main-agent gate.

## File identity

- user: 779513 bytes; SHA-256 `41f1254e40a2ecabdcfa1c6583af2fce0ae1b0ab980d5f9179bbaf687b7be64b`
- v146: 733634 bytes; SHA-256 `15978a3956fa33e8048cc54c1dad6878a7e19d9c71b84415dcaf8732f041a3b4`
- frozen_current: 734565 bytes; SHA-256 `9af0efe877115200dd99bbcf8f24f3124e2932245d71795fc00252d08e278436`
- candidate: 786143 bytes; SHA-256 `70aa097680aa1920528ba4b6d9646821ac78b367618c0e9b8dbc36439fa38044`
- previous_candidate: 785707 bytes; SHA-256 `2bcfc83635976f609f55d995fc67d6e8ee6c3e47b2ff39bc9826bdff4071e219`

Final candidate matches FINAL_SOURCECHECK: **True**. The previous candidate matches the initial source proof: **True**.

## Static findings

- source_hashes_match_expected: **PASS**
- final_candidate_matches_final_proof: **PASS**
- previous_candidate_matches_initial_source_proof: **PASS**
- eight_closeout_status_paragraphs_exact: **PASS**
- all_14_clarifications_preserved_or_superseded_by_exact_final_patches: **PASS**
- all_user_paragraphs_exactly_retained_in_order_before_final_patchset: **PASS**
- final_text_changes_are_exactly_the_eight_declared_patches: **PASS**
- all_33_new_headings_uniquely_bookmarked_linked: **PASS**
- original_520_bookmark_pairs_preserved: **PASS**
- old_internal_links_preserved_no_dangling: **PASS**
- old_relationships_preserved: **PASS**
- historical_v146_unmatched_paragraphs_all_reviewed_planning_or_overview: **PASS**
- all_nonplanning_v146_tables_preserved_in_order: **PASS**
- INNO_32_45_not_promoted: **PASS**
- TRELLIS_text_exact_three_breaks: **PASS**
- no_fixedgrid_or_width_change: **PASS**
- current_styles_headers_footers_preserved: **PASS**
- candidate_Noto_font_mapping_present: **PASS**

The eight frozen closeout paragraphs (seven status paragraphs plus the current p5 summary) are exact: 8/8.
All 14 accepted source clarifications occur exactly once in the previous merge candidate. 10 remain verbatim in the final candidate; 4 are refined by the exact final planning patch list. The 14 texts and links to their refinements are recorded in JSON.
The final candidate differs from its previous candidate at exactly 8 paragraph indexes, all covered by the eight exact old/new patches in FINAL_PATCHLIST. No unlisted paragraph-text changes were found.
All 7462 user-source paragraphs were found in order in the previous merge candidate; the final eight refinements are applied afterward at declared indexes. This does not claim every user paragraph is byte-identical in the final file.
Navigation: 33 newly added headings, each with one bookmark and one internal link; all 520 original bookmark ID/name pairs remain; no orphan internal links. Package relationships and styles/header/footer XML match the frozen closeout source.
Historical V1.46 comparison: 9 unmatched paragraphs, all classified as superseded overview/planning text; 3 exact unmatched tables, all classified as superseded planning tables. All other V1.46 table signatures remain in order. Exact exclusions and texts are in JSON.
INNO-32–45 remain IDEA/RESEARCH_CANDIDATE. TRELLIS.2 text is unchanged with exactly three added manual breaks; all 194 user tables retain their source geometry.

## Accepted exception sets

The 14 source clarification texts and the eight final old/new paragraph replacements are recorded verbatim in JSON. The final three obsolete V1.46 planning tables are the competition/paper delivery matrix, metric target table, and acquisition-content table; the nine absent old paragraphs are version/overview, architecture/document summary, reframed question, delivery-plan, and appendix-navigation text. The result does not claim that all 7,462 source paragraphs remained text-identical.

No DOCX, source file, Git state, or numeric experiment was changed or run.
