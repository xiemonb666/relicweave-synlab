/**
 * U11 主动观察 `/synlab/episodes`（计划 20.12）。
 *
 * 真实调用：`POST /episodes/{id}/reset`、`POST /episodes/{id}/step`、`GET /episodes/{id}`、
 * `GET /pools`、`GET /camera-profiles`。
 *
 * 诚实点：
 * * `reset`/`step` 需要 capability `episodes`；缺失时后端返回 503 DEPENDENCY_CAPABILITY_MISSING
 *   且不写任何状态，页面显示阻塞而不是编造 observation；
 * * 未揭示的帧不进入 state —— 页面直接渲染后端 `state.observation`，`revealed=false` 就显示未揭示；
 * * STOP 后 `step` 会被 409 拒绝；累计成本只显示后端记录的 `cost_total`；
 * * oracle 动作不会出现在部署式 action 列表里 —— 列表完全来自后端 `state.available_actions`。
 */

import { useState } from 'react';

import { AssetBrowser } from '../components/AssetBrowser';
import { MeasuredQualityTable } from '../components/MeasuredQualityTable';
import {
  ActionButton,
  Badge,
  EmptyState,
  ErrorState,
  KeyValueList,
  LoadingState,
  PageHeader,
  SectionCard,
  Tabs,
} from '../components/states';
import { getCapabilities, getEpisode, listCameraProfiles, listPools, resetEpisode, stepEpisode } from '../api/endpoints';
import { useResource } from '../api/hooks';
import { capabilityIssues, describeIssues } from '../lib/caps';
import { asArray, asNumber, asString, isRecord, pretty } from '../lib/format';
import { useAppState } from '../state/app-state';

interface StepLog {
  at: number;
  kind: 'reset' | 'step';
  request: unknown;
  response?: unknown;
  error?: unknown;
}

