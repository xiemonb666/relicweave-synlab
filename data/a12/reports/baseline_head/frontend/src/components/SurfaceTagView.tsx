/**
 * 母体真实面属性视图（U02）：用权威 `mother_mesh` 资产里的**真实面数组**着色。
 *
 * 数据来源（全部来自 `GET /assets/{id}/files/mother_mesh?key=arrays` 解出的 npz）：
 * * `mesh.vertices` (N,3) mm、`mesh.faces` (M,3) int32；
 * * `mesh.face__surface_tag` (M,) int32 —— 后端写入的逐面标签（0=outer_wall 等，
 *   名称取 `meta.surface_tag_names`）；
 * * `mesh.face__component_id`、`mesh.face__source_triangle`（若存在）。
 *
 * 诚实约定：
 * * 本页**没有厚度场**：厚度不在这些数组里，页面只显示真实可得的量（面标签 / 几何法向 /
 *   面心到轴距离 r / 面心 z），并显式写出“这不是厚度”，绝不推算厚度；
 * * 视图是把面心投影到 (r, z) 平面的回转体剖面散点，不是体积渲染；投影方式写在图注里。
 */

import { useEffect, useMemo, useRef, useState } from 'react';

import { getAsset } from '../api/endpoints';
import { useResource } from '../api/hooks';
import { loadAssetArrays, npzFaces, npzPoints, npzVector } from '../lib/assetData';
import { finiteStats } from '../lib/analysis';
import { formatNumber } from '../lib/format';
import { Badge, EmptyState, ErrorState, LoadingState, SectionCard } from './states';

/** 与后端 `surface_tag_names` 配套的固定调色板（颜色之外仍给出名称与计数）。 */
const TAG_COLORS = ['#4f9cf9', '#f2b53b', '#54c98a', '#e2686f', '#b07cf0', '#38b6c4', '#c9a227', '#8b96a8'];

export interface SurfaceTagViewProps {
  assetId: string | null;
  height?: number;
}

