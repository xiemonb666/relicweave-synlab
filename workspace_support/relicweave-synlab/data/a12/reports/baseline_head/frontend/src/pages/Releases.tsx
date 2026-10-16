/**
 * U08 数据发布 `/synlab/releases`（计划 20.9）。
 *
 * 真实调用：`POST /audits` + `GET /audits` + `GET /audits/{id}`（gate 结果与证据，未运行即 NOT_RUN）、
 * `POST /releases` + `GET /releases` + `GET /releases/{id}`（只读 manifest / hash / coverage / closure）、
 * `POST /exports` + `GET /exports/{id}`（导出不修改原 release）。
 *
 * 已知后端缺陷（本页会把它当作真实错误显示）：`POST /audits` 目前总会以
 * `500 INTERNAL_ERROR / KeyError: 'asset_ids'` 失败 —— `synlab/api/routers/governance.py`
 * 把 scope 作为 `scope` 传参，而 `synlab/api/tables.py::insert` 只识别 `scope_json` 列，
 * 写入后读回时 `row["scope"]` 是空 dict。文档 docs/a12/api_ui.md 记录了该差异。
 */

import { useState } from 'react';

import { AssetBrowser } from '../components/AssetBrowser';
import { CoverageMatrix } from '../components/CoverageMatrix';
import { SchemaForm, type FieldSpec, type FormValue } from '../components/SchemaForm';
import {
  ActionButton,
  Badge,
  CopyValue,
  EmptyState,
  ErrorState,
  KeyValueList,
  LoadingState,
  PageHeader,
  SectionCard,
} from '../components/states';
import { getAudit, getExport, getRelease, listAudits, listReleases, postAudits, postExports, postReleases } from '../api/endpoints';
import { useResource } from '../api/hooks';
import type { AuditGateBlock, CoverageBlock } from '../api/types';
import { formatTimestamp, gateLabel, gateTone, pretty, truncate } from '../lib/format';
import { useAppState } from '../state/app-state';

const RELEASE_PROFILES = [
  'SANDBOX_CORE',
  'PILOT',
  'CORE_COVERAGE',
  'SCALE_10K',
  'SCALE_50K',
  'SCALE_100K',
  'CALIBRATED_PHONE',
  'RESEARCH_EVIDENCE',
];

const AUDIT_FIELDS: FieldSpec[] = [
  { kind: 'string', path: 'run_id', label: 'run_id（可选）', hint: '审计该 run 的所有 job 输出' },
  { kind: 'string', path: 'release_id', label: 'release_id（可选）', hint: '审计既有 release 的资产集合' },
  { kind: 'stringList', path: 'asset_ids', label: 'asset_ids（可选）', hint: '直接指定资产；与 run/release 可叠加' },
  { kind: 'string', path: 'release_profile', label: 'release profile', enumValues: RELEASE_PROFILES },
  { kind: 'boolean', path: 'include_truth', label: '包含真值（需要 researcher 会话）' },
];

const RELEASE_FIELDS: FieldSpec[] = [
  { kind: 'string', path: 'release_id', label: 'release_id', required: true, hint: '3–96 字符' },
  { kind: 'string', path: 'profile', label: 'profile', required: true, enumValues: RELEASE_PROFILES },
  { kind: 'string', path: 'scope', label: 'scope', enumValues: ['SYNTHETIC', 'REAL'] },
  { kind: 'string', path: 'audit_id', label: 'audit_id', required: true, hint: '必须是一个已经产生 result 的 audit' },
  { kind: 'stringList', path: 'asset_ids', label: 'asset_ids（至少 1 个）', required: true },
  { kind: 'stringList', path: 'scope_pending', label: 'scope_pending（声明未完成的范围）' },
];

