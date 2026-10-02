/**
 * 端点封装：只覆盖 `synlab/api/routers/*.py` 里**真实存在**的路由（前缀 `/api/synlab`）。
 *
 * 与计划 21.1 表格的实际差异见 docs/a12/api_ui.md，例如后端没有 `GET /exports`、
 * `GET /registry`（只有 `/registry/{kind}`），而 `/audits`、`/camera-profiles/{id}` 等是
 * 表格未列出的真实路由。
 */

import { request, requestBlob, type RequestOptions } from './client';
import type {
  AssetDetailResponse,
  AssetsPageResponse,
  AuditDetailResponse,
  AuditListResponse,
  CameraProfileDetailResponse,
  CameraProfilesResponse,
  CapabilitiesResponse,
  ControlResponse,
  DiagnosticsRunDetailResponse,
  DiagnosticsRunsResponse,
  EpisodeResetResponse,
  EpisodeResponse,
  EpisodeStepResponse,
  ExportAcceptedResponse,
  ExportDetailResponse,
  HealthResponse,
  JobAcceptedResponse,
  JobDetailResponse,
  PageEnvelope,
  PoolsResponse,
  RegistryResponse,
  ReleaseListResponse,
  ReleaseManifest,
  ResearchTruthResponse,
  SpecValidationResponse,
  StagesResponse,
  TrainingRunDetailResponse,
  TrainingRunsResponse,
  BudgetReport,
} from './types';

export type Query = RequestOptions['query'];

/* ------------------------------------------------------------------ meta */
export const getHealth = (signal?: AbortSignal) =>
  request<HealthResponse>('/health', { signal, timeoutMs: 8000 });

export const getCapabilities = (
  opts: { doctor?: 'none' | 'light' | 'full'; refresh?: boolean; includeEnv?: boolean } = {},
  signal?: AbortSignal,
) =>
  request<CapabilitiesResponse>('/capabilities', {
    signal,
    timeoutMs: opts.doctor === 'full' ? 120_000 : 20_000,
    query: {
      doctor: opts.doctor ?? 'light',
      refresh: opts.refresh ? true : undefined,
      include_env: opts.includeEnv === false ? false : true,
    },
  });

export const getStages = (signal?: AbortSignal) => request<StagesResponse>('/stages', { signal });

export const getRegistry = (kind: string, query: Query = {}, signal?: AbortSignal) =>
  request<RegistryResponse>(`/registry/${encodeURIComponent(kind)}`, { query, signal });

export const validateSpec = (
  body: { spec: Record<string, unknown>; kind?: 'generation' | 'recipe' | 'train' | 'diagnose'; registry_check?: boolean },
  signal?: AbortSignal,
) => request<SpecValidationResponse>('/specs/validate', { method: 'POST', body, signal });

export const postBudgets = (
  body: {
    spec?: Record<string, unknown>;
    kind?: 'generation' | 'recipe' | 'train' | 'diagnose';
    stage?: string;
    planned_jobs?: number;
    requires_gpu?: boolean | null;
  },
  signal?: AbortSignal,
) => request<BudgetReport>('/budgets', { method: 'POST', body, signal });

/* ------------------------------------------------------------------ jobs */
export interface JobCreateBody {
  schema_version?: 'synlab.v3' | 'synlab.train.v1' | 'synlab.diagnose.v1';
  data_scope?: 'SYNTHETIC' | 'REAL' | null;
  release_profile?: string | null;
  spec_ref?: string | null;
  input_refs?: string[];
  idempotency_key: string;
  budget_ref?: string | null;
  stage?: string;
  spec?: Record<string, unknown>;
  planned_jobs?: number;
}

export const postJobs = (body: JobCreateBody, signal?: AbortSignal) =>
  request<JobAcceptedResponse>('/jobs', { method: 'POST', body, signal, timeoutMs: 60_000 });

export const postPreviews = (
  body: {
    stage: string;
    spec?: Record<string, unknown>;
    input_refs?: string[];
    idempotency_key?: string | null;
    budget_ref?: string | null;
    notes?: string | null;
  },
  signal?: AbortSignal,
) => request<JobAcceptedResponse>('/previews', { method: 'POST', body, signal, timeoutMs: 60_000 });

