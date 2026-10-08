from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from lxml import etree
from copy import deepcopy
import hashlib, json

WORK = Path('tmp/v147_user_merge_20261007')
SRC = WORK / 'fresh_merge_layout_fix_candidate.docx'
OUT = WORK / 'fresh_merge_layout_final_candidate.docx'
REPORT = WORK / 'fresh_merge_layout_final_static.json'
MD = WORK / 'fresh_merge_layout_final_static.md'
EXPECTED = '835fc8f257d902e817a9e44bdf8c7e9d51da93da02205ee3901adffac2eb9173'
URI = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
NS = {'w': URI}
W = '{%s}' % URI
P, TBL, TR = W+'p', W+'tbl', W+'tr'
XML_PART = 'word/document.xml'

def sha(b):
    return hashlib.sha256(b).hexdigest()

def text(el):
    return ''.join(el.xpath('.//w:t/text()', namespaces=NS))

def canon(el):
    return etree.tostring(el, method='c14n', exclusive=False, with_comments=True)

def ensure_prop(p, local, val):
    ppr = p.find('w:pPr', NS)
    if ppr is None:
        ppr = etree.Element(W+'pPr')
        p.insert(0, ppr)
    tag = W+local
    prop = ppr.find('w:'+local, NS)
    if prop is None:
        order = ['pStyle','keepNext','keepLines','pageBreakBefore','framePr','widowControl','numPr','suppressLineNumbers','pBdr','shd','tabs','suppressAutoHyphens','kinsoku','wordWrap','overflowPunct','topLinePunct','autoSpaceDE','autoSpaceDN','bidi','adjustRightInd','snapToGrid','spacing','ind','contextualSpacing','mirrorIndents','suppressOverlap','jc','textDirection','textAlignment','textboxTightWrap','outlineLvl','divId','cnfStyle','rPr','sectPr','pPrChange']
        rank = {W+name:i for i,name in enumerate(order)}
        target = rank.get(tag, 999)
        pos = len(ppr)
        for i, child in enumerate(ppr):
            if rank.get(child.tag, 999) > target:
                pos = i
                break
        prop = etree.Element(tag)
        ppr.insert(pos, prop)
    prop.set(W+'val', val)
    return ppr, prop

if not SRC.exists():
    raise SystemExit(f'Missing source candidate: {SRC}')
src_hash = sha(SRC.read_bytes())
if src_hash != EXPECTED:
    raise SystemExit(f'Source SHA mismatch: {src_hash}')
with ZipFile(SRC, 'r') as zin:
    infos = zin.infolist()
    blobs = {i.filename: zin.read(i.filename) for i in infos}
if XML_PART not in blobs:
    raise SystemExit('Missing word/document.xml')
parser = etree.XMLParser(remove_blank_text=False, resolve_entities=False)
original_xml = blobs[XML_PART]
source_root = etree.fromstring(original_xml, parser)
original_root = deepcopy(source_root)
source_body = source_root.find('w:body', NS)
if source_body is None:
    raise SystemExit('Missing document body')

matches = []
for body_i, el in enumerate(list(source_body)):
    if el.tag != TBL:
        continue
    for row_i, row in enumerate(el.xpath('./w:tr', namespaces=NS)):
        if 'Solver-native contact' in text(row):
            matches.append((body_i, row_i, el, row))
if len(matches) != 1:
    raise SystemExit(f'Expected one Solver-native contact row in a top-level table, found {len(matches)}')
body_i, row_i, table, target_row = matches[0]
rows = table.xpath('./w:tr', namespaces=NS)
if row_i != len(rows)-1:
    raise SystemExit(f'Solver row is not the unique last row: {row_i} of {len(rows)}')
paragraphs = target_row.xpath('./w:tc//w:p', namespaces=NS)
if len(paragraphs) != 3:
    raise SystemExit(f'Expected exactly three row paragraphs, got {len(paragraphs)}')
texts = [text(p) for p in paragraphs]
if not ('Solver-native contact' in texts[0] and '减少状态转换' in texts[1] and '短时断裂阶段内部接触' in texts[2]):
    raise SystemExit('Solver row paragraph text/order did not match authorization')
# Clone the full paragraphs, preserving run content/fonts/bookmarks, then remove only the last row.
clones = [deepcopy(p) for p in paragraphs]
original_row = deepcopy(target_row)
parent = target_row.getparent()
parent.remove(target_row)
insert_at = body_i + 1
for offset, p in enumerate(clones):
    body = source_root.find('w:body', NS)
    body.insert(insert_at + offset, p)
for i, p in enumerate(clones):
    ensure_prop(p, 'keepLines', 'true')
    ensure_prop(p, 'keepNext', 'true' if i < 2 else 'false')

