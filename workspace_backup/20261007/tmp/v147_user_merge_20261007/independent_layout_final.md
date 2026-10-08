# Independent final layout static audit

Status: **LAYOUT_STATIC_PASS**

Accepted 70aa base: 786143 bytes; SHA-256 70aa097680aa1920528ba4b6d9646821ac78b367618c0e9b8dbc36439fa38044.
Layout final: 786150 bytes; SHA-256 883c831648d0697f456228f4d862deda8a36ff9740ecd6aadb3a3ebfdfdffc7d.

## Checks

- base_70aa_sha_matches_pin: **PASS**
- final_sha_matches_pin: **PASS**
- same_23_part_set_and_all_22_non_document_parts_exact: **PASS**
- all_relationship_parts_byte_identical: **PASS**
- all_18217_wt_tokens_exact_in_order: **PASS**
- all_8_status_paragraphs_exact: **PASS**
- all_553_bookmarks_and_113_internal_links_exact: **PASS**
- 194_tables_and_only_target_row_5_to_4: **PASS**
- three_row_paragraphs_cloned_after_target_table: **PASS**
- cloned_paragraph_xml_exact_except_keep_flags: **PASS**
- keepNext_label_and_first_explanation_keepLines_all_three: **PASS**
- five_B13_reference_spacing_after_changes_100_to_20: **PASS**
- paragraph_C14N_diffs_are_only_five_refs_plus_three_relocated_clones: **PASS**
- all_other_body_C14N_identical: **PASS**

Ordered w:t tokens: 18217 in both files; exact sequence equal: True.
Solver-native contact row: table 185, row 5; 5→4 rows; three body paragraph clones exact: True.
B13 reference spacing after changes: 5 paragraphs, base 100 → final 20 twips.
All other body C14N identical after reversing only these layout moves: True.
The accepted semantic merge is inherited from the reviewed 70aa base; this report assesses only the subsequent layout delta.
No DOCX was modified or rendered.
