/**
 * U06 相机与采集档 `/synlab/camera-profiles`（计划 20.7）。
 *
 * 真实调用：`GET /camera-profiles`（注册表 + 真实 catalogue + 可达动作 + 标定状态）、
 * `POST /camera-profiles`（注册新版本）、`GET /camera-profiles/{id}`（历史版本）、
 * `GET /capabilities`（cameras 能力与 env）。
 * 另外本页的“U 位置 → 真实新场景帧”面板使用 `POST /specs/validate`、`POST /previews`、
 * `GET /jobs/{id}`、`GET /assets?role=obs_view` 与 `GET /assets/{id}/files/obs_view?key=arrays`
 * （见 components/CameraUPreviewPanel.tsx）。
 *
 * 验收要点落地：
 * * 滑块**不得绕过**可达限制 → 滑块 min/max/step 直接取 catalogue 的 `meta.u_allowed_range_mm`
 *   与 `meta.u_step_mm`；需要越界取值时用“精确 U 值”输入框，**由后端回答**而不是前端拦截；
 * * 未实拍档显示“未标定” → 来自 catalogue 的 `calibrated` 与 `calibration_refs`；
 * * 草稿与已应用值分开：松手前一律标“未计算”，不把草稿代入任何读数。
 */

import { useMemo, useState } from 'react';

import { CameraFrustumView } from '../components/CameraFrustumView';
import { CameraUPreviewPanel } from '../components/CameraUPreviewPanel';
import { I09ExtrinsicsCheck } from '../components/I09ExtrinsicsCheck';
import { SchemaForm, type FieldSpec, type FormValue } from '../components/SchemaForm';
import { ActionButton, Badge, BlockedState, EmptyState, ErrorState, KeyValueList, LoadingState, PageHeader, SectionCard } from '../components/states';
import { createCameraProfile, getCameraProfile, getCapabilities, listCameraProfiles } from '../api/endpoints';
import { useResource } from '../api/hooks';
import { capabilityIssues, describeIssues } from '../lib/caps';
import { formatNumber, pretty } from '../lib/format';
import { useAppState } from '../state/app-state';

const PROFILE_FIELDS: FieldSpec[] = [
  { kind: 'string', path: 'profile_id', label: 'profile_id', required: true, hint: '2–64 字符' },
  { kind: 'string', path: 'version', label: 'version', required: true, hint: '1–32 字符；同 id 同 version 会被 409 拒绝，必须升版本' },
  { kind: 'string', path: 'tier', label: 'tier', enumValues: ['GLOBAL', 'MID', 'LOCAL'] },
  {
    kind: 'string',
    path: 'calibration_source',
    label: '标定来源 calibration_source',
    enumValues: ['UNGALIBRATED', 'MANUFACTURER', 'MEASURED', 'SYNTHETIC_GT'],
    hint: '注意：后端 Literal 的“未标定”取值拼写为 UNGALIBRATED（不是 UNCALIBRATED），见差异表',
  },
];

