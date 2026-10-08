/**
 * 真实 API 客户端。任何失败都必须能被 UI 具体化展示，因此这里区分两类失败：
 *
 * * `ApiError` —— 后端返回的结构化错误信封（`{ok:false,error:{code,status,stage,...}}`），
 *   页面必须显示 `code`（例如 `ENV_CAPABILITY_MISSING`）、`message` 与 `request_id`；
 * * `NetworkError` —— 连不上后端 / 超时 / 响应不是 JSON，页面显示“后端不可用”并给出实际请求地址。
 *
 * 这里**不做任何兜底假数据**：没有后端就是没有数据。
 */

import type { ApiErrorBody } from './types';

const RAW_BASE = (import.meta.env.VITE_SYNLAB_API_BASE ?? '').trim();
export const API_BASE = RAW_BASE.replace(/\/+$/, '');
export const API_PREFIX = '/api/synlab';
export const API_ROOT = `${API_BASE}${API_PREFIX}`;

export const ROLE_HEADER = (import.meta.env.VITE_SYNLAB_ROLE ?? '').trim();
export const SESSION_HEADER = (import.meta.env.VITE_SYNLAB_SESSION ?? '').trim();
export const WORKSPACE_HEADER = (import.meta.env.VITE_SYNLAB_WORKSPACE ?? '').trim();

export const DEFAULT_TIMEOUT_MS = 30_000;

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly stage: string;
  readonly retryable: boolean;
  readonly details: Record<string, unknown>;
  readonly evidenceRefs: string[];
  readonly requestId: string;
  readonly path: string;

  constructor(body: ApiErrorBody, path: string) {
    super(body.message || body.code);
    this.name = 'ApiError';
    this.code = body.code;
    this.status = body.status;
    this.stage = body.stage;
    this.retryable = body.retryable;
    this.details = body.details ?? {};
    this.evidenceRefs = body.evidence_refs ?? [];
    this.requestId = body.request_id;
    this.path = path;
  }

  /** 一行式诊断串，直接贴进 UI / 缺陷报告。 */
  get diagnostics(): string {
    return `[${this.code}] HTTP ${this.status} · ${this.stage} · request_id=${this.requestId}`;
  }
}

export class NetworkError extends Error {
  readonly url: string;
  readonly reason: string;
  readonly cause?: unknown;

  constructor(url: string, reason: string, cause?: unknown) {
    super(`无法访问后端 ${url}：${reason}`);
    this.name = 'NetworkError';
    this.url = url;
    this.reason = reason;
    this.cause = cause;
  }
}

export interface RequestOptions {
  method?: 'GET' | 'POST';
  query?: Record<string, string | number | boolean | string[] | undefined | null>;
  body?: unknown;
  signal?: AbortSignal;
  timeoutMs?: number;
}

export function buildUrl(path: string, query?: RequestOptions['query']): string {
  const search = new URLSearchParams();
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value === undefined || value === null || value === '') continue;
      if (Array.isArray(value)) {
        for (const item of value) search.append(key, item);
      } else {
        search.append(key, String(value));
      }
    }
  }
  const qs = search.toString();
  return `${API_ROOT}${path}${qs ? `?${qs}` : ''}`;
}

function headersFor(json: boolean): HeadersInit {
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (json) headers['Content-Type'] = 'application/json';
  if (ROLE_HEADER) headers['X-SynLab-Role'] = ROLE_HEADER;
  if (SESSION_HEADER) headers['X-SynLab-Session'] = SESSION_HEADER;
  if (WORKSPACE_HEADER) headers['X-SynLab-Workspace'] = WORKSPACE_HEADER;
  return headers;
}

