# Approved table layout delta

This limited patch widens only the tblGrid/gridCol first columns in the two Root-identified metric tables. Every cell tcPr/tcW remains byte-identical to the e22 source. The fixed total table width, grid total, fonts, row spacing, borders, colors, text, row heights, bookmarks, navigation, headers/footers, metadata, and all non-target structure remain unchanged. The combined grid+tcW candidate was preserved separately after it failed bundled LibreOffice export; Root approved this grid-only candidate after visual inspection.

- evidence_channel_metric_table: body[1277], rows=8, table width=9994 twips (fixed), grid total=9992 -> 9992 twips; grid widths [798, 2299, 2298, 2298, 2299] -> [2100, 2299, 1500, 1794, 2299] twips. Five grid slots were inspected/replayed; three `gridCol/@w:w` attribute values actually changed.
- 3d_feature_metric_table: body[1296], rows=7, table width=9994 twips (fixed), grid total=9992 -> 9992 twips; grid widths [798, 2299, 2298, 2298, 2299] -> [2300, 1548, 1547, 2298, 2299] twips. Five grid slots were inspected/replayed; three `gridCol/@w:w` attribute values actually changed.

Across both tables, 10 grid slots were inspected/replayed and six `gridCol/@w:w` attribute values actually changed. The legacy JSON field `grid_columns_updated=5` counts slots replayed in each table; it does not mean five distinct values changed. Every cell `tcPr/tcW` remains unchanged.

Input DOCX SHA-256: e22e15c52aff6b4590a5fba298d13516c27b37b944d3b3e779d82124b1ffc1f2

Output DOCX SHA-256: 23a42e5f4cca40ef733edc9365c15bd0d5fdff647f8821fddec9c649e52b1455

document.xml SHA-256: a1612bdbe43a9d2566a6ea79da4c7538189f994176c52468a0622ecc812ac015 -> f63f4ede2a82d352164c3dc0f0590639951247da647cfa940c9c692b5096284e

The JSON records exact body/table positions, old/new grid widths, tcW preservation, visible text hash equality, and the changed-part inventory.
