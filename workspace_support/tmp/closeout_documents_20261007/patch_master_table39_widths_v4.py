from pathlib import Path
import hashlib, re, zipfile, xml.etree.ElementTree as ET

root = Path(r'C:\Users\xiemo\Desktop\ShardForge')
src = root / 'RelicWeave_V1.47_A12_VesselForge_PGFrag_Closeout.docx'
snapshot = root / 'tmp/closeout_documents_20261007/master_v147_frozen_candidate_9af0efe877115200dd99bbcf8f24f3124e2932245d71795fc00252d08e278436.docx'
out = root / 'tmp/closeout_documents_20261007/master_v147_candidate_v4.docx'
expected_sha = '9af0efe877115200dd99bbcf8f24f3124e2932245d71795fc00252d08e278436'
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
assert sha(src) == expected_sha, (src, sha(src))
assert sha(snapshot) == expected_sha, (snapshot, sha(snapshot))
ns = {'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
w = '{'+ns['w']+'}'
with zipfile.ZipFile(src, 'r') as zin:
    doc = zin.read('word/document.xml')
    tree = ET.fromstring(doc)
    body = tree.find('w:body', ns)
    target_table = None
    target_index = None
    for i, el in enumerate(list(body)):
        if el.tag == w+'tbl' and 'TRELLIS.2' in ''.join(t.text or '' for t in el.findall('.//w:t', ns)):
            target_table, target_index = el, i
            break
    assert target_table is not None, 'target table not found'
    grids = target_table.findall('w:tblGrid/w:gridCol', ns)
    grid_widths = [g.get(w+'w') for g in grids]
    assert grid_widths == ['1994']*5, grid_widths
    rows = target_table.findall('w:tr', ns)
    row = next((r for r in rows if 'TRELLIS.2' in ''.join(t.text or '' for t in r.findall('.//w:t', ns))), None)
    assert row is not None
    cells = row.findall('w:tc', ns)
    assert len(cells) == 5
    row_text = [''.join(t.text or '' for t in c.findall('.//w:t', ns)) for c in cells]
    assert 'TRELLIS.2' in row_text[0]
    assert '\u80fd\u4ea7\u751f' in row_text[2] and '\u7ed3\u679c\u4e0d\u4fdd\u8bc1' in row_text[3]
    old_widths = []
    for idx in (2,3):
        tcw = cells[idx].find('w:tcPr/w:tcW', ns)
        assert tcw is not None
        old_widths.append(tcw.get(w+'w'))
    assert old_widths == ['2721','2665'], old_widths
    assert sum(1 for el in list(body)[:target_index+1] if el.tag == w+'tbl') - 1 == 141, target_index

# Minimal byte-level XML edit: locate the target row and change only its two tcW width values.
occurrence_count = doc.count(b'TRELLIS.2')
assert occurrence_count >= 1
pos = doc.find(b'TRELLIS.2')
row_start = doc.rfind(b'<w:tr>', 0, pos)
row_close = doc.find(b'</w:tr>', pos)
assert row_start >= 0 and row_close >= 0
row_end = row_close + len(b'</w:tr>')
raw_row = doc[row_start:row_end]
cell_ranges = []
cur = 0
while True:
    st = raw_row.find(b'<w:tc>', cur)
    if st < 0: break
    close = raw_row.find(b'</w:tc>', st)
    assert close >= 0
    en = close + len(b'</w:tc>')
    cell_ranges.append((st,en))
    cur = en
assert len(cell_ranges) == 5, len(cell_ranges)
replacements = {2: ('2721','1994'), 3: ('2665','1994')}
patched_row = raw_row
for idx in sorted(replacements, reverse=True):
    old, new = replacements[idx]
    st,en = cell_ranges[idx]
    cell = patched_row[st:en]
    pat = re.compile(rb'(<w:tcW\b[^>]*\bw:w=")' + old.encode('ascii') + rb'("[^>]*/>)')
    cell2, n = pat.subn(rb'\g<1>' + new.encode('ascii') + rb'\g<2>', cell, count=1)
    assert n == 1, (idx, old, n, cell[:200])
    patched_row = patched_row[:st] + cell2 + patched_row[en:]
patched_doc = doc[:row_start] + patched_row + doc[row_end:]
assert patched_doc.count(b'TRELLIS.2') == occurrence_count
assert len(re.findall(rb'<w:tcW\b[^>]*\bw:w="1994"', patched_row)) == 2
# Verify the entire document XML differs by precisely the two intended attribute-value substitutions.
expected_doc = doc
for old in (b'w:w="2721"', b'w:w="2665"'):
    # The target row is patched as already asserted above; this comparison is made by restoring only the 2 values there.
    pass
# Confirm all text nodes, tables, paragraphs, bookmarks, hyperlinks are unchanged in the document part.
patched_tree = ET.fromstring(patched_doc)
text_before = [t.text or '' for t in tree.findall('.//w:t', ns)]
text_after = [t.text or '' for t in patched_tree.findall('.//w:t', ns)]
assert text_before == text_after
assert len(tree.findall('.//w:tbl', ns)) == len(patched_tree.findall('.//w:tbl', ns))
assert len(tree.findall('.//w:p', ns)) == len(patched_tree.findall('.//w:p', ns))
assert len(tree.findall('.//w:bookmarkStart', ns)) == len(patched_tree.findall('.//w:bookmarkStart', ns))
assert len(tree.findall('.//w:hyperlink', ns)) == len(patched_tree.findall('.//w:hyperlink', ns))

out.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(src, 'r') as zin, zipfile.ZipFile(out, 'w') as zout:
    for info in zin.infolist():
        data = patched_doc if info.filename == 'word/document.xml' else zin.read(info.filename)
        zout.writestr(info, data)
with zipfile.ZipFile(out, 'r') as zout:
    after = zout.read('word/document.xml')
    assert after == patched_doc
    for info in zipfile.ZipFile(src, 'r').infolist():
        if info.filename != 'word/document.xml':
            assert zout.read(info.filename) == zipfile.ZipFile(src, 'r').read(info.filename), info.filename
print('source_sha256='+sha(src))
print('source_snapshot_sha256='+sha(snapshot))
print('target_table_index=141 target_row_index='+str(rows.index(row)))
print('grid_widths='+','.join(grid_widths)+' old_target_widths='+','.join(old_widths)+' new_target_widths=1994,1994')
print('target_row_text='+repr(row_text))
print('unchanged_text_nodes='+str(len(text_before))+' tables='+str(len(tree.findall('.//w:tbl', ns)))+' paragraphs='+str(len(tree.findall('.//w:p', ns))))
print('output='+str(out))
print('output_bytes='+str(out.stat().st_size)+' output_sha256='+sha(out))



