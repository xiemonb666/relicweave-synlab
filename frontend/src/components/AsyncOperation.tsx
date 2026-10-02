/**
 * 异步操作的诚实状态卡 + 轮询 hook。
 *
 * 用途：向导第 ⑤ 步（同步单谱系预览）与 U07 的批处理面板都需要「进行中 / 失败 / 可重试」
 * 三态，并且失败时必须给出**真实错误码**与**可照抄的复现命令**。
 *
 * 数据来源约定：
 * * 后端结构化失败（problem envelope / 响应体里的 `blocked`）→ 显示 `code` + `message`；
 * * `repro` 数组是后端返回的真实命令行（本组件原样展示、可复制），前端不拼命令；
 * * 轮询只读 `GET /jobs/{id}` 的权威 state，不做任何本地推测。
 */

import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';

import { describeError } from '../api/client';
import { getJob } from '../api/endpoints';
import type { JobDetailResponse } from '../api/types';
import { Badge, CopyValue, KeyValueList } from './states';

export type AsyncPhase = 'idle' | 'running' | 'done' | 'failed';

export interface AsyncStatus {
  phase: AsyncPhase;
  /** 人类可读的当前动作（例如“第 3/12 个 job 运行中”）。 */
  label: string;
  startedAt: number | null;
  finishedAt: number | null;
  elapsedMs: number | null;
}

export const IDLE_STATUS: AsyncStatus = {
  phase: 'idle',
  label: '未开始',
  startedAt: null,
  finishedAt: null,
  elapsedMs: null,
};

/** 结构化失败信息（来自后端 code/details/repro，或本地的网络错误）。 */
export interface FailureInfo {
  code: string;
  message: string;
  stage?: string;
  retryable?: boolean;
  requestId?: string;
  details?: Record<string, unknown>;
  /** 后端给出的可照抄命令（原样展示，不由前端编造）。 */
  repro?: string[];
  hint?: string;
}

export function failureFromError(error: unknown): FailureInfo {
  const info = describeError(error);
  return {
    code: info.code,
    message: info.message,
    retryable: info.retryable,
    details: info.details,
    stage: info.kind,
  };
}

/** 失败卡：code + message + 复现命令（复制按钮）+ details（原样 JSON）。 */
export function FailureCard({
  title,
  failure,
  onRetry,
  compact,
  extra,
}: {
  title: string;
  failure: FailureInfo;
  onRetry?: () => void;
  compact?: boolean;
  extra?: ReactNode;
}) {
  return (
    <div className={`state state--error${compact ? ' state--compact' : ''}`} role="alert">
      <div className="state__title">
        {title}
        <Badge tone="bad">{failure.code}</Badge>
        {failure.retryable ? <Badge tone="info">后端标记可重试</Badge> : null}
        {failure.stage ? <span className="muted small mono">{failure.stage}</span> : null}
      </div>
      <div className="state__detail">{failure.message}</div>
      {failure.requestId ? (
        <div className="state__meta mono">request_id={failure.requestId}</div>
      ) : null}
      {failure.hint ? <div className="state__detail">{failure.hint}</div> : null}
      {failure.repro && failure.repro.length > 0 ? (
        <div className="state__detail">
          <div className="muted small">复现命令（后端原样返回，可直接粘贴执行）：</div>
          <dl className="kv kv--tight">
            {failure.repro.map((command) => (
              <div className="kv__row" key={command}>
                <dt className="mono small">repro</dt>
                <dd>
                  <CopyValue value={command} label="复现命令" />
                </dd>
              </div>
            ))}
          </dl>
        </div>
      ) : null}
      {extra}
      {failure.details && Object.keys(failure.details).length > 0 ? (
        <details className="state__details">
          <summary>后端 details（原样展示）</summary>
          <pre className="mono pre">{JSON.stringify(failure.details, null, 2)}</pre>
        </details>
      ) : null}
      {onRetry ? (
        <div className="state__action">
          <button type="button" className="btn btn--primary" onClick={onRetry}>
            重试
          </button>
        </div>
      ) : null}
    </div>
  );
}