export function ReleasesPage() {
  const app = useAppState();
  const audits = useResource((signal) => listAudits({ limit: 50 }, signal), [], { intervalMs: 20_000 });
  const releases = useResource((signal) => listReleases({ limit: 50 }, signal), [], { intervalMs: 20_000 });
  const [selectedAuditId, setSelectedAuditId] = useState<string | null>(null);
  const [selectedReleaseId, setSelectedReleaseId] = useState<string | null>(null);
  const [auditDraft, setAuditDraft] = useState<FormValue>({ release_profile: 'SANDBOX_CORE' });
  const [releaseDraft, setReleaseDraft] = useState<FormValue>({ profile: 'SANDBOX_CORE', scope: 'SYNTHETIC' });
  const [auditAction, setAuditAction] = useState<{ status: 'idle' | 'busy' | 'ok' | 'error'; response?: unknown; error?: unknown }>({
    status: 'idle',
  });
  const [releaseAction, setReleaseAction] = useState<{ status: 'idle' | 'busy' | 'ok' | 'error'; response?: unknown; error?: unknown }>({
    status: 'idle',
  });
  const [exportDraft, setExportDraft] = useState<{ adapter: 'manifest' | 'obs_pack' | 'feature_bundle' | 'oracle_truth' }>({
    adapter: 'manifest',
  });
  const [exportId, setExportId] = useState('');
  const [exportAction, setExportAction] = useState<{ status: 'idle' | 'busy' | 'ok' | 'error'; response?: unknown; error?: unknown }>({
    status: 'idle',
  });

  const auditDetail = useResource((signal) => getAudit(selectedAuditId as string, signal), [selectedAuditId], {
    enabled: Boolean(selectedAuditId),
    intervalMs: selectedAuditId ? 8000 : 0,
  });
  const releaseDetail = useResource((signal) => getRelease(selectedReleaseId as string, signal), [selectedReleaseId], {
    enabled: Boolean(selectedReleaseId),
  });
  const exportDetail = useResource((signal) => getExport(exportId, signal), [exportId], {
    enabled: exportId.length > 0,
    intervalMs: exportId ? 8000 : 0,
  });

  const selectedAuditResult = auditDetail.data?.audit.result as AuditGateBlock | undefined;
  const selectedAuditGates = selectedAuditResult?.gates ?? {};
  const auditHasResult = Boolean(auditDetail.data && Object.keys(auditDetail.data.audit.result ?? {}).length > 0);

  const coverageSource =
    (selectedAuditResult?.coverage as Record<string, unknown> | undefined) ??
    (releaseDetail.data?.coverage && Object.keys(releaseDetail.data.coverage).length > 0 ? releaseDetail.data.coverage : null);

  const gateEntries = Object.entries(selectedAuditGates).filter(([, value]) => typeof value === 'object');

  const submitAudit = async () => {
    setAuditAction({ status: 'busy' });
    try {
      const response = await postAudits({
        run_id: (auditDraft.run_id as string) || null,
        release_id: (auditDraft.release_id as string) || null,
        asset_ids: Array.isArray(auditDraft.asset_ids) ? (auditDraft.asset_ids as string[]) : [],
        release_profile: (auditDraft.release_profile as string) || 'SANDBOX_CORE',
        include_truth: auditDraft.include_truth === true,
      });
      setAuditAction({ status: 'ok', response });
      audits.reload();
      const auditId = (response as { audit_id?: string }).audit_id;
      if (auditId) setSelectedAuditId(auditId);
    } catch (error) {
      setAuditAction({ status: 'error', error });
    }
  };

  const submitRelease = async () => {
    setReleaseAction({ status: 'busy' });
    try {
      const response = await postReleases({
        release_id: String(releaseDraft.release_id ?? ''),
        profile: String(releaseDraft.profile ?? ''),
        scope: (releaseDraft.scope as 'SYNTHETIC' | 'REAL') ?? 'SYNTHETIC',
        asset_ids: Array.isArray(releaseDraft.asset_ids) ? (releaseDraft.asset_ids as string[]) : [],
        audit_id: String(releaseDraft.audit_id ?? ''),
        scope_pending: Array.isArray(releaseDraft.scope_pending) ? (releaseDraft.scope_pending as string[]) : [],
      });
      setReleaseAction({ status: 'ok', response });
      releases.reload();
      setSelectedReleaseId(String(releaseDraft.release_id ?? ''));
    } catch (error) {
      setReleaseAction({ status: 'error', error });
    }
  };

  const submitExport = async () => {
    if (!selectedReleaseId) return;
    setExportAction({ status: 'busy' });
    try {
      const response = await postExports({ release_id: selectedReleaseId, adapter: exportDraft.adapter });
      setExportAction({ status: 'ok', response });
      setExportId(response.export_id);
    } catch (error) {
      setExportAction({ status: 'error', error });
    }
  };

  return (
    <>
      <PageHeader
        title="数据发布"
        plan="U08 · 计划 20.9"
        summary="覆盖矩阵、谱系拆分、权限审计、失败/接受率、实际数据产品、版本引用闭包、计划与完成数；审计 → gate 全 PASS 才允许冻结只读 release。"
        actions={
          <div className="row">
            <Badge tone="info">release 不可变，修复必须新建版本</Badge>
            <Badge tone="warn">审计接口当前存在后端缺陷</Badge>
          </div>
        }
      />

      <SectionCard
        title="发起审计"
        subtitle="POST /audits（run/release scope → 真实 audit job；未运行时 GET 返回 NOT_RUN）"
      >
        <div className="grid2">
          <div>
            <SchemaForm fields={AUDIT_FIELDS} value={auditDraft} onChange={setAuditDraft} advanced={false} label="审计表单" />
            <div className="row">
              <ActionButton tone="primary" onClick={() => void submitAudit()} busy={auditAction.status === 'busy'}>
                提交审计
              </ActionButton>
              <span className="muted small">
                include_truth 需要 researcher 会话，否则后端返回 403 ROLE_FORBIDDEN。
              </span>
            </div>
          </div>
          <div>
            {auditAction.status === 'ok' ? (
              <div className="accepted" role="status">
                <h4>审计已受理</h4>
                <pre className="mono pre">{pretty(auditAction.response)}</pre>
              </div>
            ) : null}
            {auditAction.status === 'error' ? (
              <>
                <ErrorState error={auditAction.error} title="审计请求失败（后端真实响应）" />
                <p className="warning">
                  这是本仓库已知的后端缺陷：<code className="mono">POST /audits</code> 在写入 scope 时使用了错误的列名，
                  读回后 <code className="mono">row[&quot;scope&quot;][&quot;asset_ids&quot;]</code> 触发{' '}
                  <code className="mono">KeyError</code>，因此**任何**调用都会 500，审计无法创建。
                  页面不伪造 audit 结果；请在 docs/a12/api_ui.md 的差异表中查看完整定位，或改由 CLI 路径{' '}
                  <code className="mono">python -m synlab.cli audit --run &lt;run_id&gt;</code> 产生审计证据。
                </p>
              </>
            ) : null}
          </div>
        </div>
      </SectionCard>

      <SectionCard
        title="审计列表与 gate 结果"
        subtitle="GET /audits · GET /audits/{id}（status NOT_RUN/QUEUED/RUNNING 时不会有任何 gate 结论）"
        actions={
          <button type="button" className="btn btn--tiny" onClick={audits.reload} disabled={audits.refreshing}>
            {audits.refreshing ? '刷新中…' : '刷新'}
          </button>
        }
      >
        {audits.status === 'loading' ? <LoadingState label="读取审计列表…" /> : null}
        {audits.status === 'error' ? <ErrorState error={audits.error} onRetry={audits.reload} /> : null}
        {audits.data ? (
          audits.data.items.length === 0 ? (
            <EmptyState title="还没有审计" reason={audits.data.empty_reason ?? undefined} />
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">选择</th>
                  <th scope="col">audit_id</th>
                  <th scope="col">profile</th>
                  <th scope="col">status</th>
                  <th scope="col">job</th>
                  <th scope="col">result</th>
                  <th scope="col">创建</th>
                </tr>
              </thead>
              <tbody>
                {audits.data.items.map((audit) => (
                  <tr key={audit.audit_id} className={selectedAuditId === audit.audit_id ? 'row--selected' : undefined}>
                    <td>
                      <input
                        type="radio"
                        name="audit-select"
                        checked={selectedAuditId === audit.audit_id}
                        onChange={() => setSelectedAuditId(audit.audit_id)}
                        aria-label={`选择审计 ${audit.audit_id}`}
                      />
                    </td>
                    <td className="mono">{truncate(audit.audit_id, 24)}</td>
                    <td className="mono">{String((audit.scope as Record<string, unknown>)?.release_profile ?? '—')}</td>
                    <td>
                      <Badge tone={audit.status === 'COMPLETED' ? 'ok' : audit.status === 'FAILED' ? 'bad' : 'warn'}>
                        {audit.status}
                      </Badge>
                    </td>
                    <td className="mono small">{audit.job_id ? truncate(audit.job_id, 16) : '—'}</td>
                    <td>{Object.keys(audit.result ?? {}).length > 0 ? <Badge tone="ok">有结果</Badge> : <Badge tone="warn">空（未运行）</Badge>}</td>
                    <td>{formatTimestamp(audit.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        ) : null}

        {selectedAuditId ? (
          auditDetail.status === 'error' ? (
            <ErrorState error={auditDetail.error} onRetry={auditDetail.reload} />
          ) : auditDetail.data ? (
            <>
              <h3>
                审计详情 <span className="mono">{auditDetail.data.audit.audit_id}</span>
                {auditDetail.data.audit.truth_hidden ? <Badge tone="warn">真值依据对当前角色隐藏</Badge> : null}
              </h3>
              <KeyValueList
                rows={[
                  { label: 'status', value: auditDetail.data.audit.status },
                  { label: 'run / release', value: `${auditDetail.data.audit.run_id ?? '—'} / ${auditDetail.data.audit.release_id ?? '—'}`, mono: true },
                  { label: '必需 gate（该 profile）', value: auditDetail.data.profile_gates.join(', ') || '（profile 无必需 gate 或未知 profile）' },
                  { label: 'job', value: auditDetail.data.job ? `${auditDetail.data.job.job_id} · ${auditDetail.data.job.state}` : '未创建', mono: true },
                  { label: 'release_ready', value: String(selectedAuditResult?.release_ready ?? '未提供') },
                  { label: 'note', value: auditDetail.data.note },
                ]}
              />

              {!auditHasResult ? (
                <EmptyState
                  title="这份审计还没有结果"
                  reason="status 不是终态时后端不会推断任何 gate 结论。请等 worker 执行完（GET /jobs/{job_id} 或 SSE 事件）。"
                />
              ) : (
                <>
                  <table className="table">
                    <caption>gate 结果（来自 audit.result.gates.gates）</caption>
                    <thead>
                      <tr>
                        <th scope="col">gate</th>
                        <th scope="col">状态</th>
                        <th scope="col">是否必需</th>
                        <th scope="col">依据 / 原因</th>
                      </tr>
                    </thead>
                    <tbody>
                      {gateEntries.map(([gate, value]) => {
                        const info = value as { status?: string; reason?: string };
                        const status = info.status ?? 'PENDING';
                        return (
                          <tr key={gate}>
                            <th scope="row" className="mono">
                              {gate}
                            </th>
                            <td>
                              <Badge tone={gateTone(status)}>{gateLabel(status)}</Badge>
                            </td>
                            <td>{(selectedAuditResult?.required_gates ?? []).includes(gate) ? '必需' : '非必需'}</td>
                            <td className="small">{info.reason ?? pretty(value)}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                  <pre className="mono pre">{pretty(selectedAuditResult)}</pre>
                </>
              )}
            </>
          ) : (
            <LoadingState label="读取审计详情…" />
          )
        ) : null}
      </SectionCard>

      <SectionCard title="覆盖矩阵" subtitle="来自 audit.result.coverage 或 release.coverage（后端 COVERAGE_SPECS）">
        {coverageSource ? (
          <CoverageMatrix
            coverage={coverageSource}
            onSelectAsset={(assetId) => app.openProvenance({ kind: 'asset', id: assetId })}
          />
        ) : (
          <EmptyState
            title="没有覆盖矩阵"
            reason={
              <>
                覆盖矩阵由审计阶段真实统计（<code className="mono">coverage_matrix()</code>）。
                当前既没有已完成的审计，所选 release 也没有 coverage 字段，因此没有任何覆盖结论可显示。
              </>
            }
          />
        )}
        {coverageSource ? (
          <details>
            <summary>coverage 原始 JSON</summary>
            <pre className="mono pre">{pretty(coverageSource)}</pre>
          </details>
        ) : null}
        <p className="muted small">
          覆盖维度键：{coverageSource ? Object.keys(coverageSource).join(', ') : '—'}（其中形如
          <code className="mono"> coverage_* </code>的键会被渲染成矩阵块）。
        </p>
        {coverageSource
          ? (Object.entries(coverageSource).filter(([, value]) => typeof value === 'object') as Array<[string, CoverageBlock]>).length === 0
            ? <p className="warning">coverage 对象里没有可识别的维度块。</p>
            : null
          : null}
      </SectionCard>

      <SectionCard title="冻结 release" subtitle="POST /releases（gate pass 才能冻结；审计无 result 时后端 409 STOP_QA）">
        <div className="grid2">
          <div>
            <SchemaForm fields={RELEASE_FIELDS} value={releaseDraft} onChange={setReleaseDraft} advanced={false} label="release 表单" />
            <div className="row">
              <ActionButton
                tone="primary"
                onClick={() => void submitRelease()}
                busy={releaseAction.status === 'busy'}
                disabledReason={
                  !releaseDraft.release_id
                    ? 'release_id 不能为空'
                    : !releaseDraft.audit_id
                      ? 'audit_id 不能为空（release 必须挂在已产生 result 的审计上）'
                      : !Array.isArray(releaseDraft.asset_ids) || (releaseDraft.asset_ids as string[]).length === 0
                        ? 'asset_ids 至少需要一个资产'
                        : null
                }
              >
                冻结只读 release
              </ActionButton>
              <span className="muted small">
                可选：从下表点击一个 release_id 填充“打开对照版本”。当前选中：{selectedReleaseId ?? '无'}
              </span>
            </div>
          </div>
          <div>
            {releaseAction.status === 'ok' ? (
              <div className="accepted" role="status">
                <h4>release 已冻结</h4>
                <pre className="mono pre">{pretty(releaseAction.response)}</pre>
              </div>
            ) : null}
            {releaseAction.status === 'error' ? <ErrorState error={releaseAction.error} title="冻结被拒绝" /> : null}
          </div>
        </div>
      </SectionCard>

      <SectionCard
        title="发布列表与 manifest"
        subtitle="GET /releases · GET /releases/{id}（只读）"
        actions={
          <button type="button" className="btn btn--tiny" onClick={releases.reload} disabled={releases.refreshing}>
            {releases.refreshing ? '刷新中…' : '刷新'}
          </button>
        }
      >
        {releases.status === 'error' ? <ErrorState error={releases.error} onRetry={releases.reload} /> : null}
        {releases.data ? (
          releases.data.items.length === 0 ? (
            <EmptyState title="还没有 release" reason={releases.data.empty_reason ?? undefined} />
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">选择</th>
                  <th scope="col">release_id</th>
                  <th scope="col">profile</th>
                  <th scope="col">资产数</th>
                  <th scope="col">冻结时间</th>
                  <th scope="col">操作</th>
                </tr>
              </thead>
              <tbody>
                {releases.data.items.map((item) => {
                  const id = String((item as Record<string, unknown>).release_id ?? '');
                  const assets = (item as Record<string, unknown>).assets;
                  return (
                    <tr key={id} className={selectedReleaseId === id ? 'row--selected' : undefined}>
                      <td>
                        <input
                          type="radio"
                          name="release-select"
                          checked={selectedReleaseId === id}
                          onChange={() => setSelectedReleaseId(id)}
                          aria-label={`选择 release ${id}`}
                        />
                      </td>
                      <td className="mono">{id}</td>
                      <td className="mono">{String((item as Record<string, unknown>).profile ?? '—')}</td>
                      <td className="mono">{Array.isArray(assets) ? assets.length : String((item as Record<string, unknown>).asset_count ?? '—')}</td>
                      <td>{formatTimestamp((item as Record<string, unknown>).frozen_at)}</td>
                      <td className="rowactions">
                        <button type="button" className="btn btn--tiny" onClick={() => setSelectedReleaseId(id)}>
                          打开
                        </button>
                        <button
                          type="button"
                          className="btn btn--tiny"
                          onClick={() => setReleaseDraft({ ...releaseDraft, release_id: `${id}_fix` })}
                        >
                          新建修复版本
                        </button>
                        <button
                          type="button"
                          className="btn btn--tiny"
                          onClick={() => app.openProvenance({ kind: 'release', id })}
                        >
                          溯源
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )
        ) : null}

        {selectedReleaseId ? (
          releaseDetail.status === 'error' ? (
            <ErrorState error={releaseDetail.error} onRetry={releaseDetail.reload} />
          ) : releaseDetail.data ? (
            <>
              <h3>
                manifest <CopyValue value={releaseDetail.data.manifest_hash} label="manifest_hash" />
              </h3>
              <KeyValueList
                rows={[
                  { label: 'release_id', value: releaseDetail.data.release_id, mono: true },
                  { label: 'profile / scope', value: `${releaseDetail.data.profile} / ${releaseDetail.data.scope}` },
                  { label: 'asset_count', value: releaseDetail.data.asset_count },
                  { label: 'readonly', value: String(releaseDetail.data.readonly) },
                  { label: 'frozen_at', value: formatTimestamp(releaseDetail.data.frozen_at) },
                  { label: 'required_gates', value: (releaseDetail.data.required_gates ?? []).join(', ') || '—' },
                  { label: 'scope_pending', value: pretty(releaseDetail.data.scope_pending) },
                ]}
              />
              <table className="table table--tight">
                <caption>冻结时记录的 gate 状态</caption>
                <thead>
                  <tr>
                    <th scope="col">gate</th>
                    <th scope="col">状态</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(releaseDetail.data.gates ?? {}).map(([gate, status]) => (
                    <tr key={gate}>
                      <th scope="row" className="mono">
                        {gate}
                      </th>
                      <td>
                        <Badge tone={gateTone(String(status))}>{gateLabel(String(status))}</Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <details>
                <summary>依赖闭包（closure）</summary>
                <pre className="mono pre">{pretty(releaseDetail.data.closure)}</pre>
              </details>
              <details>
                <summary>资产清单（{releaseDetail.data.assets.length}）</summary>
                <pre className="mono pre">
                  {pretty(
                    releaseDetail.data.assets.map((asset) => ({
                      asset_id: asset.asset_id,
                      role: asset.role,
                      qa_status: asset.qa_status,
                      split: asset.split,
                      lineage_id: asset.lineage_id,
                    })),
                  )}
                </pre>
              </details>
            </>
          ) : (
            <LoadingState label="读取 release manifest…" />
          )
        ) : null}
      </SectionCard>

      <SectionCard title="导出" subtitle="POST /exports · GET /exports/{id}（导出不修改原 release）">
        <div className="row">
          <label className="field field--inline">
            <span className="field__label">adapter</span>
            <select
              className="input input--tight"
              value={exportDraft.adapter}
              onChange={(event) => setExportDraft({ adapter: event.target.value as typeof exportDraft.adapter })}
            >
              <option value="manifest">manifest</option>
              <option value="obs_pack">obs_pack</option>
              <option value="feature_bundle">feature_bundle</option>
              <option value="oracle_truth">oracle_truth（仅 researcher）</option>
            </select>
          </label>
          <ActionButton
            tone="primary"
            onClick={() => void submitExport()}
            busy={exportAction.status === 'busy'}
            disabledReason={selectedReleaseId ? null : '未选择 release'}
          >
            创建导出任务
          </ActionButton>
          <label className="field field--inline">
            <span className="field__label">export_id 查询</span>
            <input
              className="input input--tight"
              value={exportId}
              onChange={(event) => setExportId(event.target.value)}
              placeholder="export_..."
            />
          </label>
        </div>

        {exportAction.status === 'ok' ? <pre className="mono pre">{pretty(exportAction.response)}</pre> : null}
        {exportAction.status === 'error' ? <ErrorState error={exportAction.error} title="导出请求失败" /> : null}

        {exportId ? (
          exportDetail.status === 'error' ? (
            <ErrorState error={exportDetail.error} onRetry={exportDetail.reload} compact />
          ) : exportDetail.data ? (
            <KeyValueList
              rows={[
                { label: 'export_id', value: exportDetail.data.export.export_id, mono: true },
                { label: 'release_id', value: exportDetail.data.export.release_id, mono: true },
                { label: 'adapter', value: exportDetail.data.export.adapter },
                { label: 'status', value: exportDetail.data.export.status },
                { label: 'job_id', value: exportDetail.data.export.job_id ?? '—', mono: true },
                { label: 'note', value: exportDetail.data.note },
              ]}
            />
          ) : (
            <LoadingState label="读取导出状态…" />
          )
        ) : null}
      </SectionCard>

      <AssetBrowser
        title="发布范围内的资产（可挑选用于 release.asset_ids）"
        selectable="multi"
        onProvenance={(assetId) => app.openProvenance({ kind: 'asset', id: assetId })}
        pageSize={12}
        emptyReason="工作区没有资产：release 需要真实 committed refs，本页不会构造任何占位资产。"
      />
    </>
  );
}
