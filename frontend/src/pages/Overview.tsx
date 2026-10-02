/**
 * U01 实验室概览 `/synlab`（计划 20.2）。
 *
 * 真实数据来源：`GET /health`、`GET /capabilities?doctor=light`、`GET /jobs`、`GET /assets`、
 * `GET /registry/all`、`GET /releases`、`GET /audits`、`GET /stages`。
 *
 * “已就绪 / 缺失”分列来自能力探测的真实 status；成功统计只由 job 行的真实 state 归并，
 * 不由前端累加猜测。没有资产时给出导向闭环的空状态。
 */

import { Link } from 'react-router-dom';

import { getCapabilities, getRegistry, getStages, listAssets, listAudits, listReleases, listJobs } from '../api/endpoints';
import { useResource } from '../api/hooks';
import { summarizeCounts, summarizeRuns, runStateLabel } from '../lib/runs';
import { formatGb, formatRelative, formatTimestamp, jobStateLabel, truncate } from '../lib/format';
import {
  Badge,
  EmptyState,
  ErrorState,
  KeyValueList,
  LoadingState,
  PageHeader,
  SectionCard,
} from '../components/states';
import { ResourceBudgetCard } from '../components/ResourceBudgetCard';
const QUICK_LINKS: Array<{ to: string; label: string; hint: string }> = [
  { to: '/synlab/mothers/new', label: '新建配方 / 母体', hint: 'U02 · 校验 → 预算 → 预览任务' },
  { to: '/synlab/jobs', label: '批量生成与任务', hint: 'U07 · 暂停 / 恢复 / 取消 / 重试 + SSE' },
  { to: '/synlab/releases', label: '打开发布', hint: 'U08 · 审计 gate 与只读 release' },
  { to: '/synlab/training', label: '启动训练', hint: 'U09 · 真实 GPU/CPU 与 checkpoint' },
  { to: '/synlab/diagnostics', label: '启动诊断', hint: 'U10 · 固定 gallery/query 的实验' },
  { to: '/synlab/quality', label: '查看失败', hint: 'U12 · 问题代码与最小复现' },
];

