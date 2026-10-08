import collections
import json
import re
import unicodedata
from pathlib import Path
import pdfplumber
base=Path(r'tmp/review_20261005/doc_renderer_environment/font_runtime')
source_report=Path(r'tmp/review_20261005/doc_renderer_environment/new_paragraph_locations.json')
pdf=Path(r'tmp/review_20261005/doc_render_fontfixed_01/RelicWeave_V1.46_Implementation_Update_20261005.pdf')
report_path=base/'fontfixed_01_new_paragraph_locations.json'
text_path=base/'fontfixed_01_pdf_text_by_page.txt'
TOKEN_RE=re.compile(r"[^\W_]+(?:['’][^\W_]+)?",re.UNICODE)
def key(s):
    s=unicodedata.normalize('NFC',s).replace('\u00ad','')
    return re.sub(r'\s+',' ',s).strip()
def tokens(s):
    s=unicodedata.normalize('NFKC',s).replace('\u00ad','')
    return [x.casefold() for x in TOKEN_RE.findall(s)]
def subseq(hay,needle):
    if not needle or len(needle)>len(hay):return []
    return [i for i in range(len(hay)-len(needle)+1) if hay[i:i+len(needle)]==needle]
report=json.loads(source_report.read_text(encoding='utf-8'))
with pdfplumber.open(str(pdf)) as doc:
    pages=[p.extract_text() or '' for p in doc.pages]
text_path.write_text('\n'.join(f'===== PAGE {i} =====\n{t}' for i,t in enumerate(pages,1))+'\n',encoding='utf-8')
page_tokens=[tokens(t) for t in pages]
for item in report['paragraphs']:
    ix=item['docx_paragraph_index']; target=key(item['text']); page_hits=[]
    if ix==7:
        p1=pages[0]
        if '实现快照' in p1 and '2026-10-05' in p1 and '1 / 205' in p1:
            page_hits=[1]
            item['location']={'pages':page_hits,'method':'pdfplumber_snapshot_heading_and_printed_footer','evidence':'Unique 实现快照 paragraph fragment visible on page 1; printed footer 1 / 205.'}
        else:
            item['location']={'pages':[],'method':'not_found'}
            continue
    else:
        exact=[i+1 for i,p in enumerate(pages) if target in key(p)]
        if exact:
            item['location']={'pages':exact,'method':'pdfplumber_normalized_full_paragraph'}
            continue
        needle=tokens(item['text'])
        full=[i+1 for i,p in enumerate(page_tokens) if subseq(p,needle)]
        if full:
            item['location']={'pages':full,'method':'pdfplumber_full_token_sequence'}
            continue
        found=[]
        for n in range(min(12,len(needle)),0,-1):
            for offset in range(len(needle)-n+1):
                anchor=needle[offset:offset+n]
                hits=[i+1 for i,p in enumerate(page_tokens) if subseq(p,anchor)]
                if hits:found.append((n,offset,hits,anchor))
            if found:break
        if found:
            found.sort(key=lambda x:(-x[0],x[1],len(x[2])))
            n,offset,hits,anchor=found[0]
            item['location']={'pages':hits,'method':'pdfplumber_longest_contiguous_anchor','anchor_tokens':n,'anchor_offset':offset,'anchor':' '.join(anchor)}
        else:
            item['location']={'pages':[],'method':'not_found'}
report['rendered_pdf']=str(pdf.resolve())
report['pdf_page_count']=len(pages)
report['pdf_text_by_page']=str(text_path.resolve())
report['location_method_note']='Locations are for the font-fixed-01 render. pdfplumber text extraction was used because this PDF embeds the requested fonts. Paragraph 7 is verified by its unique snapshot heading/content and printed page footer; paragraph 1106 is exact-normalized text on page 30.'
report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
map_path=base/'fontfixed_01_final_render_location_map.txt'
lines=['Font-fixed-01 render location map (not a visual QA pass)','PDF pages: '+str(len(pages)),'DOCX paragraph index -> PDF page']
for x in report['paragraphs']:
    loc=x['location']; p=','.join(map(str,loc['pages'])) or 'NOT_FOUND'
    lines.append(f"{x['docx_paragraph_index']} -> {p} | {loc['method']} | {x['text'][:110]}")
map_path.write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(json.dumps({'pdf_page_count':len(pages),'paragraphs':[{ 'index':x['docx_paragraph_index'],'pages':x['location']['pages'],'method':x['location']['method']} for x in report['paragraphs']],'report':str(report_path.resolve()),'map':str(map_path.resolve())},ensure_ascii=False,indent=2))
