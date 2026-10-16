/**
 * 真实后端响应类型（来源：`synlab/api/routers/*.py` 与 `synlab/api/problems.py`）。
 *
 * 类型只描述**实际存在**的字段；后端没有保证的字段一律 optional。这里不复制任何后端
 * 取值范围（例如 vessel/material/axis 名单），范围表只从 `/registry/{kind}` 与
 * `/specs/validate` 的真实回答里取。
 */

export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
export type JsonObject = { [key: string]: unknown };

/* ------------------------------------------------------------------ 错误信封 */
export interface ApiErrorBody {
  code: string;
  status: number;
  stage: string;
  message: string;
  retryable: boolean;
  details: Record<string, unknown>;
  evidence_refs: string[];
  request_id: string;
}

/* ------------------------------------------------------------------ meta */
export interface SessionPolicy {
  role: string;
  can_read_truth: boolean;
  can_read_research: boolean;
  can_read_ancestry: boolean;
  can_request_oracle_export: boolean;
  can_create_release: boolean;
  can_audit: boolean;
  can_control_jobs: boolean;
  can_start_training: boolean;
  truth_routes_mounted: boolean;
}

export interface SessionInfo {
  role: string;
  session_id: string;
  workspace: string;
  store_id: string;
  policy: SessionPolicy;
}

export interface CapabilityProbe {
  key: string;
  module: string;
  status: string;
  available: boolean;
  error: string | null;
  entry_points?: Record<string, boolean>;
  missing_entry_points?: string[];
  resolved_from?: Record<string, string>;
}

export interface EnvProbe {
  status: string;
  detail?: string | null;
  [key: string]: unknown;
}

export interface RegistrySummaryEntry {
  count?: number;
  ids?: string[];
  [key: string]: unknown;
}

export interface HealthResponse {
  ok: boolean;
  api_version: string;
  role: string;
  workspace: string;
  store_id: string;
  research_routes_mounted: boolean;
}

export interface DoctorResult {
  mode: string;
  ok: boolean;
  problems: string[];
  sqlite_integrity?: string;
  counts?: Record<string, number>;
  files_checked?: number;
  assets?: number;
}

export interface CapabilitiesResponse {
  ok: boolean;
  api_version: string;
  prefix: string;
  server_time: number;
  session: SessionInfo;
  python: string;
  modules: Record<string, CapabilityProbe>;
  available: string[];
  missing: string[];
  stage_requirements: Record<string, string[]>;
  registry_fingerprint: string;
  probed_at?: number;
  honesty: Record<string, string>;
  worker: { command: string; in_process_execution: boolean; note: string };
  env?: Record<string, EnvProbe>;
  registry?: Record<string, RegistrySummaryEntry>;
  doctor: DoctorResult;
}

export interface StageInfo {
  stage: string;
  title: string;
  capabilities: string[];
  env: string[];
  requires_gpu: boolean;
  cost_class: string;
  estimate: Record<string, number>;
  description: string;
  implemented_by: string;
}

export interface StagesResponse {
  ok: boolean;
  stages: StageInfo[];
  capability_modules: Record<string, string>;
  note: string;
}

export interface RegistryEntry {
  kind?: string;
  id: string;
  name?: string;
  version?: string;
  status?: string;
  applicable?: unknown;
  param_schema?: JsonSchemaNode;
  [key: string]: unknown;
}

export interface RegistryResponse {
  ok: boolean;
  kind: string;
  count: number;
  entries: RegistryEntry[];
  empty_kinds: string[];
  registry_fingerprint: string;
  note: string;
}

/* ------------------------------------------------------------------ JSONSchema */
export interface JsonSchemaNode {
  type?: string | string[];
  title?: string;
  description?: string;
  default?: unknown;
  enum?: unknown[];
  const?: unknown;
  anyOf?: JsonSchemaNode[];
  oneOf?: JsonSchemaNode[];
  allOf?: JsonSchemaNode[];
  items?: JsonSchemaNode;
  properties?: Record<string, JsonSchemaNode>;
  required?: string[];
  minimum?: number;
  maximum?: number;
  exclusiveMinimum?: number;
  exclusiveMaximum?: number;
  minLength?: number;
  maxLength?: number;
  pattern?: string;
  format?: string;
  additionalProperties?: boolean | JsonSchemaNode;
  $ref?: string;
  $defs?: Record<string, JsonSchemaNode>;
  definitions?: Record<string, JsonSchemaNode>;
  [key: string]: unknown;
}

