/**
 * 展示页的五个分区（母体库 / 纹样通道 / 碎裂演示 / 退化对比 / 状态与诚实性面板）。
 *
 * 每个分区：
 * * 只渲染清单里**真实存在**的字段，缺失写“未提供”，从不补 0；
 * * 空 / 部分失败 / 全失败各有独立状态：`EmptyState` / `BlockedState` / `FailureDrawer`；
 * * 所有数值带单位，所有资产链接都指向 `GET /showcase/asset/{id}/{key}`（带 sha256 校验）。
 */

import { useMemo, useState } from 'react';

import {
  artifactOf,
  asRecord,
  levelArtifact,
  levelRow,
  num,
  showcaseAssetUrl,
  str,
  type ShowcaseAxisCatalogItem,
  type ShowcaseEntry,
} from '../../api/showcase';
import { formatBytes } from '../../lib/format';
import { SceneViewport } from '../SceneViewport';
import {
  Badge,
  CopyValue,
  EmptyState,
  KeyValueList,
  SectionCard,
  Tabs,
} from '../states';
import { FailureDrawer, type StaticFailure } from '../FailureDrawer';
import { FragmentAssemblyViewport, type FragmentRef } from './FragmentAssemblyViewport';

/* ====================================================================== 公共小件 */

const STATUS_TONE: Record<string, 'ok' | 'warn' | 'bad' | 'neutral'> = {
  OK: 'ok',
  BLOCKED: 'warn',
  FAILED: 'bad',
  NA: 'neutral',
};

export function StatusBadge({ status }: { status: string }) {
  return <Badge tone={STATUS_TONE[status] ?? 'neutral'}>{status}</Badge>;
}

function qaTone(status: string | null | undefined): 'ok' | 'warn' | 'bad' | 'neutral' {
  if (status === 'QA_PASS') return 'ok';
  if (status === 'QA_PENDING') return 'warn';
  if (status === 'QA_FAIL') return 'bad';
  return 'neutral';
}

/**
 * ISO-8601 字符串 → 本地时间。清单写的是 `datetime.now(timezone.utc).isoformat()`，
 * 不是 Unix 秒，所以不能用 `lib/format.ts::formatTimestamp`（那个只接受 epoch 秒）。
 * 解析不了就照实写“未提供”，不回落到当前时间。
 */
export function formatIso(value: unknown): string {
  if (typeof value !== 'string' || value.trim() === '') return '未提供';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return `未提供（原样：${value}）`;
  return `${date.toLocaleString('zh-CN', { hour12: false })}（清单原值 ${value}）`;
}

function failureOf(entry: ShowcaseEntry): StaticFailure {
  const failure = entry.failure;
  return {
    title: `${entry.title} · ${entry.status}`,
    code: failure?.code ?? 'UNKNOWN',
    message: failure?.message ?? '清单里没有记录失败原因（这本身是一个数据缺口）',
    stage: failure?.stage ?? null,
    retryable: failure?.retryable ?? null,
    measurements: failure?.measurements,
    detail: failure?.detail ?? null,
    sourceRef: entry.asset_id ?? entry.entry_id,
    status: entry.status,
    reproduceCommand:
      entry.kind === 'fracture'
        ? `& .venv\\Scripts\\python.exe tools\\build_demo_assets.py --only fracture --unit ${entry.entry_id} --force`
        : `& .venv\\Scripts\\python.exe tools\\build_demo_assets.py --unit ${entry.entry_id} --force`,
  };
}

function reproCommand(entry: ShowcaseEntry): string {
  return `& .venv\\Scripts\\python.exe tools\\build_demo_assets.py --unit ${entry.entry_id} --force`;
}

function unavailable(title: string, reason: string, code = 'SHOWCASE_DATA_MISSING') {
  return (
    <EmptyState
      title={title}
      reason={
        <>
          {reason} <Badge tone="neutral">{code}</Badge>
        </>
      }
    />
  );
}

/* ====================================================================== 1) 母体库 */

