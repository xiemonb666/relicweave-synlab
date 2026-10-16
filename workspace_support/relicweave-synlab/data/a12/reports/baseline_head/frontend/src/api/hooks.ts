/**
 * 异步状态与事件流 hooks。
 *
 * 统一状态机：`loading`（首次加载）→ `ready` / `error`；重新加载时保留旧数据但暴露
 * `refreshing`（避免画布闪空），`reload()` 可手动重试。任何失败都保留原始错误对象，
 * 由页面用 `describeError` 渲染具体 code/message/request_id，绝不回落成假数据。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { API_ROOT, FIXTURES_ENABLED, NetworkError } from '../api/client';
import type { RunEvent } from '../api/types';

export type ResourceStatus = 'loading' | 'ready' | 'error';

export interface Resource<T> {
  status: ResourceStatus;
  data: T | null;
  error: unknown;
  /** 已有数据时的后台刷新（轮询/手动刷新）。 */
  refreshing: boolean;
  /** 最近一次成功加载的时间戳。 */
  updatedAt: number | null;
  /** 数据来自 fixture（仅 VITE_SYNLAB_FIXTURES=1）。 */
  fixture: boolean;
  reload: () => void;
}

export interface ResourceOptions {
  /** 轮询间隔（毫秒）；0/undefined 表示不轮询。 */
  intervalMs?: number;
  /** 为 false 时挂起（例如依赖为空）。 */
  enabled?: boolean;
  /** fixture 键；仅 VITE_SYNLAB_FIXTURES=1 时生效。 */
  fixtureKey?: string;
}

export function useResource<T>(
  loader: (signal: AbortSignal) => Promise<T>,
  deps: readonly unknown[],
  options: ResourceOptions = {},
): Resource<T> {
  const { intervalMs = 0, enabled = true, fixtureKey } = options;
  const [status, setStatus] = useState<ResourceStatus>(enabled ? 'loading' : 'loading');
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);
  const [nonce, setNonce] = useState(0);
  const [fixture, setFixture] = useState(false);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  const reload = useCallback(() => setNonce((value) => value + 1), []);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const stableDeps = useMemo(() => deps, deps);

  useEffect(() => {
    if (!enabled) {
      setStatus('loading');
      return undefined;
    }
    const controller = new AbortController();
    let cancelled = false;

    const applyFixture = async (): Promise<boolean> => {
      if (!FIXTURES_ENABLED || !fixtureKey) return false;
      // 动态 import：`FIXTURES_ENABLED` 在默认构建里被静态替换为 false，整段(含 fixture 数据)
      // 会被 tree-shake 掉。只有显式 VITE_SYNLAB_FIXTURES=1 构建出来的产物才带 fixture 表。
      const { fixtureFor } = await import('../lib/fixtures');
      const value = fixtureFor(fixtureKey);
      if (value === undefined) return false;
      setFixture(true);
      setData(value as T);
      setError(null);
      setStatus('ready');
      setUpdatedAt(Date.now());
      return true;
    };

    const run = async (isRefresh: boolean) => {
      if (!isRefresh) setStatus((prev) => (prev === 'ready' ? prev : 'loading'));
      if (isRefresh) setRefreshing(true);
      if (await applyFixture()) {
        setRefreshing(false);
        return;
      }
      try {
        const value = await loaderRef.current(controller.signal);
        if (cancelled) return;
        setFixture(false);
        setData(value);
        setError(null);
        setStatus('ready');
        setUpdatedAt(Date.now());
      } catch (caught) {
        if (cancelled) return;
        if (caught instanceof DOMException && caught.name === 'AbortError') return;
        setError(caught);
        setStatus('error');
        if (!isRefresh) setData(null);
      } finally {
        if (!cancelled) setRefreshing(false);
      }
    };

    void run(nonce > 0);

    let timer: number | undefined;
    if (intervalMs > 0) {
      timer = window.setInterval(() => void run(true), intervalMs);
    }
    return () => {
      cancelled = true;
      controller.abort();
      if (timer !== undefined) window.clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, intervalMs, nonce, fixtureKey, ...stableDeps]);

  return { status, data, error, refreshing, updatedAt, fixture, reload };
}

/* ------------------------------------------------------------------ 防抖 */
export function useDebounced<T>(value: T, delayMs = 350): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delayMs);
    return () => window.clearTimeout(timer);
  }, [value, delayMs]);
  return debounced;
}

/* ------------------------------------------------------------------ SSE */
export type StreamState = 'idle' | 'connecting' | 'open' | 'reconnecting' | 'closed' | 'error';

export interface RunEventStream {
  state: StreamState;
  events: RunEvent[];
  lastSeq: number;
  error: string | null;
  /** 事件流不可用时，页面可以退化为轮询 `/jobs?run_id=`。 */
  pollingFallback: boolean;
  restart: () => void;
}