/* ------------------------------------------------------------------ specs */
export interface SpecValidationIssue {
  loc: string[];
  type: string | null;
  msg: string | null;
  input?: unknown;
}

export interface SpecValidationResponse {
  ok: boolean;
  rejected: boolean;
  kind: string;
  schema_id: string;
  errors: SpecValidationIssue[];
  warnings: string[];
  spec_hash: string | null;
  canonical: string | null;
  expanded: Record<string, unknown>;
  registry_fingerprint: string;
  note: string;
  required_capabilities?: string[];
}

export interface BudgetReport {
  feasible: boolean;
  jobs: number;
  rss_gb: number;
  rss_budget_gb: number;
  vram_gb: number;
  vram_budget_gb: number;
  temp_disk_gb: number;
  persistent_disk_gb: number;
  disk: { total_gb: number; free_gb: number; used_fraction: number; level: string };
  assumptions: Array<Record<string, unknown>>;
  note: string;
  budget_ref?: string;
  ok?: boolean;
  stage?: string;
  requires_gpu?: boolean;
  spec_valid?: boolean;
  spec_errors?: SpecValidationIssue[];
  env?: { cuda_available: boolean; status: string; detail: string | null };
  gpu_blocked?: { code: string; reason: string | null } | null;
}

/* ------------------------------------------------------------------ jobs */
export interface JobRecord {
  job_id: string;
  run_id: string;
  stage: string;
  state: string;
  attempt: number;
  owner: string | null;
  fencing: number;
  inputs: string[];
  outputs: string[];
  error: Record<string, unknown> | null;
  created_at: number;
  updated_at: number;
  progress?: { done?: number; planned?: number; unit?: string } | null;
  spec?: JsonObject;
  [key: string]: unknown;
}

export interface PageEnvelope {
  kind: string;
  order: string;
  limit: number;
  count: number;
  has_more: boolean;
  next_cursor: string | null;
  items: JobRecord[];
  workspace?: string;
  scanned?: number;
  total?: number;
  ok?: boolean;
  states?: string[];
  terminal_states?: string[];
}

export interface JobDetailResponse {
  ok: boolean;
  job: JobRecord;
  stage_title: string;
  run: {
    run_id: string;
    status: string | null;
    revision: number | null;
    profile: string | null;
    spec_hash: string | null;
  };
  progress: { done?: number; planned?: number; unit?: string } | null;
  queue_position: number | null;
  dependencies: string[];
  blocked_dependents: string[];
  resource_estimate: {
    rss_gb: number;
    vram_gb: number;
    temp_disk_gb: number;
    persistent_disk_gb: number;
    cpu_seconds: number;
    assumptions: Record<string, unknown>;
  };
  events_url: string;
  terminal: boolean;
  error: Record<string, unknown> | null;
  note: string;
}

export interface JobAcceptedResponse {
  ok: boolean;
  accepted: boolean;
  created: boolean;
  idempotent_replay: boolean;
  run_id: string;
  job_id: string;
  job_ids?: string[];
  status: string;
  spec_hash: string;
  events_url: string;
  jobs_url: string;
  dag?: Array<{ node_id: string; stage: string; job_id: string; depends_on: string[] }>;
  budget?: BudgetReport;
  note: string;
  preview?: boolean;
  preview_note?: string;
}

export interface ControlResponse {
  ok: boolean;
  action: string;
  run_id: string;
  run_status: string;
  previous_revision: number;
  revision: number;
  note: string;
  jobs_not_started?: string[];
  running_jobs?: string[];
  cancelled_jobs?: string[];
  committed_jobs_kept?: string[];
  running_jobs_draining?: string[];
  dependencies?: Record<string, Record<string, string>>;
  still_blocked?: string[];
  active_leases?: Array<Record<string, unknown>>;
  mode?: string;
  job_id?: string;
  attempt?: number;
  state?: string;
  reason?: string;
  error?: Record<string, unknown> | null;
  previous_job_id?: string;
  events_url?: string;
}

export interface RunEvent {
  seq: number;
  revision: number;
  run_id: string;
  job_id: string | null;
  type: string;
  state: string;
  progress: { done?: number; planned?: number; unit?: string } | null;
  metrics_ref: string | null;
  error_ref: string | null;
  message: string;
  created_at?: number | null;
  payload: Record<string, unknown>;
}

