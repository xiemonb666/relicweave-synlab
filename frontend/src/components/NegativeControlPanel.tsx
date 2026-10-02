/**
 * 纯背景 / 轮廓负控视图（计划 §25.1 的 A05 花纹族审计与 A32 泄漏负控相关）。
 *
 * 行为：
 * 1. 真实扫描本工作区可见的资产（`GET /assets`，含 `meta` / `files` / `label`）；
 * 2. 按关键词判定是否存在“silhouette-only / 纯背景 / 仅掩码 / 无目标”的负控资产：
 *    `silhouette`、`background_only`、`bg_only`、`mask_only`、`no_object`、`negative_control`、
 *    `silhouette_only`；
 * 3. 命中就显示它的真实图像字节或 meta；**没命中就显示 NOT_RUN 并写明扫描范围与谓词**——
 *    绝不用示意图充当负控。
 */

import { useEffect, useMemo, useState } from 'react';

import { listAssets } from '../api/endpoints';
import { useResource } from '../api/hooks';
import type { AssetRecord } from '../api/types';
import { blobUrlFor, isPng, loadAssetBytes, pngSize } from '../lib/assetData';
import { pretty } from '../lib/format';
import { Badge, BlockedState, ErrorState, KeyValueList, LoadingState, SectionCard } from './states';

const KEYWORDS = [
  'silhouette',
  'silhouette_only',
  'background_only',
  'bg_only',
  'mask_only',
  'no_object',
  'negative_control',
];

function haystack(record: AssetRecord): string {
  const meta = record.meta ?? {};
  const parts: string[] = [
    JSON.stringify(meta),
    Object.keys(record.files ?? {}).join(' '),
    String(meta.label ?? ''),
    String(meta.variant ?? ''),
    String(meta.provenance ?? ''),
  ];
  return parts.join(' ').toLowerCase();
}

export function NegativeControlPanel() {
  const assets = useResource((signal) => listAssets({ limit: 200, with_total: true }, signal), []);
  const [imageUrl, setImageUrl] = useState<{ url: string; size: string } | null>(null);
  const [imageError, setImageError] = useState<unknown>(null);

  const matches = useMemo(() => {
    const items = assets.data?.items ?? [];
    return items.filter((record) => KEYWORDS.some((keyword) => haystack(record).includes(keyword)));
  }, [assets.data]);

  const scanned = assets.data?.items.length ?? 0;
  const roles = useMemo(() => {
    const counts = new Map<string, number>();
    for (const record of assets.data?.items ?? []) counts.set(record.role, (counts.get(record.role) ?? 0) + 1);
    return [...counts.entries()].sort((a, b) => b[1] - a[1]);
  }, [assets.data]);

  const first = matches[0] ?? null;

  useEffect(() => {
    let created: string | null = null;
    let cancelled = false;
    const run = async () => {
      if (!first) {
        setImageUrl(null);
        return;
      }
      const key = Object.keys(first.files ?? {}).find((name) => /png$/.test(name));
      if (!key) {
        setImageUrl(null);
        return;
      }
      try {
        const loaded = await loadAssetBytes(first.asset_id, first.role, key);
        if (cancelled) return;
        if (!isPng(loaded.bytes)) {
          setImageError(new Error(`${key} 不是 PNG 字节（签名不匹配）`));
          return;
        }
        const size = pngSize(loaded.bytes);
        const url = blobUrlFor(loaded.bytes, 'image/png');
        created = url;
        setImageUrl({ url, size: size ? `${size.width} × ${size.height}` : '未提供' });
        setImageError(null);
      } catch (error) {
        if (!cancelled) setImageError(error);
      }
    };
    void run();
    return () => {
      cancelled = true;
      if (created) URL.revokeObjectURL(created);
    };
  }, [first]);

  return (
    <SectionCard
      title="纯背景 / 轮廓负控视图（A05 / A32 相关）"
      subtitle="GET /assets（真实扫描 meta/label/files 关键词）"
      actions={<Badge tone={matches.length > 0 ? 'ok' : 'warn'}>{matches.length > 0 ? `命中 ${matches.length} 个` : 'NOT_RUN'}</Badge>}
    >
      {assets.status === 'loading' ? <LoadingState label="扫描资产…" /> : null}
      {assets.status === 'error' ? <ErrorState error={assets.error} onRetry={assets.reload} /> : null}

      {assets.data ? (
        <p className="muted small">
          真实扫描 {scanned} 个可见资产（后端 total={assets.data.total ?? '未请求'}），谓词：任一小写化后的{' '}
          <code className="mono">{KEYWORDS.join(' | ')}</code> 出现在 <code className="mono">meta</code> /{' '}
          <code className="mono">files</code> 键名 / <code className="mono">label</code> /{' '}
          <code className="mono">variant</code> / <code className="mono">provenance</code> 中。
        </p>
      ) : null}

      {assets.data && matches.length === 0 ? (
        <BlockedState
          title="NOT_RUN：后端没有提供轮廓/纯背景负控资产"
          code="NOT_RUN"
          reason={
            <>
              这次扫描是真实的：{scanned} 个资产里没有任何一个带上述关键词，因此本页没有可显示的画面。
              前端不会用渲染帧的阈值分割冒充“silhouette-only”，也不会自己造一张纯背景图。
              解除条件（后端侧）：由 observe 路线产出 <code className="mono">silhouette_only</code> 或{' '}
              <code className="mono">background_only</code> 角色/标签的资产（A32 的同器库负控与置换负控同理由后端产出）。
            </>
          }
          items={[
            { label: '扫描谓词', value: <span className="mono">{KEYWORDS.join(', ')}</span> },
            {
              label: '扫描到的 role 分布',
              value: <span className="mono">{roles.map(([role, count]) => `${role}×${count}`).join(', ') || '（空）'}</span>,
            },
            { label: '后端 empty_reason', value: assets.data.empty_reason ?? '（有资产，但没有负控类）' },
          ]}
        />
      ) : null}

      {first ? (
        <>
          <KeyValueList
            rows={[
              { label: '命中资产', value: first.asset_id, mono: true },
              { label: 'role', value: first.role, mono: true },
              { label: 'schema / unit / frame', value: `${first.schema} / ${first.unit} / ${first.frame}`, mono: true },
              { label: 'qa_status', value: first.qa_status, mono: true },
              { label: 'files', value: Object.keys(first.files ?? {}).join(', ') || '（空）', mono: true },
            ]}
          />
          {imageError ? <ErrorState error={imageError} title="负控图读取失败" compact /> : null}
          {imageUrl ? (
            <figure className="channel">
              <img src={imageUrl.url} alt={`负控资产 ${first.asset_id} 的真实图像，${imageUrl.size} 像素`} />
              <figcaption className="muted small mono">
                真实 PNG 字节解码 · IHDR {imageUrl.size} · 来自 GET /assets/{first.asset_id}/files/{first.role}
              </figcaption>
            </figure>
          ) : null}
          <details open>
            <summary>命中资产的 meta（原样）</summary>
            <pre className="mono pre">{pretty(first.meta)}</pre>
          </details>
        </>
      ) : null}
    </SectionCard>
  );
}
