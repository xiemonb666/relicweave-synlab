from pathlib import Path
from zipfile import ZipFile
from lxml import etree
import hashlib, json

ROOT = Path(r'C:\Users\xiemo\Desktop\ShardForge')
WORK = ROOT / 'tmp/v147_user_merge_20261007'
FILES = {
    'current_v147_closeout': ROOT / 'RelicWeave_V1.47_A12_VesselForge_PGFrag_Closeout.docx',
    'user_v147_input': ROOT / 'RelicWeave_V1.47.docx',
    'original_v146': ROOT / 'RelicWeave_V1.46_A12_VesselForge_PGFrag_Integrated_NavFixed.docx',
}
DIFF = WORK / 'diff_summary.json'
OUT = WORK / 'merge_compact_preflight.json'
W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
NS = {'w': W}
Q = lambda local: f'{{{W}}}{local}'
PARSER = etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=False)

def sha_bytes(data): return hashlib.sha256(data).hexdigest()
def sha_file(path): return sha_bytes(path.read_bytes())
def read_package(path):
    with ZipFile(path) as z: return {n: z.read(n) for n in z.namelist()}
def doc_body(parts):
    doc = etree.fromstring(parts['word/document.xml'], PARSER)
    return doc, doc.find('.//w:body', NS)
def p_text(el): return ''.join(el.xpath('.//w:t/text()', namespaces=NS))
def body_direct(body): return list(body)
def p_nodes(body): return [el for el in body if el.tag == Q('p')]
def counts(parts):
    doc, body = doc_body(parts)
    children = body_direct(body)
    return {
        'parts': len(parts), 'direct_body_children': len(children),
        'direct_paragraphs': sum(el.tag == Q('p') for el in children),
        'direct_tables': sum(el.tag == Q('tbl') for el in children),
        'bookmark_starts': len(doc.findall('.//w:bookmarkStart', NS)),
        'bookmark_ends': len(doc.findall('.//w:bookmarkEnd', NS)),
        'hyperlinks': len(doc.findall('.//w:hyperlink', NS)),
        'rels_sha256': sha_bytes(parts['word/_rels/document.xml.rels']),
        'styles_sha256': sha_bytes(parts['word/styles.xml']),
        'document_xml_sha256': sha_bytes(parts['word/document.xml']),
    }

assert all(p.is_file() for p in FILES.values()), 'Missing input DOCX'
parts = {k: read_package(v) for k, v in FILES.items()}
diff = json.loads(DIFF.read_text(encoding='utf-8'))
docs = {k: doc_body(v) for k, v in parts.items()}
by_paragraph = {k: p_nodes(body) for k, (_, body) in docs.items()}

headings = []
user_ps = by_paragraph['user_v147_input']
for item in diff['new_heading_ids_and_titles']:
    title = item['heading']
    matches = [i for i, p in enumerate(user_ps) if p_text(p) == title]
    assert len(matches) == 1, (title, matches)
    idx = matches[0]
    code = title.split()[0]
    headings.append({
        'source_alignment_block': item['block'], 'section_code': code,
        'heading_sha256': sha_bytes(title.encode('utf-8')),
        'user_direct_paragraph_index': idx, 'nav_bookmark_id': 521 + len(headings),
        'nav_bookmark_name': f'RWV147_N{len(headings)+1:03d}',
    })

# The seven exact closeout paragraphs come from the current frozen V1.47.
current_ps = by_paragraph['current_v147_closeout']
base_ps = by_paragraph['original_v146']
status_paragraphs = []
status_anchor_source_v146 = [407, 409, 1311, 2052, 2097, 2223, 739]
status_sections = ['A12.19', 'A12.20', 'G0', 'G31.1', 'VesselForge', 'PG-Frag', '11']
for i, item in enumerate(diff['exact_closeout_status_paragraphs_missing_from_user_doc']):
    text = item['text']
    src_matches = [j for j, p in enumerate(current_ps) if p_text(p) == text]
    assert len(src_matches) == 1, (item['heading'], src_matches)
    anchor_idx = status_anchor_source_v146[i]
    anchor_text = p_text(base_ps[anchor_idx])
    dst_matches = [j for j, p in enumerate(user_ps) if p_text(p) == anchor_text]
    # The same shared architecture-baseline paragraph appears once under I and
    # once under J. Bind each protected status paragraph to its own appendix.
    if len(dst_matches) > 1 and status_sections[i] == 'VesselForge':
        dst_matches = [min(dst_matches)]
    elif len(dst_matches) > 1 and status_sections[i] == 'PG-Frag':
        dst_matches = [max(dst_matches)]
    assert len(dst_matches) == 1, (item['heading'], anchor_idx, dst_matches)
    status_paragraphs.append({
        'section': status_sections[i], 'source_v146_paragraph_index': anchor_idx,
        'current_closeout_paragraph_index': src_matches[0],
        'current_status_text_chars': len(text),
        'current_status_text_sha256': sha_bytes(text.encode('utf-8')),
        'user_semantic_anchor_paragraph_index': dst_matches[0],
        'anchor_text_sha256': sha_bytes(anchor_text.encode('utf-8')),
    })

