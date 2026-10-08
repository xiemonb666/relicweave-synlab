/**
 * 纹样通道预览：真实解码 `pattern_channels` 资产里的 PNG 字节并显示
 * albedo / roughness / height 三个通道（展开 chart 图）。
 *
 * 诚实约定：
 * * 图像字节直接来自 `GET /assets/{id}/files/{role}?key=...`，先校验 PNG 签名与 IHDR
 *   尺寸，再由浏览器真实解码（blob URL）；没有图像就显示“尚未生成”的阻塞原因；
 * * 显示编码说明取后端 `meta.encoding_legend` / `meta.legend` 原文，不自行编造色彩约定；
 * * 通道数值范围取 `meta.channel_stats` 原文。
 */

import { useEffect, useMemo, useState } from 'react';

import { getAsset } from '../api/endpoints';
import { useResource } from '../api/hooks';
import type { AssetRecord } from '../api/types';
import { blobUrlFor, isPng, loadAssetBytes, pngSize } from '../lib/assetData';
import { formatNumber, pretty } from '../lib/format';
import { Badge, EmptyState, ErrorState, KeyValueList, LoadingState } from './states';

const CHANNEL_LABELS: Record<string, string> = {
  albedo_png: 'albedo（反射率，显示编码）',
  roughness_png: 'roughness（粗糙度，线性灰度）',
  height_png: 'height（高度，mm）',
  png: '渲染帧（显示编码）',
};

interface ChannelState {
  key: string;
  status: 'loading' | 'ready' | 'error';
  url?: string;
  size?: { width: number; height: number; bitDepth: number; colorType: number };
  bytes?: number;
  sha256?: string;
  hashVerified?: string;
  error?: unknown;
}

function ChannelImage({ state, label }: { state: ChannelState; label: string }) {
  if (state.status === 'loading') return <LoadingState label={`读取 ${label}…`} />;
  if (state.status === 'error') return <ErrorState error={state.error} title={`${label} 读取失败`} compact />;
  if (!state.url || !state.size) return null;
  return (
    <figure className="channel">
      <img src={state.url} alt={`${label}：${state.size.width}×${state.size.height} 像素真实通道图`} />
      <figcaption>
        <strong>{label}</strong>
        <div className="muted small mono">
          IHDR {state.size.width} × {state.size.height} · bitDepth {state.size.bitDepth} · colorType {state.size.colorType} ·{' '}
          {formatNumber((state.bytes ?? 0) / 1024, 1)} KiB
        </div>
        {state.sha256 ? (
          <div className="muted small mono">
            服务端 sha256 {state.sha256.slice(0, 24)}… · 校验 {state.hashVerified ?? '未提供'}
          </div>
        ) : null}
      </figcaption>
    </figure>
  );
}

