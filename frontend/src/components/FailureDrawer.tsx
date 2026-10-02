/**
 * FailureDrawer —— 失败/隔离详情（计划 20.13 U12：问题代码、影响 run/release、最小复现、
 * 错误资产、下一动作、重试是否支持；入口对应真实日志/报告）。
 *
 * 数据来自真实 `GET /jobs/{job_id}` 的 `job.error` 与 `job.spec`，以及 `GET /jobs?state=...`
 * 的筛选结果。没有失败记录时不显示任何“待办表”。
 */

import type { ReactNode } from 'react';

import { getJob, retryJob } from '../api/endpoints';
import { useResource } from '../api/hooks';
import type { JobRecord } from '../api/types';
import { formatTimestamp, jobStateLabel, pretty } from '../lib/format';
import { ActionButton, Badge, CopyValue, Drawer, ErrorState, KeyValueList, LoadingState } from './states';

export interface FailureDrawerProps {
  jobId: string | null;
  onClose: () => void;
  /** 重试成功后回调（页面刷新列表 / 切换选中 run）。 */
  onRetried?: (response: Record<string, unknown>) => void;
  /** 已知的 job 行（避免重复请求，仍会请求详情以拿 error/spec）。 */
  fallbackJob?: JobRecord | null;
  /**
   * 非 job 来源的失败/阻塞（例如展示页 manifest 里 `status=FAILED/BLOCKED` 的条目）。
   *
   * 这些条目**没有** job id，`GET /jobs/{id}` 无从查起；此时抽屉直接从给出的结构化字段渲染
   * 真实的 code / message / stage / measurements / 最小复现命令，绝不因为“没有 job”就
   * 编一条错误出来。提供该字段时 `jobId` 必须为 null。
   */
  staticFailure?: StaticFailure | null;
}

/** 展示页/清单类条目的真实失败结构（字段名与后端错误信封一致）。 */
export interface StaticFailure {
  title: string;
  code: string;
  message: string;
  stage?: string | null;
  retryable?: boolean | null;
  measurements?: unknown;
  detail?: string | null;
  /** 该条目的真实来源标识（asset_id / entry_id / manifest 路径）。 */
  sourceRef?: string | null;
  status?: string | null;
  /** 可复现的命令行（真实存在的命令，不是示意）。 */
  reproduceCommand?: string | null;
  /** 额外的诚实字段（原样展示）。 */
  extraRows?: Array<{ label: string; value: ReactNode }>;
}

const NEXT_ACTION: Record<string, { action: string; tone: 'ok' | 'warn' | 'bad' | 'info' | 'neutral' }> = {
  FAILED: { action: '查看 error.details 与证据；若 retryable=true 可重试（会产生新 attempt）。', tone: 'bad' },
  RETRYABLE: { action: '后端明确标记可重试：直接 requeue 回 PENDING，内容种子不变。', tone: 'warn' },
  QUARANTINED: { action: '资产已隔离，不进入 release；请检查上游 QA 或换输入后重跑。', tone: 'warn' },
  BLOCKED: { action: '依赖未 COMMITTED；先修复上游 job，再 resume，不要手工改状态。', tone: 'warn' },
  CANCELLED: { action: '已取消（已提交输出被保留）。如需继续请重新提交新 run。', tone: 'neutral' },
};