export function CameraProfilesPage() {
  const app = useAppState();
  const capabilities = useResource((signal) => getCapabilities({ doctor: 'none' }, signal), []);
  const [tier, setTier] = useState<string>('');
  const profiles = useResource((signal) => listCameraProfiles({ tier: tier || undefined, limit: 50 }, signal), [tier]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState<FormValue>({
    profile_id: '',
    version: '1',
    tier: 'GLOBAL',
    calibration_source: 'UNGALIBRATED',
  });
  const [payloadText, setPayloadText] = useState('{\n  "reachable_actions": ["GLOBAL_ROTATE"],\n  "note": "由 UI 注册的真实 profile"\n}');
  const [payloadError, setPayloadError] = useState<string | null>(null);
  const [submitState, setSubmitState] = useState<{ status: 'idle' | 'busy' | 'ok' | 'error'; response?: unknown; error?: unknown }>({
    status: 'idle',
  });

  const detail = useResource((signal) => getCameraProfile(selectedId as string, signal), [selectedId], {
    enabled: Boolean(selectedId),
  });

  const catalogue = profiles.data?.catalogue ?? [];
  const selected = useMemo(() => {
    if (selectedId) {
      return catalogue.find((entry) => entry.profile_id === selectedId) ?? catalogue[0] ?? null;
    }
    return catalogue[0] ?? null;
  }, [catalogue, selectedId]);

  const uRange = useMemo(() => {
    const raw = selected?.meta?.u_allowed_range_mm;
    if (Array.isArray(raw) && raw.length >= 2) return [Number(raw[0]), Number(raw[1])] as [number, number];
    return null;
  }, [selected]);
  const uStep = useMemo(() => {
    const raw = selected?.meta?.u_step_mm;
    return typeof raw === 'number' ? raw : null;
  }, [selected]);

  const issues = capabilityIssues(capabilities.data ?? null, ['cameras']);

  const submit = async () => {
    setSubmitState({ status: 'busy' });
    let payload: Record<string, unknown>;
    try {
      const parsed: unknown = JSON.parse(payloadText);
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) throw new Error('payload 必须是 JSON 对象');
      payload = parsed as Record<string, unknown>;
      setPayloadError(null);
    } catch (error) {
      setPayloadError(`payload JSON 解析失败：${(error as Error).message}`);
      setSubmitState({ status: 'idle' });
      return;
    }
    try {
      const response = await createCameraProfile({
        profile_id: String(draft.profile_id ?? ''),
        version: String(draft.version ?? ''),
        tier: (draft.tier as 'GLOBAL' | 'MID' | 'LOCAL') ?? 'GLOBAL',
        payload,
        calibration_source: (draft.calibration_source as 'UNGALIBRATED' | 'MANUFACTURER' | 'MEASURED' | 'SYNTHETIC_GT') ?? 'UNGALIBRATED',
      });
      setSubmitState({ status: 'ok', response });
      profiles.reload();
    } catch (error) {
      setSubmitState({ status: 'error', error });
    }
  };

  return (
    <>
      <PageHeader
        title="相机与采集档"
        plan="U06 · 计划 20.7"
        summary="工作距离/U、焦点档、K/畸变、原分辨率、FOV/景深、灯态、可达范围、动作成本、标定来源与校准状态；画布给出视锥、光轴导轨、物体/支撑与景深；U 变化走真实预览请求并取回真实帧。"
        actions={
          <div className="row">
            <Badge tone="info">mm / px 双读数</Badge>
            <Badge tone="neutral">滑块受后端可达范围约束</Badge>
            <Badge tone="ok">U 变化：真实预览请求</Badge>
          </div>
        }
      />

      {issues.length > 0 ? (
        <BlockedState
          title="相机能力不可用"
          code={issues[0].status}
          reason={describeIssues(issues)}
          items={[{ label: '影响', value: '无法枚举真实档位；POST /camera-profiles 会返回 503 DEPENDENCY_CAPABILITY_MISSING' }]}
        />
      ) : null}

      <SectionCard
        title="采集档列表"
        subtitle="GET /camera-profiles（catalogue 来自 synlab.cameras.camera_profiles()，registered 来自注册表）"
        actions={
          <div className="row">
            <label className="field field--inline">
              <span className="field__label">tier</span>
              <select className="input input--tight" value={tier} onChange={(event) => setTier(event.target.value)}>
                <option value="">（全部）</option>
                <option value="GLOBAL">GLOBAL</option>
                <option value="MID">MID</option>
                <option value="LOCAL">LOCAL</option>
              </select>
            </label>
            <button type="button" className="btn btn--tiny" onClick={profiles.reload} disabled={profiles.refreshing}>
              {profiles.refreshing ? '刷新中…' : '刷新'}
            </button>
          </div>
        }
      >
        {profiles.status === 'loading' ? <LoadingState label="读取 camera profiles…" /> : null}
        {profiles.status === 'error' ? <ErrorState error={profiles.error} onRetry={profiles.reload} /> : null}
        {profiles.data ? (
          <>
            <p>
              <Badge tone={profiles.data.capability.available ? 'ok' : 'warn'}>
                capability cameras = {profiles.data.capability.status}
              </Badge>
              <span className="mono small">
                {' '}
                模块={profiles.data.capability.module} · catalogue={profiles.data.catalogue.length} · registered=
                {profiles.data.registered.length}
              </span>
            </p>
            {profiles.data.blocked_reason ? <p className="warning">{profiles.data.blocked_reason}</p> : null}
            {profiles.data.empty_reason && profiles.data.catalogue.length === 0 ? (
              <EmptyState title="没有采集档" reason={profiles.data.empty_reason} />
            ) : null}
            <p className="muted small">
              可达动作（后端白名单）：
              {profiles.data.reachable_actions.map((action) => (
                <Badge key={action} tone="neutral">
                  {action}
                </Badge>
              ))}
              · 标定状态取值：{profiles.data.calibration_states.join(', ')}
            </p>

            {profiles.data.catalogue.length > 0 ? (
              <table className="table">
                <caption>catalogue（真实档位与可达范围）</caption>
                <thead>
                  <tr>
                    <th scope="col">选择</th>
                    <th scope="col">profile</th>
                    <th scope="col">tier</th>
                    <th scope="col">工作距离 (mm)</th>
                    <th scope="col">U 位置 (mm)</th>
                    <th scope="col">U 可达范围 (mm)</th>
                    <th scope="col">FOV (mm)</th>
                    <th scope="col">景深 (mm)</th>
                    <th scope="col">标定</th>
                    <th scope="col">成本 (s)</th>
                  </tr>
                </thead>
                <tbody>
                  {profiles.data.catalogue.map((entry) => {
                    const meta = entry.meta ?? {};
                    const range = Array.isArray(meta.u_allowed_range_mm) ? (meta.u_allowed_range_mm as number[]) : null;
                    return (
                      <tr key={entry.profile_id} className={selected?.profile_id === entry.profile_id ? 'row--selected' : undefined}>
                        <td>
                          <input
                            type="radio"
                            name="camera-profile"
                            checked={selected?.profile_id === entry.profile_id}
                            onChange={() => setSelectedId(entry.profile_id)}
                            aria-label={`选择 ${entry.profile_id}`}
                          />
                        </td>
                        <td className="mono">
                          {entry.profile_id}
                          <div className="muted small">rev {entry.revision}</div>
                        </td>
                        <td>
                          <Badge tone="neutral">{entry.tier}</Badge>
                        </td>
                        <td className="mono">{formatNumber(entry.working_distance_mm, 2)}</td>
                        <td className="mono">{formatNumber(entry.u_position_mm, 2)}</td>
                        <td className="mono">{range ? `${range[0]} … ${range[1]}（步长 ${meta.u_step_mm ?? '—'}）` : '未提供'}</td>
                        <td className="mono">{entry.fov_mm.map((value) => formatNumber(value, 1)).join(' × ')}</td>
                        <td className="mono">{entry.depth_of_field_mm.map((value) => formatNumber(value, 1)).join(' … ')}</td>
                        <td>
                          <Badge tone={entry.calibrated ? 'ok' : 'warn'}>{entry.calibrated ? '已标定' : '未标定'}</Badge>
                          <div className="mono small">{(entry.calibration_refs ?? []).join(', ') || '无'}</div>
                        </td>
                        <td className="mono">{formatNumber(entry.action_cost_seconds, 1)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            ) : null}

            {profiles.data.registered.length > 0 ? (
              <table className="table table--tight">
                <caption>已注册 profile 版本（POST /camera-profiles 写入的表）</caption>
                <thead>
                  <tr>
                    <th scope="col">profile_id</th>
                    <th scope="col">version</th>
                    <th scope="col">tier</th>
                    <th scope="col">status</th>
                    <th scope="col">calibration_source</th>
                    <th scope="col">payload</th>
                    <th scope="col">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {profiles.data.registered.map((row) => (
                    <tr key={`${row.profile_id}-${row.version}`}>
                      <th scope="row" className="mono">
                        {row.profile_id}
                      </th>
                      <td className="mono">{row.version}</td>
                      <td className="mono">{row.tier}</td>
                      <td>
                        <Badge tone="neutral">{row.status}</Badge>
                      </td>
                      <td className="mono">{row.calibration_source ?? '—'}</td>
                      <td className="mono small">{JSON.stringify(row.payload)}</td>
                      <td>
                        <button type="button" className="btn btn--tiny" onClick={() => setSelectedId(row.profile_id)}>
                          查看版本历史
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <EmptyState
                title="注册表为空"
                reason="还没有通过 POST /camera-profiles 注册过档位。catalogue 是代码内置的真实档位描述，与注册表是两件事。"
              />
            )}
          </>
        ) : null}
      </SectionCard>

      <div className="grid2">
        <div>
          <CameraFrustumView entry={selected} uPositionMm={selected?.u_position_mm ?? 0} height={340} />
          <p className="muted small">
            画布上相机沿导轨的位置 = catalogue 的真实 U（{formatNumber(selected?.u_position_mm ?? 0, 2)} mm）。
            视场、景深与内参 K 同样取 catalogue 的**真实值**；要得到新 U 下的读数必须走下面的真实预览请求。
            {selected && uRange ? (
              <>
                {' '}
                滑块受后端可达范围 {uRange[0]} … {uRange[1]} mm 约束（步长 {uStep ?? '未声明'}）。
              </>
            ) : null}
          </p>
        </div>
        <div>
          <SectionCard title="注册新 profile 版本" subtitle="POST /camera-profiles（calibrated 与 calibration_source 必须一致，否则 422）">
            <SchemaForm
              fields={PROFILE_FIELDS}
              value={draft}
              onChange={setDraft}
              advanced={false}
              label="camera profile 表单"
            />
            <label className="field">
              <span className="field__label">payload（JSON 对象）</span>
              <textarea
                className="input input--code"
                rows={6}
                spellCheck={false}
                value={payloadText}
                onChange={(event) => setPayloadText(event.target.value)}
              />
              {payloadError ? <span className="field__error">{payloadError}</span> : null}
              <span className="field__hint">
                允许的 reachable_actions 由后端白名单给出；含未知动作会被 422 拒绝并返回 allowed 列表。
              </span>
            </label>
            <div className="row">
              <ActionButton
                tone="primary"
                onClick={() => void submit()}
                busy={submitState.status === 'busy'}
                disabledReason={
                  !draft.profile_id
                    ? 'profile_id 不能为空'
                    : !draft.version
                      ? 'version 不能为空'
                      : null
                }
              >
                注册 profile
              </ActionButton>
            </div>
            {submitState.status === 'ok' ? (
              <div className="accepted" role="status">
                <h4>注册成功</h4>
                <pre className="mono pre">{pretty(submitState.response)}</pre>
                <p className="warning">
                  注意（后端差异）：<code className="mono">POST /camera-profiles</code> 目前把 <code className="mono">payload</code>{' '}
                  写成了空对象——<code className="mono">synlab/api/tables.py::insert</code> 只认 <code className="mono">payload_json</code>{' '}
                  列名，路由传的是 <code className="mono">payload</code>，因此提交的 payload 会被静默丢弃（见 docs/a12/api_ui.md）。
                  上表的 payload 列显示的就是数据库里的真实内容。
                </p>
              </div>
            ) : null}
            {submitState.status === 'error' ? <ErrorState error={submitState.error} title="注册被拒绝" /> : null}
          </SectionCard>

          <SectionCard title="版本历史" subtitle="GET /camera-profiles/{profile_id}">
            {!selectedId ? (
              <EmptyState title="未选择 profile_id" reason="点击列表里的“查看版本历史”。" />
            ) : detail.status === 'loading' ? (
              <LoadingState label="读取版本历史…" />
            ) : detail.status === 'error' ? (
              <ErrorState error={detail.error} onRetry={detail.reload} compact />
            ) : detail.data ? (
              <>
                <KeyValueList
                  rows={[
                    { label: 'profile_id', value: detail.data.profile_id, mono: true },
                    { label: '版本数', value: detail.data.count },
                    { label: '最新版本', value: detail.data.latest.version, mono: true },
                  ]}
                />
                <table className="table table--tight">
                  <thead>
                    <tr>
                      <th scope="col">version</th>
                      <th scope="col">tier</th>
                      <th scope="col">calibration_source</th>
                      <th scope="col">created_at</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.data.versions.map((row) => (
                      <tr key={row.version}>
                        <th scope="row" className="mono">
                          {row.version}
                        </th>
                        <td className="mono">{row.tier}</td>
                        <td className="mono">{row.calibration_source ?? '—'}</td>
                        <td className="mono">{new Date(row.created_at * 1000).toLocaleString('zh-CN', { hour12: false })}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            ) : null}
          </SectionCard>

          <SectionCard title="U06 仍受限的项（如实列出）" subtitle="计划 20.7 的画布与交互">
            <ul className="notes">
              <li>
                <strong>近/中/远同片帧</strong>：需要后端按 tier 渲染同一片的多档帧。API 未暴露该路由，因此不生成任何图片。
              </li>
              <li>
                <strong>预计 ROI / 碰撞包络</strong>：catalogue 的 meta 里有 <code className="mono">roi_xywh</code>，已在画布下方读数中可查；
                三维包络需要支撑体与碰撞体资产，当前没有对应角色，故未绘制。
              </li>
              <li>
                <strong>灯态（LIGHT_STATE）</strong>：属于白名单里的可达动作，但当前 catalogue 未提供灯态取值，页面不编造。
              </li>
              <li>
                <strong>U 作为“已应用参数”写入后端</strong>：没有任何路由接受 <code className="mono">u_position_mm</code>
                （<code className="mono">POST /previews</code> 的 stage 白名单里没有 <code className="mono">observe</code>，
                生成 spec 又是 <code className="mono">extra=&quot;forbid&quot;</code>），因此新帧不会带新 U。
                上面面板把这两条真实 422 原样展示，而不是前端假装成功。
              </li>
            </ul>
            <button
              type="button"
              className="btn btn--tiny"
              onClick={() => app.openProvenance(null)}
              disabled
              title="没有可溯源的资产时按钮禁用"
            >
              溯源（无选中资产）
            </button>
          </SectionCard>
        </div>
      </div>

      <CameraUPreviewPanel entry={selected} />
      <I09ExtrinsicsCheck />
    </>
  );
}
