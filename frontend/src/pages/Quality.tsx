/**
 * U12 质量与故障 `/synlab/quality`（计划 20.13）。
 *
 * 真实调用：`GET /capabilities?doctor=full`（逐文件 hash 校验的深 doctor）、
 * `GET /jobs?state=FAILED|QUARANTINED|RETRYABLE`（问题任务）、`GET /jobs/{id}`（最小复现）、
 * `GET /assets?qa_status=QA_FAIL`（错误资产）、`GET /audits`、`GET /releases`（影响范围）。
 *
 * 计划要求「不能仅有一张静态待办表」：这里的每一行都能打开真实的失败抽屉（错误码、evidence、
 * job.spec 复现命令）或溯源抽屉（文件完整性、ancestry、release manifest），并给出后端支持的
 * 下一动作与是否可重试。
 */

import { useState } from 'react';

import { AssetBrowser } from '../components/AssetBrowser';
import { MeasuredQualityTable } from '../components/MeasuredQualityTable';
import {
  Badge,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  SectionCard,
} from '../components/states';
import { getCapabilities, listAudits, listJobs, listReleases } from '../api/endpoints';
import { useResource } from '../api/hooks';
import { formatRelative, jobStateLabel, pretty, truncate } from '../lib/format';
import { summarizeCounts, summarizeRuns } from '../lib/runs';
import { useAppState } from '../state/app-state';

const PROBLEM_STATES = ['FAILED', 'QUARANTINED', 'RETRYABLE'];

const NEXT_ACTION: Record<string, string> = {
  FAILED: '查看 error.details 与 evidence；retryable=true 时用 U07 的重试按钮产生新 attempt。',
  QUARANTINED: '隔离资产不进 release；检查上游 QA 报告后换输入重跑。',
  RETRYABLE: '后端明确可重试：直接 requeue 回 PENDING，内容种子不变。',
};