export function EpisodesPage() {
  const app = useAppState();
  const capabilities = useResource((signal) => getCapabilities({ doctor: 'none' }, signal), []);
  const pools = useResource((signal) => listPools({ limit: 50 }, signal), []);
  const cameras = useResource((signal) => listCameraProfiles({}, signal), []);
  const [episodeId, setEpisodeId] = useState('ep_ui_01');
  const [poolRef, setPoolRef] = useState('');
  const [cameraRef, setCameraRef] = useState('');
  const [lookupId, setLookupId] = useState('');
  const [pendingError, setPendingError] = useState<unknown>(null);
  const [pendingOk, setPendingOk] = useState<unknown>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [log, setLog] = useState<StepLog[]>([]);
  const [tab, setTab] = useState<'state' | 'log' | 'evidence'>('state');

  const episode = useResource((signal) => getEpisode(lookupId, signal), [lookupId], {
    enabled: lookupId.length > 0,
    intervalMs: lookupId ? 10_000 : 0,
  });

  const issues = capabilityIssues(capabilities.data ?? null, ['episodes', 'relations']);
  const state = episode.data?.episode.state ?? null;
  const availableActions = asArray<unknown>(state?.available_actions);
  const observation = state?.observation;
  const observationRevealed = !(isRecord(observation) && observation.revealed === false);
  const status = episode.data?.episode.status ?? asString(state?.status) ?? null;

  const doReset = async () => {
    setBusy('reset');
    setPendingError(null);
    setPendingOk(null);
    const request = { spec: {}, pool_ref: poolRef || null, camera_profile_id: cameraRef || null };
    try {
      const response = await resetEpisode(episodeId, request);
      setPendingOk(response);
      setLog((entries) => [...entries, { at: Date.now(), kind: 'reset', request, response }]);
      setLookupId(episodeId);
    } catch (error) {
      setPendingError(error);
      setLog((entries) => [...entries, { at: Date.now(), kind: 'reset', request, error }]);
    } finally {
      setBusy(null);
    }
  };

  const doStep = async (action: unknown) => {
    setBusy('step');
    setPendingError(null);
    setPendingOk(null);
    const request = { action: isRecord(action) ? action : { name: action }, expected_tick: asNumber(state?.tick) };
    try {
      const response = await stepEpisode(episodeId, request);
      setPendingOk(response);
      setLog((entries) => [...entries, { at: Date.now(), kind: 'step', request, response }]);
      episode.reload();
    } catch (error) {
      setPendingError(error);
      setLog((entries) => [...entries, { at: Date.now(), kind: 'step', request, error }]);
    } finally {
      setBusy(null);
    }
  };

  const stopBlocked = status === 'STOPPED';

  return (
    <>
      <PageHeader
        title="主动观察"
        plan="U11 · 计划 20.12"
        summary="当前观察、可达动作、累计成本、候选变化、内部 tick 与外部拍摄步；动作选中才请求对应观测，未揭示帧不进入 state；STOP 与失败在时间线可见。"
        actions={
          <div className="row">
            <Badge tone="info">动作列表完全来自后端</Badge>
            <Badge tone="warn">oracle 动作不会出现在部署式列表</Badge>
          </div>
        }
      />

      {issues.length > 0 ? (
        <SectionCard title="episode 能力阻塞" subtitle="GET /capabilities">
          <p className="warning">
            <Badge tone="warn">{issues[0]?.status}</Badge> {describeIssues(issues)}
          </p>
          <p className="muted small">
            <code className="mono">POST /episodes/&#123;id&#125;/reset</code> 与 <code className="mono">/step</code> 在能力缺失时返回 503，
            并且**不会**写入 state；<code className="mono">GET /episodes/&#123;id&#125;</code> 对未知 id 返回 404。
            本页据此显示阻塞，不生成任何观察帧。
          </p>
        </SectionCard>
      ) : null}

      <SectionCard title="episode 参数" subtitle="POST /episodes/{episode_id}/reset">
        <div className="grid3">
          <label className="field">
            <span className="field__label">episode_id</span>
            <input className="input" value={episodeId} onChange={(event) => setEpisodeId(event.target.value)} />
            <span className="field__hint">后端会做 resource ref 校验；非法 id 会被拒绝</span>
          </label>
          <label className="field">
            <span className="field__label">pool_ref（固定库）</span>
            <select className="input" value={poolRef} onChange={(event) => setPoolRef(event.target.value)}>
              <option value="">（不使用固定池）</option>
              {(pools.data?.items ?? []).map((pool) => (
                <option key={pool.pool_id} value={pool.pool_id}>
                  {pool.pool_id}（{pool.status}）
                </option>
              ))}
            </select>
            <span className="field__hint">固定初检池模式 = 局部诊断；不选则走后端默认</span>
          </label>
          <label className="field">
            <span className="field__label">camera_profile_id</span>
            <select className="input" value={cameraRef} onChange={(event) => setCameraRef(event.target.value)}>
              <option value="">（不使用相机档）</option>
              {(cameras.data?.catalogue ?? []).map((entry) => (
                <option key={entry.profile_id} value={entry.profile_id}>
                  {entry.profile_id}（{entry.calibrated ? '已标定' : '未标定'}）
                </option>
              ))}
            </select>
            <span className="field__hint">U 近移需要真实相机档与 observe 能力</span>
          </label>
        </div>

        <div className="row">
          <ActionButton tone="primary" onClick={() => void doReset()} busy={busy === 'reset'}>
            重置 episode
          </ActionButton>
          <label className="field field--inline">
            <span className="field__label">查询已有 episode</span>
            <input
              className="input input--tight"
              value={lookupId}
              onChange={(event) => setLookupId(event.target.value)}
              placeholder="episode_id"
            />
          </label>
          <ActionButton onClick={episode.reload} disabledReason={lookupId ? null : '先填写查询 id'}>
            重新拉取轨迹
          </ActionButton>
        </div>

        {pendingError ? <ErrorState error={pendingError} title="episode 请求失败（后端真实响应）" /> : null}
        {pendingOk ? (
          <div className="accepted" role="status">
            <h4>后端响应</h4>
            <pre className="mono pre">{pretty(pendingOk)}</pre>
          </div>
        ) : null}
      </SectionCard>

      <SectionCard title="轨迹与动作" subtitle="GET /episodes/{id} · POST /episodes/{id}/step">
        {!lookupId ? (
          <EmptyState title="未加载 episode" reason="先点击“重置 episode”，或在“查询已有 episode”里填写一个 id。" />
        ) : episode.status === 'error' ? (
          <ErrorState error={episode.error} onRetry={episode.reload} />
        ) : episode.status === 'loading' && !episode.data ? (
          <LoadingState label="读取 episode…" />
        ) : episode.data ? (
          <>
            <Tabs
              label="episode 视图"
              active={tab}
              onChange={(id) => setTab(id as typeof tab)}
              tabs={[
                { id: 'state', label: '当前 state' },
                { id: 'log', label: '操作日志' },
                { id: 'evidence', label: '固定库检索证据' },
              ]}
            />

            {tab === 'state' ? (
              <>
                <KeyValueList
                  rows={[
                    { label: 'episode_id', value: episode.data.episode.episode_id, mono: true },
                    { label: 'status', value: status ?? '未提供' },
                    { label: '内部 tick', value: asNumber(state?.tick) ?? '未提供' },
                    { label: '累计成本 cost_total', value: episode.data.episode.cost_total },
                    { label: '步骤数', value: episode.data.episode.steps.length },
                    { label: 'capability episodes', value: `${episode.data.capability.status}（${episode.data.capability.module}）` },
                  ]}
                />

                <h3>当前观察</h3>
                {!observation ? (
                  <EmptyState
                    title="没有观察帧"
                    reason="后端 state.observation 为空或 revealed=false：未揭示的帧不会进入 state，页面也不会替它生成图像。"
                  />
                ) : !observationRevealed ? (
                  <EmptyState title="观察尚未揭示" reason="后端返回 revealed=false；需要先执行一个可达动作才会产生对应观测。" />
                ) : (
                  <pre className="mono pre">{pretty(observation)}</pre>
                )}

                <h3>可达动作（后端 state.available_actions）</h3>
                {availableActions.length === 0 ? (
                  <EmptyState
                    title="没有可达动作"
                    reason={
                      stopBlocked
                        ? 'episode 已 STOPPED：后端不再接受任何动作（step 会返回 409 SCHEMA_INVALID）。'
                        : '后端 state.available_actions 为空或缺失。部署式列表不会包含 oracle 动作。另注意本仓库已知的后端缺陷：POST /episodes/{id}/reset 写入 api_episodes 时用的列名是 state/observation/steps，而 tables.insert 只识别 *_json 列名，因此 spec/state/observation/steps 会被静默丢掉（见 docs/a12/api_ui.md），GET 回来就是空 state。'
                    }
                  />
                ) : (
                  <ul className="actionlist">
                    {availableActions.map((action, index) => {
                      const record = isRecord(action) ? action : {};
                      const label =
                        asString(record.name ?? record.action ?? record.kind) ?? `action[${index}]`;
                      const cost = asNumber(record.cost ?? record.action_cost_seconds ?? record.cost_seconds);
                      return (
                        <li key={`${label}-${index}`}>
                          <div>
                            <strong className="mono">{label}</strong>
                            {cost !== null ? <span className="muted small"> · 声明成本 {cost}</span> : null}
                            {isRecord(action) ? <pre className="mono pre pre--inline">{pretty(action)}</pre> : null}
                          </div>
                          <ActionButton
                            tone="primary"
                            busy={busy === 'step'}
                            onClick={() => void doStep(action)}
                            disabledReason={stopBlocked ? 'episode 已 STOPPED，后端会拒绝任何 step' : null}
                          >
                            执行该动作
                          </ActionButton>
                        </li>
                      );
                    })}
                  </ul>
                )}

                <h3>state 原文</h3>
                <pre className="mono pre">{pretty(state)}</pre>

                <MeasuredQualityTable
                  rows={[
                    {
                      key: 'state.tick',
                      label: '内部 tick',
                      value: asNumber(state?.tick),
                      source: 'GET /episodes/{id}.state.tick',
                    },
                    {
                      key: 'episode.cost_total',
                      label: '累计成本',
                      value: episode.data.episode.cost_total,
                      source: 'GET /episodes/{id}.cost_total',
                    },
                    {
                      key: 'external.capture_steps',
                      label: '外部拍摄步',
                      value: null,
                      source: 'API 未提供该字段（需要 observe 模块写入 steps）',
                      flag: 'missing',
                    },
                  ]}
                  caption="成本与 tick 均来自后端记录；未提供的字段不补 0"
                />
              </>
            ) : null}

            {tab === 'log' ? (
              log.length === 0 ? (
                <EmptyState title="本次会话还没有操作" reason="reset/step 的请求与响应会记录在这里（含失败），便于复核错误→正确/正确→错误。" />
              ) : (
                <ol className="timeline__list">
                  {log.map((entry, index) => (
                    <li key={index} className="timeline__item">
                      <div className="timeline__meta">
                        <span className="mono">#{index + 1}</span>
                        <span className="mono">{new Date(entry.at).toLocaleTimeString('zh-CN', { hour12: false })}</span>
                        <Badge tone={entry.error ? 'bad' : 'ok'}>{entry.kind}</Badge>
                      </div>
                      <div className="timeline__body">
                        <pre className="mono pre pre--inline">请求 {pretty(entry.request)}</pre>
                        {entry.error ? <ErrorState error={entry.error} compact /> : <pre className="mono pre pre--inline">响应 {pretty(entry.response)}</pre>}
                      </div>
                    </li>
                  ))}
                </ol>
              )
            ) : null}

            {tab === 'evidence' ? (
              <AssetBrowser
                title="固定库检索证据（query_roster / feature_bundle / episode_trace）"
                fixedRoles={['query_roster', 'feature_bundle', 'episode_trace']}
                selectable="none"
                onProvenance={(assetId) => app.openProvenance({ kind: 'asset', id: assetId })}
                pageSize={8}
                emptyReason="还没有 episode 轨迹或检索证据资产；未运行的 episode 不会产生这些产物。"
              />
            ) : null}

            <h4>steps（后端记录，原样）</h4>
            {episode.data.episode.steps.length === 0 ? (
              <p className="muted small">后端 steps 为空；页面不推断动作是否生效。</p>
            ) : (
              <pre className="mono pre">{pretty(episode.data.episode.steps)}</pre>
            )}
            <p className="muted small">
              episode 产物（轨迹、检索证据、观察帧）按资产 role 在“固定库检索证据”标签页中列出；
              没有后端产物时该列表为空，页面不生成占位文件。
            </p>
          </>
        ) : null}
      </SectionCard>
    </>
  );
}
