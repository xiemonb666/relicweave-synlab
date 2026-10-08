from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from lxml import etree
import hashlib, json

ROOT = Path.cwd()
WORK = ROOT / 'tmp' / 'v147_user_merge_20261007'
SRC = WORK / 'fresh_merge_final_candidate.docx'
OUT = WORK / 'fresh_merge_layout_fix_candidate.docx'
REPORT = WORK / 'fresh_merge_layout_fix_static.json'
MD = WORK / 'fresh_merge_layout_fix_static.md'
EXPECTED = '70aa097680aa1920528ba4b6d9646821ac78b367618c0e9b8dbc36439fa38044'
NS_URI = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
NS = {'w': NS_URI}
W = '{%s}' % NS_URI
P = W + 'p'
XML_PART = 'word/document.xml'

def sha(data):
    return hashlib.sha256(data).hexdigest()

def ptext(node):
    return ''.join(node.xpath('.//w:t/text()', namespaces=NS))

def pstyle(node):
    x = node.find('w:pPr/w:pStyle', NS)
    return x.get(W+'val') if x is not None else ''

def canon(node):
    return etree.tostring(node, method='c14n', exclusive=False, with_comments=True)

if not SRC.exists():
    raise SystemExit(f'Missing source candidate: {SRC}')
src_hash = sha(SRC.read_bytes())
if src_hash != EXPECTED:
    raise SystemExit(f'Source SHA mismatch: {src_hash}')

with ZipFile(SRC, 'r') as zin:
    entries = zin.infolist()
    blobs = {i.filename: zin.read(i.filename) for i in entries}
if XML_PART not in blobs:
    raise SystemExit('Missing word/document.xml')
original_xml = blobs[XML_PART]
parser = etree.XMLParser(remove_blank_text=False, resolve_entities=False)
root = etree.fromstring(original_xml, parser)
body = root.find('w:body', NS)
if body is None:
    raise SystemExit('Missing document body')
children = list(body)

markers = ['OpenCV', 'COLMAP', 'SAM2', 'edmundoptics.com', 'SC3336 B']
sequences = []
for i, e in enumerate(children):
    if e.tag != P or pstyle(e) != 'Heading1' or 'B13' not in ptext(e):
        continue
    block = children[i + 1:i + 1 + len(markers)]
    if len(block) == len(markers) and all(x.tag == P and token in ptext(x) for x, token in zip(block, markers)):
        sequences.append((i, block))
if len(sequences) != 1:
    raise SystemExit(f'Expected one B13 five-reference sequence, got {len(sequences)}')
heading_i, block = sequences[0]
hits = [(heading_i + 1 + j, e, ptext(e)) for j, e in enumerate(block)]
indices = [h[0] for h in hits]
if children[heading_i].tag != P or pstyle(children[heading_i]) != 'Heading1' or 'B13' not in ptext(children[heading_i]):
    raise SystemExit('Expected preceding Heading1 B13 anchor')
for idx, para, txt in hits:
    spacing = para.find('w:pPr/w:spacing', NS)
    if spacing is None or spacing.get(W+'after') != '100':
        raise SystemExit(f'Expected after=100 on reference at body index {idx}')

solver_rows = []
for ti, tbl in enumerate(root.xpath('.//w:tbl', namespaces=NS)):
    for ri, row in enumerate(tbl.xpath('./w:tr', namespaces=NS)):
        if 'Solver-native contact' in ptext(row):
            solver_rows.append((ti, ri, tbl, row))
if len(solver_rows) != 1:
    raise SystemExit(f'Expected one Solver-native contact row, got {len(solver_rows)}')
table_index, row_index, solver_table, solver_row = solver_rows[0]
trpr = solver_row.find('w:trPr', NS)
if trpr is None:
    trpr = etree.Element(W+'trPr')
    solver_row.insert(0, trpr)
elif trpr.find('w:cantSplit', NS) is not None:
    raise SystemExit('Solver row already has cantSplit; no authorized delta needed')
etree.SubElement(trpr, W+'cantSplit')
solver_text = ptext(solver_row)
for _, para, _ in hits:
    para.find('w:pPr/w:spacing', NS).set(W+'after', '20')

blobs[XML_PART] = etree.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)
with ZipFile(OUT, 'w', ZIP_DEFLATED) as zout:
    for info in entries:
        zout.writestr(info, blobs[info.filename])

with ZipFile(OUT, 'r') as zout:
    out_names = zout.namelist()
    out_blobs = {n: zout.read(n) for n in out_names}
if out_names != [i.filename for i in entries]:
    raise SystemExit('Package part names/order changed')
unchanged_parts = [n for n in out_names if n != XML_PART and blobs[n] == out_blobs[n]]
if len(unchanged_parts) != len(out_names) - 1:
    raise SystemExit('At least one non-document package part changed')