export function MothersSection({ entries }: { entries: ShowcaseEntry[] }) {
  const mothers = useMemo(() => entries.filter((e) => e.kind === 'mother'), [entries]);
  const [selected, setSelected] = useState<string | null>(null);
  const current = mothers.find((e) => e.entry_id === selected) ?? mothers[0] ?? null;
  const glb = artifactOf(current, 'glb');
  const metrics = asRecord(current?.metrics) ?? {};
  const qa = asRecord(metrics.qa_metrics) ?? {};
  const checks = asRecord(metrics.qa_checks) ?? {};

  return (
    <SectionCard
      title="1 · 母体库"
      subtitle="来自 synlab.mothers.api 的 sample_parameters → create_mother → audit_mother → commit_mother；GLB 是米/Y-up 派生展示资产。"
      anchor="mothers"
      actions={<Badge tone="info">真实条目 {mothers.length}</Badge>}
    >
      {mothers.length === 0 ? (
        unavailable('没有母体条目', '清单里没有 kind=mother 的条目；请先运行 --only mothers。')
      ) : (
        <>
          <div className="showcase-grid" role="list">
            {mothers.map((entry) => {
              const item = asRecord(entry.metrics) ?? {};
              const active = current?.entry_id === entry.entry_id;
              return (
                <button
                  key={entry.entry_id}
                  type="button"
                  role="listitem"
                  className={`showcase-card${active ? ' showcase-card--active' : ''}`}
                  aria-pressed={active}
                  onClick={() => setSelected(entry.entry_id)}
                >
                  <div className="showcase-card__head">
                    <strong>{str(item.vessel_id) ?? entry.entry_id}</strong>
                    <StatusBadge status={entry.status} />
                  </div>
                  <div className="mono small">{entry.entry_id}</div>
                  <div className="muted small">
                    {str(item.material_id) ?? '—'} · 面 {num(item.faces) ?? '未提供'} ·{' '}
                    {num(item.volume_mm3) !== null
                      ? `${(num(item.volume_mm3) as number).toFixed(1)} mm³`
                      : '体积未提供'}
                  </div>
                  <div className="muted small">
                    水密 {item.watertight === true ? '是' : item.watertight === false ? '否' : '未提供'}
                  </div>
                </button>
              );
            })}
          </div>

          {current ? (
            <div className="showcase-detail">
              <SceneViewport
                assetId={glb ? glb.asset_id : null}
                role={glb ? (glb.role ?? 'display_lod_glb') : 'display_lod_glb'}
                fileKey={glb ? (glb.key ?? 'glb') : 'glb'}
                source="showcase"
                title={`母体 ${str(metrics.vessel_id) ?? ''} 三维视口`}
                height={340}
                notice={
                  glb
                    ? `展示资产 ${glb.asset_id}（display_lod_glb）`
                    : '该条目没有派生展示 GLB 资产'
                }
              />

              <div className="showcase-cols">
                <div>
                  <h4>真实 QA 数值（audit_mother）</h4>
                  <KeyValueList
                    rows={[
                      { label: '状态', value: <StatusBadge status={current.status} /> },
                      { label: 'qa_status', value: <Badge tone={qaTone(current.qa_status)}>{current.qa_status ?? '未提供'}</Badge> },
                      { label: 'QA state', value: str(metrics.qa_state) ?? '未提供' },
                      { label: '资产 id', value: <CopyValue value={current.asset_id ?? ''} label="asset_id" /> },
                      { label: 'role / schema', value: <span className="mono">{current.role} / {current.schema}</span>, mono: true },
                      { label: '单位 / 坐标帧', value: <span className="mono">{current.unit} / {current.frame}</span> },
                      { label: '水密', value: metrics.watertight === true ? '是' : metrics.watertight === false ? '否' : '未提供' },
                      { label: '体积', value: num(metrics.volume_mm3) !== null ? `${(num(metrics.volume_mm3) as number).toFixed(3)} mm³` : '未提供' },
                      { label: '表面积', value: num(metrics.area_mm2) !== null ? `${(num(metrics.area_mm2) as number).toFixed(3)} mm²` : '未提供' },
                      { label: '壁厚 min', value: num(qa.thickness_min_mm) !== null ? `${(num(qa.thickness_min_mm) as number).toFixed(4)} mm` : '未提供' },
                      { label: '壁厚 P05', value: num(qa.thickness_p05_mm) !== null ? `${(num(qa.thickness_p05_mm) as number).toFixed(4)} mm` : '未提供' },
                      { label: '壁厚 median', value: num(qa.thickness_median_mm) !== null ? `${(num(qa.thickness_median_mm) as number).toFixed(4)} mm` : '未提供' },
                      { label: '壁厚探针数', value: num(qa.thickness_probes) ?? '未提供' },
                      { label: '空腔比 void_ratio', value: num(qa.void_ratio) !== null ? (num(qa.void_ratio) as number).toFixed(6) : '未提供' },
                      { label: '连通体 / genus', value: `${num(qa.bodies) ?? '未提供'} / ${num(qa.genus) ?? '未提供'}` },
                      { label: '自交面对', value: num(qa.self_intersecting_pairs) ?? '未提供' },
                      { label: '面数 / 顶点', value: `${num(metrics.faces) ?? '未提供'} / ${num(metrics.vertices) ?? '未提供'}` },
                      { label: '尺寸 mm', value: <span className="mono">{Array.isArray(metrics.extent_mm) ? (metrics.extent_mm as number[]).map((v) => v.toFixed(3)).join(' × ') : '未提供'}</span> },
                      { label: '生成耗时', value: num(current.duration_s) !== null ? `${num(current.duration_s)} s` : '未提供' },
                    ]}
                  />
                </div>
                <div>
                  <h4>真实 checks（audit_mother.checks 原样）</h4>
                  {Object.keys(checks).length === 0 ? (
                    unavailable('没有 checks 字段', '该条目的 metrics.qa_checks 为空。')
                  ) : (
                    <pre className="mono pre showcase-pre">{JSON.stringify(checks, null, 1)}</pre>
                  )}
                  <h4>采样参数（sample_parameters 的真实输出）</h4>
                  <pre className="mono pre showcase-pre">
                    {JSON.stringify(metrics.params ?? '未提供', null, 1)}
                  </pre>
                </div>
              </div>

              {glb ? (
                <p className="muted small">
                  展示资产直链（走展示白名单路由，带 sha256 校验）：
                  <a href={showcaseAssetUrl(glb.asset_id, 'glb', { download: true })}>下载 GLB</a>
                  {' · '}
                  <a href={showcaseAssetUrl(glb.asset_id, 'meta')} target="_blank" rel="noreferrer">
                    查看 meta.json
                  </a>
                  {asRecord(glb.metrics)?.glb_bytes ? (
                    <span className="mono"> · {formatBytes(num(asRecord(glb.metrics)?.glb_bytes))}</span>
                  ) : null}
                </p>
              ) : null}
            </div>
          ) : null}
        </>
      )}
    </SectionCard>
  );
}

/* ====================================================================== 2) 纹样通道 */

const CHANNEL_LABELS: Array<{ key: 'albedo_png' | 'roughness_png' | 'height_png'; label: string; unit: string }> = [
  { key: 'albedo_png', label: 'albedo', unit: 'linear rgb' },
  { key: 'roughness_png', label: 'roughness', unit: '1' },
  { key: 'height_png', label: 'height_mm', unit: 'mm' },
];