/* ------------------------------------------------------------------ assets */
export interface AssetIntegrityFile {
  ok: boolean;
  size: number;
  sha256: string;
  hash_verified: string | boolean;
  [key: string]: unknown;
}

export interface AssetRecord {
  asset_id: string;
  blob_hash: string;
  role: string;
  schema: string;
  unit: string;
  frame: string;
  interpretation_hash: string;
  qa_status: string;
  lineage_id: string | null;
  split: string | null;
  created_at: number;
  revision: number;
  meta: Record<string, unknown>;
  files: Record<string, string>;
  qa: Record<string, unknown>;
  ancestry: string[];
  /** 只在 /assets/{id} 出现 */
  integrity?: { ok: boolean; problems: string[]; files: Record<string, AssetIntegrityFile> };
  file_urls?: Record<string, string>;
  research_only_role?: boolean;
  ancestry_hidden?: boolean;
}

export interface AssetsPageResponse extends Omit<PageEnvelope, 'items'> {
  items: AssetRecord[];
  role_filter: string[] | null;
  role_filter_default: string | null;
  research_roles_hidden: string[];
  empty_reason: string | null;
}

export interface AssetDetailResponse {
  ok: boolean;
  asset: AssetRecord;
  role: string;
  display_transform: unknown;
}

export interface ResearchTruthResponse {
  ok: boolean;
  asset_id: string;
  role: string;
  schema: string;
  unit: string;
  frame: string;
  qa_status: string;
  qa: Record<string, unknown>;
  meta: Record<string, unknown>;
  ancestry: string[];
  lineage_id: string | null;
  split: string | null;
  interpretation_hash: string;
  array_keys: string[];
  integrity: { ok: boolean; problems: string[] };
  truth_role: boolean;
  access: { role: string; session_id: string; note: string };
}

/* ------------------------------------------------------------------ camera */
export interface CameraCatalogueEntry {
  profile_id: string;
  revision: number;
  tier: string;
  working_distance_mm: number;
  u_position_mm: number;
  K: unknown;
  dist: unknown;
  image_size: [number, number] | number[];
  fov_mm: number[];
  depth_of_field_mm: number[];
  focus_setting: string;
  calibration_refs: string[];
  calibrated: boolean;
  action_cost_seconds: number;
  f_number: number;
  meta: Record<string, unknown>;
  [key: string]: unknown;
}

export interface CameraProfileRow {
  profile_id: string;
  version: string;
  tier: string;
  status: string;
  payload: Record<string, unknown>;
  calibration_source: string | null;
  workspace: string;
  created_at: number;
}

export interface CameraProfilesResponse {
  ok: boolean;
  capability: CapabilityProbe;
  registered: CameraProfileRow[];
  catalogue: CameraCatalogueEntry[];
  reachable_actions: string[];
  calibration_states: string[];
  blocked_reason: string | null;
  empty_reason: string | null;
}

export interface CameraProfileDetailResponse {
  ok: boolean;
  profile_id: string;
  versions: CameraProfileRow[];
  latest: CameraProfileRow;
  count: number;
}

/* ------------------------------------------------------------------ governance */
export interface AuditRow {
  audit_id: string;
  run_id: string | null;
  release_id: string | null;
  scope: Record<string, unknown>;
  status: string;
  job_id: string | null;
  result: Record<string, unknown>;
  workspace: string;
  created_at: number;
  updated_at: number;
  truth_hidden?: boolean;
}

export interface GateInfo {
  status: string;
  reason?: string;
  [key: string]: unknown;
}

export interface AuditGateBlock {
  profile?: string;
  required_gates?: string[];
  gates?: Record<string, GateInfo>;
  passed?: string[];
  pending?: string[];
  failed?: string[];
  not_applicable?: string[];
  closure?: Record<string, unknown>;
  coverage?: Record<string, unknown>;
  scanned_assets?: number;
  release_ready?: boolean;
  note?: string;
  [key: string]: unknown;
}

export interface AuditDetailResponse {
  ok: boolean;
  audit: AuditRow;
  job: JobRecord | null;
  profile_gates: string[];
  note: string;
}

export interface AuditListResponse {
  ok: boolean;
  count: number;
  items: AuditRow[];
  empty_reason: string | null;
}

