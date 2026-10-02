/**
 * U13 `/synlab/showcase` —— 合成数据可视化展示界面。
 *
 * 数据来源只有两条只读路由：`GET /showcase/manifest` 与
 * `GET /showcase/asset/{asset_id}/{key}`（`synlab/api/routers/showcase.py`），
 * 其内容是 `tools/build_demo_assets.py` 用**真实模块 API** 生成的演示数据集
 * （`data/a12_demo/demo_manifest.json`）。
 *
 * 诚实性：这里不生成任何数字。缺失就是缺失（空状态 + 原因），失败就是失败
 * （真实错误码 + message + measurements + 复现命令）。
 */

import { useMemo, useState } from 'react';

import { getShowcaseManifest, asRecord } from '../api/showcase';
import { useResource } from '../api/hooks';
import {
  Badge,
  CopyValue,
  EmptyState,
  ErrorState,
  KeyValueList,
  LoadingState,
  PageHeader,
  SectionCard,
} from '../components/states';
import {
  DegradeSection,
  FractureSection,
  MothersSection,
  PatternsSection,
  StatusSection,
  formatIso,
} from '../components/showcase/sections';

export function ShowcasePage() {
  const resource = useResource((signal) => getShowcaseManifest(signal), []);
  const data = resource.data;
  const counts = asRecord(data?.counts) ?? {};
  const total = asRecord(counts.total) ?? {};
  const byKind = asRecord(counts.by_kind) ?? {};
  const entries = useMemo(() => data?.entries ?? [], [data]);
  const axisCatalog = data?.axis_catalog ?? [];
  const [showRaw, setShowRaw] = useState(false);

  const nonOk = entries.filter((entry) => entry.status !== 'OK');
  const genAt = data?.generated_at ?? null;
  const runs = data?.runs ?? [];
  const lastRun = runs.length > 0 ? runs[runs.length - 1] : null;

  return (
    <div className="page page--showcase">
      <PageHeader
        title="合成数据展示"
        plan="U13"
        summary={
          <>
            母体 / 纹样 / 碎裂 / 退化（31 轴）四个分区的真实合成结果。全部数字来自{' '}
            <code className="mono">tools/build_demo_assets.py</code> 调用真实模块 API 的产出，
            经只读路由 <code className="mono">GET /api/synlab/showcase/manifest</code> 与{' '}
            <code className="mono">GET /api/synlab/showcase/asset/&#123;asset_id&#125;/&#123;key&#125;</code>{' '}
            读取；失败与缺失能力一律照实显示，不隐藏、不改写成“通过”。
          </>
        }
        actions={
          <button type="button" className="btn" onClick={resource.reload} disabled={resource.refreshing}>
            {resource.refreshing ? '刷新中…' : '刷新'}
          </button>
        }
      />

      {/* ------------------------------------------------------------ 顶部摘要 */}
      <SectionCard
        title="数据摘要"
        subtitle="来自 demo_manifest.json 的真实计数与生成记录"
        anchor="summary"
        actions={
          <>
            <Badge tone={data?.status === 'OK' ? 'ok' : 'warn'}>
              manifest {data?.status ?? '…'}
            </Badge>
            {resource.refreshing ? <Badge tone="info">后台刷新中</Badge> : null}
          </>
        }
      >
        {resource.status === 'loading' && !data ? (
          <LoadingState label="正在读取展示清单（GET /showcase/manifest）…" />
        ) : null}
        {resource.status === 'error' ? <ErrorState error={resource.error} onRetry={resource.reload} /> : null}

        {data && data.status === 'NOT_RUN' ? (
          <EmptyState
            title="尚未生成演示数据集"
            reason={
              <>
                {data.empty_reason ?? '本工作区没有 demo_manifest.json。'}
                <br />
                生成命令（真实可复现）：
                <br />
                <code className="mono">{data.generator_command}</code>
              </>
            }
            action={
              <span className="copy">
                <CopyValue value={data.generator_command} label="生成命令" />
              </span>
            }
          />
        ) : null}

        {data && data.status === 'OK' ? (
          <>
            <KeyValueList
              rows={[
                { label: '条目总数', value: num0(counts.entries) },
                { label: 'OK / FAILED / BLOCKED / NA', value: `${num0(total.OK)} / ${num0(total.FAILED)} / ${num0(total.BLOCKED)} / ${num0(total.NA)}` },
                { label: '母体条数', value: kindCount(byKind, 'mother') },
                { label: '纹样条数', value: kindCount(byKind, 'pattern') },
                { label: '碎裂事件数（成功）', value: `${kindCount(byKind, 'fracture')}（${num0((asRecord(byKind.fracture) ?? {}).OK)}）` },
                { label: '退化轴条数（成功）', value: `${kindCount(byKind, 'degrade')}（${num0((asRecord(byKind.degrade) ?? {}).OK)}）` },
                { label: '退化源条数', value: kindCount(byKind, 'degrade_source') },
                { label: '真实失败数（FAILED + BLOCKED）', value: <Badge tone={nonOk.length > 0 ? 'bad' : 'ok'}>{num0(total.FAILED) + num0(total.BLOCKED)}</Badge> },
                { label: '生成时间', value: formatIso(genAt) },
                { label: 'manifest 路径', value: <span className="mono">{data.manifest_path}</span> },
                { label: '演示资产库', value: <span className="mono">{data.store_path}</span> },
                { label: 'master_seed / lineage', value: <span className="mono">{data.master_seed ?? '—'} / {data.lineage_id ?? '—'}</span> },
                { label: '只读', value: data.read_only ? '是（本页不会写任何资产）' : '否' },
                { label: '最近一次生成运行', value: lastRun ? `${lastRun.command ?? '—'}（单元 ${lastRun.units_executed ?? '—'}，${lastRun.duration_s ?? '—'} s）` : '清单里没有 runs 记录' },
              ]}
            />
            <div className="row">
              <span className="muted small">生成命令（可复制）：</span>
              <CopyValue value={data.generator_command} label="生成命令" />
            </div>
            <details className="state__details" open={showRaw} onToggle={(event) => setShowRaw((event.target as HTMLDetailsElement).open)}>
              <summary>生成器运行记录（runs，真实退出码与计数）</summary>
              <pre className="mono pre showcase-pre">{JSON.stringify(runs, null, 1)}</pre>
            </details>
          </>
        ) : null}
      </SectionCard>

      {data && data.status === 'OK' ? (
        <>
          <MothersSection entries={entries} />
          <PatternsSection entries={entries} />
          <FractureSection entries={entries} mothers={entries.filter((e) => e.kind === 'mother')} />
          <DegradeSection entries={entries} axisCatalog={axisCatalog} />
          <StatusSection
            entries={entries}
            axisCatalog={axisCatalog}
            environmentFindings={data.environment_findings ?? []}
            counts={counts}
            fractureBackends={(data.fracture_backends ?? {}) as Record<string, string>}
          />
        </>
      ) : null}
    </div>
  );
}

function num0(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function kindCount(byKind: Record<string, any>, kind: string): number {
  const bucket = asRecord(byKind[kind]);
  return bucket ? num0(bucket.total) : 0;
}

export default ShowcasePage;
