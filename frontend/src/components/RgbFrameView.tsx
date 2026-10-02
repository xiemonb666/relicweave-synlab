/**
 * RgbFrameView —— 把 `obs_view` / `degrade_measurement` 资产里**真实的** `uint8` RGB 数组
 * 画成图片（浏览器内解码，不经过后端缩放，也不做任何美化）。
 *
 * 为什么要有它：退化预览要「L0 与 Ln 并排」，而这两个资产的 payload 是数组而不是 PNG 文件
 * （`files` 只有 `arrays` / `meta`）。真实可看的东西就是那个 `(H, W, 3) uint8` 帧，
 * 所以这里直接渲染原始像素并以 `image-rendering: pixelated` 展示，缩放后仍能看出它是低清帧。
 *
 * 诚实规则：
 * * 找不到声明的数组键就显示真实键名清单，不画占位图；
 * * 默认按 `payload.frames.<n>.rgb`（obs_view）或 `payload.modalities.rgb.data`
 *   （degrade_measurement）取；键名由调用方给出，本组件不猜数据语义；
 * * `valid_mask` / `mask` 存在时只把它当作 alpha 参与绘制，并在图注里写明。
 */

import { useEffect, useMemo, useRef, useState } from 'react';

import { loadAssetArrays, type NpyArray } from '../lib/assetData';
import { frameIndices } from '../lib/assetData';
import { Badge, EmptyState, ErrorState, LoadingState } from './states';
export interface RgbFrameViewProps {
  assetId: string | null;
  role: string;
  /** 数组键名（不含 `.data`）；例如 `payload.frames.3.rgb`。 */
  rgbKey: string | null;
  /** alpha 键名（可选）；例如 `payload.frames.3.valid_mask`。 */
  alphaKey?: string | null;
  label: string;
  height?: number;
}

interface DecodedFrame {
  width: number;
  height: number;
  imageData: ImageData;
  alphaUsed: string | null;
  keys: string[];
}

function toImageData(rgb: NpyArray, alpha: NpyArray | null, alphaKey: string | null): DecodedFrame | null {
  if (rgb.shape.length !== 3 || rgb.shape[2] !== 3) return null;
  const height = rgb.shape[0];
  const width = rgb.shape[1];
  const rgba = new Uint8ClampedArray(width * height * 4);
  const alphaOk = alpha !== null && alpha.shape.length === 2
    && alpha.shape[0] === height && alpha.shape[1] === width;
  for (let index = 0; index < width * height; index += 1) {
    rgba[index * 4] = Number(rgb.data[index * 3]);
    rgba[index * 4 + 1] = Number(rgb.data[index * 3 + 1]);
    rgba[index * 4 + 2] = Number(rgb.data[index * 3 + 2]);
    rgba[index * 4 + 3] = alphaOk && alpha ? (Number(alpha.data[index]) > 0 ? 255 : 0) : 255;
  }
  return {
    width,
    height,
    imageData: new ImageData(rgba, width, height),
    alphaUsed: alphaOk ? alphaKey : null,
    keys: [],
  };
}