export function OverviewPage() {
  const health = useResource((signal) => getCapabilities({ doctor: 'light' }, signal), []);
  const stages = useResource((signal) => getStages(signal), []);
  const jobs = useResource((signal) => listJobs({ limit: 100, with_total: true }, signal), [], { intervalMs: 15_000 });
  const assets = useResource((signal) => listAssets({ limit: 25, with_total: true }, signal), [], { intervalMs: 30_000 });
  const releases = useResource((signal) => listReleases({ limit: 20 }, signal), []);
  const audits = useResource((signal) => listAudits({ limit: 20 }, signal), []);
  const registry = useResource((signal) => getRegistry('all', {}, signal), []);

  const runs = summarizeRuns(jobs.data?.items ?? []);
  const problems = (jobs.data?.items ?? []).filter((job) => job.state === 'FAILED' || job.state === 'QUARANTINED');

  const capabilities = health.data;
  const readyModules = Object.values(capabilities?.modules ?? {}).filter((probe) => probe.available);
  const missingModules = Object.values(capabilities?.modules ?? {}).filter((probe) => !probe.available);
  const envEntries = Object.entries(capabilities?.env ?? {});
  const disk = capabilities?.env?.['disk'] as { detail?: string; status?: string } | undefined;
  const cuda = capabilities?.env?.['cuda'] as { detail?: string; status?: string } | undefined;

  return (
    <>
      <PageHeader
        title="实验室概览"
        plan="U01 · 计划 20.2"
        summary="能力 / doctor / registry / 资产 / run / 发布与失败的真实统计。所有数字都来自后端当前回答，刷新后与后端一致。"
        actions={
          <div className="row">
            <Link className="btn btn--primary" to="/synlab/mothers/new">
              新建配方
            </Link>
            <Link className="btn" to="/synlab/jobs">
              继续上次任务
            </Link>
          </div>
        }
      />

      {/* ---------------------------------------------------------- 连接与 doctor */}
      <SectionCard
        title="连接、会话与 doctor"
        subtitle="GET /capabilities?doctor=light"
        actions={
          <button type="button" className="btn btn--tiny" onClick={health.reload} disabled={health.refreshing}>
            {health.refreshing ? '探测中…' : '重新探测能力'}
          </button>
        }
      >
        {health.status === 'loading' ? <LoadingState label="探测后端能力…" /> : null}
        {health.status === 'error' ? <ErrorState error={health.error} onRetry={health.reload} /> : null}
        {capabilities ? (
          <>
            <KeyValueList
              rows={[
                { label: 'API 版本 / 前缀', value: `${capabilities.api_version} · ${capabilities.prefix}`, mono: true },
                { label: 'Python', value: capabilities.python, mono: true },
                { label: '会话', value: `${capabilities.session.session_id}（role=${capabilities.session.role}）`, mono: true },
                { label: '工作区 / store', value: `${capabilities.session.workspace} · ${capabilities.session.store_id}`, mono: true },
                { label: 'registry 指纹', value: <span className="mono">{capabilities.registry_fingerprint}</span> },
                { label: 'worker', value: <span className="mono">{capabilities.worker.command}</span> },
                { label: 'worker 说明', value: capabilities.worker.note },
              ]}
            />

            <h3>会话权限（服务端 policy，UI 不代替鉴权）</h3>
            <ul className="chips">
              {Object.entries(capabilities.session.policy).map(([key, value]) =>
                typeof value === 'boolean' ? (
                  <li key={key}>
                    <Badge tone={value ? 'ok' : 'neutral'}>
                      {key}={String(value)}
                    </Badge>
                  </li>
                ) : null,
              )}
            </ul>

            <h3>doctor（模式 {capabilities.doctor.mode}）</h3>
            <p>
              <Badge tone={capabilities.doctor.ok ? 'ok' : 'bad'}>
                {capabilities.doctor.ok ? 'doctor 通过' : 'doctor 报告问题'}
              </Badge>
              {capabilities.doctor.sqlite_integrity ? (
                <span className="mono small"> sqlite integrity={capabilities.doctor.sqlite_integrity}</span>
              ) : null}
            </p>
            {capabilities.doctor.problems.length > 0 ? (
              <ul className="problems">
                {capabilities.doctor.problems.map((problem) => (
                  <li key={problem} className="mono">
                    {problem}
                  </li>
                ))}
              </ul>
            ) : null}
            {capabilities.doctor.counts ? (
              <table className="table table--tight">
                <caption>doctor 直接读库统计（未运行就是 0，不代表成功）</caption>
                <tbody>
                  {Object.entries(capabilities.doctor.counts).map(([key, value]) => (
                    <tr key={key}>
                      <th scope="row">{key}</th>
                      <td className="mono">{value}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : null}
            <p className="muted small">{capabilities.honesty.missing_modules}</p>
            <p className="muted small">{capabilities.honesty.missing_backends}</p>
          </>
        ) : null}
      </SectionCard>

      {/* ---------------------------------------------------------- 能力分列 */}
      <SectionCard
        title="能力清单：已就绪 / 缺失"
        subtitle="“已实现”不等于“已验收”；缺失项按真实 status 与缺少的入口函数列出"
      >
        {health.status === 'error' ? (
          <ErrorState error={health.error} onRetry={health.reload} compact />
        ) : (
          <div className="grid2">
            <div>
              <h3>
                已就绪 <Badge tone="ok">{readyModules.length}</Badge>
              </h3>
              {readyModules.length === 0 ? (
                <EmptyState title="没有可用能力模块" reason="后端 /capabilities 报告 available 为空。" />
              ) : (
                <table className="table table--tight">
                  <thead>
                    <tr>
                      <th scope="col">能力</th>
                      <th scope="col">模块</th>
                      <th scope="col">入口函数</th>
                    </tr>
                  </thead>
                  <tbody>
                    {readyModules.map((probe) => (
                      <tr key={probe.key}>
                        <th scope="row">{probe.key}</th>
                        <td className="mono">{probe.module}</td>
                        <td className="mono small">{Object.keys(probe.entry_points ?? {}).join(', ') || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
            <div>
              <h3>
                缺失 <Badge tone="bad">{missingModules.length}</Badge>
              </h3>
              {missingModules.length === 0 ? (
                <EmptyState title="没有缺失能力" reason="后端报告 missing 为空。" />
              ) : (
                <table className="table table--tight">
                  <thead>
                    <tr>
                      <th scope="col">能力</th>
                      <th scope="col">状态码</th>
                      <th scope="col">原因 / 缺少入口</th>
                    </tr>
                  </thead>
                  <tbody>
                    {missingModules.map((probe) => (
                      <tr key={probe.key}>
                        <th scope="row">{probe.key}</th>
                        <td>
                          <Badge tone="warn">{probe.status}</Badge>
                        </td>
                        <td className="small">
                          {probe.error ?? '后端未给出原因'}
                          {probe.missing_entry_points && probe.missing_entry_points.length > 0 ? (
                            <div className="mono small">缺少：{probe.missing_entry_points.join(', ')}</div>
                          ) : null}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        )}
      </SectionCard>

      {/* ---------------------------------------------------------- 磁盘与 GPU */}
      <SectionCard title="磁盘与 GPU" subtitle="GET /capabilities 的 env 探测结果">
        {envEntries.length === 0 ? (
          <EmptyState title="后端未返回 env" reason="capabilities 响应里没有 env 字段。" />
        ) : (
          <table className="table table--tight">
            <thead>
              <tr>
                <th scope="col">能力</th>
                <th scope="col">状态</th>
                <th scope="col">详情</th>
              </tr>
            </thead>
            <tbody>
              {envEntries.map(([key, probe]) => (
                <tr key={key}>
                  <th scope="row">{key}</th>
                  <td>
                    <Badge tone={probe.status === 'OK' ? 'ok' : 'warn'}>{probe.status}</Badge>
                  </td>
                  <td className="mono small">{probe.detail ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="muted small">
          磁盘：{disk?.detail ?? '未提供'} · CUDA：{cuda?.detail ?? '未提供'}（GPU 训练结论按实际记录，不折算成 GPU 小时）
        </p>
      </SectionCard>

      {/* ---------------------------------------------------------- registry */}
      <SectionCard
        title="参数注册表（registry）"
        subtitle="GET /registry/all —— UI 表单与执行共用同一份范围表"
      >
        {registry.status === 'loading' ? <LoadingState label="读取 registry…" /> : null}
        {registry.status === 'error' ? <ErrorState error={registry.error} onRetry={registry.reload} /> : null}
        {registry.data ? (
          <>
            <p>
              <Badge tone={registry.data.count > 0 ? 'ok' : 'warn'}>条目 {registry.data.count}</Badge>
              <span className="mono small"> fingerprint={registry.data.registry_fingerprint}</span>
            </p>
            <p className="muted">{registry.data.note}</p>
            {registry.data.count === 0 ? (
              <EmptyState
                title="registry 为空：器物/材料/纹样/断裂后端/退化轴都还没有注册条目"
                reason={
                  <>
                    空的 kinds：
                    <code className="mono">{registry.data.empty_kinds.join(', ') || '（无）'}</code>
                    。这意味着 U02–U05 的“器物参数 / 材料层 / 16 纹样族 / 四必做断裂后端 / 31 退化轴”无法从后端枚举——
                    前端不会复制一份范围表来填空。请让实现模块注册到 registry，然后刷新本页。
                  </>
                }
              />
            ) : (
              <table className="table table--tight">
                <thead>
                  <tr>
                    <th scope="col">kind</th>
                    <th scope="col">id</th>
                    <th scope="col">name</th>
                    <th scope="col">version</th>
                    <th scope="col">status</th>
                  </tr>
                </thead>
                <tbody>
                  {registry.data.entries.map((entry) => (
                    <tr key={`${String(entry.kind)}-${entry.id}`}>
                      <td className="mono">{String(entry.kind ?? registry.data?.kind ?? '—')}</td>
                      <td className="mono">{entry.id}</td>
                      <td>{entry.name ?? '—'}</td>
                      <td className="mono">{entry.version ?? '—'}</td>
                      <td>
                        <Badge tone="neutral">{entry.status ?? '—'}</Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        ) : null}
      </SectionCard>

      {/* ---------------------------------------------------------- 资产与统计 */}
      <SectionCard title="资产与统计" subtitle="GET /assets?limit=25&with_total=true（服务端过滤 workspace）">
        {assets.status === 'loading' ? <LoadingState label="读取资产…" /> : null}
        {assets.status === 'error' ? <ErrorState error={assets.error} onRetry={assets.reload} /> : null}
        {assets.data ? (
          assets.data.items.length === 0 ? (
            <EmptyState
              title="这个工作区还没有任何资产"
              reason={
                <>
                  {assets.data.empty_reason ?? '后端返回空列表。'}
                  <br />
                  闭环导向：提交 <code className="mono">freeze_spec</code> 任务（无需额外能力模块，一定会被受理）→
                  在任务页查看真实事件 → 需要几何时再让实现模块补齐 mother/pattern/fracture/degrade/observe 能力。
                </>
              }
              action={
                <Link className="btn" to="/synlab/jobs">
                  去任务页创建任务
                </Link>
              }
            />
          ) : (
            <>
              <p>
                <Badge tone="info">已加载 {assets.data.items.length}</Badge>
                {assets.data.total !== undefined ? <Badge tone="neutral">total={assets.data.total}</Badge> : null}
              </p>
              <table className="table table--tight">
                <thead>
                  <tr>
                    <th scope="col">asset_id</th>
                    <th scope="col">role</th>
                    <th scope="col">unit/frame</th>
                    <th scope="col">QA</th>
                    <th scope="col">创建</th>
                  </tr>
                </thead>
                <tbody>
                  {assets.data.items.map((asset) => (
                    <tr key={asset.asset_id}>
                      <td className="mono">{truncate(asset.asset_id, 22)}</td>
                      <td>
                        <Badge tone="neutral">{asset.role}</Badge>
                      </td>
                      <td className="mono">
                        {asset.unit}/{asset.frame}
                      </td>
                      <td>
                        <Badge tone={asset.qa_status === 'QA_PASS' ? 'ok' : asset.qa_status === 'QA_FAIL' ? 'bad' : 'warn'}>
                          {asset.qa_status}
                        </Badge>
                      </td>
                      <td>{formatRelative(asset.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )
        ) : null}
      </SectionCard>

      {/* ---------------------------------------------------------- run 与失败 */}
      <SectionCard
        title="run 与失败"
        subtitle="GET /jobs?limit=100&with_total=true，按 run_id 归并"
        actions={
          <Link className="btn btn--tiny" to="/synlab/jobs">
            打开任务页
          </Link>
        }
      >
        {jobs.status === 'loading' ? <LoadingState label="读取任务列表…" /> : null}
        {jobs.status === 'error' ? <ErrorState error={jobs.error} onRetry={jobs.reload} /> : null}
        {jobs.data ? (
          <>
            <div className="grid2">
              <div>
                <h3>最近 run</h3>
                {runs.length === 0 ? (
                  <EmptyState
                    title="没有 run"
                    reason="GET /jobs 没有返回任何 job。创建任务后这里会显示真实 run 与 job 状态计数。"
                  />
                ) : (
                  <ul className="runlist">
                    {runs.slice(0, 8).map((run) => {
                      const state = runStateLabel(run.dominantState);
                      return (
                        <li key={run.run_id}>
                          <div className="row">
                            <Link className="mono linky" to="/synlab/jobs">
                              {truncate(run.run_id, 26)}
                            </Link>
                            <Badge tone={state.tone}>{state.label}</Badge>
                            {run.terminal ? <Badge tone="neutral">已终止</Badge> : <Badge tone="info">未终止</Badge>}
                          </div>
                          <div className="muted small">{summarizeCounts(run)}</div>
                          <div className="mono small">
                            {run.stages.join(' → ')} · 最近更新 {formatTimestamp(run.lastSeen)}
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>
              <div>
                <h3>
                  失败 / 隔离 <Badge tone={problems.length > 0 ? 'bad' : 'ok'}>{problems.length}</Badge>
                </h3>
                {problems.length === 0 ? (
                  <EmptyState title="没有失败或隔离的任务" reason="当前 100 条 job 里没有 FAILED/QUARANTINED。" />
                ) : (
                  <table className="table table--tight">
                    <thead>
                      <tr>
                        <th scope="col">job</th>
                        <th scope="col">阶段</th>
                        <th scope="col">状态</th>
                        <th scope="col">错误码</th>
                      </tr>
                    </thead>
                    <tbody>
                      {problems.map((job) => {
                        const state = jobStateLabel(job.state);
                        const error = job.error as Record<string, unknown> | null;
                        return (
                          <tr key={job.job_id}>
                            <td className="mono">{truncate(job.job_id, 18)}</td>
                            <td className="mono">{job.stage}</td>
                            <td>
                              <Badge tone={state.tone}>{state.label}</Badge>
                            </td>
                            <td className="mono small">{error ? String(error.code ?? '—') : '未提供 error'}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                )}
                <p className="muted small">
                  取消/失败不会计成功：这里的计数直接来自 job.state；release 是否可用要看 U08 的真实 gate。
                </p>
              </div>
            </div>
          </>
        ) : null}
      </SectionCard>

      {/* ---------------------------------------------------------- 发布与阶段 */}
      <div className="grid2">
        <SectionCard title="发布与审计" subtitle="GET /releases · GET /audits">
          <p>
            release：<Badge tone={releases.data && releases.data.count > 0 ? 'ok' : 'neutral'}>
              {releases.data?.count ?? '—'}
            </Badge>{' '}
            audit：<Badge tone={audits.data && audits.data.count > 0 ? 'ok' : 'neutral'}>{audits.data?.count ?? '—'}</Badge>
          </p>
          <p className="muted small">
            {releases.data?.empty_reason ?? releases.data?.items.length ? '' : '（无发布）'}{' '}
            {audits.data?.empty_reason ?? ''}
          </p>
          <Link className="btn btn--tiny" to="/synlab/releases">
            去发布页
          </Link>
        </SectionCard>

        <SectionCard title="任务阶段目录" subtitle="GET /stages">
          {stages.status === 'error' ? <ErrorState error={stages.error} onRetry={stages.reload} compact /> : null}
          {stages.data ? (
            <table className="table table--tight">
              <thead>
                <tr>
                  <th scope="col">阶段</th>
                  <th scope="col">能力</th>
                  <th scope="col">GPU</th>
                  <th scope="col">估算 RSS</th>
                </tr>
              </thead>
              <tbody>
                {stages.data.stages.map((stage) => (
                  <tr key={stage.stage}>
                    <th scope="row">
                      {stage.title}
                      <div className="mono small">{stage.stage}</div>
                    </th>
                    <td className="mono small">{stage.capabilities.join(', ') || '无需能力'}</td>
                    <td>{stage.requires_gpu ? <Badge tone="warn">需要</Badge> : <Badge tone="neutral">不需要</Badge>}</td>
                    <td className="mono">{formatGb(stage.estimate.rss_gb)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
        </SectionCard>
      </div>

      <ResourceBudgetCard budget={null} title="资源预算（概览页未请求）" />

      <SectionCard title="快速入口" subtitle="12 个页面全部走真实 API">
        <ul className="quicklinks">
          {QUICK_LINKS.map((link) => (
            <li key={link.to}>
              <Link to={link.to}>{link.label}</Link>
              <span className="muted small">{link.hint}</span>
            </li>
          ))}
        </ul>
      </SectionCard>
    </>
  );
}
