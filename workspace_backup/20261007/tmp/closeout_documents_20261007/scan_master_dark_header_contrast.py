from zipfile import ZipFile
from lxml import etree
from pathlib import Path
import sys

DOCX = Path(sys.argv[1]) if len(sys.argv)>1 else Path(r'C:\Users\xiemo\Desktop\ShardForge\RelicWeave_V1.46_A12_VesselForge_PGFrag_Integrated_NavFixed.docx')
W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
ns = {'w': W}
dark_rgb = {'000000','111111','1f1f1f','202020','222222','333333','404040'}
light_rgb = {'ffffff','fefefe'}
def is_dark_fill(value):
    if len(value)!=6 or any(c not in '0123456789ABCDEF' for c in value): return False
    r,g,b=(int(value[i:i+2],16) for i in (0,2,4))
    return 0.2126*r+0.7152*g+0.0722*b < 115
def visible_text(node): return ''.join(node.xpath('.//w:t/text()',namespaces=ns))
def cell_fill(cell):
    shd=cell.find('./w:tcPr/w:shd',ns)
    return shd.get('{%s}fill'%W).upper() if shd is not None and shd.get('{%s}fill'%W) else 'none'
def cell_colors(cell):
    result=[]
    for run in cell.xpath('.//w:r',namespaces=ns):
        t=''.join(run.xpath('.//w:t/text()',namespaces=ns))
        if not t.strip(): continue
        color=run.find('./w:rPr/w:color',ns)
        if color is None: value='missing'
        else: value=color.get('{%s}val'%W,'auto').lower()
        result.append((t[:64],value))
    return result
with ZipFile(DOCX) as archive:
    root=etree.fromstring(archive.read('word/document.xml'))
tables=root.findall('.//w:body/w:tbl',ns)
print('table_count',len(tables))
for i,table in enumerate(tables,1):
    rows=table.findall('./w:tr',ns)
    if not rows: continue
    cells=rows[0].findall('./w:tc',ns)
    fills=[cell_fill(c) for c in cells]
    if not any(is_dark_fill(f) for f in fills):
        continue
    colors=[cell_colors(c) for c in cells]
    values=[value for cell in colors for _,value in cell]
    suspicious=any(v in dark_rgb or v=='auto' or v=='missing' for v in values)
    if suspicious:
        text=' || '.join(visible_text(c).replace('\n',' ')[:90].encode('unicode_escape').decode('ascii') for c in cells)
        print(f'table={i} fills={fills} text={text!r} colors={colors}')
