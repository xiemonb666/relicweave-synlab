/**
 * 合成数据展示页（`/synlab/showcase`）的真实 API 客户端。
 *
 * 数据只来自两条**只读**路由（`synlab/api/routers/showcase.py`）：
 *
 * * `GET /showcase/manifest` —— `tools/build_demo_assets.py` 产出的
 *   `data/a12_demo/demo_manifest.json`，原样返回条目/指标/状态；
 * * `GET /showcase/asset/{asset_id}/{key}` —— 白名单 key `glb` / `png` / `arrays` / `meta`。
 *
 * 这里**不做任何兜底假数据**：没有清单就是 `NOT_RUN`，没有资产就是 404 结构化错误。
 */

import { API_ROOT, request, requestBlob, type RequestOptions } from './client';

export type ShowcaseStatus = 'OK' | 'BLOCKED' | 'FAILED' | 'NA';

export interface ShowcaseFailure {
  code: string;
  message: string;
  stage?: string;
  retryable?: boolean;
  measurements?: Record<string, unknown>;
  detail?: string | null;
}

export interface ShowcaseArtifact {
  asset_id: string;
  role?: string | null;
  key?: string;
  metrics?: Record<string, unknown>;
  render?: Record<string, unknown> | null;
  keys?: Record<string, string>;
}

export interface ShowcaseEntry {
  entry_id: string;
  kind: string;
  title: string;
  status: ShowcaseStatus;
  generated_at?: string | null;
  asset_id?: string | null;
  role?: string | null;
  schema?: string | null;
  unit?: string | null;
  frame?: string | null;
  qa_status?: string | null;
  duration_s?: number | null;
  attempts?: number | null;
  exit_code?: number | null;
  metrics?: Record<string, any>;
  artifacts?: Record<string, any>;
  failure?: ShowcaseFailure | null;
  /** `kind=single` 的退化条目上的原始字段 */
  axis_id?: string;
  family?: string;
  mother_entry?: string;
  vessel_id?: string;
  backend?: string;
  family_id?: string;
}

export interface ShowcaseAxisCatalogItem {
  axis_id: string | null;
  family: string;
  family_name: string;
  stage?: string;
  substage?: string;
  unit?: string;
  variants?: string[];
  default_variant?: string;
  factor_kinds?: Record<string, string>;
  accepted_sources?: string[];
  level_parameters?: Array<Record<string, unknown>>;
  generated: boolean;
  status: ShowcaseStatus;
  entry_id?: string | null;
  na_reason?: string;
}

export interface ShowcaseCounts {
  by_kind?: Record<string, { total?: number; OK?: number; BLOCKED?: number; FAILED?: number; NA?: number }>;
  total?: { OK?: number; BLOCKED?: number; FAILED?: number; NA?: number };
  entries?: number;
}

export interface ShowcaseRun {
  started_at?: string;
  command?: string;
  steps?: string[];
  limit?: number | null;
  force?: boolean;
  inline?: boolean;
  units_executed?: number;
  duration_s?: number;
  counts?: ShowcaseCounts;
}

export interface ShowcaseManifestResponse {
  ok: boolean;
  status: 'OK' | 'NOT_RUN';
  manifest_path: string;
  store_path: string;
  generator_command: string;
  generator: string;
  role: string;
  workspace: string;
  read_only: boolean;
  generated_at?: string | null;
  updated_at?: string | null;
  master_seed?: number | null;
  lineage_id?: string | null;
  schema?: string | null;
  entries: ShowcaseEntry[];
  axis_catalog: ShowcaseAxisCatalogItem[];
  runs: ShowcaseRun[];
  notes: string[];
  environment_findings: string[];
  /** 断裂后端注册状态（生成器从 `synlab.registry` 读取的真实值）。 */
  fracture_backends?: Record<string, string> | null;
  counts: ShowcaseCounts;
  summary?: { entry_count?: number; kinds?: string[]; statuses?: string[] };
  empty_reason: string | null;
}

/** 展示清单（只读）。 */
export const getShowcaseManifest = (signal?: AbortSignal) =>
  request<ShowcaseManifestResponse>('/showcase/manifest', { signal, timeoutMs: 30_000 });

export type ShowcaseAssetKey = 'glb' | 'png' | 'arrays' | 'meta';

/** 展示资产文件 URL（可直接给 `<img src>` / `<a href>`）。 */
export function showcaseAssetUrl(
  assetId: string,
  key: ShowcaseAssetKey,
  options: { name?: string; download?: boolean } = {},
): string {
  const search = new URLSearchParams();
  if (options.name) search.set('name', options.name);
  if (options.download !== undefined) search.set('download', String(options.download));
  const qs = search.toString();
  return `${API_ROOT}/showcase/asset/${encodeURIComponent(assetId)}/${encodeURIComponent(key)}${
    qs ? `?${qs}` : ''
  }`;
}

/** 展示资产字节流（带真实响应头：sha256 / 角色 / 单位 / 坐标帧）。 */
export function fetchShowcaseAsset(
  assetId: string,
  key: ShowcaseAssetKey,
  options: { name?: string; download?: boolean; signal?: AbortSignal } = {},
) {
  const query: RequestOptions['query'] = {};
  if (options.name) query.name = options.name;
  if (options.download !== undefined) query.download = options.download;
  return requestBlob(
    `/showcase/asset/${encodeURIComponent(assetId)}/${encodeURIComponent(key)}`,
    query,
    options.signal,
  );
}

/* ------------------------------------------------------------------ 取值小工具（只读真实字段，缺失即 null） */

export function asRecord(value: unknown): Record<string, any> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, any>)
    : null;
}

export function num(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim() !== '' && Number.isFinite(Number(value))) {
    return Number(value);
  }
  return null;
}

export function str(value: unknown): string | null {
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return null;
}

/** 从条目的 `artifacts` 里取出某个产物（不存在就返回 null，不造占位）。 */
export function artifactOf(entry: ShowcaseEntry | null, name: string): ShowcaseArtifact | null {
  if (!entry) return null;
  const raw = asRecord(entry.artifacts)?.[name];
  const rec = asRecord(raw);
  if (!rec || typeof rec.asset_id !== 'string') return null;
  return rec as unknown as ShowcaseArtifact;
}

/** 退化条目里某一档的产物。 */
export function levelArtifact(
  entry: ShowcaseEntry | null,
  level: number,
  name: 'png' | 'glb',
): ShowcaseArtifact | null {
  const levels = entry?.metrics?.levels;
  if (!Array.isArray(levels)) return null;
  const row = asRecord(levels.find((item: any) => num(item?.level) === level));
  const rec = asRecord(asRecord(row?.artifacts)?.[name]);
  if (!rec || typeof rec.asset_id !== 'string') return null;
  return rec as unknown as ShowcaseArtifact;
}

export function levelRow(entry: ShowcaseEntry | null, level: number): Record<string, any> | null {
  const levels = entry?.metrics?.levels;
  if (!Array.isArray(levels)) return null;
  return asRecord(levels.find((item: any) => num(item?.level) === level));
}