export function PatternChannelViewer({ assetId }: { assetId: string }) {
  const detail = useResource((signal) => getAsset(assetId, signal), [assetId]);
  const [channels, setChannels] = useState<Record<string, ChannelState>>({});
  const role = detail.data?.asset.role ?? null;

  const imageKeys = useMemo(() => {
    const record = detail.data?.asset;
    if (!record) return [] as string[];
    const declared = Array.isArray(record.meta?.image_keys) ? (record.meta.image_keys as unknown[]).map(String) : [];
    const fromFiles = Object.keys(record.files ?? {});
    const merged = [...declared.filter((key) => fromFiles.includes(key)), ...fromFiles.filter((key) => /png$/.test(key))];
    return [...new Set(merged)];
  }, [detail.data]);

  useEffect(() => {
    let cancelled = false;
    const created: string[] = [];
    const run = async () => {
      if (!role) return;
      setChannels({});
      for (const key of imageKeys) {
        setChannels((prev) => ({ ...prev, [key]: { key, status: 'loading' } }));
        try {
          const loaded = await loadAssetBytes(assetId, role, key);
          if (cancelled) return;
          if (!isPng(loaded.bytes)) {
            throw new Error(`文件 ${key} 不是 PNG（签名不匹配），本页不按图片解码`);
          }
          const size = pngSize(loaded.bytes);
          const url = blobUrlFor(loaded.bytes, 'image/png');
          created.push(url);
          setChannels((prev) => ({
            ...prev,
            [key]: {
              key,
              status: 'ready',
              url,
              size: size ?? undefined,
              bytes: loaded.bytes.byteLength,
              sha256: loaded.headers['x-synlab-file-sha256'],
              hashVerified: loaded.headers['x-synlab-hash-verified'],
            },
          }));
        } catch (error) {
          if (cancelled) return;
          setChannels((prev) => ({ ...prev, [key]: { key, status: 'error', error } }));
        }
      }
    };
    if (imageKeys.length > 0) void run();
    return () => {
      cancelled = true;
      for (const url of created) URL.revokeObjectURL(url);
    };
  }, [assetId, role, imageKeys]);

  if (detail.status === 'error') return <ErrorState error={detail.error} onRetry={detail.reload} />;
  if (detail.status === 'loading') return <LoadingState label="读取 pattern_channels 资产…" />;
  const record: AssetRecord | undefined = detail.data?.asset;
  if (!record) return null;

  if (imageKeys.length === 0) {
    return (
      <EmptyState
        title="该纹样通道资产里没有图像成员"
        reason={
          <>
            真实 <code className="mono">files</code> 键为 {Object.keys(record.files ?? {}).join(', ') || '（空）'}。
            若 <code className="mono">data/a12_demo</code> 尚未生成 PNG，请运行{' '}
            <code className="mono">python tools/build_demo_assets.py</code> 后刷新。
          </>
        }
      />
    );
  }

  const meta = record.meta ?? {};
  const legends = (meta.legend ?? {}) as Record<string, unknown>;
  const encoding = (meta.encoding_legend ?? {}) as Record<string, unknown>;
  const chart = (meta.chart ?? {}) as Record<string, unknown>;
  const stats = (meta.channel_stats ?? {}) as Record<string, unknown>;

  return (
    <div className="channels">
      <p>
        <Badge tone="ok">真实 PNG 解码</Badge>
        <span className="muted small">
          {' '}
          资产 {record.asset_id} · role {record.role} · schema {record.schema} · unit {record.unit} · frame{' '}
          {record.frame}
        </span>
      </p>
      <div className="channels__grid">
        {imageKeys.map((key) => (
          <ChannelImage key={key} state={channels[key] ?? { key, status: 'loading' }} label={CHANNEL_LABELS[key] ?? key} />
        ))}
      </div>

      <details open>
        <summary>展开 chart（后端记录的 chart 参数，非前端推断）</summary>
        <KeyValueList
          rows={[
            { label: 'chart 名称', value: String(chart.name ?? '未提供'), mono: true },
            { label: '类型', value: String(chart.kind ?? '未提供'), mono: true },
            { label: 'surface_tag', value: String(chart.surface_tag ?? '未提供'), mono: true },
            { label: 'u 周期', value: chart.u_periodic === undefined ? '未提供' : String(chart.u_periodic), mono: true },
            { label: 's 周期', value: chart.s_periodic === undefined ? '未提供' : String(chart.s_periodic), mono: true },
            {
              label: 'x 周期',
              value: chart.x_period_mm === undefined ? '未提供' : `${formatNumber(Number(chart.x_period_mm), 3)} mm`,
              mono: true,
            },
            {
              label: 's 范围（实测自 mesh）',
              value: Array.isArray(chart.s_range_mm)
                ? (chart.s_range_mm as number[]).map((value) => formatNumber(value, 3)).join(' … ') + ' mm'
                : '未提供',
              mono: true,
            },
            {
              label: 'chart 面积',
              value: chart.area_mm2 === undefined ? '未提供' : `${formatNumber(Number(chart.area_mm2), 1)} mm²`,
              mono: true,
            },
            {
              label: 's 范围来源',
              value: String(chart.s_range_source ?? '未提供'),
              mono: true,
            },
          ]}
        />
      </details>

      <details open>
        <summary>显示编码说明（后端原文）与通道实测范围</summary>
        <table className="table table--tight">
          <caption>meta.encoding_legend / meta.legend / meta.channel_stats（原样）</caption>
          <thead>
            <tr>
              <th scope="col">通道</th>
              <th scope="col">成员键</th>
              <th scope="col">编码说明（后端原文）</th>
            </tr>
          </thead>
          <tbody>
            {imageKeys.map((key) => (
              <tr key={key}>
                <th scope="row">{CHANNEL_LABELS[key] ?? key}</th>
                <td className="mono small">{key}</td>
                <td className="small">{String(legends[key] ?? encoding[key.replace('_png', '')] ?? '该资产未提供说明')}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <pre className="mono pre">{pretty(stats)}</pre>
      </details>
    </div>
  );
}
