/**
 * 真实数组分析：统计量、色标、投影、误差热图绘制。
 *
 * 全部输入都来自 `lib/npz.ts` 解出的**真实数组**；这里不做任何平滑、插值或补点：
 * 缺测位置留空（透明），统计量按有效值计数并同时给出 `n`。
 */

import type { NpyArray } from './npz';

export type AnyNumberArray = Float64Array | Float32Array | Int32Array | Int16Array | Int8Array | Uint8Array | Uint16Array | Uint32Array;

export interface Stats {
  n: number;
  min: number;
  max: number;
  mean: number;
  p50: number;
  p95: number;
  p99: number;
}

/** 只统计有限值；`mask` 给定时只统计 mask 非零位置（真实有效区）。 */
export function finiteStats(values: ArrayLike<number>, mask?: ArrayLike<number> | null): Stats | null {
  const kept: number[] = [];
  for (let index = 0; index < values.length; index += 1) {
    if (mask && !mask[index]) continue;
    const value = Number(values[index]);
    if (Number.isFinite(value)) kept.push(value);
  }
  if (kept.length === 0) return null;
  kept.sort((a, b) => a - b);
  const quantile = (q: number) => kept[Math.min(kept.length - 1, Math.max(0, Math.round(q * (kept.length - 1))))];
  const sum = kept.reduce((acc, value) => acc + value, 0);
  return {
    n: kept.length,
    min: kept[0],
    max: kept[kept.length - 1],
    mean: sum / kept.length,
    p50: quantile(0.5),
    p95: quantile(0.95),
    p99: quantile(0.99),
  };
}

/** 逐点欧氏距离 `‖a - b‖`，逐维取真实值；任一分量非有限则该点为 NaN（不写 0）。 */
export function pointDistances(a: ArrayLike<number>, b: ArrayLike<number>, dims = 3): Float64Array {
  const count = Math.min(Math.floor(a.length / dims), Math.floor(b.length / dims));
  const out = new Float64Array(count);
  for (let index = 0; index < count; index += 1) {
    let sum = 0;
    let ok = true;
    for (let dim = 0; dim < dims; dim += 1) {
      const delta = Number(a[index * dims + dim]) - Number(b[index * dims + dim]);
      if (!Number.isFinite(delta)) {
        ok = false;
        break;
      }
      sum += delta * delta;
    }
    out[index] = ok ? Math.sqrt(sum) : Number.NaN;
  }
  return out;
}

/** 逐像素绝对差 `|a - b|`（要求形状一致，形状不一致由调用方先判断并说明）。 */
export function absoluteDifference(a: ArrayLike<number>, b: ArrayLike<number>): Float64Array {
  const count = Math.min(a.length, b.length);
  const out = new Float64Array(count);
  for (let index = 0; index < count; index += 1) {
    const left = Number(a[index]);
    const right = Number(b[index]);
    out[index] = Number.isFinite(left) && Number.isFinite(right) ? Math.abs(left - right) : Number.NaN;
  }
  return out;
}

/* ------------------------------------------------------------------ 色标 */
/** viridis 近似的 9 个锚点（纯亮度+色相递增，色盲友好；但仍同时给数值刻度，不靠颜色单独表意）。 */
const VIRIDIS: Array<[number, number, number]> = [
  [68, 1, 84],
  [72, 40, 120],
  [62, 74, 137],
  [49, 104, 142],
  [38, 130, 142],
  [31, 158, 137],
  [53, 183, 121],
  [109, 205, 89],
  [180, 222, 44],
  [253, 231, 37],
];

export function viridis(t: number): [number, number, number] {
  const clamped = Number.isFinite(t) ? Math.min(1, Math.max(0, t)) : 0;
  const scaled = clamped * (VIRIDIS.length - 1);
  const low = Math.floor(scaled);
  const high = Math.min(VIRIDIS.length - 1, low + 1);
  const frac = scaled - low;
  const a = VIRIDIS[low];
  const b = VIRIDIS[high];
  return [
    Math.round(a[0] + (b[0] - a[0]) * frac),
    Math.round(a[1] + (b[1] - a[1]) * frac),
    Math.round(a[2] + (b[2] - a[2]) * frac),
  ];
}

export function rgbCss(rgb: [number, number, number]): string {
  return `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})`;
}

/* ------------------------------------------------------------------ 热图绘制 */
export interface HeatmapOptions {
  values: ArrayLike<number>;
  width: number;
  height: number;
  /** 有效掩码（0 表示缺测，画成空而不是 0）。 */
  mask?: ArrayLike<number> | null;
  min: number;
  max: number;
  scale?: number;
}

/**
 * 把一个真实 2D 标量场画进 canvas(`ImageData`)；缺测像素完全透明。
 * 返回真实绘制像素数，便于页面写出“画了多少个真实值”。
 */
