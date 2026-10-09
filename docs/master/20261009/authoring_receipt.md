# Authoring and render receipt

Final DOCX: C:\Users\xiemo\Desktop\ShardForge\RelicWeave_V1.48_ContractAligned.docx  
SHA-256: 23a42e5f4cca40ef733edc9365c15bd0d5fdff647f8821fddec9c649e52b1455  
Final PDF: C:\Users\xiemo\Desktop\ShardForge\tmp\master_contract_update_20261009\final_render_layout\RelicWeave_V1.48_ContractAligned.pdf  
PDF SHA-256: 6afa80c94ff8cfb5096a2a28753f10a5ad8958599d5e2dd9d8def94fe8237922  
228 pages; 228 PNGs at 1547 × 2002 pixels. Renderer exit code: 0. Final visual QA is queued with Root.

The frozen 42-operation body plan was applied with exact OOXML spans after checking source-text hashes. The authoring marker ran exactly once (rc=0); the original build returned rc=0. Root-approved core metadata and running edition strings remain as recorded below. The user’s protected original remains unchanged.

The JSON receipt preserves the helper hash that actually authored the final DOCX. The current helper’s later update only reports inspected/replayed grid slots versus attribute values that differ; it was not run against or used to rebuild the final DOCX.

The final layout patch changed only `word/document.xml` relative to the archived e22 candidate. It widened the grid columns in two metric tables, kept every cell `tcPr/tcW` byte-identical, preserved table width 9994 twips and the existing grid sum 9992 twips, added no row heights, and preserved visible text, bookmark/link sequences, and all other package parts.

- evidence_channel_metric_table: BODY[1277], table #95, 8 rows; fixed tblW=9994 twips; grid [798, 2299, 2298, 2298, 2299] → [2100, 2299, 1500, 1794, 2299] twips (sum 9992→9992); 5 grid slots inspected/replayed, 3 `gridCol/@w:w` attribute values actually changed; all tcW values preserved; no row heights added.
- 3d_feature_metric_table: BODY[1296], table #99, 7 rows; fixed tblW=9994 twips; grid [798, 2299, 2298, 2298, 2299] → [2300, 1548, 1547, 2298, 2299] twips (sum 9992→9992); 5 grid slots inspected/replayed, 3 `gridCol/@w:w` attribute values actually changed; all tcW values preserved; no row heights added.

Across both tables, 10 grid slots were inspected/replayed and 6 attribute values actually changed. The legacy JSON `grid_columns_updated=5` means five slots were replayed per table; it does not mean five values changed.

The combined grid-plus-cell-width trial is preserved at C:\Users\xiemo\Desktop\ShardForge\tmp\master_contract_update_20261009\render_scratch\layout_variants\grid_tcW_both.docx (SHA-256 164b65c96aa7701a0ad6036fc25c6402dc8bf86c8581c35d258c42eb17fc5a2d). Bundled LibreOffice did not produce a rasterizable PDF for that trial. Root approved the grid-only version after reviewing the disposable direct export; the isolated single-table conversions and grid-only combined export are recorded in `authoring_receipt.json`.

Final target tables appear on pages 118 and 120 after the layout adjustment. Their rendered PNG hashes are recorded in C:\Users\xiemo\Desktop\ShardForge\tmp\master_contract_update_20261009\final_render_layout\render_manifest.json; page 118 SHA-256 is 12cbf27b23230bac3902c956fdfbab446b5cd0675a2c154541d891c737455908, and page 120 SHA-256 is e914bb67e84876c358b85d7c71a0ce1f924a961af36c905a8fdb9ceab86aae7d.

Final core fields: title=RelicWeave V1.48 Contract Aligned Master Plan; subject=2026-10-09 contract alignment and qualification gates; cp:version=1.48; modified=2026-10-08T19:34:08Z. Created, creator, and revision remain unchanged.

Relative to the pinned source DOCX, changed parts remain: docProps/core.xml, word/document.xml, word/header2.xml, word/footer2.xml, and word/footer3.xml. The other 18 package parts match the pinned source bytes. Baseline-to-final structure and navigation counts are retained in the JSON receipt.

Historical pre-layout 42-operation PDF page map (not revalidated after the grid-only layout patch):  
1:p1 2:p1,p2 3:p7,p8 4:p2 5:p92 6:p189 7:p193 8:p193,p195 9:p195 10:p193,p195 11:p200 12:p8 13:p18 14:p19 15:p34 16:p34 17:p34 18:p35 19:p35 20:p36 21:p38 22:p38 23:p38 24:p41 25:p154 26:p154 27:p154 28:p11 29:p11 30:p12 31:p12 32:p63 33:p65 34:p65 35:p38 36:p38 37:p40 38:p11 39:p38,p39 40:p40 41:p95 42:p49

These per-operation page values are retained as historical references from `final_render_edition`; no refreshed 42-operation page mapping was performed against the current layout render. The current final-render target tables were verified on pages 118 and 120.

The final render manifest includes the PDF pin and every page PNG pin. The 228-page full review is waiting on Root’s final QA.
