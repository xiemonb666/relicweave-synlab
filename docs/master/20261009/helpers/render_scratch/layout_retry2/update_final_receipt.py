import copy
import hashlib
import json
import zipfile
from pathlib import Path

TASK = Path(__file__).resolve().parents[2]
WORKSPACE = TASK.parent.parent
RECEIPT_JSON = TASK / "authoring_receipt.json"
RECEIPT_MD = TASK / "authoring_receipt.md"
ARTIFACT_MD = TASK / "artifact.md"
LAYOUT_JSON = TASK / "layout_delta.json"
LAYOUT_MD = TASK / "layout_delta.md"
MANIFEST_PATH = TASK / "final_render_layout" / "render_manifest.json"
DOCX = WORKSPACE / "RelicWeave_V1.48_ContractAligned.docx"
E22 = TASK / "prefinal_layout_snapshot" / "RelicWeave_V1.48_ContractAligned.docx"
SOURCE = WORKSPACE / "RelicWeave_V1.47_A12_VesselForge_PGFrag_Closeout.docx"
PROTECTED = WORKSPACE / "RelicWeave_V1.47.docx"
FAILED_DOCX = TASK / "render_scratch" / "layout_variants" / "grid_tcW_both.docx"
FAILED_RENDER_LOG = TASK / "render_scratch" / "layout" / "render.log"
DIRECT_GRID_PDF = TASK / "render_scratch" / "layout_variants" / "grid_only_convert" / "grid_only_both.pdf"
LAYOUT_VARIANTS = TASK / "render_scratch" / "layout_variants"


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_parts(path):
    with zipfile.ZipFile(path) as archive:
        return archive.namelist(), {name: archive.read(name) for name in archive.namelist()}


receipt = json.loads(RECEIPT_JSON.read_text(encoding="utf-8"))
manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
layout = json.loads(LAYOUT_JSON.read_text(encoding="utf-8"))
if len(receipt.get("operations", [])) != 42:
    raise ValueError("the frozen 42-operation receipt was not preserved")
if manifest["docx"]["sha256"] != sha(DOCX):
    raise ValueError("render manifest DOCX pin does not match current final")
if sha(SOURCE) != receipt["source_docx"]["sha256"] or sha(PROTECTED) != receipt["protected_original"]["sha256"]:
    raise ValueError("pinned input or protected source changed")

e22_names, e22_parts = read_parts(E22)
final_names, final_parts = read_parts(DOCX)
source_names, source_parts = read_parts(SOURCE)
if final_names != e22_names or source_names != final_names:
    raise ValueError("DOCX ZIP inventories differ")
changed_vs_e22 = [name for name in final_names if final_parts[name] != e22_parts[name]]
changed_vs_source = [name for name in source_names if final_parts[name] != source_parts[name]]
if changed_vs_e22 != ["word/document.xml"]:
    raise ValueError(f"grid-only patch changed unexpected package parts vs e22: {changed_vs_e22}")
if changed_vs_source != ["docProps/core.xml", "word/document.xml", "word/header2.xml", "word/footer2.xml", "word/footer3.xml"]:
    raise ValueError(f"final package delta vs source changed unexpectedly: {changed_vs_source}")

previous_pages = {}
previous_dir = TASK / "final_render_edition"
for page in manifest["pages"]:
    prev = previous_dir / f"page-{page['page']}.png"
    current = Path(page["path"])
    if not prev.exists() or sha(current) != page["sha256"]:
        raise ValueError(f"page PNG pin mismatch on page {page['page']}")
    previous_pages[page["page"]] = prev.read_bytes() == current.read_bytes()
changed_pages = [n for n, identical in previous_pages.items() if not identical]

