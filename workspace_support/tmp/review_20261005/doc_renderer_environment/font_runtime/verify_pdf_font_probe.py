import argparse
import json
import re
from pathlib import Path
from pypdf import PdfReader
import pdfplumber

def base_font_objects(reader):
    found=[]
    for pageno, page in enumerate(reader.pages,1):
        res=page.get('/Resources')
        if res is None: continue
        fonts=res.get_object().get('/Font')
        if fonts is None: continue
        for ref in fonts.get_object().values():
            f=ref.get_object()
            objs=[f]
            descendants=f.get('/DescendantFonts')
            if descendants:
                objs.extend(x.get_object() for x in descendants.get_object())
            for obj in objs:
                base=str(obj.get('/BaseFont','')).lstrip('/')
                base=re.sub(r'^[A-Z]{6}\+','',base)
                desc=obj.get('/FontDescriptor')
                embedded=False
                if desc:
                    d=desc.get_object()
                    embedded=any(d.get(k) is not None for k in ('/FontFile','/FontFile2','/FontFile3'))
                found.append({'page':pageno,'basefont':base,'embedded':embedded})
    # retain unique face/page tuples
    seen=set(); out=[]
    for item in found:
        key=(item['page'],item['basefont'],item['embedded'])
        if key not in seen:
            seen.add(key); out.append(item)
    return out

def family_match(name, expected):
    normalize=lambda s: re.sub(r'[^a-z0-9]','',s.lower())
    return normalize(expected) in normalize(name)

def searched_char_fonts(page, pattern):
    hits=page.search(re.escape(pattern), regex=True, return_chars=True)
    return sorted({c['fontname'] for hit in hits for c in hit.get('chars',[])})

ap=argparse.ArgumentParser()
ap.add_argument('--pdf',required=True)
ap.add_argument('--png-dir',required=True)
ap.add_argument('--report',required=True)
a=ap.parse_args()
pdf=Path(a.pdf); pngdir=Path(a.png_dir)
reader=PdfReader(str(pdf))
embedded=base_font_objects(reader)
with pdfplumber.open(str(pdf)) as doc:
    all_chars=[c for page in doc.pages for c in page.chars]
    char_font_names=sorted({c['fontname'] for c in all_chars})
    latin=[]; cjk=[]
    for page in doc.pages:
        latin.extend(searched_char_fonts(page,'IN_PROGRESS'))
        cjk.extend(searched_char_fonts(page,'窄范围'))
latin=sorted(set(latin)); cjk=sorted(set(cjk))
liberation_embedded=any(f['embedded'] and family_match(f['basefont'],'Liberation Sans') for f in embedded)
droid_embedded=any(f['embedded'] and family_match(f['basefont'],'Droid Sans Fallback') for f in embedded)
liberation_used=any(family_match(x,'Liberation Sans') for x in latin)
droid_used=any(family_match(x,'Droid Sans Fallback') for x in cjk)
pngs=sorted(p.name for p in pngdir.glob('page-*.png') if p.is_file())
result={
  'pdf':str(pdf.resolve()),
  'page_count':len(reader.pages),
  'png_count':len(pngs),
  'pdf_embedded_font_faces':sorted({f['basefont'] for f in embedded if f['embedded']}),
  'pdf_char_fontnames':char_font_names,
  'ascii_probe_fontnames':latin,
  'cjk_probe_fontnames':cjk,
  'liberation_sans_embedded':liberation_embedded,
  'droid_sans_fallback_embedded':droid_embedded,
  'ascii_probe_uses_liberation_sans':liberation_used,
  'cjk_probe_uses_droid_sans_fallback':droid_used,
  'visual_probe_gate_passed':bool(len(reader.pages)>=1 and len(pngs)==len(reader.pages) and liberation_embedded and droid_embedded and liberation_used and droid_used),
}
Path(a.report).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
raise SystemExit(0 if result['visual_probe_gate_passed'] else 31)

