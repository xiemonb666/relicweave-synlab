from pathlib import Path
from zipfile import ZipFile
from lxml import etree

ROOT = Path(r'C:\Users\xiemo\Desktop\ShardForge')
DOCX = ROOT / 'RelicWeave_V1.47_A12_VesselForge_PGFrag_Closeout.docx'
TARGET = 'Droid Sans Fallback'
W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
ns = {'w': W}

with ZipFile(DOCX) as archive:
    for name in archive.namelist():
        if not name.endswith('.xml'):
            continue
        data = archive.read(name)
        try:
            root = etree.fromstring(data)
        except etree.XMLSyntaxError:
            continue
        hits = []
        for element in root.xpath('//*[@*]'):
            for key, value in element.attrib.items():
                if value == TARGET:
                    hits.append((etree.QName(element).localname, etree.QName(key).localname))
        if hits:
            east = sum(1 for _, key in hits if key == 'eastAsia')
            other = [(tag, key) for tag, key in hits if key != 'eastAsia']
            print(f'{name}: total={len(hits)} eastAsia={east} other={other[:5]}')