receipt["final_status"] = "authored_rendered_grid_only_layout_waiting_root_qa"
receipt["authoring"]["builder_sha256"] = sha(TASK / "build_master_docx.py")
receipt["authoring"]["layout_preflight_exit_code"] = 0
receipt["authoring"]["layout_patch_exit_code"] = 0
receipt["authoring"]["layout_patch"] = {
    "method": "OOXML ZIP-part replacement from the archived e22 candidate; only approved tblGrid/gridCol w:w values changed",
    "root_approval": "Root approved grid-only after visual inspection of the disposable grid-only export on pages 118 and 120.",
    "source_docx_path": str(E22.resolve()),
    "source_docx_sha256": sha(E22),
    "output_docx_path": str(DOCX.resolve()),
    "output_docx_sha256": sha(DOCX),
    "changed_package_parts_vs_e22": changed_vs_e22,
    "other_22_package_parts_raw_bytes_identical": True,
    "visible_text_identical": True,
    "bookmark_and_hyperlink_sequences_identical": True,
    "cell_tcW_widths_preserved_byte_for_byte": True,
    "row_heights_added": 0,
    "tables": layout["tables"],
    "layout_delta_json": str(LAYOUT_JSON.resolve()),
    "layout_delta_md": str(LAYOUT_MD.resolve()),
    "superseded_combined_grid_tcw_candidate": {
        "path": str(FAILED_DOCX.resolve()),
        "sha256": sha(FAILED_DOCX),
        "renderer_attempt_exit_code": 1,
        "render_log": str(FAILED_RENDER_LOG.resolve()),
        "disposition": "Preserved after bundled LibreOffice emitted no rasterizable PDF; no longer the final candidate.",
    },
    "disposable_conversion_checks": [
        {
            "variant": "table1_only_grid_plus_tcw",
            "docx_path": str((LAYOUT_VARIANTS / "table1_only.docx").resolve()),
            "docx_sha256": "f56cdb2f0dac5882c563ba05f0176fd9f5a6b39d4f14d81b2d1ed843451bb05f",
            "direct_pdf_sha256": "959a4428c76a6a2c72e497f2141f94f9753a04a476925c9a4db4072094dd4a04",
            "direct_pdf_bytes": 8167068,
            "exit_code": 0,
        },
        {
            "variant": "table2_only_grid_plus_tcw",
            "docx_path": str((LAYOUT_VARIANTS / "table2_only.docx").resolve()),
            "docx_sha256": "2064deffa6f40d82e2e5beb3c18f8f8504fd24f217d2c176ca292a06f3ae7843",
            "direct_pdf_sha256": "130ed534fe793457583314db388716ed735e3d4fa53ac57e5441d6f9fd3e9624",
            "direct_pdf_bytes": 8166672,
            "exit_code": 0,
        },
        {
            "variant": "both_tables_grid_only",
            "docx_path": str((LAYOUT_VARIANTS / "grid_only_both.docx").resolve()),
            "docx_sha256": "23a42e5f4cca40ef733edc9365c15bd0d5fdff647f8821fddec9c649e52b1455",
            "direct_pdf_path": str(DIRECT_GRID_PDF.resolve()),
            "direct_pdf_sha256": "349691498910fa1a5b874fc5c4cac37a8d0c4713bc3776e208ccf54b22249534",
            "direct_pdf_bytes": 8167430,
            "pages": 228,
            "exit_code": 0,
            "visual_probe_pages": [118, 120, 121],
        },
    ],
}

output = receipt["output_docx"]
output["path"] = str(DOCX.resolve())
output["bytes"] = DOCX.stat().st_size
output["sha256"] = sha(DOCX)
output["document_xml_sha256"] = hashlib.sha256(final_parts["word/document.xml"]).hexdigest()
output["package_part_deltas_vs_e22_before_layout"] = changed_vs_e22
output["all_other_22_parts_match_e22_before_layout_bytes"] = True
output["package_part_deltas_vs_pinned_source"] = changed_vs_source
output["all_other_18_parts_match_pinned_source_bytes"] = True

rendering = receipt["rendering"]
rendering.setdefault("render_exit_codes", {})["final_grid_only_layout_stage"] = 0
rendering["final_render_exit_code"] = 0
rendering["final_render_layout"] = {
    "docx_sha256": sha(DOCX),
    "pdf_path": manifest["pdf"]["path"],
    "pdf_bytes": manifest["pdf"]["bytes"],
    "pdf_sha256": manifest["pdf"]["sha256"],
    "pages": manifest["pdf"]["page_count"],
    "png_directory": manifest["render_directory"],
    "png_count": manifest["png_count"],
    "png_dimensions_px": [1547, 2002],
    "manifest_path": str(MANIFEST_PATH.resolve()),
    "renderer_exit_code": manifest["renderer"]["exit_code"],
    "visual_qa_status": "WAITING_FOR_ROOT_FINAL_QA",
}
rendering["final_pdf"] = {
    "path": manifest["pdf"]["path"],
    "bytes": manifest["pdf"]["bytes"],
    "sha256": manifest["pdf"]["sha256"],
    "page_count": manifest["pdf"]["page_count"],
}
rendering["output_directory"] = manifest["render_directory"]
rendering["final_png_count"] = manifest["png_count"]
rendering["final_dimensions_px"] = [1547, 2002]
rendering["final_pngs_vs_previous_stage"] = {
    "identical": len(previous_pages) - len(changed_pages),
    "different": len(changed_pages),
    "different_pages": changed_pages,
    "page_count_unchanged": len(previous_pages) == 228,
}
rendering["png_comparison_to_previous_stage"] = {
    "identical_count": len(previous_pages) - len(changed_pages),
    "different_count": len(changed_pages),
    "different_page_numbers": changed_pages,
}
rendering["final_dimensions_px"] = [1547, 2002]
rendering["stages"].append({
    "docx_sha256": sha(DOCX),
    "pdf_path": manifest["pdf"]["path"],
    "pdf_bytes": manifest["pdf"]["bytes"],
    "pdf_sha256": manifest["pdf"]["sha256"],
    "pages": manifest["pdf"]["page_count"],
    "png_directory": manifest["render_directory"],
    "changed_parts_vs_e22": changed_vs_e22,
    "renderer_exit_code": 0,
})
receipt["layout_target_pdf_pages"] = {
    "evidence_channel_metric_table": [118],
    "3d_feature_metric_table": [120],
    "independent_page_text_and_visual_check": "The final renderer preserves the grid-only layout visible in the Root-reviewed direct probe.",
}
receipt["rendered_pages"] = []
for page in manifest["pages"]:
    receipt["rendered_pages"].append({
        **page,
        "byte_identical_to_previous_edition_render": previous_pages[page["page"]],
    })