export const listJobs = (query: Query = {}, signal?: AbortSignal) =>
  request<PageEnvelope>('/jobs', { query, signal });

export const getJob = (jobId: string, signal?: AbortSignal) =>
  request<JobDetailResponse>(`/jobs/${encodeURIComponent(jobId)}`, { signal });

const control = (
  jobId: string,
  action: 'pause' | 'resume' | 'cancel',
  body: { revision?: number | null; reason?: string | null },
  signal?: AbortSignal,
) => request<ControlResponse>(`/jobs/${encodeURIComponent(jobId)}/${action}`, { method: 'POST', body, signal });

export const pauseJob = (jobId: string, body: { revision?: number | null; reason?: string | null }, signal?: AbortSignal) =>
  control(jobId, 'pause', body, signal);
export const resumeJob = (jobId: string, body: { revision?: number | null; reason?: string | null }, signal?: AbortSignal) =>
  control(jobId, 'resume', body, signal);
export const cancelJob = (jobId: string, body: { revision?: number | null; reason?: string | null }, signal?: AbortSignal) =>
  control(jobId, 'cancel', body, signal);

export const retryJob = (
  jobId: string,
  body: { reason: string; revision?: number | null; force?: boolean },
  signal?: AbortSignal,
) => request<ControlResponse>(`/jobs/${encodeURIComponent(jobId)}/retry`, { method: 'POST', body, signal });

/* ------------------------------------------------------------------ assets */
export const listAssets = (query: Query = {}, signal?: AbortSignal) =>
  request<AssetsPageResponse>('/assets', { query, signal });

export const getAsset = (assetId: string, signal?: AbortSignal) =>
  request<AssetDetailResponse>(`/assets/${encodeURIComponent(assetId)}`, { signal });

export const assetFileUrl = (assetId: string, role: string, key?: string, download = true) => {
  const params = new URLSearchParams();
  if (key) params.set('key', key);
  params.set('download', String(download));
  return `/assets/${encodeURIComponent(assetId)}/files/${encodeURIComponent(role)}?${params.toString()}`;
};

export const fetchAssetBlob = (assetId: string, role: string, key?: string, signal?: AbortSignal) =>
  requestBlob(assetFileUrl(assetId, role, key), undefined, signal);

export const getResearchTruth = (assetId: string, includeArrays = true, signal?: AbortSignal) =>
  request<ResearchTruthResponse>(`/research/assets/${encodeURIComponent(assetId)}/truth`, {
    query: { include_arrays: includeArrays },
    signal,
  });

/* ------------------------------------------------------------------ cameras */
export const listCameraProfiles = (query: Query = {}, signal?: AbortSignal) =>
  request<CameraProfilesResponse>('/camera-profiles', { query, signal });

export const createCameraProfile = (
  body: {
    profile_id: string;
    version: string;
    tier: 'GLOBAL' | 'MID' | 'LOCAL';
    payload: Record<string, unknown>;
    /** 后端 Literal 的实际取值是 UNGALIBRATED（拼写如此），见 docs/a12/api_ui.md 差异表。 */
    calibration_source: 'UNGALIBRATED' | 'MANUFACTURER' | 'MEASURED' | 'SYNTHETIC_GT';
  },
  signal?: AbortSignal,
) => request<{ ok: boolean; profile: Record<string, unknown>; registered_at: number; note: string }>(
  '/camera-profiles',
  { method: 'POST', body, signal },
);

export const getCameraProfile = (profileId: string, signal?: AbortSignal) =>
  request<CameraProfileDetailResponse>(`/camera-profiles/${encodeURIComponent(profileId)}`, { signal });

/* ------------------------------------------------------------------ governance */
export const postAudits = (
  body: {
    run_id?: string | null;
    release_id?: string | null;
    asset_ids?: string[];
    release_profile?: string;
    include_truth?: boolean;
  },
  signal?: AbortSignal,
) => request<Record<string, unknown>>('/audits', { method: 'POST', body, signal, timeoutMs: 60_000 });

export const listAudits = (query: Query = {}, signal?: AbortSignal) =>
  request<AuditListResponse>('/audits', { query, signal });

export const getAudit = (auditId: string, signal?: AbortSignal) =>
  request<AuditDetailResponse>(`/audits/${encodeURIComponent(auditId)}`, { signal });