interface ParsedFrame {
  id?: string;
  event?: string;
  data?: string;
}

function parseFrames(buffer: string): { frames: ParsedFrame[]; rest: string } {
  const frames: ParsedFrame[] = [];
  let rest = buffer;
  let index = buffer.indexOf('\n\n');
  while (index !== -1) {
    const chunk = rest.slice(0, index);
    rest = rest.slice(index + 2);
    const frame: ParsedFrame = {};
    for (const rawLine of chunk.split('\n')) {
      const line = rawLine.replace(/\r$/, '');
      if (!line || line.startsWith(':')) continue;
      const colon = line.indexOf(':');
      const field = colon === -1 ? line : line.slice(0, colon);
      const value = colon === -1 ? '' : line.slice(colon + 1).replace(/^ /, '');
      if (field === 'id') frame.id = value;
      else if (field === 'event') frame.event = value;
      else if (field === 'data') frame.data = frame.data ? `${frame.data}\n${value}` : value;
    }
    if (frame.event || frame.data !== undefined || frame.id) frames.push(frame);
    index = rest.indexOf('\n\n');
  }
  return { frames, rest };
}

/**
 * `GET /runs/{run_id}/events` 的真实 SSE 读取器。
 *
 * 用 fetch 流而不是 EventSource，原因：后端把事件类型放在 `event:` 字段（自定义事件名），
 * 而重连必须显式带上 `after_seq`/`Last-Event-ID`。这里按 `seq` 单调归并，旧事件不会回退新状态。
 */
export function useRunEventStream(runId: string | null, options: { enabled?: boolean } = {}): RunEventStream {
  const enabled = (options.enabled ?? true) && !!runId;
  const [state, setState] = useState<StreamState>(runId ? 'connecting' : 'idle');
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [lastSeq, setLastSeq] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [pollingFallback, setPollingFallback] = useState(false);
  const [restartNonce, setRestartNonce] = useState(0);
  const seqRef = useRef(0);

  useEffect(() => {
    seqRef.current = 0;
    setEvents([]);
    setLastSeq(0);
    setError(null);
    setPollingFallback(false);
    setState(runId ? 'connecting' : 'idle');
  }, [runId, restartNonce]);

  useEffect(() => {
    if (!enabled || !runId) return undefined;
    const controller = new AbortController();
    let cancelled = false;
    let attempts = 0;

    const connect = async () => {
      while (!cancelled && attempts < 5) {
        attempts += 1;
        setState(attempts === 1 ? 'connecting' : 'reconnecting');
        try {
          const url = `${API_ROOT}/runs/${encodeURIComponent(runId)}/events?follow=true&after_seq=${seqRef.current}&limit=500`;
          const response = await fetch(url, {
            headers: { Accept: 'text/event-stream', 'Last-Event-ID': String(seqRef.current) },
            signal: controller.signal,
            cache: 'no-store',
          });
          if (!response.ok || !response.body) {
            throw new Error(`HTTP ${response.status} ${response.statusText}`);
          }
          setState('open');
          setError(null);
          const reader = response.body.getReader();
          const decoder = new TextDecoder();
          let buffer = '';
          for (;;) {
            const { value, done } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const { frames, rest } = parseFrames(buffer);
            buffer = rest;
            for (const frame of frames) {
              if (frame.event === 'stream_end') {
                setState('closed');
                return;
              }
              if (frame.data === undefined) continue;
              let parsed: RunEvent;
              try {
                parsed = JSON.parse(frame.data) as RunEvent;
              } catch {
                continue;
              }
              if (typeof parsed.seq !== 'number') continue;
              if (parsed.seq <= seqRef.current) continue; // 旧 seq 不回退新状态
              seqRef.current = parsed.seq;
              setLastSeq(parsed.seq);
              setEvents((prev) => [...prev, parsed]);
            }
          }
          if (!cancelled) setState('reconnecting');
        } catch (caught) {
          if (cancelled) return;
          if (caught instanceof DOMException && caught.name === 'AbortError') return;
          setError(
            caught instanceof NetworkError
              ? caught.message
              : `事件流中断：${(caught as Error)?.message ?? String(caught)}`,
          );
          setState('reconnecting');
          await new Promise((resolve) => window.setTimeout(resolve, Math.min(4000, 400 * attempts)));
        }
      }
      if (!cancelled) {
        setState('error');
        setPollingFallback(true);
      }
    };

    void connect();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [enabled, runId, restartNonce]);

  return {
    state,
    events,
    lastSeq,
    error,
    pollingFallback,
    restart: () => setRestartNonce((value) => value + 1),
  };
}

/** 生成合法幂等键（后端要求 1..128 字符）。 */
export function newIdempotencyKey(prefix: string): string {
  const random =
    typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}:${random}`.slice(0, 128);
}
