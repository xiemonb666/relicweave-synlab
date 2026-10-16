from __future__ import annotations

from copy import deepcopy
from collections import Counter
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from lxml import etree
import hashlib, json, os

ROOT = Path(r'C:\Users\xiemo\Desktop\ShardForge')
WORK = ROOT / 'tmp/v147_user_merge_20261007'
OUTDIR = WORK / 'merge_candidate_20261007'
OUTDIR.mkdir(parents=True, exist_ok=True)
CURRENT = ROOT / 'RelicWeave_V1.47_A12_VesselForge_PGFrag_Closeout.docx'
USER = ROOT / 'RelicWeave_V1.47.docx'
V146 = ROOT / 'RelicWeave_V1.46_A12_VesselForge_PGFrag_Integrated_NavFixed.docx'
CANDIDATE = OUTDIR / 'RelicWeave_V1.47_userdiff_merged_candidate.docx'
DIFF = WORK / 'diff_summary.json'
PREFLIGHT = WORK / 'merge_compact_preflight.json'

EXPECTED = {
    'current': '9af0efe877115200dd99bbcf8f24f3124e2932245d71795fc00252d08e278436',
    'user': '41f1254e40a2ecabdcfa1c6583af2fce0ae1b0ab980d5f9179bbaf687b7be64b',
    'v146': '15978a3956fa33e8048cc54c1dad6878a7e19d9c71b84415dcaf8732f041a3b4',
}
W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
XML = 'http://www.w3.org/XML/1998/namespace'
NS = {'w': W}
Q = lambda local: f'{{{W}}}{local}'
PARSER = etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=False)

def sha_bytes(data: bytes) -> str: return hashlib.sha256(data).hexdigest()
def sha_file(path: Path) -> str: return sha_bytes(path.read_bytes())
def read_pkg(path: Path) -> dict[str, bytes]:
    with ZipFile(path, 'r') as z: return {n: z.read(n) for n in z.namelist()}
def text(el) -> str: return ''.join(el.xpath('.//w:t/text()', namespaces=NS))
def p_text(el) -> str: return text(el)
def direct_ps(body): return [e for e in body if e.tag == Q('p')]
def direct_tables(body): return [e for e in body if e.tag == Q('tbl')]
def paragraph_style(p):
    n = p.find('w:pPr/w:pStyle', NS)
    return n.get(Q('val')) if n is not None else ''
def child_texts(body):
    return [(e.tag.rsplit('}', 1)[-1], text(e)) for e in body if e.tag in (Q('p'), Q('tbl'))]

def replace_flat(el, old: str, new: str, label: str, mutations: list[dict]):
    before = text(el)
    if before.count(old) != 1:
        raise ValueError(f'{label}: expected one occurrence of {old!r}, got {before.count(old)}')
    start = before.index(old)
    end = start + len(old)
    nodes = el.xpath('.//w:t', namespaces=NS)
    offset = 0
    si = ei = None
    so = eo = 0
    for i, node in enumerate(nodes):
        value = node.text or ''
        nxt = offset + len(value)
        if si is None and start <= nxt:
            si, so = i, start - offset
        if end <= nxt:
            ei, eo = i, end - offset
            break
        offset = nxt
    if si is None or ei is None: raise ValueError(f'{label}: text range could not be mapped to w:t nodes')
    if si == ei:
        oldnode = nodes[si].text or ''
        nodes[si].text = oldnode[:so] + new + oldnode[eo:]
    else:
        first = nodes[si].text or ''
        last = nodes[ei].text or ''
        nodes[si].text = first[:so] + new
        for j in range(si + 1, ei): nodes[j].text = ''
        nodes[ei].text = last[eo:]
    after = text(el)
    assert after == before.replace(old, new, 1), (label, before, after)
    mutations.append({'label': label, 'before': before, 'after': after, 'changed': {'old': old, 'new': new}})

def make_para(template, value: str, style_id: str | None = None):
    p = etree.Element(Q('p'))
    ppr = template.find(Q('pPr')) if template is not None else None
    if ppr is not None: p.append(deepcopy(ppr))
    if style_id:
        if ppr is None:
            ppr = etree.Element(Q('pPr'))
            p.insert(0, ppr)
        ps = ppr.find(Q('pStyle'))
        if ps is None:
            ps = etree.Element(Q('pStyle'))
            ppr.insert(0, ps)
        ps.set(Q('val'), style_id)
    r = etree.SubElement(p, Q('r'))
    if template is not None:
        runs = template.findall(Q('r'))
        for source in runs:
            source_rpr = source.find(Q('rPr'))
            if source_rpr is not None:
                r.append(deepcopy(source_rpr))
                break
    t = etree.SubElement(r, Q('t'))
    if value[:1].isspace() or value[-1:].isspace(): t.set(f'{{{XML}}}space', 'preserve')
    t.text = value
    return p

def find_p_by_exact(ps, value, label):
    hits = [p for p in ps if p_text(p) == value]
    if len(hits) != 1: raise ValueError(f'{label}: expected one exact paragraph, found {len(hits)}')
    return hits[0]

def heading_paragraphs(ps, diff):
    out = {}
    for item in diff['new_heading_ids_and_titles']:
        title = item['heading']
        matches = [p for p in ps if p_text(p) == title]
        if len(matches) != 1: raise ValueError(f'heading is not unique: {title!r}, matches={len(matches)}')
        out[title.split()[0]] = matches[0]
    if len(out) != 33: raise ValueError(f'Expected 33 unique new headings, got {len(out)}')
    return out

def insert_before(body, target, value, template, mutations, label):
    p = make_para(template, value)
    body.insert(body.index(target), p)
    mutations.append({'label': label, 'before': None, 'after': value, 'kind': 'inserted_paragraph'})
    return p

def insert_after(body, anchor, value, template, mutations, label):
    p = make_para(template, value)
    body.insert(body.index(anchor) + 1, p)
    mutations.append({'label': label, 'before': None, 'after': value, 'kind': 'inserted_paragraph'})
    return p

