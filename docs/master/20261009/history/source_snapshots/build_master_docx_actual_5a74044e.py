#!/usr/bin/env python3
"""Apply the pinned, text-only V1.48 contract patch to the source DOCX."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

sys.stdout.reconfigure(encoding="utf-8")

WORKSPACE = Path(r"C:\Users\xiemo\Desktop\ShardForge")
TMP_DIR = WORKSPACE / "tmp" / "master_contract_update_20261009"
DEFAULT_PLAN = TMP_DIR / "patch_plan.json"
DEFAULT_PLAN_MD = TMP_DIR / "patch_plan.md"
DEFAULT_SOURCE = WORKSPACE / "RelicWeave_V1.47_A12_VesselForge_PGFrag_Closeout.docx"
DEFAULT_PROTECTED = WORKSPACE / "RelicWeave_V1.47.docx"
DEFAULT_OUTPUT = WORKSPACE / "RelicWeave_V1.48_ContractAligned.docx"

EXPECTED_PLAN_SHA256 = "8c611ffcc443f4d4b6374c8ba0c48c92f2034571f651238c1a7fbc8546606e08"
EXPECTED_PLAN_MD_SHA256 = "022df9010ceaa51da02cfe9ef8dd35300289298db25fb06718dba7a3c48272ca"
EXPECTED_SOURCE_SHA256 = "883c831648d0697f456228f4d862deda8a36ff9740ecd6aadb3a3ebfdfdffc7d"
EXPECTED_PROTECTED_SHA256 = "41f1254e40a2ecabdcfa1c6583af2fce0ae1b0ab980d5f9179bbaf687b7be64b"

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
W14_NS = "http://schemas.microsoft.com/office/word/2010/wordml"
XML_NS = "http://www.w3.org/XML/1998/namespace"
NS = {"w": W_NS, "r": R_NS}
W = f"{{{W_NS}}}"
R = f"{{{R_NS}}}"
W14 = f"{{{W14_NS}}}"
XML_SPACE = f"{{{XML_NS}}}space"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def q(name: str) -> str:
    return W + name


def visible_text(element: ET.Element) -> str:
    return "".join(node.text or "" for node in element.findall(".//w:t", NS))


def text_nodes(element: ET.Element) -> list[ET.Element]:
    return element.findall(".//w:t", NS)


def set_text_node(node: ET.Element, value: str | None) -> None:
    node.text = value if value else None
    if value and (value.startswith(" ") or value.endswith(" ") or "  " in value):
        node.set(XML_SPACE, "preserve")
    else:
        node.attrib.pop(XML_SPACE, None)


def set_all_visible_text(paragraph: ET.Element, value: str) -> None:
    nodes = text_nodes(paragraph)
    if not nodes:
        raise ValueError("target paragraph has no w:t text node")
    unsupported = {q("tab"), q("br"), q("instrText"), q("delText"), q("sym")}
    found = [child.tag for child in paragraph.iter() if child.tag in unsupported]
    if found:
        raise ValueError(f"target paragraph contains unsupported visible nodes: {found}")
    set_text_node(nodes[0], value)
    for node in nodes[1:]:
        set_text_node(node, None)


def replace_fragment(paragraph: ET.Element, old: str, new: str) -> None:
    nodes = text_nodes(paragraph)
    full = "".join(node.text or "" for node in nodes)
    if full.count(old) != 1:
        raise ValueError(f"expected fragment must occur once; found {full.count(old)}")
    start = full.index(old)
    end = start + len(old)
    ranges: list[tuple[int, int, ET.Element]] = []
    cursor = 0
    for node in nodes:
        value = node.text or ""
        ranges.append((cursor, cursor + len(value), node))
        cursor += len(value)
    touched = [(left, right, node) for left, right, node in ranges if left < end and right > start]
    if not touched:
        raise ValueError("fragment mapped to no w:t nodes")
    first = touched[0]
    last = touched[-1]
    if first[2] is last[2]:
        value = first[2].text or ""
        set_text_node(first[2], value[: start - first[0]] + new + value[end - first[0] :])
        return
    for index, (left, right, node) in enumerate(touched):
        value = node.text or ""
        prefix = value[: max(0, start - left)] if index == 0 else ""
        suffix = value[max(0, end - left) :] if index == len(touched) - 1 else ""
        set_text_node(node, prefix + (new if index == 0 else "") + suffix)


def p_style_value(paragraph: ET.Element) -> str | None:
    style = paragraph.find("w:pPr/w:pStyle", NS)
    return style.get(q("val")) if style is not None else None


def first_run_rpr(paragraph: ET.Element) -> ET.Element | None:
    for run in paragraph.findall(".//w:r", NS):
        props = run.find("w:rPr", NS)
        if props is not None:
            return copy.deepcopy(props)
    return None


def clone_plain_paragraph(template: ET.Element, value: str) -> ET.Element:
    paragraph = ET.Element(q("p"))
    properties = template.find("w:pPr", NS)
    if properties is not None:
        paragraph.append(copy.deepcopy(properties))
    run = ET.Element(q("r"))
    run_props = first_run_rpr(template)
    if run_props is not None:
        run.append(run_props)
    text = ET.SubElement(run, q("t"))
    set_text_node(text, value)
    paragraph.append(run)
    return paragraph


def strip_duplicate_para_ids(element: ET.Element) -> None:
    for node in element.iter():
        if node.tag == q("p"):
            node.attrib.pop(W14 + "paraId", None)
            node.attrib.pop(W14 + "textId", None)


def paragraph_shape(element: ET.Element) -> bytes:
    clone = copy.deepcopy(element)
    for node in clone.findall(".//w:t", NS):
        node.text = None
        node.attrib.pop(XML_SPACE, None)
    return ET.tostring(clone, encoding="utf-8")


def target_paragraph(body_children: list[ET.Element], locator: dict[str, Any]) -> ET.Element:
    index = int(locator["body_index"])
    if index < 0 or index >= len(body_children):
        raise IndexError(f"BODY[{index}] is outside the source body")
    item = body_children[index]
    kind = locator.get("kind")
    if kind == "paragraph":
        if item.tag != q("p"):
            raise ValueError(f"BODY[{index}] is {item.tag}, expected w:p")
        return item
    if kind == "table_cell_paragraph":
        if item.tag != q("tbl"):
            raise ValueError(f"BODY[{index}] is {item.tag}, expected w:tbl")
        rows = item.findall("./w:tr", NS)
        row_index = int(locator["row"])
        if row_index >= len(rows):
            raise IndexError(f"BODY[{index}] row {row_index} does not exist")
        cells = rows[row_index].findall("./w:tc", NS)
        cell_index = int(locator["cell"])
        if cell_index >= len(cells):
            raise IndexError(f"BODY[{index}] row {row_index} cell {cell_index} does not exist")
        paragraphs = cells[cell_index].findall("./w:p", NS)
        paragraph_index = int(locator["paragraph"])
        if paragraph_index >= len(paragraphs):
            raise IndexError(f"BODY[{index}] row {row_index} cell {cell_index} paragraph {paragraph_index} does not exist")
        return paragraphs[paragraph_index]
    raise ValueError(f"unsupported target locator kind: {kind}")


def verify_exact_source(paragraph: ET.Element, operation: dict[str, Any]) -> str:
    current = visible_text(paragraph)
    expected = operation.get("original_visible_text")
    if current != expected:
        raise ValueError(f"source visible text mismatch for {operation.get('section')}")
    current_hash = sha256_bytes(current.encode("utf-8"))
    if current_hash != operation.get("original_text_sha256"):
        raise ValueError(f"source text SHA-256 mismatch for {operation.get('section')}")
    return current


def create_table_from_template(template: ET.Element, table_spec: dict[str, Any]) -> ET.Element:
    if template.tag != q("tbl"):
        raise ValueError("table formatting template is not w:tbl")
    original_rows = template.findall("./w:tr", NS)
    gates = table_spec["rows"]
    expected_rows = len(gates) + 1
    if len(original_rows) != expected_rows:
        raise ValueError(f"table template has {len(original_rows)} rows; expected {expected_rows}")
    if any(len(row.findall("./w:tc", NS)) != len(table_spec["columns"]) for row in original_rows):
        raise ValueError("table template column count differs from contract table")
    prohibited = {q("bookmarkStart"), q("bookmarkEnd"), q("hyperlink"), q("fldChar"), q("instrText"), q("drawing"), q("pict"), q("object"), q("sdt")}
    if any(node.tag in prohibited for node in template.iter()) or any(node is not template and node.tag == q("tbl") for node in template.iter()):
        raise ValueError("table template contains a bookmark, link, field, drawing, control, or nested table")

    values: list[list[str]] = [list(table_spec["columns"])]
    for gate in gates:
        values.append(
            [
                f"{gate['id']} {gate['name']}",
                gate["acceptance"],
                f"{gate['status']}；当前缺口：{gate['gap']}",
            ]
        )

    table = ET.Element(q("tbl"))
    for child in template:
        if child.tag == q("tblPr") or child.tag == q("tblGrid"):
            table.append(copy.deepcopy(child))
    if table.find("./w:tblPr", NS) is None or table.find("./w:tblGrid", NS) is None:
        raise ValueError("table template lacks tblPr or tblGrid")

    for row_index, source_row in enumerate(original_rows):
        row = ET.Element(q("tr"))
        source_row_props = source_row.find("w:trPr", NS)
        if source_row_props is not None:
            row.append(copy.deepcopy(source_row_props))
        cells = source_row.findall("./w:tc", NS)
        for cell_index, source_cell in enumerate(cells):
            if source_cell.findall("./w:tbl", NS):
                raise ValueError("table template cell contains a nested table")
            source_paragraphs = source_cell.findall("./w:p", NS)
            if len(source_paragraphs) != 1:
                raise ValueError("table template cell must contain exactly one paragraph")
            cell = ET.Element(q("tc"))
            cell_props = source_cell.find("w:tcPr", NS)
            if cell_props is not None:
                cell.append(copy.deepcopy(cell_props))
            cell.append(clone_plain_paragraph(source_paragraphs[0], values[row_index][cell_index]))
            row.append(cell)
        table.append(row)
    strip_duplicate_para_ids(table)
    return table


def build_internal_link(nav_paragraph: ET.Element, link_text: str, anchor: str, requested_separator: str, expected_last_anchor: str) -> str:
    existing_links = nav_paragraph.findall("./w:hyperlink", NS)
    if not existing_links:
        raise ValueError("navigation paragraph has no internal hyperlink template")
    last_link = existing_links[-1]
    if last_link.get(q("anchor")) != expected_last_anchor:
        raise ValueError("navigation paragraph's final link anchor changed")
    if last_link.get(R + "id") is not None:
        raise ValueError("final navigation hyperlink unexpectedly has an external relationship")
    link_template_run = last_link.find("./w:r", NS)
    if link_template_run is None:
        raise ValueError("final navigation hyperlink has no run")

    separator_candidates: list[tuple[str, ET.Element]] = []
    for run in nav_paragraph.findall("./w:r", NS):
        value = visible_text(run)
        if len(value) == 3 and value[0].isspace() and value[2].isspace() and not value[1].isspace():
            separator_candidates.append((value, run))
    candidate_values = {value for value, _ in separator_candidates}
    if len(candidate_values) != 1 or len(separator_candidates) != 33:
        raise ValueError("navigation separator source does not contain exactly 33 identical separator runs")
    separator = separator_candidates[0][0]
    separator_template = separator_candidates[-1][1]

    separator_run = ET.Element(q("r"))
    separator_rpr = separator_template.find("./w:rPr", NS)
    if separator_rpr is not None:
        separator_run.append(copy.deepcopy(separator_rpr))
    separator_node = ET.SubElement(separator_run, q("t"))
    set_text_node(separator_node, separator)

    new_link = ET.Element(q("hyperlink"))
    new_link.set(q("anchor"), anchor)
    if q("history") in last_link.attrib:
        new_link.set(q("history"), last_link.get(q("history"), "1"))
    new_run = ET.Element(q("r"))
    link_rpr = link_template_run.find("./w:rPr", NS)
    if link_rpr is not None:
        new_run.append(copy.deepcopy(link_rpr))
    link_node = ET.SubElement(new_run, q("t"))
    set_text_node(link_node, link_text)
    new_link.append(new_run)

    if list(nav_paragraph)[-1] is not last_link:
        raise ValueError("final navigation link is not the last existing paragraph child")
    nav_paragraph.append(separator_run)
    nav_paragraph.append(new_link)
    return separator


def create_contract_heading(template: ET.Element, text: str, bookmark_name: str, bookmark_id: str) -> ET.Element:
    if p_style_value(template) != "Heading2":
        raise ValueError("contract heading template is not Heading2")
    paragraph = ET.Element(q("p"))
    ppr = template.find("w:pPr", NS)
    if ppr is not None:
        paragraph.append(copy.deepcopy(ppr))
    start = ET.Element(q("bookmarkStart"))
    start.set(q("id"), bookmark_id)
    start.set(q("name"), bookmark_name)
    paragraph.append(start)
    run = ET.Element(q("r"))
    rpr = first_run_rpr(template)
    if rpr is not None:
        run.append(rpr)
    text_node = ET.SubElement(run, q("t"))
    set_text_node(text_node, text)
    paragraph.append(run)
    end = ET.Element(q("bookmarkEnd"))
    end.set(q("id"), bookmark_id)
    paragraph.append(end)
    strip_duplicate_para_ids(paragraph)
    return paragraph


def register_document_namespaces(xml_bytes: bytes) -> None:
    for _, (prefix, uri) in ET.iterparse(__import__("io").BytesIO(xml_bytes), events=("start-ns",)):
        if prefix != "xml":
            try:
                ET.register_namespace(prefix, uri)
            except ValueError:
                pass


def parse_document(xml_bytes: bytes) -> ET.Element:
    register_document_namespaces(xml_bytes)
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True))
    return ET.fromstring(xml_bytes, parser=parser)


def serialize_document(root: ET.Element, original_xml: bytes) -> bytes:
    result = ET.tostring(root, encoding="utf-8", xml_declaration=False, short_empty_elements=True)
    match = re.match(rb"\s*<\?xml[^?]*\?>", original_xml)
    if match:
        result = match.group(0) + result
    return result


def bookmark_pairs(root: ET.Element) -> list[tuple[str, str]]:
    starts = root.findall(".//w:bookmarkStart", NS)
    ends = root.findall(".//w:bookmarkEnd", NS)
    start_ids = [item.get(q("id"), "") for item in starts]
    end_ids = [item.get(q("id"), "") for item in ends]
    if len(starts) != len(ends) or sorted(start_ids) != sorted(end_ids):
        raise ValueError("bookmark starts and ends are not paired by id")
    ids = [item.get(q("id"), "") for item in starts]
    names = [item.get(q("name"), "") for item in starts]
    if len(ids) != len(set(ids)) or len(names) != len(set(names)):
        raise ValueError("bookmark ids or names are not unique")
    return [(item.get(q("id"), ""), item.get(q("name"), "")) for item in starts]


def hyperlink_anchors(root: ET.Element) -> list[str]:
    links = root.findall(".//w:hyperlink", NS)
    anchors: list[str] = []
    for link in links:
        anchor = link.get(q("anchor"))
        if not anchor:
            raise ValueError("found an internal hyperlink without w:anchor")
        if link.get(R + "id") is not None:
            raise ValueError("found a hyperlink relationship id in the internal-only navigation")
        anchors.append(anchor)
    return anchors


def paragraph_texts(element: ET.Element) -> list[str]:
    if element.tag == q("p"):
        return [visible_text(element)]
    return [visible_text(p) for p in element.findall(".//w:p", NS)]


def paragraphs_in(element: ET.Element) -> list[ET.Element]:
    if element.tag == q("p"):
        return [element]
    return element.findall(".//w:p", NS)


def transform_document(document_xml: bytes, plan: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    root = parse_document(document_xml)
    body = root.find(".//w:body", NS)
    if body is None:
        raise ValueError("word/document.xml has no w:body")
    original_children = list(body)
    if len(original_children) != 2669:
        raise ValueError(f"source w:body child count is {len(original_children)}, expected 2669")
    if original_children[-1].tag != q("sectPr"):
        raise ValueError("final w:sectPr is not the last body child")

    original_child_bytes = [ET.tostring(item, encoding="utf-8") for item in original_children]
    original_child_paragraph_texts = [paragraph_texts(item) for item in original_children]
    original_paragraph_count = len(root.findall(".//w:body//w:p", NS))
    original_bookmarks = bookmark_pairs(root)
    original_links = hyperlink_anchors(root)
    original_tables = root.findall(".//w:body//w:tbl", NS)
    original_body7_links = original_children[7].findall("./w:hyperlink", NS)
    if len(original_bookmarks) != 553:
        raise ValueError(f"source bookmark count is {len(original_bookmarks)}, expected 553")
    if len(original_links) != 113 or len(original_body7_links) != 33:
        raise ValueError(f"source hyperlinks are full={len(original_links)}, BODY[7]={len(original_body7_links)}; expected 113 and 33")
    if len(original_tables) != 194:
        raise ValueError(f"source table count is {len(original_tables)}, expected 194")

    for operation in plan["operations"]:
        action = operation["action"]
        if action == "insert_contract_section_and_gate_table":
            index = int(operation["locator"]["after_body_index"])
            anchor = original_children[index]
            anchor_text = visible_text(anchor)
            if anchor_text != operation["anchor_visible_text"]:
                raise ValueError("contract section anchor visible text mismatch")
            if sha256_bytes(anchor_text.encode("utf-8")) != operation["anchor_text_sha256"]:
                raise ValueError("contract section anchor SHA-256 mismatch")
            if anchor.tag != q("tbl") or int(operation["following_body_index"]) != index + 1:
                raise ValueError("contract section anchor or following index changed")
        elif action in {"replace_paragraph_text", "replace_cell_paragraph_text", "replace_exact_fragment", "insert_after_anchor", "append_internal_navigation_link"}:
            paragraph = target_paragraph(original_children, operation["locator"])
            verify_exact_source(paragraph, operation)
        else:
            raise ValueError(f"unsupported plan action {action}")

    plan_section = next(op for op in plan["operations"] if op["action"] == "insert_contract_section_and_gate_table")
    table_template = original_children[100]
    if table_template.tag != q("tbl"):
        raise ValueError("BODY[100] is not the 8x3 table formatting template")
    heading_template = original_children[103]
    intro_template = original_children[105]
    if heading_template.tag != q("p") or p_style_value(heading_template) != "Heading2":
        raise ValueError("BODY[103] is not a Heading2 formatting template")
    if intro_template.tag != q("p"):
        raise ValueError("BODY[105] is not a paragraph formatting template")
    table = create_table_from_template(table_template, plan_section["table"])

    existing_ids = [int(item[0]) for item in original_bookmarks]
    bookmark_id = str(max(existing_ids) + 1 if existing_ids else 1)
    bookmark_name = plan_section["bookmark"]["name"]
    if any(name == bookmark_name for _, name in original_bookmarks):
        raise ValueError("new bookmark name already exists")

    changes: list[dict[str, Any]] = []
    allowed_text_body_indices: set[int] = set()
    expected_target_texts: dict[tuple[int, int], str] = {}

    # Apply text edits against the original body node identities before any insertions.
    for operation in plan["operations"]:
        action = operation["action"]
        if action not in {"replace_paragraph_text", "replace_cell_paragraph_text", "replace_exact_fragment"}:
            continue
        locator = operation["locator"]
        body_index = int(locator["body_index"])
        paragraph = target_paragraph(original_children, locator)
        old_text = verify_exact_source(paragraph, operation)
        before_shape = paragraph_shape(paragraph)
        if action == "replace_exact_fragment":
            replace_fragment(paragraph, operation["expected_fragment"], operation["replacement_fragment"])
        else:
            set_all_visible_text(paragraph, operation["replacement_text"])
        new_text = visible_text(paragraph)
        allowed_text_body_indices.add(body_index)
        p_ordinal = paragraphs_in(original_children[body_index]).index(paragraph)
        expected_target_texts[(body_index, p_ordinal)] = new_text
        if paragraph_shape(paragraph) != before_shape:
            raise ValueError(f"text edit changed paragraph structure for {operation.get('section')}")
        changes.append({
            "action": action,
            "section": operation.get("section"),
            "locator": locator,
            "source_text_sha256": operation["original_text_sha256"],
            "source_text": old_text,
            "result_text": new_text,
        })

    # Insert new revision-note paragraphs using only nearby pPr/rPr formatting.
    for operation in plan["operations"]:
        if operation["action"] != "insert_after_anchor":
            continue
        index = int(operation["locator"]["body_index"])
        anchor = original_children[index]
        if anchor.tag != q("p"):
            raise ValueError("revision note anchor is not a paragraph")
        paragraphs = operation["inserted_content"]["paragraphs"]
        templates = [anchor] if index == 6 else [original_children[465]]
        if index not in {6, 466}:
            raise ValueError(f"unexpected insert_after_anchor location BODY[{index}]")
        for text_index, text in enumerate(paragraphs):
            template = templates[min(text_index, len(templates) - 1)]
            added = clone_plain_paragraph(template, text)
            strip_duplicate_para_ids(added)
            body.insert(list(body).index(anchor) + 1 + text_index, added)
            changes.append({
                "action": "insert_paragraph",
                "section": operation.get("section"),
                "after_body_index": index,
                "result_text": text,
            })

    # Insert the heading, explanatory paragraph, and MC01-MC07 table after the pinned anchor table.
    anchor = original_children[int(plan_section["locator"]["after_body_index"])]
    following = original_children[int(plan_section["following_body_index"])]
    heading = create_contract_heading(heading_template, plan_section["heading"], bookmark_name, bookmark_id)
    intro = clone_plain_paragraph(intro_template, plan_section["intro"])
    strip_duplicate_para_ids(intro)
    insert_at = list(body).index(anchor) + 1
    body.insert(insert_at, heading)
    body.insert(insert_at + 1, intro)
    body.insert(insert_at + 2, table)
    if list(body).index(following) != insert_at + 3:
        raise ValueError("new contract section was not placed immediately before original BODY[107]")
    changes.extend([
        {"action": "insert_heading", "section": plan_section.get("section"), "result_text": plan_section["heading"], "bookmark": {"id": bookmark_id, "name": bookmark_name}},
        {"action": "insert_paragraph", "section": plan_section.get("section"), "result_text": plan_section["intro"]},
        {"action": "insert_table", "section": plan_section.get("section"), "rows": len(plan_section["table"]["rows"]) + 1, "columns": len(plan_section["table"]["columns"])},
    ])

    # Add one internal bookmark link without altering the original 33 navigation links.
    nav_operation = next(op for op in plan["operations"] if op["action"] == "append_internal_navigation_link")
    nav_paragraph = original_children[int(nav_operation["locator"]["body_index"])]
    before_nav_children = [ET.tostring(item, encoding="utf-8") for item in list(nav_paragraph)]
    applied_separator = build_internal_link(
        nav_paragraph,
        nav_operation["link_text"],
        nav_operation["bookmark_anchor"],
        nav_operation["separator_text"],
        "RW147_10_3",
    )
    if [ET.tostring(item, encoding="utf-8") for item in list(nav_paragraph)[:len(before_nav_children)]] != before_nav_children:
        raise ValueError("an existing BODY[7] navigation child changed")
    changes.append({
        "action": "append_internal_navigation_link",
        "section": nav_operation.get("section"),
        "link_text": nav_operation["link_text"],
        "bookmark_anchor": nav_operation["bookmark_anchor"],
        "plan_separator_text": nav_operation["separator_text"],
        "applied_source_separator_text": applied_separator,
        "original_body7_link_count": len(original_body7_links),
        "new_body7_link_count": len(nav_paragraph.findall("./w:hyperlink", NS)),
    })

    if body[-1].tag != q("sectPr"):
        raise ValueError("final w:sectPr moved from the end of the document body")
    if len(body) != len(original_children) + 6:
        raise ValueError(f"body child count after insertion is {len(body)}, expected {len(original_children) + 6}")
    if len(root.findall(".//w:body//w:tbl", NS)) != 195:
        raise ValueError("final table count is not 195")

    new_bookmarks = bookmark_pairs(root)
    if len(new_bookmarks) != 554 or (bookmark_id, bookmark_name) not in new_bookmarks:
        raise ValueError("final bookmark count or new bookmark pair is invalid")
    final_links = hyperlink_anchors(root)
    body7_links = original_children[7].findall("./w:hyperlink", NS)
    if len(final_links) != 114 or len(body7_links) != 34:
        raise ValueError(f"final hyperlinks are full={len(final_links)}, BODY[7]={len(body7_links)}; expected 114 and 34")
    bookmark_names = {name for _, name in new_bookmarks}
    unreachable = sorted({anchor_name for anchor_name in final_links if anchor_name not in bookmark_names})
    if unreachable:
        raise ValueError(f"unreachable internal hyperlink anchors: {unreachable[:10]}")
    if final_links != original_links[:len(original_body7_links)] + [bookmark_name] + original_links[len(original_body7_links):]:
        raise ValueError("preexisting internal hyperlinks changed or were reordered")
    if final_links[len(original_body7_links)] != bookmark_name:
        raise ValueError("the appended navigation link does not target the new section")

    # Verify that every original body node is unchanged except the declared text nodes/nav paragraph.
    modified_text_paragraphs: dict[int, set[int]] = {}
    for body_index, paragraph_ordinal in expected_target_texts:
        modified_text_paragraphs.setdefault(body_index, set()).add(paragraph_ordinal)
    added_by_index: dict[int, ET.Element] = {}
    for original_index, original_item in enumerate(original_children):
        if original_index == 7:
            continue
        current = original_item
        if original_index not in allowed_text_body_indices:
            if ET.tostring(current, encoding="utf-8") != original_child_bytes[original_index]:
                raise ValueError(f"unexpected non-text modification to original BODY[{original_index}]")
            continue
        before_paragraphs = original_child_paragraph_texts[original_index]
        after_paragraphs = paragraph_texts(current)
        if len(before_paragraphs) != len(after_paragraphs):
            raise ValueError(f"paragraph count changed inside original BODY[{original_index}]")
        target_ordinals = modified_text_paragraphs.get(original_index, set())
        for paragraph_ordinal, (before_text, after_text) in enumerate(zip(before_paragraphs, after_paragraphs)):
            expected = expected_target_texts.get((original_index, paragraph_ordinal), before_text)
            if after_text != expected:
                raise ValueError(f"unexpected text change in BODY[{original_index}] paragraph {paragraph_ordinal}")
        if not target_ordinals:
            raise ValueError(f"BODY[{original_index}] marked as text-edit target without target paragraph")

    # All non-target original body nodes and all original hyperlink/bookmark nodes remain intact.
    new_xml = serialize_document(root, document_xml)
    stats = {
        "source_document_xml_sha256": sha256_bytes(document_xml),
        "result_document_xml_sha256": sha256_bytes(new_xml),
        "source_body_direct_children": len(original_children),
        "result_body_direct_children": len(body),
        "source_paragraphs_all_descendants": original_paragraph_count,
        "result_paragraphs_all_descendants": len(root.findall(".//w:body//w:p", NS)),
        "source_tables": len(original_tables),
        "result_tables": len(root.findall(".//w:body//w:tbl", NS)),
        "source_bookmarks": len(original_bookmarks),
        "result_bookmarks": len(new_bookmarks),
        "source_internal_hyperlinks": len(original_links),
        "result_internal_hyperlinks": len(final_links),
        "source_body7_internal_hyperlinks": len(original_body7_links),
        "result_body7_internal_hyperlinks": len(body7_links),
        "all_internal_anchor_targets_reachable": True,
        "existing_internal_links_preserved_in_order": True,
        "new_bookmark_id": bookmark_id,
        "new_bookmark_name": bookmark_name,
        "final_sectPr_is_last_body_child": body[-1].tag == q("sectPr"),
        "changed_text_records": changes,
    }
    return new_xml, stats


def validate_plan_and_source(args: argparse.Namespace) -> tuple[dict[str, Any], bytes, dict[str, bytes], dict[str, Any]]:
    plan_path = Path(args.plan)
    plan_md_path = Path(args.plan_md)
    source_path = Path(args.source)
    protected_path = Path(args.protected_source)
    output_path = Path(args.output)
    if sha256_file(plan_path) != args.expected_plan_sha256:
        raise ValueError("patch_plan.json does not match the pinned SHA-256")
    if sha256_file(plan_md_path) != args.expected_plan_md_sha256:
        raise ValueError("patch_plan.md does not match the pinned SHA-256")
    if sha256_file(source_path) != args.expected_source_sha256:
        raise ValueError("source master DOCX does not match the pinned SHA-256")
    if sha256_file(protected_path) != args.expected_protected_sha256:
        raise ValueError("protected original DOCX does not match the pinned SHA-256")
    if output_path.exists() and not args.preflight_only:
        raise FileExistsError(f"refusing to overwrite existing output: {output_path}")
    if plan_path.stat().st_size != 76958 or plan_md_path.stat().st_size != 48099:
        raise ValueError("pinned patch plan byte lengths changed")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan.get("operation_count") != 42 or len(plan.get("operations", [])) != 42:
        raise ValueError("pinned patch plan operation count is not 42")
    if Path(plan.get("source_docx", {}).get("path", "")).name != source_path.name:
        raise ValueError("patch plan source basename does not match source input")
    if plan.get("source_docx", {}).get("sha256") != args.expected_source_sha256:
        raise ValueError("patch plan source SHA does not match expected source")
    if plan.get("source_docx", {}).get("bytes") != 786150 or source_path.stat().st_size != 786150:
        raise ValueError("source master DOCX byte length differs from the pinned baseline")
    if Path(plan.get("output_docx", "")).name != output_path.name:
        raise ValueError("output basename does not match the pinned patch plan")
    with zipfile.ZipFile(source_path, "r") as source_zip:
        names = source_zip.namelist()
        if len(names) != 23 or len(names) != len(set(names)):
            raise ValueError("source DOCX part inventory differs from 23 unique parts")
        parts = {name: source_zip.read(name) for name in names}
    document_xml = parts.get("word/document.xml")
    if document_xml is None:
        raise ValueError("source DOCX has no word/document.xml")
    result_xml, stats = transform_document(document_xml, plan)
    stats.update({
        "source_docx_sha256": args.expected_source_sha256,
        "source_docx_bytes": source_path.stat().st_size,
        "protected_original_docx_sha256": args.expected_protected_sha256,
        "patch_plan_sha256": args.expected_plan_sha256,
        "patch_plan_bytes": plan_path.stat().st_size,
        "patch_plan_md_sha256": args.expected_plan_md_sha256,
        "patch_plan_md_bytes": plan_md_path.stat().st_size,
        "operation_count": len(plan["operations"]),
        "non_document_xml_parts_raw_bytes_preserved_expected": len(parts) - 1,
        "output_docx_path": str(output_path),
    })
    return plan, result_xml, parts, stats


def write_docx(source_path: Path, output_path: Path, result_xml: bytes, source_parts: dict[str, bytes]) -> dict[str, Any]:
    scratch_dir = TMP_DIR / "render_scratch"
    temporary_path = scratch_dir / "RelicWeave_V1.48_ContractAligned.building.docx"
    if temporary_path.exists():
        raise FileExistsError(f"refusing to overwrite existing build scratch file: {temporary_path}")
    scratch_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(source_path, "r") as source_zip, zipfile.ZipFile(temporary_path, "w", allowZip64=True) as output_zip:
        output_zip.comment = source_zip.comment
        for info in source_zip.infolist():
            name = info.filename
            payload = result_xml if name == "word/document.xml" else source_parts[name]
            output_zip.writestr(copy.copy(info), payload)

    with zipfile.ZipFile(temporary_path, "r") as check_zip:
        if check_zip.namelist() != list(source_parts.keys()):
            raise ValueError("output DOCX zip part order/inventory changed")
        changed = []
        for name in check_zip.namelist():
            data = check_zip.read(name)
            if name == "word/document.xml":
                if data != result_xml:
                    raise ValueError("output document.xml bytes differ from requested patch")
                changed.append(name)
            elif data != source_parts[name]:
                raise ValueError(f"non-document XML part changed: {name}")
        if changed != ["word/document.xml"]:
            raise ValueError(f"unexpected changed DOCX parts: {changed}")

    if sha256_file(source_path) != EXPECTED_SOURCE_SHA256:
        raise ValueError("source master DOCX changed during authoring")
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite existing output: {output_path}")
    temporary_path.replace(output_path)
    return {
        "output_docx_sha256": sha256_file(output_path),
        "output_docx_bytes": output_path.stat().st_size,
        "changed_zip_parts": ["word/document.xml"],
        "unchanged_zip_parts_raw_bytes": len(source_parts) - 1,
    }


ROOT_APPROVED_RUNNING_EDITION_SOURCE_SHA256 = "de59dba1e6766fd9dda91ee5b6e8054adb11b971a8309eb5056571a85e2e9f04"
ROOT_APPROVED_RUNNING_EDITION_PART_TEXT = {
    "word/header2.xml": (
        "RelicWeave  V1.47  完整项目方案",
        "RelicWeave  V1.48  完整项目方案",
    ),
    "word/footer2.xml": (
        "2026年10月7日    ",
        "2026年10月9日    ",
    ),
    "word/footer3.xml": (
        "RelicWeave V1.41  ",
        "RelicWeave V1.48  ",
    ),
}


def replace_single_wt_text(part_name: str, part_data: bytes, old_text: str, new_text: str) -> bytes:
    old_bytes = old_text.encode("utf-8")
    new_bytes = new_text.encode("utf-8")
    pattern = re.compile(rb"(<w:t\b[^>]*>)" + re.escape(old_bytes) + rb"(</w:t>)")
    matches = list(pattern.finditer(part_data))
    if len(matches) != 1:
        raise ValueError(f"{part_name} expected one exact w:t text node, found {len(matches)}")
    return pattern.sub(lambda match: match.group(1) + new_bytes + match.group(2), part_data, count=1)


def apply_root_approved_running_edition(input_path: Path, output_path: Path) -> dict[str, Any]:
    input_path = input_path.resolve()
    output_path = output_path.resolve()
    if input_path.parent != TMP_DIR.resolve() or input_path.name != "v148_before_running_edition_de59dba1.docx":
        raise ValueError("running-edition patch requires the pinned, preserved pre-patch candidate in the task directory")
    if output_path != DEFAULT_OUTPUT.resolve():
        raise ValueError("running-edition patch is limited to the authorized V1.48 final output path")
    if sha256_file(input_path) != ROOT_APPROVED_RUNNING_EDITION_SOURCE_SHA256:
        raise ValueError("pre-patch candidate does not match the Root-approved SHA-256")
    if not output_path.exists() or sha256_file(output_path) != ROOT_APPROVED_RUNNING_EDITION_SOURCE_SHA256:
        raise ValueError("current final output is not the approved pre-patch candidate")

    with zipfile.ZipFile(input_path, "r") as input_zip:
        names = input_zip.namelist()
        if len(names) != 23 or len(names) != len(set(names)):
            raise ValueError("pre-patch candidate part inventory differs from 23 unique parts")
        source_parts = {name: input_zip.read(name) for name in names}
        replacement_parts = dict(source_parts)
        for part_name, (old_text, new_text) in ROOT_APPROVED_RUNNING_EDITION_PART_TEXT.items():
            if part_name not in replacement_parts:
                raise ValueError(f"pre-patch candidate is missing {part_name}")
            replacement_parts[part_name] = replace_single_wt_text(
                part_name, replacement_parts[part_name], old_text, new_text
            )

        scratch_dir = TMP_DIR / "render_scratch"
        temporary_path = scratch_dir / "RelicWeave_V1.48_ContractAligned.edition-patch.tmp.docx"
        if temporary_path.exists():
            raise FileExistsError(f"refusing to overwrite running-edition scratch file: {temporary_path}")
        scratch_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(temporary_path, "w", allowZip64=True) as output_zip:
            output_zip.comment = input_zip.comment
            for info in input_zip.infolist():
                output_zip.writestr(copy.copy(info), replacement_parts[info.filename])

    with zipfile.ZipFile(temporary_path, "r") as check_zip:
        if check_zip.namelist() != names:
            raise ValueError("running-edition patch changed ZIP part order or inventory")
        changed = [
            name for name in names
            if check_zip.read(name) != source_parts[name]
        ]
        expected_changed = ["word/header2.xml", "word/footer2.xml", "word/footer3.xml"]
        if changed != expected_changed:
            raise ValueError(f"running-edition patch changed unexpected DOCX parts: {changed}")
        for name in names:
            if name not in expected_changed and check_zip.read(name) != source_parts[name]:
                raise ValueError(f"running-edition patch changed protected part bytes: {name}")
    if output_path.exists() and sha256_file(output_path) != ROOT_APPROVED_RUNNING_EDITION_SOURCE_SHA256:
        raise ValueError("final output changed while applying the authorized running-edition patch")
    os.replace(temporary_path, output_path)
    return {
        "output_docx_sha256": sha256_file(output_path),
        "output_docx_bytes": output_path.stat().st_size,
        "changed_zip_parts": ["word/header2.xml", "word/footer2.xml", "word/footer3.xml"],
        "unchanged_zip_parts": len(names) - 3,
        "document_xml_sha256": hashlib.sha256(replacement_parts["word/document.xml"]).hexdigest(),
    }


ROOT_APPROVED_LAYOUT_SOURCE_SHA256 = "e22e15c52aff6b4590a5fba298d13516c27b37b944d3b3e779d82124b1ffc1f2"
ROOT_APPROVED_FAILED_LAYOUT_OUTPUT_SHA256 = "164b65c96aa7701a0ad6036fc25c6402dc8bf86c8581c35d258c42eb17fc5a2d"
ROOT_APPROVED_FAILED_LAYOUT_DELTA_JSON_SHA256 = "2ff9ffa8f3bbc356aa86bb2d5e3c13bed0b1aea46ffee85ae017487253ae2309"
ROOT_APPROVED_FAILED_LAYOUT_DELTA_MD_SHA256 = "0edae996557c1081b7885df65d9e078f85d2fbec451bafc7ec4003a230dbf46b"
ROOT_APPROVED_TABLE_LAYOUTS = {
    "evidence_channel_metric_table": {
        "markers": ("pat_inter", "thick_rmse_rel"),
        "raw_disambiguator": "Top-200",
        "headers": ("证据通道", "GT vs 非GT", "AUC", "Top-200精确率", "实测判断"),
        "target_widths_twips": (2100, 2299, 1500, 1794, 2299),
    },
    "3d_feature_metric_table": {
        "markers": ("thick_trigram_inter", "curv_K_inter"),
        "raw_disambiguator": "P@200",
        "headers": ("3D证据", "AUC", "P@200", "裁定", "大白话"),
        "target_widths_twips": (2300, 1548, 1547, 2298, 2299),
    },
}


def _table_layout_targets(document_xml: bytes) -> tuple[bytes, list[dict[str, Any]]]:
    root = ET.fromstring(document_xml)
    body = root.find(".//w:body", NS)
    if body is None:
        raise ValueError("layout source has no w:body")
    document_tables = [node for node in root.iter() if node.tag == q("tbl")]
    found: list[dict[str, Any]] = []
    for body_index, top in enumerate(list(body)):
        candidates = [top] if top.tag == q("tbl") else [node for node in top.iter() if node.tag == q("tbl")]
        for table in candidates:
            rows = table.findall("./w:tr", NS)
            cells_by_row = [row.findall("./w:tc", NS) for row in rows]
            cells = [cell for row_cells in cells_by_row for cell in row_cells]
            cell_texts = [visible_text(cell) for cell in cells]
            joined_text = "|".join(cell_texts)
            headers = tuple(visible_text(cell) for cell in (cells_by_row[0] if cells_by_row else []))
            for key, spec in ROOT_APPROVED_TABLE_LAYOUTS.items():
                if all(marker in joined_text for marker in spec["markers"]) and headers == spec["headers"]:
                    tbl_pr = table.find("./w:tblPr", NS)
                    tbl_w = tbl_pr.find("./w:tblW", NS) if tbl_pr is not None else None
                    layout = tbl_pr.find("./w:tblLayout", NS) if tbl_pr is not None else None
                    grid = table.find("./w:tblGrid", NS)
                    grid_columns = grid.findall("./w:gridCol", NS) if grid is not None else []
                    grid_widths = [int(column.get(q("w"), "0")) for column in grid_columns]
                    tc_widths = []
                    for row_cells in cells_by_row:
                        row_widths = []
                        for cell in row_cells:
                            if cell.find("./w:tcPr/w:gridSpan", NS) is not None:
                                raise ValueError(f"{key} has a gridSpan; refusing a column-width edit")
                            tc_w = cell.find("./w:tcPr/w:tcW", NS)
                            if tc_w is None:
                                raise ValueError(f"{key} has a cell without tcW")
                            row_widths.append(int(tc_w.get(q("w"), "0")))
                        tc_widths.append(row_widths)
                    if len(grid_widths) != 5 or len(rows) == 0 or any(len(row) != 5 for row in cells_by_row):
                        raise ValueError(f"{key} is not the expected five-column table")
                    if any(tuple(row) != tuple(grid_widths) for row in tc_widths):
                        raise ValueError(f"{key} cell widths do not match its table grid")
                    if tbl_w is None or tbl_w.get(q("type")) != "dxa" or int(tbl_w.get(q("w"), "0")) != 9994:
                        raise ValueError(f"{key} table width differs from the approved 9994-twip width")
                    if layout is None or layout.get(q("type")) != "fixed":
                        raise ValueError(f"{key} does not use the expected fixed table layout")
                    if sum(grid_widths) != 9992 or sum(spec["target_widths_twips"]) != 9992:
                        raise ValueError(f"{key} grid total would change")
                    all_text = "".join(text.text or "" for text in table.iter() if text.tag == q("t"))
                    text_hash = hashlib.sha256(all_text.encode("utf-8")).hexdigest()
                    row_heights = [
                        [(height.get(q("val")), height.get(q("hRule"))) for height in row.findall("./w:trPr/w:trHeight", NS)]
                        for row in rows
                    ]
                    found.append({
                        "key": key,
                        "body_index": body_index,
                        "table_index_1based": document_tables.index(table) + 1,
                        "table": table,
                        "markers": list(spec["markers"]),
                        "raw_markers": [*spec["markers"], spec["raw_disambiguator"]],
                        "headers": list(headers),
                        "row_count": len(rows),
                        "column_count": len(grid_widths),
                        "table_width_twips": int(tbl_w.get(q("w"))),
                        "layout_type": layout.get(q("type")),
                        "grid_widths_twips": grid_widths,
                        "tc_widths_by_row_twips": tc_widths,
                        "target_widths_twips": list(spec["target_widths_twips"]),
                        "grid_total_twips": sum(grid_widths),
                        "text_sha256": text_hash,
                        "row_heights": row_heights,
                    })
    if len(found) != len(ROOT_APPROVED_TABLE_LAYOUTS) or {item["key"] for item in found} != set(ROOT_APPROVED_TABLE_LAYOUTS):
        raise ValueError("the two uniquely pinned metric tables were not both found")
    return document_xml, found


def _raw_table_spans(document_xml: bytes) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    depth = 0
    start = -1
    for match in re.finditer(rb"</?w:tbl\b[^>]*>", document_xml):
        tag = match.group(0)
        if tag.startswith(b"</"):
            depth -= 1
            if depth < 0:
                raise ValueError("unbalanced table close tag in document.xml")
            if depth == 0:
                spans.append((start, match.end()))
                start = -1
        elif not tag.endswith(b"/>"):
            if depth == 0:
                start = match.start()
            depth += 1
    if depth != 0 or start != -1:
        raise ValueError("unbalanced table tags in document.xml")
    return spans


def _patch_width_on_tag(tag: bytes, old_width: int, new_width: int, table_key: str) -> bytes:
    pattern = re.compile(rb'(w:w=")(\d+)(")')
    matches = list(pattern.finditer(tag))
    if len(matches) != 1 or int(matches[0].group(2)) != old_width:
        raise ValueError(f"{table_key} encountered an unexpected width tag")
    return pattern.sub(lambda match: match.group(1) + str(new_width).encode("ascii") + match.group(3), tag, count=1)


def _patch_tag_sequence(block: bytes, tag_name: bytes, old_widths: list[int], new_widths: list[int], table_key: str) -> tuple[bytes, int]:
    pattern = re.compile(rb"<" + tag_name + rb"\b[^>]*/?>")
    matches = list(pattern.finditer(block))
    if len(matches) != len(old_widths) or len(old_widths) != len(new_widths):
        raise ValueError(f"{table_key} {tag_name.decode('ascii')} count differs from the pinned shape")
    pieces: list[bytes] = []
    cursor = 0
    for index, match in enumerate(matches):
        pieces.append(block[cursor:match.start()])
        pieces.append(_patch_width_on_tag(match.group(0), old_widths[index], new_widths[index], table_key))
        cursor = match.end()
    pieces.append(block[cursor:])
    return b"".join(pieces), len(matches)


def _apply_one_table_widths(segment: bytes, record: dict[str, Any]) -> tuple[bytes, int, int]:
    key = record["key"]
    old_widths = record["grid_widths_twips"]
    new_widths = record["target_widths_twips"]
    grid_match = re.search(rb"<w:tblGrid\b[^>]*>.*?</w:tblGrid>", segment, flags=re.DOTALL)
    if grid_match is None:
        raise ValueError(f"{key} has no raw w:tblGrid block")
    new_grid, grid_count = _patch_tag_sequence(grid_match.group(0), b"w:gridCol", old_widths, new_widths, key)
    segment = segment[:grid_match.start()] + new_grid + segment[grid_match.end():]
    return segment, grid_count, 0


def _mask_target_table_grid_values(document_xml: bytes, target_markers: list[list[str]]) -> bytes:
    spans = _raw_table_spans(document_xml)
    masked = document_xml
    targets: list[tuple[int, int]] = []
    for markers in target_markers:
        matches = [(start, end) for start, end in spans if all(marker.encode("utf-8") in document_xml[start:end] for marker in markers)]
        if len(matches) != 1:
            raise ValueError("could not uniquely mask an approved target table")
        targets.append(matches[0])
    for start, end in sorted(targets, reverse=True):
        segment = masked[start:end]
        segment = re.sub(rb'(<w:gridCol\b[^>]*?\bw:w=")\d+(")', rb'\1#\2', segment)
        masked = masked[:start] + segment + masked[end:]
    return masked


def transform_approved_table_widths(document_xml: bytes) -> tuple[bytes, dict[str, Any]]:
    _, records = _table_layout_targets(document_xml)
    spans = _raw_table_spans(document_xml)
    result = document_xml
    updated_records: list[dict[str, Any]] = []
    targets: list[tuple[int, int, dict[str, Any]]] = []
    for record in records:
        markers = [marker.encode("utf-8") for marker in record["raw_markers"]]
        matched_spans = [(start, end) for start, end in spans if all(marker in document_xml[start:end] for marker in markers)]
        if len(matched_spans) != 1:
            raise ValueError(f"{record['key']} raw OOXML table span is not unique")
        targets.append((matched_spans[0][0], matched_spans[0][1], record))
    for start, end, record in sorted(targets, key=lambda item: item[0], reverse=True):
        original_segment = result[start:end]
        patched_segment, grid_count, cell_count = _apply_one_table_widths(original_segment, record)
        result = result[:start] + patched_segment + result[end:]
        updated = {key: value for key, value in record.items() if key != "table"}
        updated["grid_columns_updated"] = grid_count
        updated["cell_widths_updated"] = cell_count
        updated["tc_widths_preserved"] = True
        updated["new_grid_total_twips"] = sum(record["target_widths_twips"])
        updated_records.append(updated)
    updated_records.sort(key=lambda item: item["body_index"])

    before_root = ET.fromstring(document_xml)
    after_root = ET.fromstring(result)
    before_text = [node.text or "" for node in before_root.iter() if node.tag == q("t")]
    after_text = [node.text or "" for node in after_root.iter() if node.tag == q("t")]
    if before_text != after_text:
        raise ValueError("table width patch changed visible document text")
    marker_groups = [record["raw_markers"] for record in records]
    if _mask_target_table_grid_values(document_xml, marker_groups) != _mask_target_table_grid_values(result, marker_groups):
        raise ValueError("document.xml changed outside the two target tblGrid/gridCol width values")
    before_body = before_root.find(".//w:body", NS)
    after_body = after_root.find(".//w:body", NS)
    if before_body is None or after_body is None or [node.tag for node in before_body] != [node.tag for node in after_body]:
        raise ValueError("table width patch changed body structure")
    before_bookmarks = [(node.get(q("id")), node.get(q("name"))) for node in before_root.iter() if node.tag == q("bookmarkStart")]
    after_bookmarks = [(node.get(q("id")), node.get(q("name"))) for node in after_root.iter() if node.tag == q("bookmarkStart")]
    before_links = [(node.get(q("anchor")), node.get(q("id"))) for node in before_root.iter() if node.tag == q("hyperlink")]
    after_links = [(node.get(q("anchor")), node.get(q("id"))) for node in after_root.iter() if node.tag == q("hyperlink")]
    if before_bookmarks != after_bookmarks or before_links != after_links:
        raise ValueError("table width patch changed bookmarks or hyperlinks")
    if result == document_xml:
        raise ValueError("table width patch produced no changes")
    return result, {
        "status": "PREFLIGHT_PASS",
        "input_document_xml_sha256": hashlib.sha256(document_xml).hexdigest(),
        "output_document_xml_sha256": hashlib.sha256(result).hexdigest(),
        "visible_text_identical": True,
        "body_child_tags_identical": True,
        "bookmark_and_hyperlink_sequences_identical": True,
        "only_target_tblGrid_gridCol_values_changed": True,
        "all_tcPr_tcW_widths_preserved": True,
        "row_heights_added": 0,
        "tables": updated_records,
    }


def apply_root_approved_table_layout_patch(input_path: Path, output_path: Path, preflight_only: bool = False) -> dict[str, Any]:
    input_path = input_path.resolve()
    output_path = output_path.resolve()
    expected_input = (TMP_DIR / "prefinal_layout_snapshot" / "RelicWeave_V1.48_ContractAligned.docx").resolve()
    if input_path != expected_input:
        raise ValueError("table-width patch requires the exact pre-layout candidate in prefinal_layout_snapshot")
    if output_path != DEFAULT_OUTPUT.resolve():
        raise ValueError("table-width patch is limited to the authorized V1.48 final output path")
    if sha256_file(input_path) != ROOT_APPROVED_LAYOUT_SOURCE_SHA256:
        raise ValueError("pre-layout candidate does not match the Root-approved SHA-256")
    if not output_path.exists() or sha256_file(output_path) != ROOT_APPROVED_FAILED_LAYOUT_OUTPUT_SHA256:
        raise ValueError("current final output is not the pinned combined grid+tcW candidate")
    delta_json_path = TMP_DIR / "layout_delta.json"
    delta_md_path = TMP_DIR / "layout_delta.md"
    if not preflight_only:
        if not delta_json_path.exists() or not delta_md_path.exists():
            raise FileNotFoundError("the combined grid+tcW delta reports must be preserved before replacement")
        if sha256_file(delta_json_path) != ROOT_APPROVED_FAILED_LAYOUT_DELTA_JSON_SHA256 or sha256_file(delta_md_path) != ROOT_APPROVED_FAILED_LAYOUT_DELTA_MD_SHA256:
            raise ValueError("existing layout delta reports do not match the archived combined grid+tcW variant")

    with zipfile.ZipFile(input_path, "r") as input_zip:
        names = input_zip.namelist()
        if len(names) != 23 or len(names) != len(set(names)):
            raise ValueError("pre-layout DOCX part inventory differs from 23 unique parts")
        source_parts = {name: input_zip.read(name) for name in names}
        original_xml = source_parts.get("word/document.xml")
        if original_xml is None:
            raise ValueError("pre-layout DOCX has no word/document.xml")
        result_xml, report = transform_approved_table_widths(original_xml)

        if preflight_only:
            return report

        scratch_dir = TMP_DIR / "render_scratch"
        temporary_path = scratch_dir / "RelicWeave_V1.48_ContractAligned.grid-only-layout-patch.tmp.docx"
        if temporary_path.exists():
            raise FileExistsError(f"refusing to overwrite layout-patch scratch file: {temporary_path}")
        scratch_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(temporary_path, "w", allowZip64=True) as output_zip:
            output_zip.comment = input_zip.comment
            for info in input_zip.infolist():
                payload = result_xml if info.filename == "word/document.xml" else source_parts[info.filename]
                output_zip.writestr(copy.copy(info), payload)

    with zipfile.ZipFile(temporary_path, "r") as check_zip:
        if check_zip.namelist() != names:
            raise ValueError("layout patch changed ZIP part order or inventory")
        changed = [name for name in names if check_zip.read(name) != source_parts[name]]
        if changed != ["word/document.xml"]:
            raise ValueError(f"layout patch changed unexpected DOCX parts: {changed}")
        if check_zip.read("word/document.xml") != result_xml:
            raise ValueError("layout patch output document.xml differs from its verified result")
    if sha256_file(input_path) != ROOT_APPROVED_LAYOUT_SOURCE_SHA256:
        raise ValueError("pre-layout candidate changed during layout authoring")
    if sha256_file(output_path) != ROOT_APPROVED_FAILED_LAYOUT_OUTPUT_SHA256:
        raise ValueError("final output changed while applying the authorized grid-only layout patch")
    os.replace(temporary_path, output_path)
    report.update({
        "status": "APPLIED",
        "input_docx_path": str(input_path),
        "input_docx_sha256": sha256_file(input_path),
        "output_docx_path": str(output_path),
        "output_docx_sha256": sha256_file(output_path),
        "output_docx_bytes": output_path.stat().st_size,
        "changed_package_parts": ["word/document.xml"],
        "other_22_package_parts_raw_bytes_preserved": True,
        "supersedes_failed_combined_grid_tcw_candidate_sha256": ROOT_APPROVED_FAILED_LAYOUT_OUTPUT_SHA256,
        "failed_combined_candidate_preserved_at": str((TMP_DIR / "render_scratch" / "layout_variants" / "grid_tcW_both.docx").resolve()),
    })
    delta_json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    table_lines = []
    for table in report["tables"]:
        table_lines.append(
            f"- {table['key']}: body[{table['body_index']}], rows={table['row_count']}, "
            f"table width={table['table_width_twips']} twips (fixed), grid total="
            f"{table['grid_total_twips']} -> {table['new_grid_total_twips']} twips; "
            f"column widths {table['grid_widths_twips']} -> {table['target_widths_twips']} twips."
        )
    md = (
        "# Approved table layout delta\n\n"
        "This limited patch widens only the tblGrid/gridCol first columns in the two Root-identified metric tables. "
        "Every cell tcPr/tcW remains byte-identical to the e22 source. The fixed total table width, grid total, fonts, "
        "row spacing, borders, colors, text, row heights, bookmarks, navigation, headers/footers, metadata, and all "
        "non-target structure remain unchanged. The combined grid+tcW candidate was preserved separately after it "
        "failed bundled LibreOffice export; Root approved this grid-only candidate after visual inspection.\n\n"
        + "\n".join(table_lines)
        + "\n\n"
        + f"Input DOCX SHA-256: {report['input_docx_sha256']}\n\n"
        + f"Output DOCX SHA-256: {report['output_docx_sha256']}\n\n"
        + f"document.xml SHA-256: {report['input_document_xml_sha256']} -> {report['output_document_xml_sha256']}\n\n"
        + "The JSON records exact body/table positions, old/new grid widths, tcW preservation, visible text hash equality, and the changed-part inventory."
    )
    delta_md_path.write_text(md, encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", default=str(DEFAULT_PLAN))
    parser.add_argument("--plan-md", default=str(DEFAULT_PLAN_MD))
    parser.add_argument("--source", default=str(DEFAULT_SOURCE))
    parser.add_argument("--protected-source", default=str(DEFAULT_PROTECTED))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--expected-plan-sha256", default=EXPECTED_PLAN_SHA256)
    parser.add_argument("--expected-plan-md-sha256", default=EXPECTED_PLAN_MD_SHA256)
    parser.add_argument("--expected-source-sha256", default=EXPECTED_SOURCE_SHA256)
    parser.add_argument("--expected-protected-sha256", default=EXPECTED_PROTECTED_SHA256)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--apply-running-edition-from")
    parser.add_argument("--table-layout-preflight-from")
    parser.add_argument("--apply-table-layout-from")
    args = parser.parse_args()

    try:
        if args.table_layout_preflight_from:
            result = apply_root_approved_table_layout_patch(
                Path(args.table_layout_preflight_from), Path(args.output), preflight_only=True
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.apply_table_layout_from:
            result = apply_root_approved_table_layout_patch(
                Path(args.apply_table_layout_from), Path(args.output), preflight_only=False
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.apply_running_edition_from:
            result = apply_root_approved_running_edition(
                Path(args.apply_running_edition_from), Path(args.output)
            )
            print(json.dumps({"running_edition_patch": "PASS", "stats": result}, ensure_ascii=False, indent=2))
            return 0
        plan, result_xml, parts, stats = validate_plan_and_source(args)
        if args.preflight_only:
            print(json.dumps({"preflight": "PASS", "stats": stats}, ensure_ascii=False, indent=2))
            return 0
        output_result = write_docx(Path(args.source), Path(args.output), result_xml, parts)
        stats.update(output_result)
        print(json.dumps({"build": "PASS", "stats": stats}, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"build": "FAIL", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
