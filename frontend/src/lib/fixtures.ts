/**
 * 只在 `VITE_SYNLAB_FIXTURES=1` 时启用的测试 fixture。
 *
 * 默认构建里这份表不会被任何读取路径命中；命中时 UI 顶部与每个数据卡片都会显示
 * “FIXTURE（非真实后端数据）”标记，避免把测试数据误当成实测结果（计划 20.15 / 25.2）。
 * fixture 只用于**无后端**时的前端联调与 Playwright 冒烟，不代表任何后端结论。
 */

import type { CapabilitiesResponse, PageEnvelope } from '../api/types';

export const FIXTURE_NOTICE = 'FIXTURE 模式：以下内容来自本地测试 fixture，不是真实后端响应';

const fixtureCapabilities: CapabilitiesResponse = {
  ok: true,
  api_version: 'synlab.api.v1',
  prefix: '/api/synlab',
  server_time: 0,
  session: {
    role: 'fixture',
    session_id: 'fixture',
    workspace: 'fixture',
    store_id: 'store_fixture',
    policy: {
      role: 'fixture',
      can_read_truth: false,
      can_read_research: false,
      can_read_ancestry: false,
      can_request_oracle_export: false,
      can_create_release: false,
      can_audit: false,
      can_control_jobs: false,
      can_start_training: false,
      truth_routes_mounted: false,
    },
  },
  python: 'fixture',
  modules: {},
  available: [],
  missing: [],
  stage_requirements: {},
  registry_fingerprint: 'sha256:fixture',
  honesty: { note: FIXTURE_NOTICE },
  worker: { command: 'fixture', in_process_execution: false, note: FIXTURE_NOTICE },
  doctor: { mode: 'none', ok: false, problems: [FIXTURE_NOTICE] },
};

const fixtureJobs: PageEnvelope = {
  kind: 'job',
  order: 'created_at.asc,id.asc',
  limit: 50,
  count: 0,
  has_more: false,
  next_cursor: null,
  items: [],
  workspace: 'fixture',
  scanned: 0,
  ok: true,
  states: ['PENDING', 'RUNNING', 'COMMITTED', 'FAILED', 'CANCELLED'],
  terminal_states: ['COMMITTED', 'CANCELLED', 'FAILED'],
};

const TABLE: Record<string, unknown> = {
  capabilities: fixtureCapabilities,
  jobs: fixtureJobs,
};

export function fixtureFor(key: string): unknown | undefined {
  return TABLE[key];
}