export function PatternsSection({ entries }: { entries: ShowcaseEntry[] }) {
  const patterns = useMemo(
    () => entries.filter((e) => e.kind === 'pattern').sort((a, b) => a.entry_id.localeCompare(b.entry_id)),
    [entries],
  );
  const [selected, setSelected] = useState<string | null>(null);
  const current = patterns.find((e) => e.entry_id === selected) ?? patterns[0] ?? null;
  const channels = artifactOf(current, 'channels');
  const metrics = asRecord(current?.metrics) ?? {};
  const raster = asRecord(metrics.raster) ?? {};
  const legend = asRecord(metrics.legend) ?? {};
  const seam = asRecord(metrics.seam) ?? {};
  const seamChart = asRecord(seam.chart_space) ?? {};
  const scale = asRecord(metrics.scale) ?? {};
  const spectrum = asRecord(scale.spectrum) ?? {};
  const channelStats = asRecord(metrics.channel_stats) ?? {};

  return (
    <SectionCard
      title="2 · 纹样通道"
      subtitle="build_pattern → evaluate（真实母体上面积加权采样）→ (x,s) 网格分箱 → albedo / roughness / height_mm 三通道 PNG；PNG 是显示编码，非线性真值。"
      anchor="patterns"
      actions={<Badge tone="info">真实条目 {patterns.length}</Badge>}
    >
      {patterns.length === 0 ? (
        unavailable('没有纹样条目', '清单里没有 kind=pattern 的条目；请先运行 --only patterns。')
      ) : (
        <>
          <Tabs
            label="纹样族选择"
            active={current?.entry_id ?? ''}
            onChange={(id) => setSelected(id)}
            tabs={patterns.map((entry) => ({
              id: entry.entry_id,
              label: `${str(asRecord(entry.metrics)?.family_id) ?? entry.entry_id} · ${str(asRecord(entry.metrics)?.family_name) ?? ''}`,
            }))}
          />

          {current ? (
            <div className="showcase-detail">
              <div className="row">
                <StatusBadge status={current.status} />
                <Badge tone="neutral">母体 {current.mother_entry ?? '未提供'}</Badge>
                <Badge tone="info">recipe {str(metrics.recipe_hash)?.slice(0, 22) ?? '未提供'}</Badge>
                <Badge tone="neutral">palette {str(metrics.palette_id) ?? '未提供'}</Badge>
                <span className="muted small">
                  生成于 {formatIso(current.generated_at)} · 耗时 {num(current.duration_s) ?? '—'} s
                </span>
              </div>

              {!channels ? (
                unavailable('该纹样没有通道图像资产', 'artifact channels 缺失；清单里没有 PNG 可展示。')
              ) : (
                <>
                  <div className="showcase-channels">
                    {CHANNEL_LABELS.map((channel) => {
                      const payloadKey = str(asRecord(channels.keys)?.[channel.key.replace('_png', '')]) ?? channel.key;
                      return (
                        <figure key={channel.key} className="showcase-figure">
                          <img
                            src={showcaseAssetUrl(channels.asset_id, 'png', { name: payloadKey })}
                            alt={`${current.entry_id} ${channel.label} 通道（显示编码 PNG）`}
                            width={256}
                            height={128}
                            loading="lazy"
                          />
                          <figcaption>
                            <strong>{channel.label}</strong>
                            <span className="muted small">（{channel.unit}）</span>
                            <div className="mono small">payload key: {payloadKey}</div>
                          </figcaption>
                        </figure>
                      );
                    })}
                  </div>
                  <div className="banner banner--legend" role="note">
                    <strong>显示编码说明（图例）</strong>
                    <ul>
                      {CHANNEL_LABELS.map((channel) => (
                        <li key={channel.key}>
                          <code className="mono">{channel.label}</code>：
                          {str(legend[channel.key]) ?? '清单未提供该通道的图例字符串'}
                        </li>
                      ))}
                    </ul>
                    <div className="muted small">
                      栅格方法：{str(raster.method) ?? '未提供'}；网格 {num(raster.width) ?? '?'}×
                      {num(raster.height) ?? '?'}，采样 n={num(raster.n_samples) ?? '?'}，
                      分箱覆盖{' '}
                      {num(raster.bin_coverage) !== null
                        ? `${((num(raster.bin_coverage) as number) * 100).toFixed(1)}%`
                        : '未提供'}
                      ，每有效 bin 平均样本{' '}
                      {num(raster.mean_samples_per_filled_bin)?.toFixed(2) ?? '未提供'}。
                    </div>
                  </div>
                </>
              )}

              <div className="showcase-cols">
                <div>
                  <h4>接缝与尺度实测（audit_pattern）</h4>
                  <KeyValueList
                    rows={[
                      { label: 'audit_pass', value: <Badge tone={metrics.audit_pass ? 'ok' : 'bad'}>{String(metrics.audit_pass ?? '未提供')}</Badge> },
                      { label: '接缝最大色差', value: num(seamChart.max_abs_color_error) !== null ? `${num(seamChart.max_abs_color_error)} (线性 rgb)` : '未提供' },
                      { label: '接缝容差', value: num(seamChart.tolerance) !== null ? String(num(seamChart.tolerance)) : '未提供' },
                      { label: '接缝导数失配 P99', value: num(seamChart.p99_deriv_mismatch_abs) !== null ? String(num(seamChart.p99_deriv_mismatch_abs)) : '未提供' },
                      { label: '导数比值预算', value: num(seamChart.deriv_ratio_budget) !== null ? String(num(seamChart.deriv_ratio_budget)) : '未提供' },
                      { label: '接缝采样对 n', value: num(seamChart.n_pairs) ?? '未提供' },
                      { label: 'x 周期', value: num(raster.x_period_mm) !== null ? `${(num(raster.x_period_mm) as number).toFixed(3)} mm（周期性=${raster.x_periodic === true ? '是' : '否'}）` : '未提供' },
                      { label: 's 范围', value: Array.isArray(raster.s_range_mm) ? `${(raster.s_range_mm as number[]).map((v) => v.toFixed(3)).join(' … ')} mm` : '未提供' },
                      { label: '声明线宽', value: num(scale.declared_line_width_mm) !== null ? `${(num(scale.declared_line_width_mm) as number).toFixed(4)} mm` : '未提供' },
                      { label: '线宽实测', value: str(asRecord(scale.line_width_mm)?.status) === 'OK' ? `${num(asRecord(scale.line_width_mm)?.value_mm) ?? '未提供'} mm` : `NA：${str(asRecord(scale.line_width_mm)?.reason) ?? '未提供'}` },
                      { label: '主波长', value: num(spectrum.dominant_wavelength_mm) !== null ? `${(num(spectrum.dominant_wavelength_mm) as number).toFixed(4)} mm` : '未提供' },
                      { label: '倍频带覆盖', value: num(spectrum.octave_band_coverage) !== null ? String(num(spectrum.octave_band_coverage)) : '未提供' },
                      { label: '高频残差', value: num(spectrum.high_frequency_residual) !== null ? String(num(spectrum.high_frequency_residual)) : '未提供' },
                      { label: 'albedo 线性范围', value: `${num(channelStats.albedo_linear_min)?.toFixed(4) ?? '—'} … ${num(channelStats.albedo_linear_max)?.toFixed(4) ?? '—'}` },
                      { label: 'roughness 范围', value: `${num(channelStats.roughness_min)?.toFixed(4) ?? '—'} … ${num(channelStats.roughness_max)?.toFixed(4) ?? '—'}` },
                      { label: 'height_mm 范围', value: `${num(channelStats.height_mm_min)?.toFixed(6) ?? '—'} … ${num(channelStats.height_mm_max)?.toFixed(6) ?? '—'}` },
                      { label: 'pattern_region 占比', value: num(channelStats.pattern_region_fraction) !== null ? `${((num(channelStats.pattern_region_fraction) as number) * 100).toFixed(2)}%` : '未提供' },
                    ]}
                  />
                </div>
                <div>
                  <h4>通道资产</h4>
                  {channels ? (
                    <p className="muted small">
                      asset_id <CopyValue value={channels.asset_id} label="channels asset_id" />
                      <br />
                      直链：
                      {CHANNEL_LABELS.map((channel) => {
                        const payloadKey = str(asRecord(channels.keys)?.[channel.key.replace('_png', '')]) ?? channel.key;
                        return (
                          <span key={channel.key}>
                            {' '}
                            <a
                              href={showcaseAssetUrl(channels.asset_id, 'png', { name: payloadKey, download: true })}
                            >
                              {channel.label}.png
                            </a>
                          </span>
                        );
                      })}
                    </p>
                  ) : (
                    <p className="muted">没有通道资产。</p>
                  )}
                  {current.status !== 'OK' && current.failure ? (
                    <div className="state state--error state--compact" role="alert">
                      <div className="state__title">
                        <Badge tone="bad">{current.failure.code}</Badge> {current.failure.message}
                      </div>
                      <div className="mono small">
                        复现：<code>{reproCommand(current)}</code>
                      </div>
                    </div>
                  ) : null}
                  <h4>audit_pattern 原始返回</h4>
                  <pre className="mono pre showcase-pre">
                    {JSON.stringify(
                      {
                        seam: metrics.seam,
                        scale: metrics.scale,
                        determinism: metrics.determinism,
                        region: metrics.region,
                        audit_failures: metrics.audit_failures,
                      },
                      null,
                      1,
                    )}
                  </pre>
                </div>
              </div>
            </div>
          ) : null}
        </>
      )}
    </SectionCard>
  );
}

