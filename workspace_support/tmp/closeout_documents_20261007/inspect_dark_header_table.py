from zipfile import ZipFile
from lxml import etree

DOCX='RelicWeave_V1.46_A12_VesselForge_PGFrag_Integrated_NavFixed.docx'
W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
ns={'w':W}
with ZipFile(DOCX) as archive:
    root=etree.fromstring(archive.read('word/document.xml'))
tables=root.findall('.//w:body/w:tbl',ns)
table=tables[38]
for ci,cell in enumerate(table.findall('./w:tr[1]/w:tc',ns),1):
    print('cell',ci,'text',( ''.join(cell.xpath('.//w:t/text()',namespaces=ns)) ).encode('unicode_escape').decode('ascii'))
    for run in cell.xpath('.//w:r',namespaces=ns):
        if ''.join(run.xpath('.//w:t/text()',namespaces=ns)).strip():
            rp=run.find('./w:rPr',ns)
            print(' rPr',etree.tostring(rp,encoding='unicode') if rp is not None else 'NONE')
    shd=cell.find('./w:tcPr/w:shd',ns)
    print(' fill', shd.attrib if shd is not None else None)