export function SurfaceTagView({ assetId, height = 360 }: SurfaceTagViewProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [painted, setPainted] = useState(0);

  const detail = useResource(() => getAsset(assetId as string), [assetId], {
    enabled: Boolean(assetId),
  });
  const arrays = useResource(() => loadAssetArrays(assetId as string, 'mother_mesh', 'arrays'), [assetId], {
    enabled: Boolean(assetId),
  });

  const derived = useMemo(() => {
    const map = arrays.data?.arrays;
    if (!map) return null;
    const vertices = npzPoints(map, 'mesh.vertices');
    const faces = npzFaces(map, 'mesh.faces');
    const tags = npzVector(map, 'mesh.face__surface_tag');
    if (!vertices || !faces || !tags) return null;
    const faceCount = Math.floor(faces.length / 3);
    const zPerFace = new Float64Array(faceCount);
    const radius = new Float64Array(faceCount);
    const normalZ = new Float64Array(faceCount);
    const normalR = new Float64Array(faceCount);
    for (let face = 0; face < faceCount; face += 1) {
      const ia = faces[face * 3];
      const ib = faces[face * 3 + 1];
      const ic = faces[face * 3 + 2];
      const ax = vertices[ia * 3];
      const ay = vertices[ia * 3 + 1];
      const az = vertices[ia * 3 + 2];
      const bx = vertices[ib * 3];
      const by = vertices[ib * 3 + 1];
      const bz = vertices[ib * 3 + 2];
      const cx = vertices[ic * 3];
      const cy = vertices[ic * 3 + 1];
      const cz = vertices[ic * 3 + 2];
      const mx = (ax + bx + cx) / 3;
      const my = (ay + by + cy) / 3;
      const mz = (az + bz + cz) / 3;
      zPerFace[face] = mz;
      const r = Math.hypot(mx, my);
      radius[face] = r;
      // 由真实顶点与面索引计算的几何法向（叉积方向，未归一化）
      const ux = bx - ax;
      const uy = by - ay;
      const uz = bz - az;
      const vx = cx - ax;
      const vy = cy - ay;
      const vz = cz - az;
      const nx = uy * vz - uz * vy;
      const ny = uz * vx - ux * vz;
      const nz = ux * vy - uy * vx;
      const length = Math.hypot(nx, ny, nz) || 1;
      normalZ[face] = nz / length;
      normalR[face] = (nx * mx + ny * my) / (r || 1) / length;
    }
    const tagCounts = new Map<number, number>();
    for (let face = 0; face < faceCount; face += 1) {
      const tag = Math.round(tags[face]);
      tagCounts.set(tag, (tagCounts.get(tag) ?? 0) + 1);
    }
    return {
      vertices,
      faces,
      tags,
      faceCount,
      radius,
      zPerFace,
      normalZ,
      normalR,
      tagCounts,
      rStats: finiteStats(radius),
      zStats: finiteStats(zPerFace),
      arrayKeys: [...map.keys()],
    };
  }, [arrays.data]);

  const tagNames = useMemo(() => {
    const raw = detail.data?.asset.meta?.surface_tag_names;
    if (Array.isArray(raw)) return raw.map(String);
    const charts = detail.data?.asset.meta?.charts;
    if (Array.isArray(charts) && charts.length > 0) {
      const legal = (charts[0] as Record<string, unknown>)?.legal_tags;
      if (Array.isArray(legal)) return legal.map(String);
    }
    return [] as string[];
  }, [detail.data]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !derived) return;
    const width = canvas.clientWidth || 640;
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext('2d');
    if (!context) return;
    context.fillStyle = '#11151c';
    context.fillRect(0, 0, width, height);
    const pad = 16;
    const rMax = Math.max(...derived.radius, 1);
    const zMin = derived.zStats?.min ?? 0;
    const zMax = derived.zStats?.max ?? 1;
    const spanZ = zMax - zMin || 1;
    const step = Math.max(1, Math.ceil(derived.faceCount / 60000));
    for (let face = 0; face < derived.faceCount; face += step) {
      const tag = Math.round(derived.tags[face]);
      context.fillStyle = TAG_COLORS[((tag % TAG_COLORS.length) + TAG_COLORS.length) % TAG_COLORS.length];
      const px = pad + (derived.radius[face] / rMax) * (width - pad * 2);
      const py = height - pad - ((derived.zPerFace[face] - zMin) / spanZ) * (height - pad * 2);
      context.fillRect(px, py, 1.8, 1.8);
    }
    setPainted(Math.ceil(derived.faceCount / step));
  }, [derived, height]);

  if (!assetId) {
    return (
      <EmptyState
        title="未选择 mother_mesh 资产"
        reason="在左侧“权威母体 mesh（mother_mesh）”里选一个资产，这里会用它的真实面数组着色。"
      />
    );
  }
  if (detail.status === 'error') return <ErrorState error={detail.error} onRetry={detail.reload} />;
  if (arrays.status === 'error') return <ErrorState error={arrays.error} onRetry={arrays.reload} />;
  if (detail.status === 'loading' || arrays.status === 'loading') return <LoadingState label="读取 mother_mesh 真实数组…" />;

  const record = detail.data?.asset;
  if (!record) return null;

  if (!derived) {
    return (
      <EmptyState
        title="该 mother_mesh 没有可用的逐面数组"
        reason={
          <>
            需要同时存在 <code className="mono">mesh.vertices</code> / <code className="mono">mesh.faces</code> /{' '}
            <code className="mono">mesh.face__surface_tag</code>。本资产实际键为{' '}
            <span className="mono">{(arrays.data && [...arrays.data.arrays.keys()].join(', ')) || '（未知）'}</span>。
          </>
        }
      />
    );
  }

  const thicknessKeys = derived.arrayKeys.filter((key) => /thick|wall_th|t_mm/i.test(key));

  return (
    <div className="tagsview">
      <p>
        <Badge tone="ok">真实面标签着色</Badge>
        <span className="muted small">
          {' '}
          资产 {record.asset_id} · {derived.faceCount} 面 · {Math.floor(derived.vertices.length / 3)} 顶点 ·{' '}
          {derived.tags.length} 个 surface_tag
        </span>
      </p>
      <div className="realmap__body">
        <canvas
          ref={canvasRef}
          style={{ width: '100%', height }}
          role="img"
          aria-label={`母体逐面 surface_tag 剖面散点：面心到轴距离 0 到 ${formatNumber(derived.rStats?.max ?? 0, 2)} mm`}
        />
        <div className="realmap__legend">
          <table className="table table--tight">
            <caption>surface_tag 合法值（meta.surface_tag_names）与实际面数</caption>
            <thead>
              <tr>
                <th scope="col">颜色</th>
                <th scope="col">tag 索引</th>
                <th scope="col">名称</th>
                <th scope="col">真实面数</th>
              </tr>
            </thead>
            <tbody>
              {[...derived.tagCounts.entries()]
                .sort((a, b) => a[0] - b[0])
                .map(([tag, count]) => (
                  <tr key={tag}>
                    <td>
                      <span
                        className="swatch"
                        style={{ background: TAG_COLORS[((tag % TAG_COLORS.length) + TAG_COLORS.length) % TAG_COLORS.length] }}
                        aria-hidden="true"
                      />
                    </td>
                    <th scope="row" className="mono">
                      {tag}
                    </th>
                    <td>{tagNames[tag] ?? '（后端未给名称）'}</td>
                    <td className="mono">{count}</td>
                  </tr>
                ))}
            </tbody>
          </table>
          <p className="muted small">绘制 {painted} 个面（按真实面序等间隔抽样，不平均、不插值）。</p>
        </div>
      </div>

      <SectionCard title="这里显示的量分别是什么" subtitle="本资产没有厚度场，因此不显示厚度">
        <table className="table table--tight">
          <thead>
            <tr>
              <th scope="col">量</th>
              <th scope="col">来源</th>
              <th scope="col">实测范围</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <th scope="row">逐面 surface_tag（内外壁/口沿/足/底）</th>
              <td className="mono small">mesh.face__surface_tag（后端写入）</td>
              <td className="small">索引 {[...derived.tagCounts.keys()].sort((a, b) => a - b).join(', ')}</td>
            </tr>
            <tr>
              <th scope="row">面心到轴距离 r = √(x²+y²)</th>
              <td className="mono small">由 mesh.vertices + mesh.faces 计算</td>
              <td className="mono small">
                {formatNumber(derived.rStats?.min ?? 0, 3)} … {formatNumber(derived.rStats?.max ?? 0, 3)} mm
              </td>
            </tr>
            <tr>
              <th scope="row">面心 z</th>
              <td className="mono small">由 mesh.vertices 计算</td>
              <td className="mono small">
                {formatNumber(derived.zStats?.min ?? 0, 3)} … {formatNumber(derived.zStats?.max ?? 0, 3)} mm
              </td>
            </tr>
            <tr>
              <th scope="row">几何法向（nz / 径向分量）</th>
              <td className="mono small">由真实顶点与面索引叉积计算</td>
              <td className="mono small">见下方“面法向分布”</td>
            </tr>
            <tr>
              <th scope="row">壁厚</th>
              <td className="mono small">本资产数组键：{derived.arrayKeys.join(', ')}</td>
              <td className="small">
                没有厚度场：以上键名里{thicknessKeys.length === 0 ? '没有任何厚度字段' : `只有 ${thicknessKeys.join(', ')}`}。
                页面不推算厚度，也不显示占位热图。
              </td>
            </tr>
          </tbody>
        </table>
        <details>
          <summary>面法向分布（真实计算的 nz 统计）</summary>
          <dl className="kv kv--tight">
            <div className="kv__row">
              <dt>nz 最小 / 最大</dt>
              <dd className="mono">
                {formatNumber(finiteStats(derived.normalZ)?.min ?? 0, 4)} /{' '}
                {formatNumber(finiteStats(derived.normalZ)?.max ?? 0, 4)}
              </dd>
            </div>
            <div className="kv__row">
              <dt>径向法向分量最小 / 最大</dt>
              <dd className="mono">
                {formatNumber(finiteStats(derived.normalR)?.min ?? 0, 4)} /{' '}
                {formatNumber(finiteStats(derived.normalR)?.max ?? 0, 4)}
              </dd>
            </div>
          </dl>
          <p className="muted small">
            外壁面片的径向法向分量应接近 +1、内壁接近 −1；上面是真实计算结果，可用来核对 surface_tag 是否与几何一致。
          </p>
        </details>
      </SectionCard>
    </div>
  );
}
