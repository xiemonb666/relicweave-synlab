/**
 * JobTimeline —— 真实 SSE 事件时间线（计划 20.8 / 20.14.8）。
 *
 * 事件来自 `GET /runs/{run_id}/events`（seq/revision 单调）。时间线只显示后端发来的事件：
 * heartbeat 不是假百分比，缺 progress 就显示“未计数”。断线时显示当前流状态与
 * Last-Event-ID（已收到的最大 seq），并提示可退化为轮询。
 */

import { useEffect, useRef } from 'react';

import type { RunEvent } from '../api/types';
import type { StreamState } from '../api/hooks';
import { formatTimestamp, jobStateLabel } from '../lib/format';
import { Badge, EmptyState } from './states';

export interface JobTimelineProps {
  events: RunEvent[];
  streamState: StreamState;
  lastSeq: number;
  streamError?: string | null;
  pollingFallback?: boolean;
  emptyReason?: React.ReactNode;
  title?: string;
}

const STREAM_LABEL: Record<StreamState, { label: string; tone: 'ok' | 'warn' | 'bad' | 'info' | 'neutral' }> = {
  idle: { label: '未连接（没有选中 run）', tone: 'neutral' },
  connecting: { label: '连接中', tone: 'info' },
  open: { label: '事件流已连接', tone: 'ok' },
  reconnecting: { label: '断线重连中（带 Last-Event-ID）', tone: 'warn' },
  closed: { label: '事件流已正常结束', tone: 'ok' },
  error: { label: '事件流不可用', tone: 'bad' },
};

export function JobTimeline({
  events,
  streamState,
  lastSeq,
  streamError,
  pollingFallback,
  emptyReason,
  title = '任务时间线',
}: JobTimelineProps) {
  const listRef = useRef<HTMLOListElement>(null);
  const previousCount = useRef(0);

  useEffect(() => {
    // 新事件到达时把焦点区域滚动到底部（可键盘访问，不抢焦点）
    if (events.length > previousCount.current && listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
    previousCount.current = events.length;
  }, [events.length]);

  const stream = STREAM_LABEL[streamState];

  return (
    <div className="timeline">
      <div className="timeline__head">
        <h3>{title}</h3>
        <Badge tone={stream.tone}>{stream.label}</Badge>
        <span className="mono small">已接收 {events.length} 个事件 · Last-Event-ID(seq)={lastSeq}</span>
        {pollingFallback ? <Badge tone="warn">已退化为轮询 GET /jobs?run_id=</Badge> : null}
      </div>

      {streamError ? (
        <p className="warning" role="status">
          事件流错误：<span className="mono">{streamError}</span>。时间线保留已收到的事件；页面会继续用{' '}
          <code className="mono">GET /jobs?run_id=</code> 轮询权威状态。
        </p>
      ) : null}

      {events.length === 0 ? (
        <EmptyState
          title="还没有事件"
          reason={
            emptyReason ?? (
              <>
                该 run 尚未产生事件，或事件流还没建立。后端 <code className="mono">seq</code> 持久化，
                重连会从 Last-Event-ID 之后继续，不会补造事件。
              </>
            )
          }
        />
      ) : (
        <ol className="timeline__list" ref={listRef}>
          {events.map((event) => {
            const state = jobStateLabel(event.state);
            const progress = event.progress;
            return (
              <li key={`${event.seq}-${event.type}`} className="timeline__item">
                <div className="timeline__meta">
                  <span className="mono">#{event.seq}</span>
                  <span className="mono">rev {event.revision}</span>
                  <span className="mono">{formatTimestamp(event.created_at)}</span>
                </div>
                <div className="timeline__body">
                  <div className="timeline__title">
                    <Badge tone="info">{event.type}</Badge>
                    <Badge tone={state.tone}>{state.label}</Badge>
                    {event.job_id ? <span className="mono small">{event.job_id}</span> : null}
                    {event.metrics_ref ? <span className="mono small">metrics_ref={event.metrics_ref}</span> : null}
                    {event.error_ref ? <Badge tone="bad">error_ref={event.error_ref}</Badge> : null}
                  </div>
                  {event.message ? <div className="timeline__message">{event.message}</div> : null}
                  {progress ? (
                    <div className="timeline__progress">
                      <progress
                        value={progress.done ?? 0}
                        max={progress.planned && progress.planned > 0 ? progress.planned : undefined}
                      />
                      <span className="mono">
                        {progress.done ?? '未计数'} / {progress.planned ?? '未计数'} {progress.unit ?? '（单位未提供）'}
                      </span>
                    </div>
                  ) : (
                    <div className="muted small">本事件未携带 progress —— handler 还没计数，不按墙钟推算。</div>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