export interface CoverageBlock {
  kind: string;
  declared_field: string;
  required: number;
  covered: number;
  complete: boolean;
  covered_ids: string[];
  missing_ids: string[];
  evidence: Record<string, string>;
}

export interface CoverageMatrixPayload {
  scanned_assets: number;
  basis: string;
  [key: string]: unknown;
}

export interface ReleaseManifest {
  ok: boolean;
  release_id: string;
  manifest_hash: string;
  profile: string;
  scope: string;
  gates: Record<string, string>;
  required_gates: string[];
  scope_completed: unknown;
  scope_pending: unknown;
  coverage: Record<string, unknown>;
  closure: Record<string, unknown> | null;
  assets: AssetRecord[];
  asset_count: number;
  frozen_at: number | null;
  readonly: boolean;
  manifest_url: string;
}

export interface ReleaseListResponse {
  ok: boolean;
  count: number;
  items: Array<Record<string, unknown>>;
  empty_reason: string | null;
}

export interface ExportRow {
  export_id: string;
  release_id: string;
  adapter: string;
  status: string;
  job_id: string | null;
  result: Record<string, unknown>;
  workspace: string;
  created_at: number;
  updated_at: number;
}

export interface ExportAcceptedResponse {
  ok: boolean;
  accepted: boolean;
  export_id: string;
  job_id: string;
  run_id: string;
  status: string;
  adapter: string;
  release_id: string;
  events_url: string;
  export_url: string;
  note: string;
}

export interface ExportDetailResponse {
  ok: boolean;
  export: ExportRow;
  note: string;
}

/* ------------------------------------------------------------------ learning */
export interface PoolRow {
  pool_id: string;
  release_id: string | null;
  spec: Record<string, unknown>;
  status: string;
  job_id: string | null;
  result: Record<string, unknown>;
  workspace: string;
  created_at: number;
  updated_at: number;
}

export interface PoolsResponse {
  ok: boolean;
  count: number;
  items: PoolRow[];
  capability: CapabilityProbe;
}

export interface TrainingRunRow {
  training_run_id: string;
  release_id: string | null;
  spec: Record<string, unknown>;
  status: string;
  job_id: string | null;
  result: Record<string, unknown>;
  workspace: string;
  created_at: number;
  updated_at: number;
}

export interface TrainingRunsResponse {
  ok: boolean;
  count: number;
  items: TrainingRunRow[];
  capability: CapabilityProbe;
}

export interface MetricPoint {
  step?: number;
  value?: number;
  name?: string;
  [key: string]: unknown;
}

export interface TrainingRunDetailResponse {
  ok: boolean;
  training_run: TrainingRunRow;
  jobs: JobRecord[];
  checkpoint_assets: string[];
  metrics: Record<string, unknown>;
  curves: Array<Record<string, unknown>>;
  capability: CapabilityProbe;
  not_run_reason: string | null;
}

export interface DiagnosticsRunRow {
  diagnostics_run_id: string;
  spec: Record<string, unknown>;
  status: string;
  job_id: string | null;
  result: Record<string, unknown>;
  workspace: string;
  created_at: number;
  updated_at: number;
}

export interface DiagnosticsRunsResponse {
  ok: boolean;
  count: number;
  items: DiagnosticsRunRow[];
  capability: CapabilityProbe;
}

export interface DiagnosticsRunDetailResponse {
  ok: boolean;
  diagnostics_run: DiagnosticsRunRow;
  curves: Array<Record<string, unknown>>;
  queries: Array<Record<string, unknown>>;
  capability: CapabilityProbe;
  not_run_reason: string | null;
}

export interface EpisodeRow {
  episode_id: string;
  spec: Record<string, unknown>;
  state: {
    tick?: number;
    observation?: unknown;
    available_actions?: unknown[];
    cost_total?: number;
    status?: string;
    [key: string]: unknown;
  };
  observation?: unknown;
  steps: unknown[];
  cost_total: number;
  status: string;
  workspace: string;
  created_at: number;
  updated_at: number;
}

export interface EpisodeResponse {
  ok: boolean;
  episode: EpisodeRow;
  capability: CapabilityProbe;
}

export interface EpisodeResetResponse {
  ok: boolean;
  episode_id: string;
  state: EpisodeRow['state'];
  note: string;
}

export interface EpisodeStepResponse {
  ok: boolean;
  episode_id: string;
  requested_action: unknown;
  state: EpisodeRow['state'];
  note: string;
}
