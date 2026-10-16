/**
 * Layout —— 三栏骨架与顶栏（计划 20.1）。
 *
 * 顶栏显示：工作区、角色/权限、当前 run、合成/真实标记、任务与 GPU 状态。
 * 这些全部来自真实 `GET /health` 与 `GET /capabilities`，没有后端时顶栏直接显示
 * “后端不可用”并给出错误码，而不是假装在线。
 */

import { NavLink, Outlet } from 'react-router-dom';

import { getCapabilities, getHealth, listJobs } from '../api/endpoints';
import { API_ROOT, FIXTURES_ENABLED } from '../api/client';
import { useResource } from '../api/hooks';
import { summarizeRuns } from '../lib/runs';
import { Badge, FIXTURE_BANNER_TEXT, FixtureBanner } from './states';
import { FailureDrawer } from './FailureDrawer';
import { ProvenanceDrawer } from './ProvenanceDrawer';
import { useAppState } from '../state/app-state';

const NAV: Array<{ to: string; label: string; plan: string }> = [
  { to: '/synlab', label: '实验室概览', plan: 'U01' },
  { to: '/synlab/mothers/new', label: '母体编辑', plan: 'U02' },
  { to: '/synlab/patterns', label: '花纹编辑', plan: 'U03' },
  { to: '/synlab/fracture', label: '断裂预览', plan: 'U04' },
  { to: '/synlab/degradation', label: '退化对比', plan: 'U05' },
  { to: '/synlab/camera-profiles', label: '相机与采集档', plan: 'U06' },
  { to: '/synlab/jobs', label: '批量生成与任务', plan: 'U07' },
  { to: '/synlab/releases', label: '数据发布', plan: 'U08' },
  { to: '/synlab/training', label: '预训练', plan: 'U09' },
  { to: '/synlab/diagnostics', label: '诊断面板', plan: 'U10' },
  { to: '/synlab/episodes', label: '主动观察', plan: 'U11' },
  { to: '/synlab/quality', label: '质量与故障', plan: 'U12' },
  { to: '/synlab/showcase', label: '合成数据展示', plan: 'U13' },
];

export function Layout() {
  const app = useAppState();

  const health = useResource((signal) => getHealth(signal), [], { intervalMs: 20_000 });
  const capabilities = useResource((signal) => getCapabilities({ doctor: 'none' }, signal), [], {
    intervalMs: 60_000,
  });
  const jobs = useResource((signal) => listJobs({ limit: 50, with_total: true }, signal), [], {
    intervalMs: 15_000,
  });

  const runs = summarizeRuns(jobs.data?.items ?? []);
  const activeRuns = runs.filter((run) => !run.terminal);
  const failed = (jobs.data?.items ?? []).filter((job) =>
    ['FAILED', 'QUARANTINED', 'RETRYABLE'].includes(job.state),
  );
  const session = capabilities.data?.session;
  const cuda = capabilities.data?.env ? capabilities.data.env['cuda'] : undefined;
  const missingCount = capabilities.data?.missing?.length ?? 0;

  const workspace = health.data?.workspace ?? session?.workspace ?? '未知（后端不可达）';
  const researchMounted = health.data?.research_routes_mounted ?? session?.policy.truth_routes_mounted;

  return (
    <div className="app">
      <a className="skiplink" href="#main">
        跳到主内容
      </a>

      <header className="topbar">
        <div className="topbar__brand">
          <strong>RelicWeave</strong>
          <span>A12 合成实验室</span>
        </div>

        <div className="topbar__facts">
          <span className="fact">
            <span className="fact__key">工作区</span>
            <span className="fact__value">{workspace}</span>
          </span>
          <span className="fact">
            <span className="fact__key">角色</span>
            <span className="fact__value">
              {health.data?.role ?? session?.role ?? '未连接'}
              {session ? (session.policy.can_read_truth ? '（可读真值）' : '（不可读真值）') : ''}
            </span>
          </span>
          <span className="fact">
            <span className="fact__key">数据口径</span>
            <span className="fact__value">
              <Badge tone="info">SYNTHETIC</Badge>
              {session?.policy.truth_routes_mounted === false ? <Badge tone="warn">真值路由未挂载</Badge> : null}
            </span>
          </span>
          <span className="fact">
            <span className="fact__key">当前 run</span>
            <span className="fact__value mono">{app.selectedRunId ?? '未选择（在任务页选择）'}</span>
          </span>
          <span className="fact">
            <span className="fact__key">任务</span>
            <span className="fact__value">
              {jobs.status === 'error' ? (
                <Badge tone="bad">任务列表不可用</Badge>
              ) : (
                <>
                  <Badge tone={activeRuns.length > 0 ? 'info' : 'neutral'}>未终止 run {activeRuns.length}</Badge>
                  <Badge tone={failed.length > 0 ? 'bad' : 'ok'}>失败/隔离/可重试 {failed.length}</Badge>
                  {jobs.data?.total !== undefined ? <span className="mono"> total={jobs.data.total}</span> : null}
                </>
              )}
            </span>
          </span>
          <span className="fact">
            <span className="fact__key">GPU</span>
            <span className="fact__value">
              {cuda ? (
                <Badge tone={cuda.status === 'OK' ? 'ok' : 'warn'}>{cuda.status ?? '未知'}</Badge>
              ) : (
                <Badge tone="neutral">未探测</Badge>
              )}
              {missingCount > 0 ? <Badge tone="warn">缺能力 {missingCount} 项</Badge> : null}
            </span>
          </span>
          <span className="fact">
            <span className="fact__key">API</span>
            <span className="fact__value">
              <span className="mono small">{API_ROOT}</span>
            </span>
          </span>
        </div>

        <div className="topbar__status">
          {health.status === 'error' ? (
            <Badge tone="bad">后端不可用</Badge>
          ) : health.data?.ok ? (
            <Badge tone="ok">
              已连接 v{health.data.api_version} · {health.data.store_id}
            </Badge>
          ) : (
            <Badge tone="warn">连接中…</Badge>
          )}
          {researchMounted === false ? <Badge tone="warn">研究路由未挂载</Badge> : null}
        </div>
      </header>

      <FixtureBanner enabled={FIXTURES_ENABLED} />

      <div className="app__body">
        <nav className="sidenav" aria-label="合成实验室页面">
          <ul>
            {NAV.map((item) => (
              <li key={item.to}>
                <NavLink
                  to={item.to}
                  end={item.to === '/synlab'}
                  className={({ isActive }) => (isActive ? 'sidenav__link sidenav__link--active' : 'sidenav__link')}
                >
                  <span className="sidenav__plan">{item.plan}</span>
                  {item.label}
                </NavLink>
              </li>
            ))}
          </ul>
          <div className="sidenav__foot">
            <p className="muted small">
              所有页面数据来自 <code className="mono">/api/synlab</code> 真实路由；无后端时显示具体错误码，
              不使用任何 mock 数据。
            </p>
            {FIXTURES_ENABLED ? <Badge tone="warn">{FIXTURE_BANNER_TEXT}</Badge> : null}
          </div>
        </nav>

        <main className="main" id="main">
          <Outlet />
        </main>
      </div>

      <FailureDrawer
        jobId={app.failureJobId}
        onClose={() => app.openFailure(null)}
        onRetried={() => {
          jobs.reload();
        }}
      />
      <ProvenanceDrawer target={app.provenance} onClose={app.closeProvenance} />
    </div>
  );
}