export function QualityPage() {
  const app = useAppState();
  const [doctorMode, setDoctorMode] = useState<'light' | 'full'>('light');
  const capabilities = useResource((signal) => getCapabilities({ doctor: doctorMode, refresh: true }, signal), [doctorMode]);
  const problemJobs = useResource(
    (signal) => listJobs({ state: PROBLEM_STATES, limit: 100, with_total: true }, signal),
    [],
    { intervalMs: 20_000 },
  );
  const allJobs = useResource((signal) => listJobs({ limit: 100 }, signal), [], { intervalMs: 30_000 });
  const audits = useResource((signal) => listAudits({ limit: 50 }, signal), []);
  const releases = useResource((signal) => listReleases({ limit: 50 }, signal), []);

  const problems = problemJobs.data?.items ?? [];
  const runs = summarizeRuns(allJobs.data?.items ?? []);

  const byCode = new Map<string, typeof problems>();
  for (const job of problems) {
    const error = job.error as Record<string, unknown> | null;
    const code = error ? String(error.code ?? 'UNKNOWN') : 'NO_ERROR_FIELD';
    const list = byCode.get(code) ?? [];
    list.push(job);
    byCode.set(code, list);
  }

  const runOf = (runId: string) => runs.find((run) => run.run_id === runId) ?? null;

  return (
    <>
      <PageHeader
        title="质量与故障"
        plan="U12 · 计划 20.13"
        summary="聚合全部验收门与隔离：问题代码、影响 run/release、最小复现、错误资产、下一动作、重试是否支持；入口对应实际日志/报告。"
        actions={
          <div className="row">
            <Badge tone="info">研究材料可叠 clean/physical/obs</Badge>
            <Badge tone="neutral">现场候选页只显示合法输入</Badge>
          </div>
        }
      />

      <SectionCard
        title="深度 doctor（逐文件 hash 校验）"
        subtitle="GET /capabilities?doctor=full"
        actions={
          <div className="row">
            <label className="field field--inline">
              <span className="field__label">doctor 模式</span>
              <select className="input input--tight" value={doctorMode} onChange={(event) => setDoctorMode(event.target.value as 'light' | 'full')}>
                <option value="light">light（SQLite 完整性 + 计数）</option>
                <option value="full">full（逐文件 hash）</option>
              </select>
            </label>
            <button type="button" className="btn btn--tiny" onClick={capabilities.reload} disabled={capabilities.refreshing}>
              {capabilities.refreshing ? '校验中…' : '重新校验'}
            </button>
          </div>
        }
      >
        {capabilities.status === 'loading' ? <LoadingState label="执行 doctor…" /> : null}
        {capabilities.status === 'error' ? <ErrorState error={capabilities.error} onRetry={capabilities.reload} /> : null}
        {capabilities.data ? (
          <>
            <p>
              <Badge tone={capabilities.data.doctor.ok ? 'ok' : 'bad'}>
                {capabilities.data.doctor.ok ? 'doctor 通过' : 'doctor 报告问题'}
              </Badge>
              <span className="mono small">
                {' '}
                mode={capabilities.data.doctor.mode} · files_checked={capabilities.data.doctor.files_checked ?? '—'} ·
                assets={capabilities.data.doctor.assets ?? '—'}
              </span>
            </p>
            {capabilities.data.doctor.problems.length > 0 ? (
              <ul className="problems">
                {capabilities.data.doctor.problems.map((problem) => (
                  <li key={problem} className="mono">
                    {problem}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted small">doctor 未报告问题。</p>
            )}
            <details>
              <summary>能力与 doctor 原始响应</summary>
              <pre className="mono pre">{pretty({ doctor: capabilities.data.doctor, missing: capabilities.data.missing, available: capabilities.data.available })}</pre>
            </details>
          </>
        ) : null}
      </SectionCard>

      <SectionCard
        title="问题代码聚合"
        subtitle="GET /jobs?state=FAILED&state=QUARANTINED&state=RETRYABLE（后端过滤，不由前端全量扫描）"
        actions={
          <button type="button" className="btn btn--tiny" onClick={problemJobs.reload} disabled={problemJobs.refreshing}>
            {problemJobs.refreshing ? '刷新中…' : '刷新'}
          </button>
        }
      >
        {problemJobs.status === 'loading' ? <LoadingState label="读取问题任务…" /> : null}
        {problemJobs.status === 'error' ? <ErrorState error={problemJobs.error} onRetry={problemJobs.reload} /> : null}
        {problemJobs.data ? (
          problems.length === 0 ? (
            <EmptyState
              title="当前没有失败/隔离/可重试任务"
              reason="这是一个真实结论：GET /jobs 用 state 过滤后返回 0 行。它不代表“全部通过”，验收门请看 U08 的 gate 结果。"
            />
          ) : (
            <>
              <div className="statrow">
                {[...byCode.entries()].map(([code, list]) => (
                  <span key={code} className="stat">
                    <Badge tone="bad">{code}</Badge>
                    <strong>{list.length}</strong>
                  </span>
                ))}
                {problemJobs.data.total !== undefined ? <span className="muted small">total={problemJobs.data.total}</span> : null}
              </div>

              <table className="table">
                <caption>问题任务（每一行都能打开真实证据）</caption>
                <thead>
                  <tr>
                    <th scope="col">job</th>
                    <th scope="col">stage</th>
                    <th scope="col">状态</th>
                    <th scope="col">错误码</th>
                    <th scope="col">可重试</th>
                    <th scope="col">影响 run</th>
                    <th scope="col">下一动作</th>
                    <th scope="col">证据</th>
                  </tr>
                </thead>
                <tbody>
                  {problems.map((job) => {
                    const error = job.error as Record<string, unknown> | null;
                    const state = jobStateLabel(job.state);
                    const run = runOf(job.run_id);
                    return (
                      <tr key={job.job_id}>
                        <th scope="row" className="mono">
                          {truncate(job.job_id, 20)}
                        </th>
                        <td className="mono">{job.stage}</td>
                        <td>
                          <Badge tone={state.tone}>{state.label}</Badge>
                        </td>
                        <td className="mono small">{error ? String(error.code ?? '—') : '未提供 error 字段'}</td>
                        <td>
                          {error ? (
                            <Badge tone={error.retryable ? 'warn' : 'bad'}>{String(error.retryable)}</Badge>
                          ) : (
                            <Badge tone="neutral">未知</Badge>
                          )}
                        </td>
                        <td className="mono small">
                          {truncate(job.run_id, 18)}
                          {run ? <div className="muted small">{summarizeCounts(run)}</div> : null}
                        </td>
                        <td className="small">{NEXT_ACTION[job.state] ?? '按后端状态决定'}</td>
                        <td className="rowactions">
                          <button type="button" className="btn btn--tiny" onClick={() => app.openFailure(job.job_id)}>
                            失败详情
                          </button>
                          <button
                            type="button"
                            className="btn btn--tiny"
                            onClick={() => app.openProvenance({ kind: 'job', id: job.job_id })}
                          >
                            溯源
                          </button>
                          <button type="button" className="btn btn--tiny" onClick={() => app.setSelectedRunId(job.run_id)}>
                            选中该 run
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </>
          )
        ) : null}
      </SectionCard>

      <div className="grid2">
        <SectionCard title="错误资产" subtitle="GET /assets?qa_status=QA_FAIL">
          <AssetBrowser
            title="QA 失败资产"
            fixedQaStatus="QA_FAIL"
            selectable="none"
            onProvenance={(assetId) => app.openProvenance({ kind: 'asset', id: assetId })}
            pageSize={10}
            emptyReason="没有 QA_FAIL 资产：这是后端根据真实 qa_status 过滤的结果。"
          />
        </SectionCard>

        <SectionCard title="影响范围：审计与发布" subtitle="GET /audits · GET /releases">
          <h3>审计</h3>
          {audits.status === 'error' ? <ErrorState error={audits.error} onRetry={audits.reload} compact /> : null}
          {audits.data ? (
            audits.data.items.length === 0 ? (
              <p className="muted small">{audits.data.empty_reason ?? '没有审计。'}</p>
            ) : (
              <table className="table table--tight">
                <thead>
                  <tr>
                    <th scope="col">audit</th>
                    <th scope="col">status</th>
                    <th scope="col">result</th>
                    <th scope="col">关联</th>
                  </tr>
                </thead>
                <tbody>
                  {audits.data.items.map((audit) => (
                    <tr key={audit.audit_id}>
                      <th scope="row" className="mono">
                        {truncate(audit.audit_id, 20)}
                      </th>
                      <td>
                        <Badge tone={audit.status === 'COMPLETED' ? 'ok' : 'warn'}>{audit.status}</Badge>
                      </td>
                      <td>{Object.keys(audit.result ?? {}).length > 0 ? <Badge tone="ok">有结果</Badge> : <Badge tone="warn">空</Badge>}</td>
                      <td className="mono small">
                        {audit.run_id ? `run ${truncate(audit.run_id, 14)}` : ''} {audit.release_id ? `release ${audit.release_id}` : ''}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )
          ) : null}

          <h3>发布</h3>
          {releases.status === 'error' ? <ErrorState error={releases.error} onRetry={releases.reload} compact /> : null}
          {releases.data ? (
            releases.data.items.length === 0 ? (
              <p className="muted small">{releases.data.empty_reason ?? '没有 release。'}</p>
            ) : (
              <table className="table table--tight">
                <thead>
                  <tr>
                    <th scope="col">release</th>
                    <th scope="col">profile</th>
                    <th scope="col">溯源</th>
                  </tr>
                </thead>
                <tbody>
                  {releases.data.items.map((item) => {
                    const id = String((item as Record<string, unknown>).release_id ?? '');
                    return (
                      <tr key={id}>
                        <th scope="row" className="mono">
                          {id}
                        </th>
                        <td className="mono">{String((item as Record<string, unknown>).profile ?? '—')}</td>
                        <td>
                          <button type="button" className="btn btn--tiny" onClick={() => app.openProvenance({ kind: 'release', id })}>
                            打开 manifest
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )
          ) : null}
        </SectionCard>
      </div>

      <SectionCard title="最近任务健康度" subtitle="GET /jobs（真实 state 计数）">
        {allJobs.status === 'error' ? <ErrorState error={allJobs.error} onRetry={allJobs.reload} /> : null}
        {allJobs.data ? (
          <>
            <div className="statrow">
              {Object.entries(
                (allJobs.data.items ?? []).reduce<Record<string, number>>((accumulator, job) => {
                  accumulator[job.state] = (accumulator[job.state] ?? 0) + 1;
                  return accumulator;
                }, {}),
              ).map(([state, count]) => (
                <span key={state} className="stat">
                  <Badge tone={jobStateLabel(state).tone}>{jobStateLabel(state).label}</Badge>
                  <strong>{count}</strong>
                </span>
              ))}
            </div>
            <MeasuredQualityTable
              rows={[
                {
                  key: 'jobs.total',
                  label: '窗口内 job 数（limit=100）',
                  value: (allJobs.data.items ?? []).length,
                  source: 'GET /jobs?limit=100',
                },
                {
                  key: 'jobs.failed',
                  label: 'FAILED',
                  value: (allJobs.data.items ?? []).filter((job) => job.state === 'FAILED').length,
                  source: 'GET /jobs（state 字段）',
                },
                {
                  key: 'jobs.quarantined',
                  label: 'QUARANTINED',
                  value: (allJobs.data.items ?? []).filter((job) => job.state === 'QUARANTINED').length,
                  source: 'GET /jobs（state 字段）',
                },
                {
                  key: 'acceptance.gates',
                  label: '验收门结论',
                  value: null,
                  source: '需要已完成审计（GET /audits/{id}.result.gates）；没有审计时不写成 PASS',
                  flag: 'missing',
                },
                {
                  key: 'acceptance.rate',
                  label: '接受率',
                  value: null,
                  source: 'API 未提供接受率统计字段',
                  flag: 'missing',
                },
              ]}
              caption="窗口内计数与缺失项；缺失项明确标注而不是写 0 分"
            />
            <p className="muted small">
              最近一次刷新：{formatRelative(Date.now() / 1000)}
              {' · '}本页不把“没有失败任务”表述成“已验收通过”。
            </p>
            <details>
              <summary>失败任务原始 error JSON（前 5 条）</summary>
              <pre className="mono pre">{pretty(problems.slice(0, 5).map((job) => ({ job_id: job.job_id, error: job.error })))}</pre>
            </details>
          </>
        ) : (
          <LoadingState label="读取任务健康度…" />
        )}
      </SectionCard>

      <SectionCard title="研究材料叠加（clean / physical / obs）" subtitle="按 role 列出可叠加的资产">
        <AssetBrowser
          title="研究材料（clean_truth / physical_truth / obs_result / obs_view）"
          fixedRoles={['clean_truth', 'physical_truth', 'obs_result', 'obs_view']}
          selectable="multi"
          onProvenance={(assetId) => app.openProvenance({ kind: 'asset', id: assetId })}
          pageSize={10}
          emptyReason="没有研究材料资产；部署会话下这些研究角色会被后端隐藏（research_roles_hidden）。"
        />
        <p className="muted small">
          现场候选页只显示合法输入：部署会话调用 <code className="mono">GET /assets</code> 时后端默认只返回部署安全角色，
          请求研究角色会得到 <code className="mono">403 ROLE_FORBIDDEN</code>。
        </p>
      </SectionCard>
    </>
  );
}