def insert_break_after(p, phrase, label, break_log):
    old_text = p_text(p)
    if old_text.count(phrase) != 1:
        raise ValueError(f'{label}: phrase count {old_text.count(phrase)} for {phrase!r}')
    boundary = old_text.index(phrase) + len(phrase)
    nodes = p.xpath('.//w:t', namespaces=NS)
    running = 0
    prev = None
    selected = None
    local = 0
    for node in nodes:
        value = node.text or ''
        end = running + len(value)
        if boundary == running and prev is not None:
            selected = prev
            local = len(prev.text or '')
            break
        if running < boundary <= end:
            selected = node
            local = boundary - running
            break
        prev = node
        running = end
    if selected is None:
        if boundary == running and prev is not None:
            selected = prev
            local = len(prev.text or '')
        else:
            raise ValueError(f'{label}: break location not mapped')
    run = selected.getparent()
    if run.tag != Q('r'): raise ValueError(f'{label}: w:t not directly in w:r')
    idx = run.index(selected)
    value = selected.text or ''
    br = etree.Element(Q('br'))
    if local < len(value):
        suffix = deepcopy(selected)
        suffix.text = value[local:]
        selected.text = value[:local]
        run.insert(idx + 1, br)
        run.insert(idx + 2, suffix)
    else:
        run.insert(idx + 1, br)
    assert p_text(p) == old_text, label
    break_log.append({'label': label, 'paragraph_text_sha256': sha_bytes(old_text.encode('utf-8')), 'phrase': phrase, 'text_unchanged': True})

def set_white_header(table, expected, label):
    rows = table.findall(Q('tr'))
    if not rows: raise ValueError(f'{label}: missing first row')
    cells = rows[0].findall(Q('tc'))
    actual = [text(c) for c in cells]
    if actual != expected: raise ValueError(f'{label}: unexpected headers {actual!r}')
    count = 0
    for cell in cells:
        for run in cell.xpath('.//w:r[.//w:t]', namespaces=NS):
            rpr = run.find(Q('rPr'))
            if rpr is None:
                rpr = etree.Element(Q('rPr'))
                run.insert(0, rpr)
            color = rpr.find(Q('color'))
            if color is None: color = etree.SubElement(rpr, Q('color'))
            color.set(Q('val'), 'FFFFFF')
            for name in ('themeColor', 'themeTint', 'themeShade'):
                color.attrib.pop(Q(name), None)
            count += 1
    return count

def add_heading_bookmark(p, bookmark_id, bookmark_name):
    if p.xpath('.//w:bookmarkStart|.//w:bookmarkEnd', namespaces=NS):
        raise ValueError(f'new heading already contains bookmark: {p_text(p)}')
    start = etree.Element(Q('bookmarkStart'))
    start.set(Q('id'), str(bookmark_id)); start.set(Q('name'), bookmark_name)
    ppr = p.find(Q('pPr'))
    p.insert(p.index(ppr) + 1 if ppr is not None else 0, start)
    end = etree.Element(Q('bookmarkEnd'))
    end.set(Q('id'), str(bookmark_id))
    p.append(end)

def add_nav_link(nav_p, bookmark_name, label):
    link = etree.SubElement(nav_p, Q('hyperlink'))
    link.set(Q('anchor'), bookmark_name)
    link.set(Q('history'), '1')
    run = etree.SubElement(link, Q('r'))
    rpr = etree.SubElement(run, Q('rPr'))
    color = etree.SubElement(rpr, Q('color')); color.set(Q('val'), '0563C1')
    underline = etree.SubElement(rpr, Q('u')); underline.set(Q('val'), 'single')
    size = etree.SubElement(rpr, Q('sz')); size.set(Q('val'), '14')
    east = etree.SubElement(rpr, Q('rFonts')); east.set(Q('eastAsia'), 'Noto Sans SC')
    t = etree.SubElement(run, Q('t')); t.text = label

def insert_linebreaks_in_trellis(body, break_log):
    matches = []
    for table_index, table in enumerate(direct_tables(body), 1):
        for row_index, row in enumerate(table.findall(Q('tr'))):
            cells = row.findall(Q('tc'))
            cell_texts = [text(c) for c in cells]
            if any('TRELLIS.2' in s for s in cell_texts):
                matches.append((table_index, row_index, cells, cell_texts))
    if len(matches) != 1: raise ValueError(f'Expected one TRELLIS.2 row, got {len(matches)}')
    table_index, row_index, cells, cell_texts = matches[0]
    adv_hits = [i for i, s in enumerate(cell_texts) if '能产生复杂拓扑' in s and '和高多样性的长尾资产，' in s]
    limit_hits = [i for i, s in enumerate(cell_texts) if '结果不保证物理可用、' in s]
    if len(adv_hits) != 1 or len(limit_hits) != 1 or adv_hits[0] == limit_hits[0]:
        raise ValueError(f'TRELLIS.2 advantages/restrictions cells not unique: {cell_texts!r}')
    adv = cells[adv_hits[0]]; limits = cells[limit_hits[0]]
    adv_ps = [p for p in adv.xpath('.//w:p', namespaces=NS) if '能产生复杂拓扑' in p_text(p)]
    limit_ps = [p for p in limits.xpath('.//w:p', namespaces=NS) if '结果不保证物理可用、' in p_text(p)]
    if len(adv_ps) != 1 or len(limit_ps) != 1: raise ValueError('Expected one target paragraph per TRELLIS.2 cell')
    before_adv, before_limits = text(adv), text(limits)
    insert_break_after(adv_ps[0], '能产生复杂拓扑', f'TRELLIS.2 advantages break 1 (table {table_index}, row {row_index})', break_log)
    insert_break_after(adv_ps[0], '和高多样性的长尾资产，', f'TRELLIS.2 advantages break 2 (table {table_index}, row {row_index})', break_log)
    insert_break_after(limit_ps[0], '结果不保证物理可用、', f'TRELLIS.2 restrictions break (table {table_index}, row {row_index})', break_log)
    if text(adv) != before_adv or text(limits) != before_limits: raise AssertionError('TRELLIS.2 text changed')
    return {'table_index': table_index, 'row_index': row_index, 'advantages_cell_index': adv_hits[0], 'limitations_cell_index': limit_hits[0], 'text_unchanged': True}

def table_rows_with_first_match(body, header0, header1):
    found = []
    for table_index, table in enumerate(direct_tables(body), 1):
        rows = table.findall(Q('tr'))
        if not rows: continue
        cells = rows[0].findall(Q('tc'))
        values = [text(c) for c in cells]
        if len(values) >= 2 and values[0] == header0 and values[1] == header1:
            found.append((table_index, table))
    if len(found) != 1: raise ValueError(f'Expected one table with header {header0!r}/{header1!r}, got {len(found)}')
    return found[0]

