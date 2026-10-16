from zipfile import ZipFile
from lxml import etree

DOCX = 'RelicWeave_V1.46_A12_VesselForge_PGFrag_Integrated_NavFixed.docx'
W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
ns = {'w': W}
with ZipFile(DOCX) as archive:
    for name in ('word/header2.xml', 'word/footer2.xml'):
        root = etree.fromstring(archive.read(name))
        print(name)
        for pi, paragraph in enumerate(root.findall('.//w:p', ns)):
            for ti, node in enumerate(paragraph.findall('.//w:t', ns)):
                print(' ', pi, ti, (node.text or '').encode('unicode_escape').decode('ascii'), 'parent', etree.QName(node.getparent()).localname)
            print('  fields', [etree.QName(n).localname for n in paragraph.iter() if etree.QName(n).localname in {'fldChar', 'instrText'}])