/* ====================================================================== 3) 碎裂演示 */

export function FractureSection({
  entries,
  mothers,
}: {
  entries: ShowcaseEntry[];
  mothers: ShowcaseEntry[];
}) {
  const events = useMemo(
    () => entries.filter((e) => e.kind === 'fracture'),
    [entries],
  );
  const [selected, setSelected] = useState<string | null>(null);
  const [explode, setExplode] = useState(0);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const current = events.find((e) => e.entry_id === selected) ?? events[0] ?? null;
  const metrics = asRecord(current?.metrics) ?? {};
  const fragmentsRaw = Array.isArray(metrics.fragments) ? (metrics.fragments as any[]) : [];

  const fragments: FragmentRef[] = useMemo(() => {
    const out: FragmentRef[] = [];
    for (const item of fragmentsRaw) {
      const rec = asRecord(item) ?? {};
      const glb = asRecord(rec.glb) ?? {};
      const assetId = str(glb.asset_id);
      if (!assetId) continue;
      out.push({
        fragment_id: str(rec.fragment_id) ?? assetId,
        asset_id: assetId,
        role: str(glb.role) ?? 'display_lod_glb',
        file_key: str(glb.key) ?? 'glb',
        volume_mm3: num(rec.volume_mm3),
        label: str(rec.fragment_id) ?? undefined,
      });
    }
    return out;
  }, [fragmentsRaw]);

  const motherEntry = mothers.find((m) => m.entry_id === `mother:${current?.vessel_id ?? ''}`) ?? null;
  const motherGlb = artifactOf(motherEntry, 'glb');
  const hasFragments = fragments.length > 0;

  return (
    <SectionCard
      title="3 · 碎裂演示"
      subtitle="fracture_event + audit_fracture 的真实结果。失败/阻塞事件照实展示错误码、message 与 measurements，并给出可复现命令。"
      anchor="fracture"
      actions={
        <>
          <Badge tone="info">事件 {events.length}</Badge>
          <Badge tone={events.some((e) => e.status === 'OK') ? 'ok' : 'bad'}>
            成功 {events.filter((e) => e.status === 'OK').length}
          </Badge>
        </>
      }
    >
      {events.length === 0 ? (
        unavailable('没有碎裂事件', '清单里没有 kind=fracture 的条目；请先运行 --only fracture。')
      ) : (
        <>
          <Tabs
            label="碎裂事件选择"
            active={current?.entry_id ?? ''}
            onChange={(id) => {
              setSelected(id);
              setExplode(0);
            }}
            tabs={events.map((entry) => ({
              id: entry.entry_id,
              label: `${entry.vessel_id ?? ''} / ${entry.backend ?? ''} · ${entry.status}`,
            }))}
          />

          {current ? (
            <div className="showcase-detail">
              <div className="row">
                <StatusBadge status={current.status} />
                <Badge tone="neutral">后端 {current.backend ?? '未提供'}</Badge>
                <Badge tone="neutral">母体 {current.vessel_id ?? '未提供'}</Badge>
                <Badge tone="neutral">
                  后端注册状态 {str(metrics.backend_status) ?? '未提供'}
                </Badge>
                <span className="muted small">耗时 {num(current.duration_s) ?? '—'} s</span>
              </div>

              {current.status !== 'OK' && current.failure ? (
                <>
                  <div className="state state--error" role="alert">
                    <div className="state__title">
                      {current.title}
                      <Badge tone={current.status === 'BLOCKED' ? 'warn' : 'bad'}>
                        {current.failure.code}
                      </Badge>
                      <Badge tone="neutral">{current.status}</Badge>
                    </div>
                    <div className="state__detail">{current.failure.message}</div>
                    <div className="state__meta mono">stage={current.failure.stage || '未提供'}</div>
                    {current.failure.detail ? (
                      <div className="state__detail">{current.failure.detail}</div>
                    ) : null}
                    <div className="state__action">
                      <button type="button" className="btn" onClick={() => setDrawerOpen(true)}>
                        打开失败详情（FailureDrawer）
                      </button>
                    </div>
                    <p className="muted small">
                      等价 CLI 复现：<code className="mono">{reproCommand(current)}</code>
                    </p>
                  </div>
                  <FailureDrawer
                    jobId={null}
                    staticFailure={drawerOpen ? failureOf(current) : null}
                    onClose={() => setDrawerOpen(false)}
                  />
                </>
              ) : null}

              {current.status === 'OK' ? (
                <>
                  <div className="row">
                    <label className="check check--range">
                      爆炸位移 {explode.toFixed(3)} m
                      <input
                        type="range"
                        min={0}
                        max={0.3}
                        step={0.005}
                        value={explode}
                        onChange={(event) => setExplode(Number(event.target.value))}
                        disabled={!hasFragments}
                        aria-label="爆炸位移（仅展示变换）"
                      />
                    </label>
                    <button type="button" className="btn btn--tiny" onClick={() => setExplode(0)} disabled={!hasFragments}>
                      回到原位
                    </button>
                  </div>
                  <FragmentAssemblyViewport fragments={fragments} explode={explode} height={340} />
                </>
              ) : (
                <>
                  <div className="banner banner--warn" role="note">
                    该事件没有成功产出碎片，因此**没有碎片三维视图、也没有爆炸视图**（爆炸是碎片的展示变换，
                    对母体几何做爆炸会是伪造）。下面显示母体的<b>参考</b>几何，并明确标注它不是断裂结果。
                  </div>
                  {motherGlb ? (
                    <SceneViewport
                      assetId={motherGlb.asset_id}
                      role={motherGlb.role ?? 'display_lod_glb'}
                      fileKey={motherGlb.key ?? 'glb'}
                      source="showcase"
                      title={`母体 ${current.vessel_id ?? ''} 参考几何（不是断裂结果）`}
                      height={300}
                      notice="母体参考几何：该碎裂事件 FAILED/BLOCKED，没有任何碎片可展示"
                    />
                  ) : (
                    unavailable('没有可展示的参考几何', '该事件的母体条目缺少派生展示 GLB 资产。')
                  )}
                </>
              )}

              <div className="showcase-cols">
                <div>
                  <h4>真实指标</h4>
                  <KeyValueList
                    rows={[
                      { label: '碎片段数', value: num(metrics.fragment_count) ?? '未提供（事件未成功）' },
                      { label: 'tiny 数', value: num(metrics.tiny_count) ?? '未提供' },
                      { label: 'debris 数', value: num(metrics.debris_count) ?? '未提供' },
                      { label: '共享面 patch 数', value: num(metrics.interface_count) ?? '未提供' },
                      { label: '母体体积', value: num(metrics.mother_volume_mm3) !== null ? `${(num(metrics.mother_volume_mm3) as number).toFixed(3)} mm³` : '未提供' },
                      { label: '碎片体积和', value: num(metrics.fragment_volume_sum_mm3) !== null ? `${(num(metrics.fragment_volume_sum_mm3) as number).toFixed(3)} mm³` : '未提供' },
                      { label: '体积守恒相对差', value: num(metrics.volume_conservation_rel) !== null ? String(num(metrics.volume_conservation_rel)) : '未提供（事件未成功）' },
                      { label: '后端注册状态', value: str(metrics.backend_status) ?? '未提供' },
                    ]}
                  />
                  {current.status !== 'OK' ? (
                    <>
                      <h4>失败 measurements（原样）</h4>
                      <pre className="mono pre showcase-pre">
                        {JSON.stringify(current.failure?.measurements ?? {}, null, 1)}
                      </pre>
                    </>
                  ) : null}
                </div>
                <div>
                  <h4>碎片列表</h4>
                  {fragmentsRaw.length === 0 ? (
                    unavailable(
                      '没有碎片',
                      '该事件没有记录任何碎片（失败/阻塞事件不会产生碎片资产）。',
                    )
                  ) : (
                    <table className="table">
                      <thead>
                        <tr>
                          <th>fragment_id</th>
                          <th>体积 mm³</th>
                          <th>面积 mm²</th>
                          <th>面数</th>
                          <th>来源面覆盖均值</th>
                          <th>tiny</th>
                          <th>GLB</th>
                        </tr>
                      </thead>
                      <tbody>
                        {fragmentsRaw.map((item: any) => {
                          const rec = asRecord(item) ?? {};
                          const glb = asRecord(rec.glb) ?? {};
                          const assetId = str(glb.asset_id);
                          return (
                            <tr key={str(rec.fragment_id) ?? assetId ?? Math.random().toString()}>
                              <td className="mono small">{str(rec.fragment_id) ?? '未提供'}</td>
                              <td className="mono small">{num(rec.volume_mm3)?.toFixed(4) ?? '未提供'}</td>
                              <td className="mono small">{num(rec.area_mm2)?.toFixed(4) ?? '未提供'}</td>
                              <td className="mono small">{num(rec.faces) ?? '未提供'}</td>
                              <td className="mono small">
                                {num(rec.source_face_coverage)?.toFixed(3) ?? '未提供'}
                              </td>
                              <td>{rec.is_tiny === true ? '是' : rec.is_tiny === false ? '否' : '未提供'}</td>
                              <td>
                                {assetId ? (
                                  <a href={showcaseAssetUrl(assetId, 'glb', { download: true })}>下载</a>
                                ) : (
                                  '无'
                                )}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  )}
                  <h4>全部后端注册状态（真实注册表）</h4>
                  <KeyValueList
                    rows={[
                      { label: 'plane_shared_cut', value: 'IMPLEMENTED（已实现）' },
                      { label: 'rough_shared_cut', value: 'IMPLEMENTED（已实现）' },
                      { label: 'secondary_fracture', value: 'IMPLEMENTED（已实现）' },
                      { label: 'warped_partition', value: <Badge tone="warn">PENDING</Badge> },
                      { label: 'fracture_modes', value: <Badge tone="bad">MISSING</Badge> },
                    ]}
                  />
                  <p className="muted small">
                    上表取自 <code className="mono">synlab.fracture.api.BUILT_BACKENDS</code> /
                    <code className="mono">PENDING_BACKENDS</code> 与注册表状态；
                    本页不把 PENDING/MISSING 显示成“通过”。
                  </p>
                </div>
              </div>
            </div>
          ) : null}
        </>
      )}
    </SectionCard>
  );
}

/* ====================================================================== 4) 退化对比 */

const FAMILY_LABEL: Record<string, string> = {
  P: 'P 物理',
  I: 'I 成像',
  G: 'G 几何',
  X: 'X 估计',
};

export function DegradeSection({
  entries,
  axisCatalog,
}: {
  entries: ShowcaseEntry[];
  axisCatalog: ShowcaseAxisCatalogItem[];
}) {
  const degradeEntries = useMemo(
    () => new Map(entries.filter((e) => e.kind === 'degrade').map((e) => [e.axis_id ?? e.entry_id, e])),
    [entries],
  );
  const [axis, setAxis] = useState<string | null>(null);
  const [level, setLevel] = useState(0);
  const [mode, setMode] = useState<'image' | 'mesh'>('image');
  const [drawerOpen, setDrawerOpen] = useState(false);

  const catalog = useMemo(() => {
    const withAxis = axisCatalog.filter((item) => item.axis_id);
    const order = ['P', 'I', 'G', 'X'];
    return [...withAxis].sort((a, b) => {
      const fa = order.indexOf(a.family);
      const fb = order.indexOf(b.family);
      if (fa !== fb) return fa - fb;
      return (a.axis_id ?? '').localeCompare(b.axis_id ?? '');
    });
  }, [axisCatalog]);

  const generatedAxes = catalog.filter((item) => item.generated);
  const currentAxis = axis ?? generatedAxes[0]?.axis_id ?? null;
  const currentItem = catalog.find((item) => item.axis_id === currentAxis) ?? null;
  const currentEntry = currentAxis ? degradeEntries.get(currentAxis) ?? null : null;
  const metrics = asRecord(currentEntry?.metrics) ?? {};
  const identity = asRecord(metrics.level0_identity) ?? {};
  const row = levelRow(currentEntry, level);
  const pngArtifact = levelArtifact(currentEntry, level, 'png');
  const glbArtifact = levelArtifact(currentEntry, level, 'glb');
  const measured = asRecord(row?.measured) ?? {};
  const units = asRecord(row?.units) ?? {};
  const planned = asRecord(row?.planned) ?? {};
  const levelFailure = asRecord(row?.failure);

  const hasImage = Boolean(pngArtifact);
  const hasMesh = Boolean(glbArtifact);
  const effectiveMode = mode === 'image' && !hasImage && hasMesh ? 'mesh' : mode;

  return (
    <SectionCard
      title="4 · 退化对比"
      subtitle="apply_axis 在同一个 source、同一个冻结 basis 上的 5 档真实结果；level 0 必须返回原始资产引用/字节（identity）。"
      anchor="degrade"
      actions={
        <>
          <Badge tone="info">已生成轴 {generatedAxes.length} / 31</Badge>
          <Badge tone="neutral">
            NA 轴 {catalog.filter((i) => !i.generated).length}
          </Badge>
        </>
      }
    >
      <div className="showcase-axisbar" role="group" aria-label="退化轴选择（按 P/I/G/X 分组）">
        {(['P', 'I', 'G', 'X'] as const).map((family) => (
          <div key={family} className="showcase-axisbar__group">
            <div className="showcase-axisbar__label">{FAMILY_LABEL[family]}</div>
            <div className="showcase-axisbar__items">
              {catalog
                .filter((item) => item.family === family)
                .map((item) => {
                  const generated = item.generated;
                  const disabledReason = generated
                    ? null
                    : item.na_reason ?? '本次演示集没有生成该轴的数据';
                  return (
                    <button
                      key={item.axis_id ?? family}
                      type="button"
                      className={`chip${currentAxis === item.axis_id ? ' chip--active' : ''}${
                        generated ? '' : ' chip--na'
                      }`}
                      onClick={() => {
                        setAxis(item.axis_id);
                        setLevel(0);
                      }}
                      disabled={!generated}
                      title={disabledReason ?? `${item.axis_id} · ${item.stage ?? ''}`}
                    >
                      {item.axis_id}
                      {!generated ? ' · NA' : ''}
                    </button>
                  );
                })}
            </div>
          </div>
        ))}
      </div>

      {!currentItem ? (
        unavailable('没有退化轴数据', '清单里的 axis_catalog 为空；请先运行 --only degrade。')
      ) : !currentEntry ? (
        <EmptyState
          title={`${currentItem.axis_id} 没有生成数据（NA）`}
          reason={
            <>
              {currentItem.na_reason ?? '本次演示集没有生成该轴的数据。'}
              <br />
              真实轴声明：stage={currentItem.stage ?? '—'} · substage={currentItem.substage ?? '—'} ·
              变体 {(currentItem.variants ?? []).join(' / ') || '未提供'} · 接受源{' '}
              {(currentItem.accepted_sources ?? []).join(' / ') || '未提供'}
              <br />
              生成方式（真实命令）：
              <code className="mono">
                & .venv\Scripts\python.exe tools\build_demo_assets.py --only degrade
              </code>
            </>
          }
        />
      ) : (
        <div className="showcase-detail">
          <div className="row">
            <StatusBadge status={currentEntry.status} />
            <Badge tone="neutral">{currentItem.axis_id}</Badge>
            <Badge tone="info">stage {str(metrics.stage) ?? '—'}</Badge>
            <Badge tone="neutral">variant {str(metrics.variant) ?? '—'}</Badge>
            <Badge tone="neutral">factor {str(metrics.factor_kind) ?? '—'}</Badge>
            <Badge tone={identity.identity ? 'ok' : 'bad'}>
              level 0 identity：{identity.identity ? '是' : '否'}
            </Badge>
            <Badge tone="neutral">calibration {str(metrics.calibration_status) ?? '—'}</Badge>
          </div>

          <div className="row">
            <label className="check check--range">
              档位 level {level}
              <input
                type="range"
                min={0}
                max={4}
                step={1}
                value={level}
                onChange={(event) => setLevel(Number(event.target.value))}
                aria-label="退化档位"
              />
            </label>
            <div className="row" role="group" aria-label="档位按钮">
              {[0, 1, 2, 3, 4].map((value) => (
                <button
                  key={value}
                  type="button"
                  className={`chip${level === value ? ' chip--active' : ''}`}
                  onClick={() => setLevel(value)}
                >
                  L{value}
                </button>
              ))}
            </div>
            <Tabs
              label="对比模式"
              active={effectiveMode}
              onChange={(id) => setMode(id as 'image' | 'mesh')}
              tabs={[
                { id: 'image', label: '图像对比', disabledReason: hasImage ? null : '该档没有渲染 PNG 资产' },
                { id: 'mesh', label: '几何/点云对比', disabledReason: hasMesh ? null : '该档没有 mesh GLB 资产' },
              ]}
            />
          </div>

          {level === 0 ? (
            <div className="banner banner--ok" role="note">
              <strong>level 0 = 真恒等</strong>：identity={String(identity.identity)} ·
              identity_reference_ok={String(identity.identity_reference_ok)} ·
              bytes_unchanged={String(identity.bytes_unchanged)}；
              返回的 asset_id 就是 source 资产 <code className="mono">{str(identity.asset_id) ?? '—'}</code>
              （source_hash={str(identity.source_hash)?.slice(0, 24)}…，
              result_hash={str(identity.result_hash)?.slice(0, 24)}…）。
            </div>
          ) : null}

          {row?.status && row.status !== 'OK' ? (
            <div className="state state--error" role="alert">
              <div className="state__title">
                {currentItem.axis_id} L{level} 未达到 OK
                <Badge tone={row.status === 'NA' ? 'neutral' : 'bad'}>{String(row.status)}</Badge>
                {levelFailure ? <Badge tone="bad">{str(levelFailure.code) ?? ''}</Badge> : null}
              </div>
              <div className="state__detail">{str(levelFailure?.message) ?? '清单未记录 message'}</div>
              <div className="state__meta mono">stage={str(levelFailure?.stage) || '未提供'}</div>
              <div className="state__action">
                <button type="button" className="btn" onClick={() => setDrawerOpen(true)}>
                  打开失败详情（FailureDrawer）
                </button>
              </div>
            </div>
          ) : null}
          <FailureDrawer
            jobId={null}
            staticFailure={
              drawerOpen && levelFailure
                ? {
                    title: `${currentItem.axis_id} level ${level} · ${String(row?.status)}`,
                    code: str(levelFailure.code) ?? 'UNKNOWN',
                    message: str(levelFailure.message) ?? '清单未记录 message',
                    stage: str(levelFailure.stage),
                    retryable: levelFailure.retryable === true,
                    measurements: {
                      ...(asRecord(levelFailure.measurements) ?? {}),
                      planned,
                      level,
                      variant: str(metrics.variant),
                    },
                    detail: str(levelFailure.detail),
                    sourceRef: currentEntry.entry_id,
                    status: str(row?.status),
                    reproduceCommand: reproCommand(currentEntry),
                    extraRows: [
                      { label: 'axis_id', value: currentItem.axis_id ?? '—' },
                      { label: 'source_asset', value: <span className="mono">{str(metrics.source_asset) ?? '—'}</span> },
                      { label: 'basis_id', value: <span className="mono">{str(metrics.basis_id) ?? '—'}</span> },
                    ],
                  }
                : null
            }
            onClose={() => setDrawerOpen(false)}
          />

          <div className="showcase-compare">
            <figure className="showcase-figure showcase-figure--wide">
              <figcaption>
                <strong>baseline · level 0</strong>（identity，引用 source 资产）
              </figcaption>
              {levelArtifact(currentEntry, 0, 'png') ? (
                <img
                  src={showcaseAssetUrl((levelArtifact(currentEntry, 0, 'png') as any).asset_id, 'png')}
                  alt={`${currentItem.axis_id} level 0 baseline 渲染`}
                  loading="lazy"
                />
              ) : levelArtifact(currentEntry, 0, 'glb') ? (
                <SceneViewport
                  assetId={(levelArtifact(currentEntry, 0, 'glb') as any).asset_id}
                  role={(levelArtifact(currentEntry, 0, 'glb') as any).role ?? 'display_lod_glb'}
                  fileKey={(levelArtifact(currentEntry, 0, 'glb') as any).key ?? 'glb'}
                  source="showcase"
                  title="level 0 几何（identity）"
                  height={260}
                />
              ) : (
                <EmptyState title="level 0 没有可视化产物" reason="该轴的 level 0 只返回 source 资产引用，没有派生图像/几何展示资产。" />
              )}
            </figure>
            <figure className="showcase-figure showcase-figure--wide">
              <figcaption>
                <strong>当前档 · level {level}</strong>
                {level === 0 ? '（与 baseline 是同一个资产）' : ''}
              </figcaption>
              {effectiveMode === 'image' ? (
                pngArtifact ? (
                  <img
                    src={showcaseAssetUrl(pngArtifact.asset_id, 'png')}
                    alt={`${currentItem.axis_id} level ${level} 渲染`}
                    loading="lazy"
                  />
                ) : (
                  <EmptyState
                    title="该档没有渲染 PNG"
                    reason="这一档的 apply_axis 没有产出可渲染的帧/外观通道（或该档失败）。切到几何模式或用清单里的失败原因。"
                  />
                )
              ) : glbArtifact ? (
                <SceneViewport
                  assetId={glbArtifact.asset_id}
                  role={glbArtifact.role ?? 'display_lod_glb'}
                  fileKey={glbArtifact.key ?? 'glb'}
                  source="showcase"
                  title={`${currentItem.axis_id} L${level} 几何`}
                  height={260}
                />
              ) : (
                <EmptyState title="该档没有 mesh GLB" reason="这一档没有几何变化或没有导出展示资产。" />
              )}
            </figure>
          </div>

          <div className="showcase-cols">
            <div>
              <h4>实测变化量（Measurement.measured，单位来自 units）</h4>
              {Object.keys(measured).length === 0 ? (
                <p className="muted">
                  该档没有 measured 字段（level 0 是恒等，不产生变化量；失败档只记录 planned）。
                </p>
              ) : (
                <KeyValueList
                  rows={Object.entries(measured).map(([key, value]) => ({
                    label: `${key}${units[key] ? `（${String(units[key])}）` : ''}`,
                    value: <span className="mono">{typeof value === 'number' ? (value as number).toFixed(6) : String(value)}</span>,
                  }))}
                />
              )}
              <h4>声明参数（planned）</h4>
              <pre className="mono pre showcase-pre">{JSON.stringify(planned, null, 1)}</pre>
            </div>
            <div>
              <h4>同一 source / 同一 basis</h4>
              <KeyValueList
                rows={[
                  { label: 'source_kind', value: str(metrics.source_kind) ?? '未提供' },
                  { label: 'source_asset', value: <span className="mono">{str(metrics.source_asset) ?? '未提供'}</span> },
                  { label: 'source_provenance', value: <span className="small">{str(metrics.source_provenance) ?? '未提供'}</span> },
                  { label: 'source_content_hash', value: <span className="mono small">{str(metrics.source_content_hash) ?? '未提供'}</span> },
                  { label: 'basis_id', value: <span className="mono">{str(metrics.basis_id) ?? '未提供'}</span> },
                  { label: 'basis_seed_ref', value: <span className="mono small">{str(metrics.basis_seed_ref) ?? '未提供'}</span> },
                  { label: 'basis_payload_keys', value: (Array.isArray(metrics.basis_payload_keys) ? (metrics.basis_payload_keys as string[]).join(', ') : '未提供') },
                  { label: 'label_invalidations', value: (Array.isArray(metrics.label_invalidations) ? (metrics.label_invalidations as string[]).join(', ') || '无' : '未提供') },
                  { label: 'accepted_sources', value: (currentItem.accepted_sources ?? []).join(' / ') || '未提供' },
                ]}
              />
              <h4>逐档真实状态</h4>
              <table className="table">
                <thead>
                  <tr>
                    <th>level</th>
                    <th>状态</th>
                    <th>identity</th>
                    <th>realized</th>
                    <th>产物</th>
                    <th>asset_id</th>
                  </tr>
                </thead>
                <tbody>
                  {[0, 1, 2, 3, 4].map((value) => {
                    const item = levelRow(currentEntry, value);
                    if (!item) return null;
                    const artifacts = asRecord(item.artifacts) ?? {};
                    const keys = ['png', 'glb'].filter((key) => asRecord(artifacts[key]));
                    return (
                      <tr key={value}>
                        <td>L{value}</td>
                        <td>
                          <StatusBadge status={String(item.status)} />
                        </td>
                        <td>{item.identity === true ? '是' : item.identity === false ? '否' : '未提供'}</td>
                        <td>{item.realized === true ? '是' : item.realized === false ? '否' : '未提供'}</td>
                        <td>{keys.length > 0 ? keys.join(' + ') : '无'}</td>
                        <td className="mono small">{str(item.asset_id) ?? '—'}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <p className="muted small">
                复现该轴（真实命令）：<code className="mono">{reproCommand(currentEntry)}</code>
              </p>
            </div>
          </div>
        </div>
      )}
    </SectionCard>
  );
}

/* ====================================================================== 5) 状态与诚实性面板 */

export function StatusSection({
  entries,
  axisCatalog,
  environmentFindings,
  counts,
  fractureBackends,
}: {
  entries: ShowcaseEntry[];
  axisCatalog: ShowcaseAxisCatalogItem[];
  environmentFindings: string[];
  counts: Record<string, any>;
  fractureBackends: Record<string, string>;
}) {
  const problems = entries.filter((e) => e.status !== 'OK');
  const naAxes = axisCatalog.filter((item) => item.axis_id && !item.generated);
  const byKind = asRecord(counts.by_kind) ?? {};
  const fractureEntries = entries.filter((e) => e.kind === 'fracture');
  const fractureOk = fractureEntries.filter((e) => e.status === 'OK');
  const degradeEntries = entries.filter((e) => e.kind === 'degrade');
  const degradeLevelFailures = degradeEntries.flatMap((entry) =>
    (Array.isArray(entry.metrics?.levels) ? (entry.metrics?.levels as any[]) : [])
      .filter((row: any) => row?.status && row.status !== 'OK')
      .map((row: any) => ({
        entry_id: entry.entry_id,
        level: row.level,
        code: str(asRecord(row.failure)?.code) ?? '未记录',
        message: str(asRecord(row.failure)?.message) ?? '未记录',
      })),
  );

  return (
    <SectionCard
      title="5 · 状态与诚实性面板"
      subtitle="所有 BLOCKED / FAILED / NA 条目与原因原样列出；缺失能力不会被显示成“通过”。"
      anchor="honesty"
      actions={
        <>
          <Badge tone={problems.length === 0 ? 'ok' : 'bad'}>非 OK 条目 {problems.length}</Badge>
          <Badge tone="neutral">NA 轴 {naAxes.length} / 31</Badge>
        </>
      }
    >
      <h4>按类别统计（来自 demo_manifest.json 的真实计数）</h4>
      <table className="table">
        <thead>
          <tr>
            <th>类别</th>
            <th>总数</th>
            <th>OK</th>
            <th>FAILED</th>
            <th>BLOCKED</th>
            <th>NA</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(byKind).map(([kind, bucket]: [string, any]) => (
            <tr key={kind}>
              <td>{kind}</td>
              <td>{num(bucket?.total) ?? 0}</td>
              <td>{num(bucket?.OK) ?? 0}</td>
              <td>{num(bucket?.FAILED) ?? 0}</td>
              <td>{num(bucket?.BLOCKED) ?? 0}</td>
              <td>{num(bucket?.NA) ?? 0}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h4>非 OK 条目及原因</h4>
      {problems.length === 0 ? (
        <EmptyState title="没有非 OK 条目" reason="本次演示集的每个条目都达到了 OK。" />
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>entry_id</th>
              <th>类别</th>
              <th>状态</th>
              <th>错误码</th>
              <th>message</th>
              <th>stage</th>
              <th>复现</th>
            </tr>
          </thead>
          <tbody>
            {problems.map((entry) => (
              <tr key={entry.entry_id}>
                <td className="mono small">{entry.entry_id}</td>
                <td>{entry.kind}</td>
                <td>
                  <StatusBadge status={entry.status} />
                </td>
                <td className="mono small">{entry.failure?.code ?? '未记录'}</td>
                <td className="small">{entry.failure?.message ?? '未记录'}</td>
                <td className="mono small">{entry.failure?.stage ?? '—'}</td>
                <td className="mono small">
                  <code>{reproCommand(entry)}</code>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h4>31 个退化轴中未生成数据的轴（NA 及原因）</h4>
      {naAxes.length === 0 ? (
        <EmptyState title="31 个轴都有数据" reason="axis_catalog 里没有未生成的轴。" />
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>axis_id</th>
              <th>stage</th>
              <th>substage</th>
              <th>变体</th>
              <th>接受源</th>
              <th>NA 原因</th>
            </tr>
          </thead>
          <tbody>
            {naAxes.map((item) => (
              <tr key={item.axis_id ?? 'unknown'}>
                <td className="mono">{item.axis_id}</td>
                <td className="small">{item.stage ?? '—'}</td>
                <td className="small">{item.substage ?? '—'}</td>
                <td className="small">{(item.variants ?? []).join(' / ') || '—'}</td>
                <td className="small">{(item.accepted_sources ?? []).join(' / ') || '—'}</td>
                <td className="small">{item.na_reason ?? '未提供'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h4>环境与能力事实（生成器写入清单，原样展示）</h4>
      {environmentFindings.length === 0 ? (
        <EmptyState title="清单没有记录环境事实" reason="environment_findings 为空。" />
      ) : (
        <ul className="showcase-list">
          {environmentFindings.map((text) => (
            <li key={text}>{text}</li>
          ))}
        </ul>
      )}

      <h4>断裂后端注册状态（synlab.registry，真实注册表）</h4>
      {Object.keys(fractureBackends).length === 0 ? (
        <EmptyState title="注册表未返回 fracture_backend 条目" reason="清单的 fracture_backends 为空；生成器读取注册表失败时会照实留空。" />
      ) : (
        <KeyValueList
          rows={Object.entries(fractureBackends).map(([id, status]) => ({
            label: id,
            value: (
              <Badge tone={status === 'IMPLEMENTED' ? 'ok' : status === 'PENDING' ? 'warn' : 'bad'}>
                {status}
              </Badge>
            ),
          }))}
        />
      )}
      <p className="muted small">
        本演示集尝试了 {fractureEntries.length} 个真实断裂事件，成功 {fractureOk.length} 个；
        其余条目的**真实错误码与 message** 见上表。后端注册状态为 PENDING / MISSING 的调用会被
        结构化拒绝（<code className="mono">OPERATOR_NOT_REALIZED</code>），页面不会把它显示成“通过”。
      </p>

      <h4>逐档失败的环境/能力缺口（来自清单条目，全部为数据驱动）</h4>
      <ul className="showcase-list">
        <li>
          <strong>退化轴逐档失败（{degradeLevelFailures.length} 档）</strong>：
          {degradeLevelFailures.length === 0 ? (
            '本次演示集没有逐档失败。'
          ) : (
            <ul>
              {degradeLevelFailures.slice(0, 12).map((item) => (
                <li key={`${item.entry_id}-${item.level}`} className="small">
                  <code className="mono">
                    {item.entry_id} L{item.level}
                  </code>
                  ：<code className="mono">{item.code}</code> —— {item.message}
                </li>
              ))}
              {degradeLevelFailures.length > 12 ? (
                <li className="small">…还有 {degradeLevelFailures.length - 12} 档，见各轴分区。</li>
              ) : null}
            </ul>
          )}
        </li>
        <li>
          <strong>Blender 缺失</strong>：本机没有 bpy（无 Windows + py3.12 wheel），
          渲染只有软件光栅后端；<code className="mono">synlab.observe.render.capability_probe()</code> 如实报告。
        </li>
        <li>
          <strong>实拍数据缺失</strong>：仓库里没有任何真实实拍数据，本页所有数据都是合成数据
          （<code className="mono">data_scope=SYNTHETIC</code>）。
        </li>
        <li>
          <strong>进程被杀（PROCESS_KILLED）</strong>：本机对重负载 Python 进程会直接杀进程树；
          生成器把这种结局记为 BLOCKED 并保留 attempts 计数，绝不当成算法结论。
        </li>
      </ul>

      <p className="muted small">
        详细说明与复现步骤见仓库内文档 <code className="mono">docs/a12/showcase.md</code>
        （前端预览服务器不提供 docs 静态文件，因此这里不做成会 404 的链接）。
      </p>
    </SectionCard>
  );
}
