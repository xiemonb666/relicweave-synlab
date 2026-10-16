from pathlib import Path
import hashlib, re, zipfile, xml.etree.ElementTree as ET
from xml.parsers import expat

ROOT = Path(r'C:\Users\xiemo\Desktop\ShardForge')
SRC = ROOT / 'tmp/closeout_documents_20261007/master_v147_frozen_candidate_9af0efe877115200dd99bbcf8f24f3124e2932245d71795fc00252d08e278436.docx'
OUT = ROOT / 'tmp/closeout_documents_20261007/master_v147_candidate_table141_fixedgrid_diag.docx'
EXPECTED = '9af0efe877115200dd99bbcf8f24f3124e2932245d71795fc00252d08e278436'
NS = {'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
W = '{'+NS['w']+'}'
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
assert sha(SRC) == EXPECTED

with zipfile.ZipFile(SRC, 'r') as zin:
    source_doc = zin.read('word/document.xml')
    source_tree = ET.fromstring(source_doc)
    body = source_tree.find('w:body', NS)
    direct_tables = [e for e in list(body) if e.tag == W+'tbl']
    assert len(direct_tables) == 176
    target = direct_tables[141]
    target_text = ''.join(x.text or '' for x in target.findall('.//w:t', NS))
    assert 'TRELLIS.2' in target_text
    grid_cols = target.findall('w:tblGrid/w:gridCol', NS)
    grid_widths = [int(g.get(W+'w')) for g in grid_cols]
    assert grid_widths == [1994]*5, grid_widths
    target_rows = target.findall('w:tr', NS)
    assert len(target_rows) == 7, len(target_rows)
    original_widths = []
    for ri, tr in enumerate(target_rows):
        cells = tr.findall('w:tc', NS)
        assert len(cells) == 5, (ri, len(cells))
        for ci, cell in enumerate(cells):
            assert cell.find('w:tcPr/w:gridSpan', NS) is None, (ri,ci,'gridSpan')
            assert cell.find('w:tcPr/w:hMerge', NS) is None, (ri,ci,'hMerge')
            tcw = cell.find('w:tcPr/w:tcW', NS)
            assert tcw is not None and tcw.get(W+'type') == 'dxa', (ri,ci,'tcW')
            original_widths.append(int(tcw.get(W+'w')))
    tblpr = target.find('w:tblPr', NS)
    old_tblw = tblpr.find('w:tblW', NS)
    old_layout = tblpr.find('w:tblLayout', NS)
    assert old_tblw is not None and old_tblw.get(W+'type') == 'auto' and old_tblw.get(W+'w') == '0'
    assert old_layout is not None and old_layout.get(W+'type') == 'autofit'
    original_part_hashes = {i.filename: hashlib.sha256(zin.read(i.filename)).hexdigest() for i in zin.infolist() if i.filename != 'word/document.xml'}

# Get raw byte offsets for direct child table 141; patch only that table substring.
stack=[]; direct_index=-1; active=None; target_bounds=None
parser=expat.ParserCreate()
def start(name, attrs):
    global direct_index, active
    if name == 'w:tbl' and stack and stack[-1] == 'w:body':
        direct_index += 1
        if direct_index == 141:
            active = {'start': parser.CurrentByteIndex}
    stack.append(name)
def end(name):
    global active, target_bounds
    if name == 'w:tbl' and len(stack) >= 2 and stack[-2] == 'w:body' and active is not None:
        at = parser.CurrentByteIndex
        gt = source_doc.find(b'>', at)
        assert gt >= 0
        target_bounds = (active['start'], gt+1)
        active = None
    stack.pop()
parser.StartElementHandler=start
parser.EndElementHandler=end
parser.Parse(source_doc, True)
assert target_bounds is not None, 'raw target table not found'
table_start, table_end = target_bounds
raw_table = source_doc[table_start:table_end]
assert raw_table.count(b'<w:tbl>') == 1 and raw_table.count(b'</w:tbl>') == 1, 'nested table present'
assert raw_table.count(b'<w:tc>') == 35, raw_table.count(b'<w:tc>')

# Normalize each unmerged direct cell to its corresponding original grid column width.
cell_no = 0
def patch_cell(match):
    global cell_no
    cell = match.group(0)
    col = cell_no % 5
    width = grid_widths[col]
    cell_no += 1
    tags = list(re.finditer(rb'<w:tcW\b[^>]*/>', cell))
    assert len(tags) == 1, (cell_no, len(tags))
    tag = tags[0].group(0)
    assert re.search(rb'\bw:type="dxa"', tag), tag
    new_tag, n = re.subn(rb'\bw:w="[0-9]+"', b'w:w="'+str(width).encode('ascii')+b'"', tag, count=1)
    assert n == 1, tag
    return cell[:tags[0].start()] + new_tag + cell[tags[0].end():]
patched_table, cell_count = re.subn(rb'<w:tc>.*?</w:tc>', patch_cell, raw_table, flags=re.S)
assert cell_count == 35 and cell_no == 35
# Set this table to fixed layout at the existing grid's exact aggregate width.
tblw_pat = re.compile(rb'<w:tblW\b[^>]*/>')
tblw_matches = list(tblw_pat.finditer(patched_table)); assert len(tblw_matches) == 1
old_tag = tblw_matches[0].group(0)
new_tag = re.sub(rb'\bw:w="[0-9]+"', b'w:w="'+str(sum(grid_widths)).encode('ascii')+b'"', old_tag, count=1)
new_tag = re.sub(rb'\bw:type="[^"]+"', b'w:type="dxa"', new_tag, count=1)
assert new_tag != old_tag and b'w:w="9970"' in new_tag and b'w:type="dxa"' in new_tag
patched_table = patched_table[:tblw_matches[0].start()] + new_tag + patched_table[tblw_matches[0].end():]
layout_pat = re.compile(rb'<w:tblLayout\b[^>]*/>')
layout_matches = list(layout_pat.finditer(patched_table)); assert len(layout_matches) == 1
old_layout_tag = layout_matches[0].group(0)
new_layout_tag = re.sub(rb'\bw:type="[^"]+"', b'w:type="fixed"', old_layout_tag, count=1)
assert new_layout_tag != old_layout_tag and b'w:type="fixed"' in new_layout_tag
patched_table = patched_table[:layout_matches[0].start()] + new_layout_tag + patched_table[layout_matches[0].end():]
patched_doc = source_doc[:table_start] + patched_table + source_doc[table_end:]
# Replacing the altered table with its original raw bytes must exactly recover source document.xml.
assert patched_doc[:table_start] + raw_table + patched_doc[table_start+len(patched_table):] == source_doc

# Verify semantic invariants and only intended table-level delta.
patched_tree=ET.fromstring(patched_doc)
patched_tables=[e for e in list(patched_tree.find('w:body',NS)) if e.tag==W+'tbl']
assert len(patched_tables)==176
p_table=patched_tables[141]
pgrid=[int(g.get(W+'w')) for g in p_table.findall('w:tblGrid/w:gridCol',NS)]
assert pgrid==grid_widths
p_pr=p_table.find('w:tblPr',NS)
assert p_pr.find('w:tblLayout',NS).get(W+'type')=='fixed'
assert p_pr.find('w:tblW',NS).get(W+'type')=='dxa' and int(p_pr.find('w:tblW',NS).get(W+'w'))==sum(grid_widths)
for ri,tr in enumerate(p_table.findall('w:tr',NS)):
    cells=tr.findall('w:tc',NS); assert len(cells)==5
    for ci,cell in enumerate(cells):
        assert int(cell.find('w:tcPr/w:tcW',NS).get(W+'w'))==grid_widths[ci], (ri,ci)
assert [''.join(t.text or '' for t in e.findall('.//w:t',NS)) for e in source_tree.findall('.//w:p',NS)] == [''.join(t.text or '' for t in e.findall('.//w:t',NS)) for e in patched_tree.findall('.//w:p',NS)]
assert len(source_tree.findall('.//w:bookmarkStart',NS)) == len(patched_tree.findall('.//w:bookmarkStart',NS)) == 520
assert len(source_tree.findall('.//w:hyperlink',NS)) == len(patched_tree.findall('.//w:hyperlink',NS)) == 80

with zipfile.ZipFile(SRC,'r') as zin, zipfile.ZipFile(OUT,'w') as zout:
    for info in zin.infolist():
        data=patched_doc if info.filename=='word/document.xml' else zin.read(info.filename)
        zout.writestr(info,data)
with zipfile.ZipFile(OUT,'r') as zout:
    assert zout.read('word/document.xml')==patched_doc
    for name,before_sha in original_part_hashes.items():
        assert hashlib.sha256(zout.read(name)).hexdigest()==before_sha, name
print('source_sha256='+sha(SRC))
print('table_index=141 rows='+str(len(target_rows))+' direct_cells='+str(cell_count)+' grid_twips='+','.join(map(str,grid_widths)))
print('source_layout=autofit source_table_width=auto:0 candidate_layout=fixed candidate_table_width=dxa:'+str(sum(grid_widths)))
print('source_direct_cell_widths='+','.join(map(str,original_widths)))
print('candidate_all_35_direct_cells='+','.join(map(str,grid_widths)))
print('merge_check=0 gridSpan and 0 hMerge; text and bookmarks/hyperlinks preserved')
print('all_other_package_parts=unchanged')
print('candidate='+str(OUT)+' bytes='+str(OUT.stat().st_size)+' sha256='+sha(OUT))