blobs[XML_PART] = etree.tostring(source_root, xml_declaration=True, encoding='UTF-8', standalone=True)
with ZipFile(OUT, 'w', ZIP_DEFLATED) as zout:
    for info in infos:
        zout.writestr(info, blobs[info.filename])

with ZipFile(OUT, 'r') as zout:
    out_names = zout.namelist()
    out_blobs = {n:zout.read(n) for n in out_names}
if out_names != [i.filename for i in infos]:
    raise SystemExit('Package part names/order changed')
unchanged = [n for n in out_names if n != XML_PART and out_blobs[n] == blobs[n]]
if len(unchanged) != len(out_names)-1:
    raise SystemExit('A non-document package part changed')
candidate_root = etree.fromstring(out_blobs[XML_PART], parser)
candidate_body = candidate_root.find('w:body', NS)
candidate_body_items = list(candidate_body)
candidate_table = candidate_body_items[body_i]
if candidate_table.tag != TBL or len(candidate_table.xpath('./w:tr', namespaces=NS)) != len(rows)-1:
    raise SystemExit('Target table row count was not reduced by exactly one')
if len(candidate_root.xpath('.//w:tbl', namespaces=NS)) != len(source_root.xpath('.//w:tbl', namespaces=NS)):
    raise SystemExit('Table count changed')
expected_inserted = candidate_body_items[body_i+1:body_i+4]
if len(expected_inserted) != 3 or any(x.tag != P for x in expected_inserted):
    raise SystemExit('Three body paragraphs were not inserted immediately after the target table')
if [text(x) for x in expected_inserted] != texts:
    raise SystemExit('Inserted body paragraph text/order changed')
for i, p in enumerate(expected_inserted):
    kn = p.find('w:pPr/w:keepNext', NS)
    kl = p.find('w:pPr/w:keepLines', NS)
    if kn is None or kn.get(W+'val') != ('true' if i < 2 else 'false'):
        raise SystemExit('keepNext value incorrect')
    if kl is None or kl.get(W+'val') != 'true':
        raise SystemExit('keepLines value incorrect')

# Reconstruct by removing the inserted paragraphs and restoring the original row;
# canonical equality proves there are no other document.xml changes.
normalized = etree.fromstring(out_blobs[XML_PART], parser)
norm_body = normalized.find('w:body', NS)
norm_items = list(norm_body)
for _ in range(3):
    norm_body.remove(norm_body[body_i+1])
norm_table = list(norm_body)[body_i]
norm_table.append(original_row)
if canon(normalized) != canon(original_root):
    raise SystemExit('Changes exceed moving the last row paragraphs to body and adding specified keep properties')

before_text = etree.fromstring(original_xml, parser).xpath('.//w:t/text()', namespaces=NS)
after_text = candidate_root.xpath('.//w:t/text()', namespaces=NS)
if before_text != after_text:
    raise SystemExit('w:t sequence changed')
text_digest = sha(json.dumps(before_text, ensure_ascii=False, separators=(',',':')).encode('utf-8'))
out_hash = sha(OUT.read_bytes())
proof = {
    'source':str(SRC),'source_sha256':src_hash,
    'candidate':str(OUT),'candidate_sha256':out_hash,'candidate_bytes':OUT.stat().st_size,
    'package_part_count':len(out_names),'unchanged_non_document_parts':len(unchanged),
    'table_count_before_after':[len(source_root.xpath('.//w:tbl',namespaces=NS)),len(candidate_root.xpath('.//w:tbl',namespaces=NS))],
    'target_table_body_index':body_i,'target_table_rows_before_after':[len(rows),len(rows)-1],
    'moved_paragraphs':texts,
    'body_paragraph_pagination':[{'keepNext':'true' if i<2 else 'false','keepLines':'true'} for i in range(3)],
    'w_t_count':len(before_text),'w_t_sequence_preserved':True,'w_t_sequence_sha256':text_digest,
    'document_xml_reconstruction_exact':True
}
REPORT.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
MD.write_text(
    '# Final layout relocation static proof\n\n'
    f'- Source SHA-256: {src_hash}\n'
    f'- Candidate SHA-256: {out_hash} ({OUT.stat().st_size:,} bytes)\n'
    f'- All {len(unchanged)} non-document package parts are byte-identical; table count remains 194 and the target table has one fewer row.\n'
    f'- All {len(before_text):,} w:t values retain their exact sequence (SHA-256 {text_digest}).\n'
    '- The Solver label and two explanation paragraphs were moved in order from the unique last row to immediately after its table. First two paragraphs have keepNext=true; all three have keepLines=true; the last has keepNext=false.\n'
    '- Removing those three paragraphs and restoring the original row reconstructs the original document.xml exactly.\n',
    encoding='utf-8')
print(json.dumps(proof,ensure_ascii=False,separators=(',',':')))