def main():
    for key, path in [('current', CURRENT), ('user', USER), ('v146', V146)]:
        if sha_file(path) != EXPECTED[key]: raise SystemExit(f'{key} input hash mismatch: {sha_file(path)}')
    current_parts, user_parts, v146_parts = read_pkg(CURRENT), read_pkg(USER), read_pkg(V146)
    if set(current_parts) != set(user_parts) or set(current_parts) != set(v146_parts): raise SystemExit('Package part names diverged')
    if current_parts['word/_rels/document.xml.rels'] != user_parts['word/_rels/document.xml.rels']:
        raise SystemExit('Current and user document relationships differ')
    if user_parts['word/styles.xml'] != v146_parts['word/styles.xml']:
        raise SystemExit('User style part differs from V1.46')
    diff = json.loads(DIFF.read_text(encoding='utf-8'))
    compact = json.loads(PREFLIGHT.read_text(encoding='utf-8'))

    doc = etree.fromstring(user_parts['word/document.xml'], PARSER)
    body = doc.find('.//w:body', NS)
    original_body_children = [e for e in body if e.tag in (Q('p'), Q('tbl'))]
    original_text_hashes = [sha_bytes((e.tag.rsplit('}',1)[-1] + '\0' + text(e)).encode('utf-8')) for e in original_body_children]
    ps = direct_ps(body)
    if len(ps) != 2448 or len(direct_tables(body)) != 194: raise SystemExit('Unexpected donor V1.47 body counts')
    headings = heading_paragraphs(ps, diff)
    mutations: list[dict] = []
    insertions: list[dict] = []
    format_changes: list[dict] = []
    break_log: list[dict] = []

    # The user's V1.47 intro and subtitle remain the incoming authored version.
    user_p5 = ps[5]
    current_doc = etree.fromstring(current_parts['word/document.xml'], PARSER)
    current_ps = direct_ps(current_doc.find('.//w:body', NS))
    if len(current_ps) <= 5: raise SystemExit('Current closeout front summary missing')
    current_summary = deepcopy(current_ps[5])
    if 'moving-front' not in text(current_summary) or 'step_index=8..11' not in text(current_summary):
        raise SystemExit('Unexpected current closeout front summary text')
    body.insert(body.index(user_p5) + 1, current_summary)
    insertions.append({'label': 'preserved current full scientific closeout summary after user V1.47 intro', 'text_sha256': sha_bytes(text(current_summary).encode('utf-8')), 'chars': len(text(current_summary))})

    # Reinsert the seven exact, already accepted current status paragraphs at their semantic source anchors.
    status_anchor_source_v146 = [407, 409, 1311, 2052, 2097, 2223, 739]
    status_sections = ['A12.19', 'A12.20', 'G0', 'G31.1', 'VesselForge', 'PG-Frag', '11']
    v146_doc = etree.fromstring(v146_parts['word/document.xml'], PARSER)
    v146_ps = direct_ps(v146_doc.find('.//w:body', NS))
    if len(v146_ps) != 2343: raise SystemExit('Original V1.46 direct paragraph count mismatch')
    for i, status in enumerate(diff['exact_closeout_status_paragraphs_missing_from_user_doc']):
        status_text = status['text']
        source_matches = [p for p in current_ps if p_text(p) == status_text]
        if len(source_matches) != 1: raise SystemExit(f"Status source mismatch {status['heading']!r}")
        anchor_text = p_text(v146_ps[status_anchor_source_v146[i]])
        anchor_matches = [p for p in direct_ps(body) if p_text(p) == anchor_text]
        if len(anchor_matches) > 1 and status_sections[i] == 'VesselForge': anchor_matches = [min(anchor_matches, key=lambda p: body.index(p))]
        if len(anchor_matches) > 1 and status_sections[i] == 'PG-Frag': anchor_matches = [max(anchor_matches, key=lambda p: body.index(p))]
        if len(anchor_matches) != 1: raise SystemExit(f"Status anchor ambiguity {status_sections[i]}: {len(anchor_matches)}")
        copied = deepcopy(source_matches[0])
        body.insert(body.index(anchor_matches[0]) + 1, copied)
        insertions.append({'label': f'protected current status {status_sections[i]}', 'source_baseline_paragraph': status_anchor_source_v146[i], 'status_sha256': sha_bytes(status_text.encode('utf-8')), 'chars': len(status_text), 'anchor_sha256': sha_bytes(anchor_text.encode('utf-8'))})

    # The active priority paragraph follows section 1.3 and precedes section 2.
    section2_hits = [p for p in direct_ps(body) if p_text(p).strip().startswith('2 合并主线与边界')]
    if len(section2_hits) != 1: raise SystemExit(f'Expected one section 2 heading, got {len(section2_hits)}')
    section2 = section2_hits[0]
    previous_ps = [p for p in direct_ps(body) if body.index(p) < body.index(section2) and p_text(p).strip()]
    if not previous_ps: raise SystemExit('Could not find section 1.3 body paragraph')
    priority_text = ('本轮仍仅处理已授权的文档收口、方案/交接与备份；UA-IFRMN 等 P0 研究候选不覆盖当前执行优先级。'
        '新实验或开发须由用户明确重启。本阶段完整物理合格包仍为 0；PG-Frag 25–35%、VesselForge 30–40%、A12 30–40%仅为工程进度估计，不代表物理准确度或资格覆盖率，也不因本方案新增而上调。'
        'PG-Frag 与 VesselForge 的物理资格缺口仍优先闭合。')
    insert_before(body, section2, priority_text, previous_ps[-1], mutations, 'post-section-1.3 active-priority and restart boundary')

    # Closed-gallery member metrics and denominator contract.
    p222 = find_p_by_exact(direct_ps(body), '2.2.2 器物成员恢复指标、完整分母与退化曲线', '2.2.2 heading')
    p222_idx = body.index(p222)
    next_heading = next((p for p in direct_ps(body) if body.index(p) > p222_idx and p_text(p).strip().startswith('2.3 ')), None)
    if next_heading is None: raise SystemExit('2.3 section anchor missing')
    sec222_ps = [p for p in direct_ps(body) if p222_idx < body.index(p) < body.index(next_heading)]
    metric_para = next((p for p in sec222_ps if p_text(p).startswith('对query q定义V_G(q)')), None)
    if metric_para is None: raise SystemExit('2.2.2 member metric paragraph missing')
    old_closure = '只有object membership已闭合、缺失实物去向已记录且UNKNOWN不被强行归类的母体，才进入Level 3主评测。'
    new_closure = ('只有对冻结图库 G 中全部候选条目的成员归属已闭合（排除 query q）且 UNKNOWN 不被强行归类的母体，才进入 Level 3 闭集主评测。'
        '未入库或遗失的物理碎片及其去向仍作为 provenance 元数据记录，但不要求找回全部实物，也不构成本数据库范围闭集评测的通用前置条件。')
    replace_flat(metric_para, old_closure, new_closure, '2.2.2 frozen-gallery closure correction', mutations)
    metric_addendum = ('成员指标边界补充：对 V_G 非空而预测集合 V_hat 为空的 query，Recall=0、F1=0、Precision=N/A；'
        'V_G 为空而 V_hat 非空时，单独报告 member-absent 的错误纳入、覆盖与拒判风险；两者均为空是正确空集决策，不把未定义的 Precision/Recall 伪记为 1。'
        '闭集主结果与 partial/open-world 诊断分开，同时在全工作流分母中报告未闭合排除率与拒判。先按 query 汇总到物理器物，再按独立器物/来源簇宏平均并给簇级区间；碎片、视图和 episode 不作为独立样本。成员集合闭合与 R2 邻接边闭合分别审计。')
    insert_after(body, metric_para, metric_addendum, metric_para, mutations, '2.2.2 empty-set, open-world, macro and denominator contract')

    # Correct B2.3's mistaken requirement to recover unregistered physical fragments.
    b23 = headings['B2.3']
    b23_idx = body.index(b23)
    b23_next = next((p for p in direct_ps(body) if body.index(p) > b23_idx and paragraph_style(p).lower().startswith('heading')), None)
    b23_body = next((p for p in direct_ps(body) if body.index(p) > b23_idx and (b23_next is None or body.index(p) < body.index(b23_next)) and 'member_manifest' in p_text(p)), None)
    if b23_body is None: raise SystemExit('B2.3 member_manifest paragraph missing')
    old_b23 = '若某母体只知道若干邻接但不知道是否还有同器物碎片遗失或未入库，则只可参加Level 1/2的限定评测，不能进入完整成员恢复主分母。'
    new_b23 = ('Level 3 的闭合范围是冻结图库 G 中每个候选条目的 membership GT 均可判定（且排除 query q）；不要求证明所有物理失片均已追回。'
        '未入库/遗失碎片去向应在 provenance 中标注，但仅因物理碎片未找回，不排除数据库范围成员评测。R2 边集另行闭合或标注未知，不能替代 member-set closure。')
    replace_flat(b23_body, old_b23, new_b23, 'B2.3 gallery closure correction', mutations)
    b23_add = ('空集与分母按 2.2.2 的同一合同报告；membership GT 只对冻结 gallery 中候选条目闭合，R2 缺边不自动改标 R1。')
    insert_after(body, b23_body, b23_add, b23_body, mutations, 'B2.3 metric cross-reference')

    # Build a refreshed heading lookup after status/paragraph insertions and authorized heading edits.
    ps = direct_ps(body)
    headings = heading_paragraphs(ps, diff)

    # A6.15 bounded cache and measurable resource contract, at end of the section.
    a615_resource = ('资源合同：Step 0 仅把离线预编码结果写入磁盘/CPU 缓存，并按需读取固定 Top-K 候选的局部 token；不把全图库 token bank 或全 N² 关系图常驻 GPU。'
        '在 A6.17 后冻结 K、局部 token 数 L、迭代上限、假设数与重读邻域半径，并报告端到端 P95 延迟、峰值 VRAM/RAM 与 FLOPs。5090 吞吐尚未实测，不能用标称规格替代。')
    insert_before(body, headings['A6.16'], a615_resource, next(p for p in direct_ps(body) if body.index(p) < body.index(headings['A6.16']) and p_text(p).strip()), mutations, 'A6.15 bounded cache and end-to-end resource contract')

    # Correct the online/offline sentence in A6.16 and add the typed truth/permission ontology.
    a616 = headings['A6.16']
    a616_next = headings['A6.17']
    a616_ps = [p for p in direct_ps(body) if body.index(a616) < body.index(p) < body.index(a616_next)]
    relation_para = next((p for p in a616_ps if '最终 A—C 是 R1、R2 还是 UNKNOWN' in p_text(p)), None)
    if relation_para is None: raise SystemExit('A6.16 relation semantics paragraph missing')
    replace_flat(relation_para,
        '最终 A—C 是 R1、R2 还是 UNKNOWN，仍要由直接接触证据和历史邻接真值判定。',
        '最终 A—C 是 R1、R2 还是 UNKNOWN，应由允许的当前观测与模型后验作在线预测；历史邻接真值只用于隔离的监督目标或离线评测。',
        'A6.16 remove online historical-GT lookup', mutations)
    a616_add = ('真值本体与权限合同：在闭合且可判定的真值中，same-vessel 是等价关系并具有传递性，R2 是原碎裂事件中直接历史邻接关系且不传递；'
        'UNKNOWN 表示证据不足、标签缺失或拒判的认识状态，不是第四种物理类别。预测关系保持软分布，不用预测图连通性硬传递身份或邻接；联合输出要求 P_R2 ≤ P_same，缺失的 R2 标签不得补成 R1，只有已知标签进入对应监督损失。'
        '训练模型输入仅能使用 allowlisted Obs；关系/成员 GT 可作为监督目标或离线 Oracle 诊断，但必须与输入、memory 和 candidate generator 隔离。历史 GT 邻接、GT poses、motherID、true graph 与 TruthPack 不得在线读取；motherID 仅用于母体划分/审计，provenance ID 仅用于审计与去相关，不作为身份特征。运行时若需姿态，只能写入预测 pose_hat 及不确定性。')
    insert_before(body, a616_next, a616_add, a616_ps[-1], mutations, 'A6.16 ground-truth ontology and permission boundary')

    # Same-style hard negatives and source-shortcut controls.
    a618_add = ('可辨识性与拒判合同：确认集必须包含同风格、同模具、同批次但属于不同实物的 hard negatives，并显式覆盖观测歧义；'
        '对当前允许观测不可区分的候选应保留候选/UNKNOWN 或拒判，不强迫选定成员。外观、材料、器型只作先验而非身份证明；训练/开发/确认按物理器物及更高层来源簇隔离，并审计 motherID、袋号、背景、会话、seed、文件名和来源捷径。')
    insert_before(body, headings['A6.19'], a618_add, direct_ps(body)[body.index(headings['A6.18'])] if False else a616_ps[-1], mutations, 'A6.18 same-style identifiability and abstention contract')

    # Belief changes cannot rewrite physical truth; confidence is not calibration.
    a619_add = ('版本与校准合同：belief/posterior 的修订只产生新的模型状态版本，不改变历史 GT。labelVersion 仅因独立 GT 审计更正或新的碎裂事件/叶片集合而变化，并保留事件谱系与旧版本。'
        'posterior confidence 不自动等于置信区间或校准概率；校准器只在开发集拟合并冻结，按关系、质量域/OOD 与覆盖—风险报告适用范围。')
    a619_prev = next(p for p in reversed(direct_ps(body)[:body.index(headings['A6.20'])]) if p_text(p).strip())
    insert_before(body, headings['A6.20'], a619_add, a619_prev, mutations, 'A6.19 belief-version and calibration contract')

    # Rename the potentially overclaiming heading while keeping its navigation code.
    old_a620 = p_text(headings['A6.20'])
    new_a620 = old_a620.replace('Oracle 关系上限', 'Oracle 关系诊断')
    if old_a620 == new_a620: raise SystemExit('A6.20 heading wording did not match expected phrase')
    replace_flat(headings['A6.20'], 'Oracle 关系上限', 'Oracle 关系诊断', 'A6.20 heading: upper-bound wording to diagnostic', mutations)
    a622 = headings['A6.22']
    a620_add = ('Oracle-R2 仅是离线特权上下文诊断，不是严格信息论上限或部署路径；保持同一候选集、上下文数量/质量与计算预算，加入度数、质量和来源匹配的 shuffled-R2 控制，并在可行时加入同候选/同预算的 GT-R1 控制，以分离接触收益和同对象提示。任何 GT 都不得进入在线候选生成或推理。'
        'B1 scalar feedback 是必报最小基线；若匹配 Oracle 诊断有正向信号，允许把 B2 latent feedback 作为唯一下一项最小机制检验，即使 B1 无增益。若 Oracle 为 null，先审计闭合、容量、协议与统计功效，再按资源 STOP；不得据此宣称关系信息普遍不存在。具备合格真实观测、冻结图库与闭合成员 GT 时，真实域静态/成员/上下文测试不要求先有物理合格 synthetic pack；该 pack 只作为物理合成、物理退化或合成预训练主张的门槛。')
    a620_prev = next(p for p in reversed(direct_ps(body)[:body.index(a622)]) if p_text(p).strip())
    insert_before(body, a622, a620_add, a620_prev, mutations, 'A6.20-A6.21 privileged diagnostic, matched controls and real-data eligibility')
    # In A6.21 body, replace any remaining strict 'Oracle upper limit' wording.
    a621 = headings['A6.21']
    a622_i = body.index(a622)
    for p in list(direct_ps(body)):
        if body.index(a621) < body.index(p) < a622_i and 'Oracle-R2 上限' in p_text(p):
            replace_flat(p, 'Oracle-R2 上限', '匹配的 Oracle-R2 特权上下文诊断', 'A6.21 Oracle label correction', mutations)

    # Preserve every ledger addition as a research hypothesis, never an established novelty result.
    a622_add = ('研究主张边界：A6.15–A6.28、EXP10–EXP12 与 INNO-32 至 INNO-45 均是研究假设/候选合同，状态仍为 RESEARCH_CANDIDATE 或 IDEA；'
        '16 篇参考文献只提供机制灵感与对照，不证明本方案已经实现、首次提出、优于 SOTA 或在真实器物上有效。任何主张均须经预注册对照与独立真实器物确认。')
    insert_before(body, headings['A6.23'], a622_add, next(p for p in reversed(direct_ps(body)[:body.index(headings['A6.23'])]) if p_text(p).strip()), mutations, 'A6.22 research and novelty boundary')

    # Correct new A6.14 reference-table descriptions and bibliography versions/venues.
    reference_table_index, reference_table = table_rows_with_first_match(body, '参考工作', '原工作关键机制')
    reference_rows = reference_table.findall(Q('tr'))
    row_by_prefix = {}
    for ri, row in enumerate(reference_rows):
        cells = row.findall(Q('tc'))
        if not cells: continue
        first = text(cells[0])
        for prefix in ('SARe:', 'GARF:', 'TORA:', 'MV-RoMa:', 'Coconut /'):
            if first.startswith(prefix):
                if prefix in row_by_prefix: raise SystemExit(f'Duplicate A6.14 reference row {prefix}')
                row_by_prefix[prefix] = (ri, cells)
    if set(row_by_prefix) != {'SARe:', 'GARF:', 'TORA:', 'MV-RoMa:', 'Coconut /'}:
        raise SystemExit(f'Missing audited reference rows: {set(row_by_prefix)}')
    ri,cells=row_by_prefix['SARe:']
    replace_flat(cells[0], 'Structure-Aware Large-Scale 3D Fragment Reassembly', 'Structure-Aware Generative 3D Fragment Reassembly', 'A6.14 SARe v2 title', mutations)
    replace_flat(cells[0], 'arXiv:2603.21611', 'arXiv:2603.21611 v2', 'A6.14 SARe v2 identifier', mutations)
    replace_flat(cells[1], '联合预测 fracture-surface token probability 与 inter-fragment contact graph；推理期用几何一致性验证候选接触边，只固定可靠子结构，并对其余不确定部分重采样。',
        'v2 将 query-aligned local geometry 与 task-native structural supervision 融入 point flow；推理期进行几何验证，并对不确定部分重采样。',
        'A6.14 SARe v2 mechanism', mutations)
    replace_flat(cells[2], '直接说明“大规模碎片下错误邻接会产生级联失败”，因此预测关系不能写成永久事实；本项目可借鉴“先预测—再验证—只软写入可靠结构—不确定部分允许重算”的闭环。',
        'v1 讨论错误邻接的级联风险；v2 的几何验证/重采样支持“先预测—再验证—不确定部分允许重算”的设计类比，但不证明本项目关系记忆有效。',
        'A6.14 SARe version-bounded interpretation', mutations)
    ri,cells=row_by_prefix['GARF:']
    replace_flat(cells[1], 'one-step preassembly', 'two-session flow matching（单步预装配初始化＋多步细化）', 'A6.14 GARF inference wording', mutations)
    ri,cells=row_by_prefix['TORA:']
    replace_flat(cells[0], 'arXiv:2604.04050', 'ECCV 2026 accepted；arXiv:2604.04050', 'A6.14 TORA venue', mutations)
    replace_flat(cells[3], '当前作为预印本思想来源', '已标注为 ECCV 2026 accepted；仍须单独验证 teacher 选择、蒸馏损失和推理增益', 'A6.14 TORA status', mutations)
    ri,cells=row_by_prefix['MV-RoMa:']
    replace_flat(cells[0], '（2026，arXiv:2603.27542）', '（CVPR 2026 accepted；arXiv:2603.27542）', 'A6.14 MV-RoMa venue', mutations)
    ri,cells=row_by_prefix['Coconut /']
    replace_flat(cells[0], 'arXiv:2412.06769；ICLR 2025 workshop', 'arXiv:2412.06769 v4；COLM 2025 accepted（ICLR 2025 workshop为可选历史）', 'A6.14 Coconut current venue', mutations)

    def patch_ref(prefix, old, new, label):
        found = [p for p in direct_ps(body) if p_text(p).startswith(prefix)]
        if len(found) != 1: raise SystemExit(f'{label}: bibliography paragraph count {len(found)}')
        replace_flat(found[0], old, new, label, mutations)
    patch_ref('1. Jia et al. SARe:', 'SARe: Structure-Aware Large-Scale 3D Fragment Reassembly. arXiv:2603.21611, 2026.',
        'SARe: Structure-Aware Generative 3D Fragment Reassembly. arXiv:2603.21611 v2, 2026. https://arxiv.org/abs/2603.21611v2', 'A6.24 SARe bibliography/version/URL')
    patch_ref('3. Li et al. GARF:', 'ICCV 2025.',
        'ICCV 2025. Two-session flow matching: one-step preassembly initialization plus multi-step refinement. https://openaccess.thecvf.com/content/ICCV2025/papers/Li_GARF_Learning_Generalizable_3D_Reassembly_for_Real-World_Fractures_ICCV_2025_paper.pdf', 'A6.24 GARF proceedings/method/URL')
    patch_ref('6. Lee et al. TORA:', 'arXiv:2604.04050, 2026.',
        'ECCV 2026 accepted; arXiv:2604.04050, 2026. https://arxiv.org/abs/2604.04050', 'A6.24 TORA venue/URL')
    patch_ref('10. Lee, Kang, Yoo. MV-RoMa:', 'arXiv:2603.27542, 2026.',
        'CVPR 2026 accepted; arXiv:2603.27542, 2026. https://arxiv.org/abs/2603.27542', 'A6.24 MV-RoMa venue/URL')
    patch_ref('13. Hao et al. Training Large Language Models', 'arXiv:2412.06769; ICLR 2025 Workshop.',
        'arXiv:2412.06769 v4; COLM 2025 accepted (ICLR 2025 workshop is optional history). https://arxiv.org/abs/2412.06769v4 ; https://colmweb.org/2025/AcceptedPapers.html', 'A6.24 Coconut current venue/URL')

    # Append the EXP12 corruption denominators and independent-error replay protocol before A9.
    exp12 = headings['EXP12']
    a9_hits = [p for p in direct_ps(body) if p_text(p).strip().startswith('A9 结果归档与常见失败处理')]
    if len(a9_hits) != 1 or body.index(a9_hits[0]) <= body.index(exp12): raise SystemExit('EXP12/A9 boundary missing')
    exp12_prev = next(p for p in reversed(direct_ps(body)[:body.index(a9_hits[0])]) if p_text(p).strip())
    exp12_add = ('EXP12 腐化分母与 STOP 端点：分别报告漏失真 R2、错误接受 R2、R1↔R2 交换、错误成员纳入和来源相关边的计数/分母；'
        '0/5/10/20/30% 只是压力配方，不预称现实错误率。错误率须在独立冻结器物上测得并重放实际分类型及来源相关结构；没有 R2 seed 或 memory 为空时必须退回静态基线。报告成员错误注入、覆盖—风险与端到端成本，不只报 R1 Hit@K。')
    insert_before(body, a9_hits[0], exp12_add, exp12_prev, mutations, 'EXP12 corruption denominators and empty-memory STOP')

    # Separate changes to observations from physical wear/new fracture events.
    a1221 = headings['A12.21']; a1222 = headings['A12.22']
    a1221_ps = [p for p in direct_ps(body) if body.index(a1221) < body.index(p) < body.index(a1222)]
    truthpack_ps = [p for p in a1221_ps if 'TruthPack' in p_text(p)]
    if len(truthpack_ps) != 1: raise SystemExit(f'A12.21 TruthPack paragraph count {len(truthpack_ps)}')
    replace_flat(truthpack_ps[0], 'TruthPack只供评测',
        'TruthPack 用于离线评测；关系/成员 GT 可隔离作为监督目标或离线 Oracle，模型输入仅限 allowlisted Obs，GT 不得写入输入、memory 或 candidate generator',
        'A12.21 supervised-label versus runtime permission', mutations)
    a1221_add = ('退化真值分轨：观测扰动轨固定历史 GT，只改遮挡、成像、重建缺失等可见性；真实磨损、材料移除、新崩口或二次碎裂另建事件轨，保存 parent/child leaf lineage、current_fit_valid、evidence_visible 与版本化 current-leaf relations，同时单独保留历史 R2 事实。'
        'D1–D4 在独立标定前只是软件 recipe，D5 是真实域独立确认而非有序标量严重度；31 个退化轴仍属软件 QA/UNCAL，不作年代或物理严重度声明。')
    insert_before(body, a1222, a1221_add, a1221_ps[-1], mutations, 'A12.21 observation versus physical-event degradation')

    # D6.5 interaction contract: explain uncertainty, evidence and real-data eligibility.
    d65 = headings['D6.5']; d7_hits = [p for p in direct_ps(body) if p_text(p).strip().startswith('D7 首版与后续版本路线')]
    if len(d7_hits) != 1 or body.index(d7_hits[0]) <= body.index(d65): raise SystemExit('D6.5/D7 boundary missing')
    d65_prev = next(p for p in reversed(direct_ps(body)[:body.index(d7_hits[0])]) if p_text(p).strip())
    d65_add = ('证据不足时，成员视图必须显示 UNKNOWN/证据不足、缺失证据与可执行补采建议（含预算），并给出 STOP 或 revision 原因；不得强制分配成员或自动恢复/确认器物。'
        '有合格真实观测、冻结图库和闭合成员 GT 时，可进行真实数据静态、成员或关系上下文测试；物理合格 synthetic pack 只约束物理合成、物理退化和合成预训练主张，不是这些真实数据测试的通用前置条件。')
    insert_before(body, d7_hits[0], d65_add, d65_prev, mutations, 'D6.5 evidence insufficiency, recapture, STOP and real-data eligibility')

    # Keep all 33 added section headings reachable without disturbing historical links.
    ps = direct_ps(body)
    nav_heading_hits = [p for p in ps if p_text(p).strip() == '文档导航']
    if len(nav_heading_hits) != 1: raise SystemExit(f'Expected one front navigation heading, got {len(nav_heading_hits)}')
    max_old_bookmark = max(int(n.get(Q('id'))) for n in doc.findall('.//w:bookmarkStart', NS))
    existing_bookmark_ids = {(n.get(Q('id')), n.get(Q('name'))) for n in doc.findall('.//w:bookmarkStart', NS)}
    existing_bookmark_ends = [n.get(Q('id')) for n in doc.findall('.//w:bookmarkEnd', NS)]
    if len(existing_bookmark_ids) != 520 or len(existing_bookmark_ends) != 520: raise SystemExit('Incoming old bookmark identity count changed')
    new_links = []
    new_heading_map = heading_paragraphs(direct_ps(body), diff)
    for idx, item in enumerate(diff['new_heading_ids_and_titles']):
        code = item['heading'].split()[0]
        p = new_heading_map[code]
        b_id = max_old_bookmark + idx + 1
        b_name = f'RWV147_N{idx+1:03d}'
        add_heading_bookmark(p, b_id, b_name)
        new_links.append({'section_code': code, 'heading_sha256': sha_bytes(p_text(p).encode('utf-8')), 'bookmark_id': b_id, 'bookmark_name': b_name})
    nav_p = make_para(nav_heading_hits[0], 'V1.47新增章节：', style_id='Normal')
    nav_ppr = nav_p.find(Q('pPr'))
    if nav_ppr is None:
        nav_ppr = etree.Element(Q('pPr')); nav_p.insert(0, nav_ppr)
    spacing = nav_ppr.find(Q('spacing'))
    if spacing is None: spacing = etree.SubElement(nav_ppr, Q('spacing'))
    spacing.set(Q('after'), '40')
    for i, item in enumerate(new_links):
        if i:
            sep = etree.SubElement(nav_p, Q('r'))
            rpr = etree.SubElement(sep, Q('rPr'))
            sz = etree.SubElement(rpr, Q('sz')); sz.set(Q('val'), '14')
            st = etree.SubElement(sep, Q('t')); st.text = ' · '
        add_nav_link(nav_p, item['bookmark_name'], item['section_code'])
    body.insert(body.index(nav_heading_hits[0]) + 1, nav_p)
    insertions.append({'label': 'compact front navigation for all 33 new headings', 'links': len(new_links), 'section_codes': [x['section_code'] for x in new_links]})

    # Fix only explicit East Asian fallback references in imported document.xml.
    font_refs = doc.xpath('.//w:rFonts[@w:eastAsia=$font]', namespaces=NS, font='Droid Sans Fallback')
    for ref in font_refs: ref.set(Q('eastAsia'), 'Noto Sans SC')
    format_changes.append({'kind': 'eastAsia_font_mapping', 'from': 'Droid Sans Fallback', 'to': 'Noto Sans SC', 'references_changed': len(font_refs), 'scope': 'imported word/document.xml only'})

    # Preserve the approved low-contrast A12.17 dark-header fix, identified by its exact header text.
    contrast_expected = ['功能域', '责任项目 / 默认接口', '详细实施位置']
    contrast_hits = []
    for ti, table in enumerate(direct_tables(body), 1):
        rows = table.findall(Q('tr'))
        if not rows: continue
        first = [text(c) for c in rows[0].findall(Q('tc'))]
        if first == contrast_expected: contrast_hits.append((ti, table))
    if len(contrast_hits) != 1: raise SystemExit(f'A12.17 exact header table count {len(contrast_hits)}')
    contrast_table_idx, contrast_table = contrast_hits[0]
    color_count = set_white_header(contrast_table, contrast_expected, 'A12.17 table-39 dark header')
    format_changes.append({'kind': 'A12.17 dark-header contrast', 'table_index_in_user_candidate': contrast_table_idx, 'header_cells': len(contrast_expected), 'text_runs_explicitly_white': color_count, 'header_text': contrast_expected})

    # Apply only the three approved local line breaks in TRELLIS.2 cells; no width edits.
    trellis_info = insert_linebreaks_in_trellis(body, break_log)
    format_changes.append({'kind': 'TRELLIS.2 manual line breaks', **trellis_info, 'breaks_added': len(break_log)})

    # INNO-32 through INNO-45 are imported in full and must stay research/idea entries.
    ledger_rows = []
    for table_index, table in enumerate(direct_tables(body), 1):
        for row_index, row in enumerate(table.findall(Q('tr'))):
            row_text = ' '.join(text(c) for c in row.findall(Q('tc')))
            for n in range(32, 46):
                token = f'INNO-{n}'
                if token in row_text:
                    status = next((s for s in ('RESEARCH_CANDIDATE', 'IDEA', 'RESEARCH') if s in row_text), None)
                    if status is None: raise SystemExit(f'{token} lacks a research status in its row')
                    ledger_rows.append({'id': token, 'status': status, 'table': table_index, 'row': row_index, 'row_sha256': sha_bytes(row_text.encode('utf-8'))})
    if sorted(x['id'] for x in ledger_rows) != [f'INNO-{n}' for n in range(32, 46)]:
        raise SystemExit('INNO-32..45 not all present exactly in research ledger rows')

    # In-memory proof that all donor body paragraphs and tables remain ordered and present.
    preserved_original_children = [e for e in body if id(e) in {id(x) for x in original_body_children}]
    if preserved_original_children != original_body_children: raise SystemExit('Original user body children moved, removed, or duplicated')
    after_text_hashes = [sha_bytes((e.tag.rsplit('}',1)[-1] + '\0' + text(e)).encode('utf-8')) for e in preserved_original_children]
    if len(original_text_hashes) != len(after_text_hashes): raise SystemExit('Donor body text-block count mismatch')

    # Current status paragraphs and front summary are exact, present once after all insertions.
    final_ps = direct_ps(body)
    protected_statuses = []
    for status in diff['exact_closeout_status_paragraphs_missing_from_user_doc']:
        matches = [p for p in final_ps if p_text(p) == status['text']]
        if len(matches) != 1: raise SystemExit(f"Protected status paragraph not unique: {status['heading']}")
        protected_statuses.append({'section': status['heading'], 'chars': len(status['text']), 'sha256': sha_bytes(status['text'].encode('utf-8'))})
    if sum(p_text(p) == text(current_summary) for p in final_ps) != 1: raise SystemExit('Protected current p5 summary missing/duplicated')

    # Recheck all 33 old section codes remain navigable, all old book IDs/names remain present.
    current_bookmarks = {(n.get(Q('id')), n.get(Q('name'))) for n in doc.findall('.//w:bookmarkStart', NS)}
    if not existing_bookmark_ids.issubset(current_bookmarks): raise SystemExit('One or more original bookmark identities were lost')
    new_bookmarks = [x for x in current_bookmarks if x[1] and x[1].startswith('RWV147_N')]
    if len(new_bookmarks) != 33: raise SystemExit(f'Expected 33 new bookmarks, got {len(new_bookmarks)}')
    hyperlinks = doc.findall('.//w:hyperlink', NS)
    if len(hyperlinks) != 113: raise SystemExit(f'Expected 80 existing + 33 new hyperlinks, got {len(hyperlinks)}')
    new_anchor_links = [h for h in hyperlinks if h.get(Q('anchor'), '').startswith('RWV147_N')]
    if len(new_anchor_links) != 33: raise SystemExit(f'Expected 33 new anchor links, got {len(new_anchor_links)}')
    if len(doc.findall('.//w:bookmarkStart', NS)) != len(doc.findall('.//w:bookmarkEnd', NS)):
        raise SystemExit('Bookmark start/end count mismatch')
    if doc.xpath('.//w:rFonts[@w:eastAsia=$font]', namespaces=NS, font='Droid Sans Fallback'):
        raise SystemExit('Unmapped explicit East Asian fallback remains in imported document.xml')

    # Confirm only the user-input relationships/package parts plus merged document.xml differ from current base.
    merged_xml = etree.tostring(doc, xml_declaration=True, encoding='UTF-8', standalone=True)
    output_parts = dict(current_parts)
    output_parts['word/document.xml'] = merged_xml
    with ZipFile(CURRENT, 'r') as zin, ZipFile(CANDIDATE, 'w', ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = merged_xml if info.filename == 'word/document.xml' else current_parts[info.filename]
            zout.writestr(info, data)
    candidate_hash = sha_file(CANDIDATE)

    # Reopen the written archive so the proof is about the saved candidate, not only the in-memory tree.
    saved_parts = read_pkg(CANDIDATE)
    saved_doc = etree.fromstring(saved_parts['word/document.xml'], PARSER)
    saved_body = saved_doc.find('.//w:body', NS)
    saved_ps = direct_ps(saved_body)
    saved_tables = direct_tables(saved_body)
    expected_non_document_unchanged = all(saved_parts[n] == current_parts[n] for n in current_parts if n != 'word/document.xml')
    if not expected_non_document_unchanged: raise SystemExit('Non-document package part unexpectedly changed')
    if saved_parts['word/_rels/document.xml.rels'] != current_parts['word/_rels/document.xml.rels']:
        raise SystemExit('Document relationships changed')
    if len(saved_tables) != 194: raise SystemExit(f'Expected imported 194 tables, got {len(saved_tables)}')
    if len(saved_doc.findall('.//w:bookmarkStart', NS)) != 553 or len(saved_doc.findall('.//w:bookmarkEnd', NS)) != 553:
        raise SystemExit('Expected 520 original and 33 new balanced bookmarks')
    if len(saved_doc.findall('.//w:hyperlink', NS)) != 113: raise SystemExit('Saved link count mismatch')
    if len(saved_ps) < 2450: raise SystemExit(f'Saved paragraph count implausible: {len(saved_ps)}')

    proof = {
        'purpose': 'Static merge validation only. Candidate is not promoted and has not been rendered.',
        'inputs': {k: {'path': str(p), 'bytes': p.stat().st_size, 'sha256': sha_file(p)} for k,p in [('current_closeout', CURRENT),('user_input',USER),('v146_baseline',V146)]},
        'candidate': {'path': str(CANDIDATE), 'bytes': CANDIDATE.stat().st_size, 'sha256': candidate_hash},
        'package': {'parts': len(saved_parts), 'non_document_parts_byte_identical_to_current_closeout': expected_non_document_unchanged, 'document_relationships_byte_identical': saved_parts['word/_rels/document.xml.rels'] == current_parts['word/_rels/document.xml.rels'], 'tables': len(saved_tables), 'paragraphs': len(saved_ps), 'bookmark_starts': len(saved_doc.findall('.//w:bookmarkStart', NS)), 'bookmark_ends': len(saved_doc.findall('.//w:bookmarkEnd', NS)), 'hyperlinks': len(saved_doc.findall('.//w:hyperlink', NS))},
        'original_user_body': {'direct_text_blocks': len(original_text_hashes), 'all_original_paragraph_table_nodes_retained_in_original_order_before_save': True, 'before_text_hashes': original_text_hashes, 'after_text_hashes': after_text_hashes},
        'protected_current_state': {'seven_status_paragraphs': protected_statuses, 'front_scientific_summary_sha256': sha_bytes(text(current_summary).encode('utf-8')), 'front_scientific_summary_present_once': True},
        'new_heading_navigation': new_links,
        'innovation_ledger': ledger_rows,
        'approved_text_mutations': mutations,
        'format_only_changes': format_changes,
        'trellis_breaks': break_log,
        'static_checks': {
            'source_hash_pins_match': True, 'original_relationships_preserved': True,
            'all_520_original_bookmark_id_name_pairs_preserved': True, '33_new_unique_bookmarks_and_anchor_links': True,
            'all_original_80_hyperlinks_retained_plus_33_new': True, 'all_14_innovations_retained_as_research_or_idea': True,
            'A12_17_dark_header_text_explicit_white': True, 'Droid_eastAsia_mapped_in_imported_document_xml': len(font_refs),
            'TRELLIS_2_exactly_three_breaks_text_unchanged': len(break_log) == 3,
            'candidate_rendered': False, 'root_master_modified': False,
        },
        'root_approved_scope': compact['root_approved_patch_spec'],
    }
    proof_path = OUTDIR / 'merge_static_validation.json'
    proof_path.write_text(json.dumps(proof, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')
    proof_hash = sha_file(proof_path)
    md_path = OUTDIR / 'merge_CHANGELOG.md'
    md = f'''# V1.47 research-plan merge candidate — static review only\n\n**Candidate:** `{CANDIDATE}`  \n**Bytes:** {CANDIDATE.stat().st_size}  \n**SHA-256:** `{candidate_hash}`  \n**Static proof:** `{proof_path}` (SHA-256 `{proof_hash}`)\n\nThe candidate uses the reviewed user V1.47 document body and current V1.47 closeout package parts. It preserves the user's new research proposal and all INNO-32–INNO-45 entries as RESEARCH_CANDIDATE/IDEA, reinserts seven exact implementation-status paragraphs plus the current front scientific status summary, and applies only the root-approved content and local-format patches recorded in `merge_static_validation.json`.\n\nStatic verification confirms 23 package parts, 194 tables, 553 balanced bookmarks (the original 520 identities plus 33 new anchors), 113 hyperlinks (the original 80 plus 33 front-navigation links), unchanged package relationships and unchanged non-document parts from the frozen closeout base. Every source/user body paragraph and table node remains in its original order before save. The saved candidate has not been rendered, promoted, or copied over the frozen master.\n\nThe document XML includes the corrected frozen-gallery member contract, empty-set/whole-workflow metrics, GT permission boundary, relation ontology, same-style hard negatives, belief/calibration rule, Oracle controls, EXP12 corruption denominators, observation-vs-physical-event degradation split, D6.5 evidence/STOP behavior, reference-version corrections, unique heading navigation, approved A12.17 header contrast, East Asian font mapping, and exactly three TRELLIS.2 manual breaks. No solver, CAD, source-code, or numerical task was run.\n'''
    md_path.write_text(md, encoding='utf-8')
    print(f'candidate={CANDIDATE}')
    print(f'candidate_bytes={CANDIDATE.stat().st_size}')
    print(f'candidate_sha256={candidate_hash}')
    print(f'static_proof={proof_path}')
    print(f'static_proof_bytes={proof_path.stat().st_size}')
    print(f'static_proof_sha256={proof_hash}')
    print(f'changelog={md_path}')
    print(f'changelog_sha256={sha_file(md_path)}')
    print(f'body_paragraphs={len(saved_ps)} tables={len(saved_tables)} bookmarks=553 hyperlinks=113')

if __name__ == '__main__': main()
