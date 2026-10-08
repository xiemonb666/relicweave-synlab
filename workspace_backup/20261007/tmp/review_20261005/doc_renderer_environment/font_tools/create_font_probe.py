import json
from pathlib import Path
from zipfile import ZipFile
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

workspace = Path(r'C:\Users\xiemo\Desktop\ShardForge')
source = workspace / 'RelicWeave_V1.46_Implementation_Update_20261005.docx'
report = workspace / 'tmp/review_20261005/doc_renderer_environment/new_paragraph_locations.json'
out = workspace / 'tmp/review_20261005/doc_renderer_environment/font_runtime/font_probe_input.docx'
with report.open(encoding='utf-8') as f:
    added = {x['docx_paragraph_index']: x['text'] for x in json.load(f)['paragraphs']}
probe_texts = [added[i] for i in (7, 1106, 1107, 1108, 1109)]

doc = Document(str(source))
body = doc._element.body
for child in list(body):
    if child.tag != qn('w:sectPr'):
        body.remove(child)

normal = doc.styles['Normal']
assert normal._element.rPr is not None and normal._element.rPr.rFonts is not None
normal_fonts = normal._element.rPr.rFonts
normal_request = {name: normal_fonts.get(qn('w:' + name)) for name in ('ascii','hAnsi','cs','eastAsia')}
assert normal_request == {'ascii':'Liberation Sans','hAnsi':'Liberation Sans','cs':'Liberation Sans','eastAsia':'Droid Sans Fallback'}, normal_request

def apply_requested_fonts(run):
    run.font.name = 'Liberation Sans'
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.rFonts
    if rfonts is None:
        rfonts = OxmlElement('w:rFonts')
        rpr.insert(0, rfonts)
    for name, value in normal_request.items():
        rfonts.set(qn('w:' + name), value)

def add_paragraph(text):
    p = doc.add_paragraph(style='Normal')
    r = p.add_run(text)
    apply_requested_fonts(r)
    return p

for text in probe_texts:
    add_paragraph(text)
table = doc.add_table(rows=2, cols=2)
table.style = 'Table Grid'
cell_texts = [
    '范围 / Scope',
    '窄范围 / Narrow scope',
    '状态 / Status',
    '合格高仿真预训练包 = 0; IN_PROGRESS',
]
for cell, text in zip((c for row in table.rows for c in row.cells), cell_texts):
    p = cell.paragraphs[0]
    p.style = 'Normal'
    p.clear()
    r = p.add_run(text)
    apply_requested_fonts(r)

doc.save(str(out))
# Verify the saved probe still contains the exact source Normal declaration and all 5 target text blocks.
with ZipFile(out) as z:
    xml = z.read('word/styles.xml').decode('utf-8')
    document_xml = z.read('word/document.xml').decode('utf-8')
for value in ('Liberation Sans', 'Droid Sans Fallback'):
    assert value in xml, value
for text in probe_texts + cell_texts:
    assert text in document_xml, text[:48]
print('probe=' + str(out))
print('source_normal_fonts=' + json.dumps(normal_request, ensure_ascii=False))
print('probe_paragraphs=' + str(len(probe_texts)) + ';table_cells=' + str(len(cell_texts)))
print('probe_sha256=' + __import__('hashlib').sha256(out.read_bytes()).hexdigest())


