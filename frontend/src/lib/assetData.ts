/**
 * 真实资产数据加载：把 `GET /assets/{id}/files/{role}?key=...` 的字节流读成
 * 可计算的数值（npz）或可解码的图像字节（png）。
 *
 * 只做两件事：发真实请求 + 解析真实字节。没有缓存造假、没有 fallback 数据；
 * 缓存只在同一页面会话内避免重复下载同一个资产（键含 assetId/role/key，值就是后端响应）。
 */

import { fetchAssetBlob } from '../api/endpoints';
import { NpzFormatError, readNpz, type NpyArray } from './npz';

export {
  npzFaces,
  npzGet,
  npzNumber,
  npzNumbers,
  npzPoints,
  npzScalar2d,
  npzVector,
  type NpyArray,
  type NpyTypedArray,
} from './npz';

export interface LoadedArrays {
  assetId: string;
  role: string;
  key: string;
  arrays: Map<string, NpyArray>;
  /** 后端响应头（含 X-SynLab-File-Sha256 / X-SynLab-Hash-Verified）。 */
  headers: Record<string, string>;
  bytes: number;
  url: string;
}

export interface LoadedBytes {
  assetId: string;
  role: string;
  key: string;
  bytes: Uint8Array;
  headers: Record<string, string>;
  url: string;
}

const arraysCache = new Map<string, Promise<LoadedArrays>>();
const bytesCache = new Map<string, Promise<LoadedBytes>>();

function headerRecord(headers: Headers): Record<string, string> {
  const out: Record<string, string> = {};
  headers.forEach((value, name) => {
    out[name] = value;
  });
  return out;
}

function cacheKey(assetId: string, role: string, key: string): string {
  return `${assetId}|${role}|${key}`;
}

/** 同一会话内的重复读取复用后端响应（响应头里的 sha256 会原样保留用于核对）。 */
export function loadAssetBytes(assetId: string, role: string, key: string): Promise<LoadedBytes> {
  const id = cacheKey(assetId, role, key);
  const cached = bytesCache.get(id);
  if (cached) return cached;
  const task = (async (): Promise<LoadedBytes> => {
    const { blob, headers, url } = await fetchAssetBlob(assetId, role, key);
    const bytes = new Uint8Array(await blob.arrayBuffer());
    return { assetId, role, key, bytes, headers: headerRecord(headers), url };
  })();
  bytesCache.set(id, task);
  task.catch(() => bytesCache.delete(id));
  return task;
}

/** 读取真实 `arrays`（npz）资产并解码为数值表。 */
export function loadAssetArrays(assetId: string, role: string, key = 'arrays'): Promise<LoadedArrays> {
  const id = cacheKey(assetId, role, key);
  const cached = arraysCache.get(id);
  if (cached) return cached;
  const task = (async (): Promise<LoadedArrays> => {
    const loaded = await loadAssetBytes(assetId, role, key);
    const buffer = loaded.bytes.buffer.slice(
      loaded.bytes.byteOffset,
      loaded.bytes.byteOffset + loaded.bytes.byteLength,
    ) as ArrayBuffer;
    const arrays = await readNpz(buffer);
    if (arrays.size === 0) {
      throw new NpzFormatError('<npz>', '压缩包里没有任何 .npy 成员');
    }
    return {
      assetId,
      role,
      key,
      arrays,
      headers: loaded.headers,
      bytes: loaded.bytes.byteLength,
      url: loaded.url,
    };
  })();
  arraysCache.set(id, task);
  task.catch(() => arraysCache.delete(id));
  return task;
}

export function clearAssetDataCache(): void {
  arraysCache.clear();
  bytesCache.clear();
}

/* --------------------------------------------------------------- 真实帧结构读取 */

export interface ViewFrameData {
  index: number;
  /** `payload.frames.N.*` 里的真实键名清单（用于“本资产到底有什么”的说明）。 */
  keys: string[];
}

/** 从 arrays 的键名里找出所有 `payload.frames.N` 下标。 */
export function frameIndices(arrays: Map<string, NpyArray>, prefix = 'payload.frames.'): number[] {
  const found = new Set<number>();
  for (const key of arrays.keys()) {
    if (!key.startsWith(prefix)) continue;
    const rest = key.slice(prefix.length);
    const dot = rest.indexOf('.');
    const head = dot === -1 ? rest : rest.slice(0, dot);
    const index = Number.parseInt(head, 10);
    if (Number.isFinite(index)) found.add(index);
  }
  return [...found].sort((a, b) => a - b);
}

/** 某一帧真实存在的成员键名（去掉 `payload.frames.N.` 前缀）。 */
export function frameMemberKeys(arrays: Map<string, NpyArray>, index: number, prefix = 'payload.frames.'): string[] {
  const head = `${prefix}${index}.`;
  return [...arrays.keys()]
    .filter((key) => key.startsWith(head))
    .map((key) => key.slice(head.length))
    .sort();
}

/** PNG 签名校验：确认字节流真的是 PNG，而不是被当成图片的别的东西。 */
export const PNG_SIGNATURE = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];

export function isPng(bytes: Uint8Array): boolean {
  if (bytes.byteLength < 24) return false;
  return PNG_SIGNATURE.every((value, index) => bytes[index] === value);
}

/** 从 PNG 的 IHDR 里读真实像素尺寸（不做图像解码，只读头部）。 */
export function pngSize(bytes: Uint8Array): { width: number; height: number; bitDepth: number; colorType: number } | null {
  if (!isPng(bytes)) return null;
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const width = view.getUint32(16, false);
  const height = view.getUint32(20, false);
  return { width, height, bitDepth: bytes[24], colorType: bytes[25] };
}

export function blobUrlFor(bytes: Uint8Array, type: string): string {
  return URL.createObjectURL(new Blob([bytes as BlobPart], { type }));
}