export const postReleases = (
  body: {
    release_id: string;
    profile: string;
    scope?: 'SYNTHETIC' | 'REAL';
    asset_ids: string[];
    audit_id: string;
    scope_pending?: string[];
    coverage?: Record<string, unknown>;
  },
  signal?: AbortSignal,
) =>
  request<{ ok: boolean; release: Record<string, unknown>; gates: Record<string, string>; audit_id: string; note: string }>(
    '/releases',
    { method: 'POST', body, signal, timeoutMs: 120_000 },
  );

export const listReleases = (query: Query = {}, signal?: AbortSignal) =>
  request<ReleaseListResponse>('/releases', { query, signal });

export const getRelease = (releaseId: string, signal?: AbortSignal) =>
  request<ReleaseManifest>(`/releases/${encodeURIComponent(releaseId)}`, { signal });

export const postExports = (
  body: { release_id: string; adapter?: 'manifest' | 'obs_pack' | 'feature_bundle' | 'oracle_truth'; idempotency_key?: string },
  signal?: AbortSignal,
) => request<ExportAcceptedResponse>('/exports', { method: 'POST', body, signal });

export const getExport = (exportId: string, signal?: AbortSignal) =>
  request<ExportDetailResponse>(`/exports/${encodeURIComponent(exportId)}`, { signal });

/* ------------------------------------------------------------------ learning */
export const listPools = (query: Query = {}, signal?: AbortSignal) =>
  request<PoolsResponse>('/pools', { query, signal });

export const postPools = (
  body: { release_id: string; spec?: Record<string, unknown>; idempotency_key?: string },
  signal?: AbortSignal,
) => request<Record<string, unknown>>('/pools', { method: 'POST', body, signal });

export const listTrainingRuns = (query: Query = {}, signal?: AbortSignal) =>
  request<TrainingRunsResponse>('/training/runs', { query, signal });

export const postTrainingRuns = (
  body: { spec: Record<string, unknown>; release_id?: string | null; idempotency_key?: string },
  signal?: AbortSignal,
) => request<Record<string, unknown>>('/training/runs', { method: 'POST', body, signal, timeoutMs: 60_000 });

export const getTrainingRun = (id: string, signal?: AbortSignal) =>
  request<TrainingRunDetailResponse>(`/training/runs/${encodeURIComponent(id)}`, { signal });

export const resumeTrainingRun = (id: string, body: { checkpoint_ref?: string | null } = {}, signal?: AbortSignal) =>
  request<Record<string, unknown>>(`/training/runs/${encodeURIComponent(id)}/resume`, { method: 'POST', body, signal });

export const listDiagnosticsRuns = (query: Query = {}, signal?: AbortSignal) =>
  request<DiagnosticsRunsResponse>('/diagnostics/runs', { query, signal });

export const postDiagnosticsRuns = (
  body: { spec: Record<string, unknown>; checkpoint_ref?: string | null; pool_ref?: string | null; idempotency_key?: string },
  signal?: AbortSignal,
) => request<Record<string, unknown>>('/diagnostics/runs', { method: 'POST', body, signal, timeoutMs: 60_000 });

export const getDiagnosticsRun = (id: string, signal?: AbortSignal) =>
  request<DiagnosticsRunDetailResponse>(`/diagnostics/runs/${encodeURIComponent(id)}`, { signal });

export const resetEpisode = (
  episodeId: string,
  body: { spec?: Record<string, unknown>; pool_ref?: string | null; camera_profile_id?: string | null },
  signal?: AbortSignal,
) => request<EpisodeResetResponse>(`/episodes/${encodeURIComponent(episodeId)}/reset`, { method: 'POST', body, signal });

export const stepEpisode = (
  episodeId: string,
  body: { action: Record<string, unknown>; expected_tick?: number | null },
  signal?: AbortSignal,
) => request<EpisodeStepResponse>(`/episodes/${encodeURIComponent(episodeId)}/step`, { method: 'POST', body, signal });

export const getEpisode = (episodeId: string, signal?: AbortSignal) =>
  request<EpisodeResponse>(`/episodes/${encodeURIComponent(episodeId)}`, { signal });