export function FailureDrawer({ jobId, onClose, onRetried, fallbackJob, staticFailure }: FailureDrawerProps) {
  const resource = useResource(
    (signal) => getJob(jobId as string, signal),
    [jobId],
    { enabled: Boolean(jobId), intervalMs: jobId ? 5000 : 0 },
  );

  const detail = resource.data;
  const job = detail?.job ?? fallbackJob ?? null;
  const error = (detail?.error ?? job?.error ?? null) as Record<string, unknown> | null;
  const retryable = Boolean(error && error.retryable);
  const state = job?.state ?? 'UNKNOWN';

  const append = (object: Record<string, unknown> | null | undefined) => object ?? {};

  const retry = async () => {
    if (!jobId) return;
    const response = await retryJob(jobId, { reason: `UI 手动重试（state=${state}）` });
    onRetried?.(response as unknown as Record<string, unknown>);
    resource.reload();
  };

  const spec = append(job?.spec);
  const cmd = `python -m synlab.cli job --job ${jobId ?? ''} --json`;

  // ---------------------------------------------------------------- 非 job 来源（展示清单条目）
  if (!jobId && staticFailure) {
    return (
      <Drawer open title={staticFailure.title} onClose={onClose}>
        <div className="drawer__section">
          <h4>问题代码与信息（来自 demo_manifest.json，非 job）</h4>
          <KeyValueList
            rows={[
              { label: '状态', value: <Badge tone={staticFailure.status === 'BLOCKED' ? 'warn' : 'bad'}>{staticFailure.status ?? 'FAILED'}</Badge> },
              { label: 'code', value: <Badge tone="bad">{staticFailure.code}</Badge> },
              { label: 'message', value: staticFailure.message },
              { label: 'stage', value: staticFailure.stage || '未提供' },
              { label: 'retryable', value: String(staticFailure.retryable ?? '未提供') },
              { label: 'source_ref', value: <span className="mono">{staticFailure.sourceRef ?? '未提供'}</span> },
            ]}
          />
          {staticFailure.detail ? <p className="muted">{staticFailure.detail}</p> : null}
          {staticFailure.measurements !== undefined && staticFailure.measurements !== null ? (
            <details className="state__details" open>
              <summary>measurements（后端原样返回）</summary>
              <pre className="mono pre">{pretty(staticFailure.measurements)}</pre>
            </details>
          ) : null}
        </div>

        {staticFailure.extraRows && staticFailure.extraRows.length > 0 ? (
          <div className="drawer__section">
            <h4>相关真实字段</h4>
            <KeyValueList rows={staticFailure.extraRows} />
          </div>
        ) : null}

        <div className="drawer__section">
          <h4>最小复现</h4>
          {staticFailure.reproduceCommand ? (
            <p>
              等价 CLI 复现（本仓库真实支持的命令形式）：
              <br />
              <code className="mono">{staticFailure.reproduceCommand}</code>
            </p>
          ) : (
            <p className="muted">该条目没有可复现命令（不是 job 产出）。</p>
          )}
        </div>

        <div className="drawer__section">
          <h4>下一动作</h4>
          <p className="muted">
            展示页只读，不会重试或改写任何资产。要改变这里的结论，必须修好上游模块后重跑生成器
            （<code className="mono">tools/build_demo_assets.py</code>），清单会记录新的真实状态。
          </p>
        </div>
      </Drawer>
    );
  }

  return (
    <Drawer open={Boolean(jobId)} title={`失败 / 隔离详情 ${jobId ?? ''}`} onClose={onClose}>
      {resource.status === 'loading' && !detail ? <LoadingState label="加载 job 详情（GET /jobs/{id}）…" /> : null}
      {resource.status === 'error' ? <ErrorState error={resource.error} onRetry={resource.reload} compact /> : null}

      {detail ? (
        <>
          <div className="drawer__section">
            <h4>状态</h4>
            <div className="row">
              <Badge tone={jobStateLabel(state).tone}>{jobStateLabel(state).label}</Badge>
              <span className="mono small">
                stage={detail.job.stage}（{detail.stage_title}）· attempt={detail.job.attempt} · terminal=
                {String(detail.terminal)}
              </span>
            </div>
            <KeyValueList
              rows={[
                { label: 'run_id', value: <CopyValue value={detail.job.run_id} label="run_id" /> },
                { label: 'run 状态', value: detail.run.status ?? '后端未返回' },
                { label: 'run revision', value: detail.run.revision ?? '后端未返回' },
                { label: 'spec_hash', value: <span className="mono">{detail.run.spec_hash ?? '后端未返回'}</span> },
                { label: '队列位置', value: detail.queue_position === null ? '不在 PENDING 队列' : detail.queue_position },
                { label: '依赖 job', value: detail.dependencies.length > 0 ? detail.dependencies.join(', ') : '无' },
                { label: '被它阻塞', value: detail.blocked_dependents.length > 0 ? detail.blocked_dependents.join(', ') : '无' },
                { label: '更新时间', value: formatTimestamp(detail.job.updated_at) },
              ]}
            />
          </div>

          <div className="drawer__section">
            <h4>问题代码与信息</h4>
            {error ? (
              <>
                <KeyValueList
                  rows={[
                    { label: 'code', value: <Badge tone="bad">{String(error.code ?? '未提供')}</Badge> },
                    { label: 'message', value: String(error.message ?? '未提供') },
                    { label: 'stage', value: String(error.stage ?? '未提供') },
                    { label: 'retryable', value: String(error.retryable ?? '未提供') },
                    {
                      label: 'evidence_refs',
                      value: Array.isArray(error.evidence_refs)
                        ? (error.evidence_refs as unknown[]).join(', ') || '无'
                        : '无',
                    },
                  ]}
                />
                <pre className="mono pre">{pretty(error)}</pre>
              </>
            ) : (
              <p className="muted">
                该 job 当前没有 error 字段（state={state}）。注意 <code className="mono">FAILED</code> 之外的状态
                （例如 <code className="mono">QUARANTINED</code>）也可能带 error，请以页面顶部的真实状态为准。
              </p>
            )}
          </div>

          <div className="drawer__section">
            <h4>下一动作</h4>
            <p>{NEXT_ACTION[state]?.action ?? '按后端返回的状态与 error 决定；页面不推测处置方式。'}</p>
            <div className="row">
              <ActionButton
                tone="primary"
                busy={false}
                onClick={() => void retry()}
                disabledReason={
                  retryable
                    ? null
                    : `后端 error.retryable=${String(error?.retryable ?? '无 error')}，只有明确可重试的错误才允许重试`
                }
              >
                重试（产生新 attempt）
              </ActionButton>
            </div>
          </div>

          <div className="drawer__section">
            <h4>最小复现（来自 job.spec，服务端真实记录）</h4>
            <KeyValueList
              rows={[
                { label: 'workspace', value: String(spec.workspace ?? '未提供'), mono: true },
                { label: 'node_id', value: String(spec.node_id ?? '未提供'), mono: true },
                { label: 'chain', value: String(spec.chain ?? '未提供'), mono: true },
                { label: 'input_refs', value: Array.isArray(spec.input_refs) ? (spec.input_refs as string[]).join(', ') || '无' : '无' },
                { label: 'budget_ref', value: String(spec.budget_ref ?? '未提供'), mono: true },
                { label: 'planned_jobs', value: String(spec.planned_jobs ?? '未提供'), mono: true },
                { label: '输出资产', value: detail.job.outputs.length > 0 ? detail.job.outputs.join(', ') : '无（未提交任何输出）' },
              ]}
            />
            <p className="muted small">
              等价 CLI 复现（本仓库真实支持的命令形式）：<code className="mono">{cmd}</code>
            </p>
            <pre className="mono pre">{pretty(spec)}</pre>
          </div>

          <div className="drawer__section">
            <h4>影响范围</h4>
            <p className="muted">
              影响 run：<code className="mono">{detail.job.run_id}</code>。是否影响某个 release 需要看该 run 是否已被
              审计/冻结 —— 释放页会用 <code className="mono">GET /releases</code> 与{' '}
              <code className="mono">GET /audits</code> 的真实 manifest 判定，本抽屉不推测。
            </p>
          </div>
        </>
      ) : null}
    </Drawer>
  );
}