/** 运行中提示：显示已等待的真实时长与当前权威状态，不预测剩余时间。 */
export function RunningCard({
  title,
  label,
  elapsedMs,
  details,
}: {
  title: string;
  label: string;
  elapsedMs: number | null;
  details?: Array<{ label: string; value: ReactNode }>;
}) {
  return (
    <div className="state state--loading" role="status" aria-live="polite">
      <div className="state__title">
        <span className="spinner__dot" aria-hidden="true" />
        {title}
        <Badge tone="info">进行中</Badge>
      </div>
      <div className="state__detail">{label}</div>
      <div className="state__meta mono">
        已等待 {elapsedMs === null ? '—' : `${(elapsedMs / 1000).toFixed(1)} s`}（真实墙钟；剩余时间不预测）
      </div>
      {details && details.length > 0 ? <KeyValueList rows={details} /> : null}
    </div>
  );
}

export interface JobWatchState {
  detail: JobDetailResponse | null;
  status: AsyncStatus;
  error: unknown;
  polling: boolean;
  stop: () => void;
}

/**
 * 轮询一个真实 job 直到终止态（或父组件停止）。
 *
 * `intervalMs` 默认 1000 ms；后端每次返回的都是 `GET /jobs/{id}` 的权威 state，本 hook
 * 只在 state 变化时更新 detail，避免无意义重渲染（预览性能要求 5）。
 */
export function useJobWatch(
  jobId: string | null,
  options: { enabled?: boolean; intervalMs?: number; onTerminal?: (detail: JobDetailResponse) => void } = {},
): JobWatchState {
  const { enabled = true, intervalMs = 1000 } = options;
  const [detail, setDetail] = useState<JobDetailResponse | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [phase, setPhase] = useState<AsyncPhase>('idle');
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [elapsedMs, setElapsedMs] = useState<number | null>(null);
  const [nonce] = useState(0);
  const terminalRef = useRef(false);
  const callbackRef = useRef(options.onTerminal);
  callbackRef.current = options.onTerminal;

  useEffect(() => {
    if (!jobId || !enabled) {
      terminalRef.current = false;
      setPhase('idle');
      setDetail(null);
      setError(null);
      setStartedAt(null);
      setElapsedMs(null);
      return undefined;
    }
    terminalRef.current = false;
    setPhase('running');
    setStartedAt(Date.now());
    setError(null);
    return undefined;
  }, [jobId, enabled, nonce]);

  useEffect(() => {
    if (!jobId || !enabled || terminalRef.current) return undefined;
    let cancelled = false;
    let timer: number | undefined;

    const poll = async () => {
      try {
        const response = await getJob(jobId);
        if (cancelled) return;
        setDetail((previous) => (previous && previous.job.state === response.job.state
          && previous.job.updated_at === response.job.updated_at ? previous : response));
        if (response.terminal) {
          terminalRef.current = true;
          setPhase('done');
          callbackRef.current?.(response);
          return;
        }
      } catch (caught) {
        if (cancelled) return;
        setError(caught);
        setPhase('failed');
        return;
      }
      timer = window.setTimeout(() => void poll(), intervalMs);
    };
    void poll();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [jobId, enabled, intervalMs, nonce]);

  useEffect(() => {
    if (phase !== 'running' || startedAt === null) return undefined;
    const tick = window.setInterval(() => setElapsedMs(Date.now() - startedAt), 250);
    return () => window.clearInterval(tick);
  }, [phase, startedAt]);

  const stop = useCallback(() => {
    terminalRef.current = true;
    setPhase('idle');
  }, []);

  return {
    detail,
    error,
    polling: phase === 'running',
    status: {
      phase: error ? 'failed' : phase,
      label: detail ? `job state = ${detail.job.state}` : phase === 'running' ? '等待权威状态…' : '未开始',
      startedAt,
      finishedAt: phase === 'done' ? Date.now() : null,
      elapsedMs,
    },
    stop,
  };
}