current_p5 = p_text(current_ps[5])
user_title_matches = [i for i,p in enumerate(user_ps) if p_text(p) == p_text(user_ps[5])]
assert len(user_title_matches) == 1
report = {
    'purpose': 'Compact read-only preflight for the approved document-only V1.47 merge; candidate not yet built.',
    'inputs': {
        k: {'filename': path.name, 'bytes': path.stat().st_size,
            'sha256': sha_file(path), 'structure': counts(parts[k])}
        for k, path in FILES.items()
    },
    'package_comparison': {
        'same_part_names_current_user': set(parts['current_v147_closeout']) == set(parts['user_v147_input']),
        'same_document_relationships_current_user': parts['current_v147_closeout']['word/_rels/document.xml.rels'] == parts['user_v147_input']['word/_rels/document.xml.rels'],
        'user_styles_equal_v146': parts['user_v147_input']['word/styles.xml'] == parts['original_v146']['word/styles.xml'],
        'closeout_styles_equal_v146': parts['current_v147_closeout']['word/styles.xml'] == parts['original_v146']['word/styles.xml'],
        'changed_common_parts_current_user': sorted(n for n in set(parts['current_v147_closeout']) & set(parts['user_v147_input']) if parts['current_v147_closeout'][n] != parts['user_v147_input'][n]),
        'reviewed_diff': {
            'additions': diff['paragraph_stream_counts'].get('additions'),
            'deletions': diff['paragraph_stream_counts'].get('deletions'),
            'replacements': diff['paragraph_stream_counts'].get('replacements'),
            'new_headings': len(headings),
            'new_tables_net': 18,
            'historical_result_blocks_changed': diff['historical_result_scope']['changed_historical_result_paragraphs'],
        },
    },
    'planned_heading_navigation': headings,
    'protected_current_closeout_status_paragraphs': status_paragraphs,
    'protected_current_front_summary': {
        'source_current_paragraph_index': 5, 'text_chars': len(current_p5),
        'text_sha256': sha_bytes(current_p5.encode('utf-8')),
        'insert_after_user_paragraph_index': 5,
    },
    'root_approved_patch_spec': {
        'scope': 'Use user document body and current closeout ancillary package parts; retain all imported research ideas; reinsert 7 exact status paragraphs plus the current front status summary; no source implementation or numerical work.',
        'front_priority': 'The closeout, handover and backup remain the active priority; research P0 does not authorize new development; new experiments/development require explicit user restart; 0 physically qualified packages; engineering estimates unchanged and are not physical accuracy.',
        'member_metrics': 'Closed membership is frozen-gallery G excluding q; do not require recovery of every missing physical fragment. Empty-set and absent-mate rules explicit; closed/open world separate; whole-workflow denominator; query-to-object macro/cluster intervals; R2 closure separate.',
        'truth_permissions': 'GT relation/member labels may be supervised targets or offline Oracle diagnostics but are isolated from input, memory and candidate generation; online inputs are allowlisted observations; GT poses/true graph not online; motherID only split/audit; provenance IDs not identity features.',
        'relation_ontology': 'Ground-truth same-vessel equivalence/transitive; direct historic R2 non-transitive; prediction remains soft; UNKNOWN epistemic; P_R2 <= P_same; missing R2 is not R1; predicted pose_hat plus uncertainty only.',
        'evaluation_and_resources': 'Same-style/mould/batch hard negatives; belief revision does not change GT; calibration and coverage-risk; offline privileged Oracle-R2 diagnostic with matched shuffled-R2 and feasible GT-R1 controls; B1 scalar required; B2 latent conditional; resource STOP is not universal impossibility; report fixed K/L/iteration/hypothesis/radius, P95, peak VRAM/RAM, FLOPs; 5090 throughput unmeasured.',
        'degradation_and_ui': 'Separate fixed-GT observation perturbation from physical material loss/new events with lineage/current fit/evidence visibility; D1-D4 are uncalibrated recipes, D5 real confirmation, 31 axes software QA; D6.5 shows insufficient evidence/recapture/budget/STOP, no forced members/automatic restoration; physically qualified synthetic pack gates synthetic physics/pretraining claims only.',
        'references_and_novelty': 'Correct SARe v2, GARF two-session (one-step initialization plus multi-step refinement), TORA ECCV 2026 accepted, MV-RoMa CVPR 2026 accepted, Coconut COLM 2025 with workshop as optional history; ideas remain RESEARCH/IDEA, no first/SOTA claim.',
        'format_only': 'Map imported explicit East Asian Droid Sans Fallback refs to Noto Sans SC; white text on original A12.17 dark header; exactly 3 approved TRELLIS.2 line breaks; no failed table-width diagnostics.',
        'navigation': 'Add unique internal bookmark and one compact front navigation link for each of the 33 new headings; preserve original 520 bookmark identities, 80 hyperlink identities, all existing relationships.',
    },
}
OUT.write_text(json.dumps(report, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')
print(f'output={OUT} bytes={OUT.stat().st_size} sha256={sha_file(OUT)}')
print(f"headings={len(headings)} status_paragraphs={len(status_paragraphs)} compact_limit_ok={OUT.stat().st_size < 200000}")