async function readError(response: Response, path: string): Promise<never> {
  let text = '';
  try {
    text = await response.text();
  } catch {
    text = '';
  }
  let parsed: unknown = null;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = null;
    }
  }
  const envelope = parsed as { error?: ApiErrorBody } | null;
  if (envelope && envelope.error && typeof envelope.error.code === 'string') {
    throw new ApiError(envelope.error, path);
  }
  // 非结构化错误（例如 FastAPI 自身的 404 {"detail":"Not Found"}）也如实抛出。
  const detail =
    parsed && typeof parsed === 'object' && 'detail' in (parsed as Record<string, unknown>)
      ? String((parsed as Record<string, unknown>).detail)
      : text.slice(0, 400) || response.statusText;
  // dev/preview 反代在后端未启动时会返回 5xx 且正文不是结构化错误信封。
  // FastAPI 自己抛出的任何失败（含 500 INTERNAL_ERROR）都一定带 `{ok:false,error:{...}}`，
  // 所以“5xx 且无信封”可以可靠地判定为“没连上后端”，给一个可操作的 code。
  const unreachable = response.status >= 500;
  const connectionHint = /ECONNREFUSED|ECONNRESET|EAI_AGAIN|ENOTFOUND|socket hang up|proxy error/i.test(text);
  throw new ApiError(
    {
      code: unreachable ? 'BACKEND_UNREACHABLE' : `HTTP_${response.status}`,
      status: response.status,
      stage: unreachable ? 'transport.proxy' : 'transport',
      message: unreachable
        ? `未收到后端结构化错误（HTTP ${response.status}）：${text.slice(0, 200) || response.statusText}${
            connectionHint ? '（代理报告连接被拒绝/中断）' : '（通常表示后端进程未启动或端口/代理配置错误）'
          }`
        : detail || `HTTP ${response.status}`,
      retryable: response.status >= 500,
      details: { raw_body: text.slice(0, 800) },
      evidence_refs: [],
      request_id: response.headers.get('X-Request-Id') ?? '',
    },
    path,
  );
}

async function requestRaw(path: string, options: RequestOptions = {}): Promise<Response> {
  const url = buildUrl(path, options.query);
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), options.timeoutMs ?? DEFAULT_TIMEOUT_MS);
  const onAbort = () => controller.abort();
  options.signal?.addEventListener('abort', onAbort);
  try {
    const response = await fetch(url, {
      method: options.method ?? 'GET',
      headers: headersFor(options.body !== undefined),
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: controller.signal,
      credentials: 'omit',
      cache: 'no-store',
    });
    if (!response.ok) await readError(response, path);
    return response;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (options.signal?.aborted) throw error;
    const aborted = (error as { name?: string })?.name === 'AbortError';
    throw new NetworkError(
      url,
      aborted
        ? `请求超时（${options.timeoutMs ?? DEFAULT_TIMEOUT_MS} ms），后端未在时限内响应`
        : `${(error as Error)?.message ?? '网络错误'}（后端未启动、端口/代理配置错误或被浏览器拦截）`,
      error,
    );
  } finally {
    window.clearTimeout(timeout);
    options.signal?.removeEventListener('abort', onAbort);
  }
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await requestRaw(path, options);
  try {
    return (await response.json()) as T;
  } catch (error) {
    throw new NetworkError(buildUrl(path, options.query), `响应不是合法 JSON：${String(error)}`, error);
  }
}

/** 资产文件流（GLB / 数组包）。返回 Blob 与真实响应头，头里带 sha256 与 hash 校验结果。 */
export async function requestBlob(
  path: string,
  query?: RequestOptions['query'],
  signal?: AbortSignal,
): Promise<{ blob: Blob; headers: Headers; url: string }> {
  const response = await requestRaw(path, { query, signal, timeoutMs: 120_000 });
  const url = buildUrl(path, query);
  const headers = response.headers;
  const blob = await response.blob();
  return { blob, headers, url };
}

/** 诊断串，渲染在错误卡片里供复制。 */
export function describeError(error: unknown): {
  kind: 'api' | 'network' | 'unreachable' | 'unknown';
  title: string;
  code: string;
  message: string;
  diagnostics: string;
  retryable: boolean;
  details?: Record<string, unknown>;
} {
  if (error instanceof ApiError) {
    const unreachable = error.code === 'BACKEND_UNREACHABLE';
    return {
      kind: unreachable ? 'unreachable' : 'api',
      title: unreachable ? '后端不可用（代理无法连接）' : `后端返回错误 ${error.status}`,
      code: error.code,
      message: error.message,
      diagnostics: error.diagnostics,
      retryable: error.retryable,
      details: error.details,
    };
  }
  if (error instanceof NetworkError) {
    return {
      kind: 'network',
      title: '后端不可用',
      code: 'BACKEND_UNREACHABLE',
      message: error.message,
      diagnostics: `GET/POST ${error.url} · ${error.reason}`,
      retryable: true,
    };
  }
  const fallback = error as Error | undefined;
  return {
    kind: 'unknown',
    title: '未知错误',
    code: 'UNKNOWN',
    message: fallback?.message ?? String(error),
    diagnostics: fallback?.stack ?? String(error),
    retryable: false,
  };
}

/** 只有在显式开启时才为 true；UI 用它显示 fixture 标记。 */
export const FIXTURES_ENABLED = (import.meta.env.VITE_SYNLAB_FIXTURES ?? '') === '1';