after_root = etree.fromstring(out_blobs[XML_PART], parser)
after_body = after_root.find('w:body', NS)
after_children = list(after_body)
after_hits = [(i, after_children[i], ptext(after_children[i])) for i in indices]
for (idx0, _, txt0), (idx1, para, txt1) in zip(hits, after_hits):
    if idx0 != idx1 or txt0 != txt1:
        raise SystemExit('B13 paragraph anchor/text changed')
    spacing = para.find('w:pPr/w:spacing', NS)
    if spacing.get(W+'after') != '20':
        raise SystemExit('B13 spacing change did not land')
out_solver = []
for ti, tbl in enumerate(after_root.xpath('.//w:tbl', namespaces=NS)):
    for ri, row in enumerate(tbl.xpath('./w:tr', namespaces=NS)):
        if 'Solver-native contact' in ptext(row):
            out_solver.append((ti, ri, row))
if len(out_solver) != 1 or out_solver[0][0:2] != (table_index, row_index):
    raise SystemExit('Solver row position/uniqueness changed')
if out_solver[0][2].find('w:trPr/w:cantSplit', NS) is None:
    raise SystemExit('cantSplit is missing')

original_root = etree.fromstring(original_xml, parser)
original_text = original_root.xpath('.//w:t/text()', namespaces=NS)
final_text = after_root.xpath('.//w:t/text()', namespaces=NS)
if original_text != final_text:
    raise SystemExit('w:t sequence changed')
normalized = etree.fromstring(out_blobs[XML_PART], parser)
norm_body = normalized.find('w:body', NS)
norm_children = list(norm_body)
for idx, marker in zip(indices, markers):
    para = norm_children[idx]
    if para.tag != P or marker not in ptext(para):
        raise SystemExit('Could not normalize B13 marker')
    para.find('w:pPr/w:spacing', NS).set(W+'after', '100')
norm_solver = []
for tbl in normalized.xpath('.//w:tbl', namespaces=NS):
    for row in tbl.xpath('./w:tr', namespaces=NS):
        if 'Solver-native contact' in ptext(row):
            norm_solver.append(row)
if len(norm_solver) != 1:
    raise SystemExit('Could not normalize Solver row')
norm_trpr = norm_solver[0].find('w:trPr', NS)
if norm_trpr is None:
    raise SystemExit('Missing normalized trPr')
for c in list(norm_trpr):
    if c.tag == W+'cantSplit':
        norm_trpr.remove(c)
if len(norm_trpr) == 0:
    norm_solver[0].remove(norm_trpr)
if canon(normalized) != canon(original_root):
    raise SystemExit('Document XML contains changes beyond five after-spacing edits and one cantSplit')

text_digest = sha(json.dumps(original_text, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
out_hash = sha(OUT.read_bytes())
proof = {
    'source': str(SRC),
    'source_sha256': src_hash,
    'candidate': str(OUT),
    'candidate_sha256': out_hash,
    'candidate_bytes': OUT.stat().st_size,
    'package_part_count': len(out_names),
    'unchanged_non_document_parts': len(unchanged_parts),
    'document_xml_only_delta': True,
    'w_t_sequence_preserved': True,
    'w_t_count': len(original_text),
    'w_t_sequence_sha256': text_digest,
    'b13_heading_body_index': heading_i,
    'b13_reference_paragraphs': [
        {'body_index': idx, 'marker': marker, 'after_before': '100', 'after_after': '20', 'text_sha256': sha(txt.encode('utf-8'))}
        for (idx, para, txt), marker in zip(hits, markers)
    ],
    'solver_row': {'table_index': table_index, 'row_index': row_index, 'cantSplit_added': True, 'text_sha256': sha(solver_text.encode('utf-8'))},
    'allowed_xml_delta_only': True
}
REPORT.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
MD.write_text(
    '# Narrow layout-fix candidate static proof\n\n'
    f'- Source candidate SHA-256: {src_hash}\n'
    f'- New candidate SHA-256: {out_hash} ({OUT.stat().st_size:,} bytes)\n'
    f'- Package: {len(out_names)} parts; all {len(unchanged_parts)} non-document parts byte-identical.\n'
    f'- Text: all {len(original_text):,} w:t values retain the exact sequence (SHA-256 {text_digest}).\n'
    '- XML delta: exactly five B13 reference paragraph after-spacing values changed from 100 to 20 twips, plus cantSplit on the unique Solver-native contact row. Normalizing those six authorized changes reproduces the original document.xml canonically.\n'
    f'- B13 source paragraphs: body indexes {indices}; Solver row: table {table_index}, row {row_index}.\n',
    encoding='utf-8')
print(json.dumps(proof, ensure_ascii=False, separators=(',', ':')))
