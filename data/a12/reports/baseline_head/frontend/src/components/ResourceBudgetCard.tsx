/**
 * ResourceBudgetCard —— 资源预算卡（计划 20.8：预算不足阻止启动且保留草稿）。
 *
 * 数据来自真实 `POST /budgets`（或 `POST /jobs` 返回的 budget 字段）与 `GET /stages`。
 * 后端的 `assumptions[].source` 明确写着“development initial values; not a measured
 * throughput guarantee”，这里原样显示，不把它包装成实测吞吐。
 */

import type { BudgetReport, StageInfo } from '../api/types';
import { asNumber, formatGb, pretty } from '../lib/format';
import { Badge, EmptyState } from './states';

export interface ResourceBudgetCardProps {
  budget: BudgetReport | null;
  stage?: StageInfo | null;
  title?: string;
  emptyReason?: React.ReactNode;
  /** 官方 runtime 预算缺失时由调用方补充（例如 capabilities.env 的磁盘信息）。 */
  env?: { cuda_available: boolean; status: string; detail: string | null } | null;
}

function Bar({ value, max, tone }: { value: number; max: number; tone: 'ok' | 'warn' | 'bad' }) {
  const pct = max > 0 ? Math.min(100, Math.max(0, (value / max) * 100)) : 0;
  return (
    <span className="bar" role="img" aria-label={`已用 ${value} / 预算 ${max}，占 ${pct.toFixed(0)}%`}>
      <span className={`bar__fill bar__fill--${tone}`} style={{ width: `${pct}%` }} />
    </span>
  );
}

export function ResourceBudgetCard({ budget, stage, title = '资源预算', emptyReason, env }: ResourceBudgetCardProps) {
  if (!budget) {
    return (
      <section className="card" aria-label={title}>
        <header className="card__head">
          <h2 className="card__title">{title}</h2>
        </header>
        <div className="card__body">
          <EmptyState
            title="尚未请求预算估算"
            reason={
              emptyReason ?? (
                <>
                  预算来自真实的 <code className="mono">POST /budgets</code>。点击“估算资源”后这里会显示
                  rss/vram/临时磁盘与可行性；后端不可行时返回 <code className="mono">409 BUDGET_EXCEEDED</code>。
                </>
              )
            }
          />
        </div>
      </section>
    );
  }

  const rssRatio = budget.rss_budget_gb > 0 ? budget.rss_gb / budget.rss_budget_gb : 0;
  const vramRatio = budget.vram_budget_gb > 0 ? budget.vram_gb / budget.vram_budget_gb : 0;
  const gpuProbe = budget.env ?? env ?? null;

  return (
    <section className="card" aria-label={title}>
      <header className="card__head">
        <div>
          <h2 className="card__title">
            {title}
            <Badge tone={budget.feasible ? 'ok' : 'bad'}>{budget.feasible ? '可准入' : '超出预算'}</Badge>
            {budget.requires_gpu ? <Badge tone="warn">需要 GPU</Badge> : null}
          </h2>
          <p className="card__subtitle">
            stage={budget.stage ?? stage?.stage ?? '未提供'} · planned_jobs={budget.jobs} · budget_ref=
            {budget.budget_ref ?? '未提供'}
          </p>
        </div>
      </header>
      <div className="card__body">
        <dl className="kv">
          <div className="kv__row">
            <dt>RSS</dt>
            <dd>
              <span className="mono">
                {formatGb(budget.rss_gb)} / 预算 {formatGb(budget.rss_budget_gb)}（{Math.round(rssRatio * 100)}%）
              </span>
              <Bar value={budget.rss_gb} max={budget.rss_budget_gb} tone={rssRatio > 0.9 ? 'bad' : rssRatio > 0.7 ? 'warn' : 'ok'} />
            </dd>
          </div>
          <div className="kv__row">
            <dt>VRAM</dt>
            <dd>
              <span className="mono">
                {formatGb(budget.vram_gb)} / 预算 {formatGb(budget.vram_budget_gb)}（{Math.round(vramRatio * 100)}%）
              </span>
              <Bar value={budget.vram_gb} max={budget.vram_budget_gb} tone={vramRatio > 0.9 ? 'bad' : vramRatio > 0.7 ? 'warn' : 'ok'} />
            </dd>
          </div>
          <div className="kv__row">
            <dt>临时磁盘 / 持久磁盘</dt>
            <dd className="mono">
              {formatGb(budget.temp_disk_gb)} / {formatGb(budget.persistent_disk_gb)}
            </dd>
          </div>
          <div className="kv__row">
            <dt>磁盘水位</dt>
            <dd className="mono">
              剩余 {asNumber(budget.disk?.free_gb)?.toFixed(2) ?? '未提供'} GB / 总{' '}
              {asNumber(budget.disk?.total_gb)?.toFixed(2) ?? '未提供'} GB · 使用率{' '}
              {budget.disk ? `${(budget.disk.used_fraction * 100).toFixed(1)}%` : '未提供'} · 等级{' '}
              {budget.disk?.level ?? '未提供'}
            </dd>
          </div>
          <div className="kv__row">
            <dt>GPU 环境</dt>
            <dd className="mono">
              {gpuProbe
                ? `cuda_available=${String(gpuProbe.cuda_available)} · status=${gpuProbe.status} · ${gpuProbe.detail ?? '无 detail'}`
                : '后端未返回 env'}
            </dd>
          </div>
          {budget.gpu_blocked ? (
            <div className="kv__row">
              <dt>GPU 阻塞</dt>
              <dd>
                <Badge tone="warn">{budget.gpu_blocked.code}</Badge> {budget.gpu_blocked.reason ?? '无原因说明'}
              </dd>
            </div>
          ) : null}
          {budget.spec_valid === false ? (
            <div className="kv__row">
              <dt>spec 校验</dt>
              <dd>
                <Badge tone="bad">spec 未通过</Badge>
                <pre className="mono pre pre--inline">{pretty(budget.spec_errors ?? [])}</pre>
              </dd>
            </div>
          ) : null}
        </dl>

        <details open>
          <summary>后端假设（原样显示，注意它是否声明为实测）</summary>
          <ul className="assumptions">
            {(budget.assumptions ?? []).map((item, index) => (
              <li key={index} className="mono small">
                {JSON.stringify(item)}
              </li>
            ))}
          </ul>
          <p className="muted">{budget.note}</p>
        </details>

        {stage ? (
          <details>
            <summary>阶段定义（GET /stages）</summary>
            <dl className="kv kv--tight">
              <div className="kv__row">
                <dt>阶段</dt>
                <dd className="mono">
                  {stage.stage} · {stage.title}
                </dd>
              </div>
              <div className="kv__row">
                <dt>所需能力</dt>
                <dd className="mono">{stage.capabilities.length > 0 ? stage.capabilities.join(', ') : '（无需能力模块）'}</dd>
              </div>
              <div className="kv__row">
                <dt>所需环境能力</dt>
                <dd className="mono">{stage.env.length > 0 ? stage.env.join(', ') : '—'}</dd>
              </div>
              <div className="kv__row">
                <dt>成本类 / 实现方</dt>
                <dd className="mono">
                  {stage.cost_class} / {stage.implemented_by}
                </dd>
              </div>
              {stage.description ? (
                <div className="kv__row">
                  <dt>说明</dt>
                  <dd>{stage.description}</dd>
                </div>
              ) : null}
            </dl>
          </details>
        ) : null}
      </div>
    </section>
  );
}