RECEIPT_JSON.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

op_pages = []
for op in receipt["operations"]:
    pages = ",".join(f"p{p}" for p in op.get("pdf_pages", []))
    op_pages.append(f"{op['operation_index']}:{pages}")

layout_lines = []
for table in layout["tables"]:
    layout_lines.append(
        f"- {table['key']}: BODY[{table['body_index']}], table #{table['table_index_1based']}, "
        f"{table['row_count']} rows; fixed tblW={table['table_width_twips']} twips; grid "
        f"{table['grid_widths_twips']} → {table['target_widths_twips']} twips (sum {table['grid_total_twips']}→{table['new_grid_total_twips']}); "
        f"all tcW values preserved; grid columns changed={table['grid_columns_updated']}; no row heights added."
    )
md = f"""# Authoring and render receipt

Final DOCX: {DOCX.resolve()}  
SHA-256: {sha(DOCX)}  
Final PDF: {manifest['pdf']['path']}  
PDF SHA-256: {manifest['pdf']['sha256']}  
228 pages; 228 PNGs at 1547 × 2002 pixels. Renderer exit code: 0. Final visual QA is queued with Root.

The frozen 42-operation body plan was applied with exact OOXML spans after checking source-text hashes. The authoring marker ran exactly once (rc=0); the original build returned rc=0. Root-approved core metadata and running edition strings remain as recorded below. The user’s protected original remains unchanged.

The final layout patch changed only `word/document.xml` relative to the archived e22 candidate. It widened the grid columns in two metric tables, kept every cell `tcPr/tcW` byte-identical, preserved table width 9994 twips and the existing grid sum 9992 twips, added no row heights, and preserved visible text, bookmark/link sequences, and all other package parts.

{chr(10).join(layout_lines)}

The combined grid-plus-cell-width trial is preserved at {FAILED_DOCX.resolve()} (SHA-256 {sha(FAILED_DOCX)}). Bundled LibreOffice did not produce a rasterizable PDF for that trial. Root approved the grid-only version after reviewing the disposable direct export; the isolated single-table conversions and grid-only combined export are recorded in `authoring_receipt.json`.

Final target tables appear on pages 118 and 120 after the layout adjustment. Their rendered PNG hashes are recorded in {MANIFEST_PATH.resolve()}; page 118 SHA-256 is {manifest['pages'][117]['sha256']}, and page 120 SHA-256 is {manifest['pages'][119]['sha256']}.

Final core fields: title={output['core_properties']['title']}; subject={output['core_properties']['subject']}; cp:version={output['core_properties']['version']}; modified={output['core_properties']['modified_utc']}. Created, creator, and revision remain unchanged.

Relative to the pinned source DOCX, changed parts remain: docProps/core.xml, word/document.xml, word/header2.xml, word/footer2.xml, and word/footer3.xml. The other 18 package parts match the pinned source bytes. Baseline-to-final structure and navigation counts are retained in the JSON receipt.

Frozen 42-operation PDF page map:  
{' '.join(op_pages)}

The final render manifest includes the PDF pin and every page PNG pin. The 228-page full review is waiting on Root’s final QA.
"""
RECEIPT_MD.write_text(md, encoding="utf-8")

artifact = f"""# V1.48 contract-aligned master plan

Final DOCX: {DOCX.resolve()}  
SHA-256: {sha(DOCX)}  
PDF: {manifest['pdf']['path']}  
PDF SHA-256: {manifest['pdf']['sha256']}  
Pages: 228. Final PNGs: {manifest['render_directory']} .

The document contains the frozen contract alignment, Root-approved core metadata and running edition strings, and the approved grid-only readability fix for the two metric tables. The final table patch changes only their `tblGrid/gridCol` widths; every cell width and all other text/package parts remain as recorded in the authoring receipt. The superseded combined grid-and-cell-width trial and disposable diagnostics are preserved under {LAYOUT_VARIANTS.resolve()} .

Authoring receipt: {RECEIPT_JSON.resolve()}  
Layout delta: {LAYOUT_JSON.resolve()}  
Final render manifest: {MANIFEST_PATH.resolve()}  
The final 228-page visual QA is pending Root review.
"""
ARTIFACT_MD.write_text(artifact, encoding="utf-8")

print(json.dumps({
    "final_docx_sha256": sha(DOCX),
    "final_pdf_sha256": manifest["pdf"]["sha256"],
    "page_count": manifest["pdf"]["page_count"],
    "png_count": manifest["png_count"],
    "changed_vs_e22": changed_vs_e22,
    "changed_vs_source": changed_vs_source,
    "different_pages_vs_previous_edition_render": changed_pages,
    "operation_count": len(receipt["operations"]),
}, ensure_ascii=False, indent=2))