export function RgbFrameView({ assetId, role, rgbKey, alphaKey, label, height = 200 }: RgbFrameViewProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [status, setStatus] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle');
  const [error, setError] = useState<unknown>(null);
  const [decoded, setDecoded] = useState<DecodedFrame | null>(null);
  const [bytes, setBytes] = useState<number | null>(null);

  useEffect(() => {
    if (!assetId || !rgbKey) {
      setStatus('idle');
      setDecoded(null);
      return undefined;
    }
    let cancelled = false;
    setStatus('loading');
    setError(null);
    const run = async () => {
      try {
        const loaded = await loadAssetArrays(assetId, role, 'arrays');
        if (cancelled) return;
        const rgb = loaded.arrays.get(rgbKey);
        if (!rgb) {
          setDecoded({ width: 0, height: 0, imageData: new ImageData(1, 1), alphaUsed: null,
                       keys: [...loaded.arrays.keys()].sort() });
          setStatus('error');
          setError(new Error(`该资产没有数组键 ${rgbKey}；实际键：${[...loaded.arrays.keys()].sort().join(', ')}`));
          return;
        }
        const alpha = alphaKey ? loaded.arrays.get(alphaKey) ?? null : null;
        const frame = toImageData(rgb, alpha, alphaKey ?? null);
        if (!frame) {
          setStatus('error');
          setError(new Error(`数组 ${rgbKey} 的形状是 [${rgb.shape.join(', ')}]，不是 (H, W, 3) uint8 帧`));
          return;
        }
        setBytes(loaded.bytes);
        setDecoded({ ...frame, keys: [...loaded.arrays.keys()].sort() });
        setStatus('ready');
      } catch (caught) {
        if (cancelled) return;
        if (caught instanceof DOMException && caught.name === 'AbortError') return;
        setError(caught);
        setStatus('error');
      }
    };
    void run();
    return () => {
      cancelled = true;
    };
  }, [assetId, role, rgbKey, alphaKey]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || status !== 'ready' || !decoded || decoded.width === 0) return;
    canvas.width = decoded.width;
    canvas.height = decoded.height;
    const context = canvas.getContext('2d');
    if (!context) return;
    context.putImageData(decoded.imageData, 0, 0);
  }, [decoded, status]);

  const frameList = useMemo(() => (decoded ? frameIndices(new Map(decoded.keys.map((key) => [key, {} as NpyArray]))) : []), [decoded]);

  return (
    <div className="framepreview">
      <div className="framepreview__head">
        <strong>{label}</strong>
        {status === 'ready' && decoded ? (
          <>
            <Badge tone="ok">
              真实帧 {decoded.width}×{decoded.height}
            </Badge>
            <span className="mono small">{rgbKey}</span>
            {decoded.alphaUsed ? <Badge tone="neutral">alpha={decoded.alphaUsed}</Badge> : null}
            {bytes !== null ? <span className="mono small">{bytes} B</span> : null}
          </>
        ) : null}
      </div>
      <div className="framepreview__canvas" style={{ minHeight: `${Math.min(height, 240)}px` }}>
        <canvas ref={canvasRef} className="framepreview__pixel" aria-label={`${label} 的真实 RGB 帧`} />
        {status === 'loading' ? <LoadingState label="解码 arrays.npz…" /> : null}
        {status === 'idle' ? (
          <EmptyState title="没有可显示的帧" reason="未选择资产或该资产没有声明 RGB 数组键。" />
        ) : null}
        {status === 'error' ? <ErrorState error={error} compact title="无法解码该帧" /> : null}
      </div>
      {status === 'ready' && decoded && decoded.keys.length > 0 ? (
        <p className="muted small mono">
          该资产真实数组键：{decoded.keys.slice(0, 12).join(', ')}
          {decoded.keys.length > 12 ? ` …（共 ${decoded.keys.length} 个）` : ''}
          {frameList.length > 0 ? ` · 帧下标 ${frameList.join(', ')}` : ''}
        </p>
      ) : null}
    </div>
  );
}

/** `obs_view` 的第一帧 RGB 键（真实键名格式：`payload.frames.<n>.rgb`）。 */
export function firstFrameRgbKey(keys: string[] | null | undefined, member = 'rgb'): string | null {
  if (!keys || keys.length === 0) return null;
  const map = new Map<string, NpyArray>(keys.map((key) => [key, {} as NpyArray]));
  const indices = frameIndices(map);
  if (indices.length === 0) return null;
  const candidate = `payload.frames.${indices[0]}.${member}`;
  return keys.includes(candidate) ? candidate : null;
}

/** `degrade_measurement` 的单一 RGB 键（如果存在）。 */
export function modalityRgbKey(keys: string[] | null | undefined): string | null {
  const candidate = 'payload.modalities.rgb.data';
  if (!keys) return null;
  return keys.includes(candidate) ? candidate : null;
}

/** 真实数组键清单只在解码后才知道；这里把「已知声明」和「解码结果」合并成一个键名。 */
export function declaredOrFirstFrame(keys: string[] | null | undefined): string | null {
  return firstFrameRgbKey(keys) ?? modalityRgbKey(keys);
}