export function drawHeatmap(canvas: HTMLCanvasElement, options: HeatmapOptions): number {
  const { values, width, height, mask, min, max } = options;
  const scale = Math.max(1, Math.floor(options.scale ?? 1));
  const outWidth = Math.max(1, Math.floor(width / scale));
  const outHeight = Math.max(1, Math.floor(height / scale));
  canvas.width = outWidth;
  canvas.height = outHeight;
  const context = canvas.getContext('2d');
  if (!context) return 0;
  const image = context.createImageData(outWidth, outHeight);
  const span = max - min;
  let painted = 0;
  for (let y = 0; y < outHeight; y += 1) {
    for (let x = 0; x < outWidth; x += 1) {
      // 降采样时取块内第一个真实值，不做平均（平均会掩盖单像素异常）
      const sourceIndex = (y * scale) * width + x * scale;
      const value = Number(values[sourceIndex]);
      const offset = (y * outWidth + x) * 4;
      if (mask && !mask[sourceIndex]) continue;
      if (!Number.isFinite(value)) continue;
      const t = span > 0 ? (value - min) / span : 0;
      const [r, g, b] = viridis(t);
      image.data[offset] = r;
      image.data[offset + 1] = g;
      image.data[offset + 2] = b;
      image.data[offset + 3] = 255;
      painted += 1;
    }
  }
  context.putImageData(image, 0, 0);
  return painted;
}

/* ------------------------------------------------------------------ 三维投影 */
export type ProjectionAxis = 'xy' | 'xz' | 'yz' | 'iso';

export interface ProjectedPoints {
  u: Float64Array;
  v: Float64Array;
  uLabel: string;
  vLabel: string;
}

const ISO_COS = Math.cos(Math.PI / 6);
const ISO_SIN = Math.sin(Math.PI / 6);

/** 把真实 `(N,3)` mm 点投影到 2D；`iso` 为固定角度等轴测，不改变数据本身。 */
export function projectPoints(points: ArrayLike<number>, axis: ProjectionAxis): ProjectedPoints {
  const count = Math.floor(points.length / 3);
  const u = new Float64Array(count);
  const v = new Float64Array(count);
  for (let index = 0; index < count; index += 1) {
    const x = Number(points[index * 3]);
    const y = Number(points[index * 3 + 1]);
    const z = Number(points[index * 3 + 2]);
    if (axis === 'xy') {
      u[index] = x;
      v[index] = -y;
    } else if (axis === 'xz') {
      u[index] = x;
      v[index] = -z;
    } else if (axis === 'yz') {
      u[index] = y;
      v[index] = -z;
    } else {
      u[index] = (x - y) * ISO_COS;
      v[index] = -z - (x + y) * ISO_SIN;
    }
  }
  const labels: Record<ProjectionAxis, [string, string]> = {
    xy: ['X (mm)', 'Y (mm)'],
    xz: ['X (mm)', 'Z (mm)'],
    yz: ['Y (mm)', 'Z (mm)'],
    iso: ['(X−Y)·cos30° (mm)', 'Z + (X+Y)·sin30° (mm)'],
  };
  return { u, v, uLabel: labels[axis][0], vLabel: labels[axis][1] };
}

/* ------------------------------------------------------------------ 姿态/K */
export interface CameraIntrinsicsReadout {
  fx: number;
  fy: number;
  cx: number;
  cy: number;
  /** 真实推导：工作距离 / fx（mm/px）。后端 CameraProfile 用同一公式。 */
  mmPerPixel: number;
}

export function intrinsicsFromArray(array: NpyArray): CameraIntrinsicsReadout | null {
  if (array.data.length < 9) return null;
  const fx = Number(array.data[0]);
  const cx = Number(array.data[2]);
  const fy = Number(array.data[4]);
  const cy = Number(array.data[5]);
  if (![fx, fy, cx, cy].every((value) => Number.isFinite(value))) return null;
  return { fx, fy, cx, cy, mmPerPixel: Number.NaN };
}

export function withWorkingDistance(readout: CameraIntrinsicsReadout, workingDistanceMm: number): CameraIntrinsicsReadout {
  return { ...readout, mmPerPixel: workingDistanceMm / readout.fx };
}

/** 4×4 齐次矩阵第 4 列的平移（真实相机中心读数）。 */
export function translationFromMatrix(array: NpyArray): [number, number, number] | null {
  if (array.data.length < 16) return null;
  const values: [number, number, number] = [Number(array.data[3]), Number(array.data[7]), Number(array.data[11])];
  return values.every((value) => Number.isFinite(value)) ? values : null;
}

export function matricesEqual(a: NpyArray, b: NpyArray, tolerance = 1e-9): boolean | null {
  if (a.data.length !== b.data.length || a.data.length === 0) return null;
  for (let index = 0; index < a.data.length; index += 1) {
    if (Math.abs(Number(a.data[index]) - Number(b.data[index])) > tolerance) return false;
  }
  return true;
}
