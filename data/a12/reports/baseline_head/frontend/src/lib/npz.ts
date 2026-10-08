/**
 * 真实 NPZ / NPY 读取器：把后端 `arrays` 资产（`numpy.savez` 产物）在浏览器里解码成数值。
 *
 * 这里没有任何示例数据或兜底：
 * * NPZ 是标准 ZIP 容器 —— 按中央目录解析，`stored`（0）直接取切片，`deflate`（8）用浏览器
 *   原生 `DecompressionStream('deflate-raw')` 解压；
 * * NPY 头是 numpy 自己写的 Python 字面量 dict —— 只提取 `descr` / `fortran_order` / `shape`
 *   三个字段，读不出来就抛错（不猜、不补默认值）；
 * * 大端（`>`）与 Fortran 序数组一律显式报错，避免把字节序读错的值当成真实测量值展示。
 */

export type NpyTypedArray =
  | Float64Array
  | Float32Array
  | Int32Array
  | Int16Array
  | Int8Array
  | Uint32Array
  | Uint16Array
  | Uint8Array;

export interface NpyArray {
  /** NPZ 内的数组名（例如 `payload.points`）。 */
  key: string;
  /** numpy dtype 字符串原文（例如 `<f8`）。 */
  dtype: string;
  /** 形状（NPY 头里的 shape 原文）。 */
  shape: number[];
  /** 展平后的真实数值，行优先。 */
  data: NpyTypedArray;
}

export class NpzFormatError extends Error {
  readonly key: string;
  constructor(key: string, message: string) {
    super(`${key}: ${message}`);
    this.name = 'NpzFormatError';
    this.key = key;
  }
}

const ZIP_EOCD = 0x06054b50;
const ZIP_CENTRAL = 0x02014b50;
const ZIP_LOCAL = 0x04034b50;
const NPY_MAGIC = [0x93, 0x4e, 0x55, 0x4d, 0x50, 0x59];

function findEocd(view: DataView): number {
  const max = Math.min(view.byteLength, 65_557 + 22);
  for (let offset = view.byteLength - 22; offset >= Math.max(0, view.byteLength - max); offset -= 1) {
    if (view.getUint32(offset, true) === ZIP_EOCD) return offset;
  }
  throw new NpzFormatError('<zip>', '没有找到 ZIP 中央目录结尾记录（EOCD）：不是合法的 npz/zip 字节流');
}

interface ZipEntry {
  name: string;
  method: number;
  compressedSize: number;
  uncompressedSize: number;
  localOffset: number;
}

function readCentralDirectory(view: DataView, bytes: Uint8Array): ZipEntry[] {
  const eocd = findEocd(view);
  const count = view.getUint16(eocd + 10, true);
  let offset = view.getUint32(eocd + 16, true);
  const entries: ZipEntry[] = [];
  for (let index = 0; index < count; index += 1) {
    if (view.getUint32(offset, true) !== ZIP_CENTRAL) {
      throw new NpzFormatError('<zip>', `中央目录第 ${index} 条签名非法（offset=${offset}）`);
    }
    const method = view.getUint16(offset + 10, true);
    const compressedSize = view.getUint32(offset + 20, true);
    const uncompressedSize = view.getUint32(offset + 24, true);
    const nameLength = view.getUint16(offset + 28, true);
    const extraLength = view.getUint16(offset + 30, true);
    const commentLength = view.getUint16(offset + 32, true);
    const localOffset = view.getUint32(offset + 42, true);
    const name = new TextDecoder('utf-8').decode(bytes.subarray(offset + 46, offset + 46 + nameLength));
    entries.push({ name, method, compressedSize, uncompressedSize, localOffset });
    offset += 46 + nameLength + extraLength + commentLength;
  }
  return entries;
}

function localDataOffset(view: DataView, entry: ZipEntry): number {
  const offset = entry.localOffset;
  if (view.getUint32(offset, true) !== ZIP_LOCAL) {
    throw new NpzFormatError(entry.name, '本地文件头签名非法');
  }
  const nameLength = view.getUint16(offset + 26, true);
  const extraLength = view.getUint16(offset + 28, true);
  return offset + 30 + nameLength + extraLength;
}

async function inflateRaw(bytes: Uint8Array): Promise<Uint8Array> {
  const stream = new Blob([bytes as BlobPart]).stream();
  const decompressor = (
    globalThis as unknown as { DecompressionStream?: new (format: string) => TransformStream<Uint8Array, Uint8Array> }
  ).DecompressionStream;
  if (!decompressor) {
    throw new NpzFormatError('<zip>', '本浏览器不支持 DecompressionStream；无法解压 deflate 存储的 npz 成员');
  }
  const piped = stream.pipeThrough(new decompressor('deflate-raw'));
  const chunks: Uint8Array[] = [];
  const reader = piped.getReader();
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    if (value) chunks.push(value);
  }
  const total = chunks.reduce((sum, chunk) => sum + chunk.byteLength, 0);
  const out = new Uint8Array(total);
  let cursor = 0;
  for (const chunk of chunks) {
    out.set(chunk, cursor);
    cursor += chunk.byteLength;
  }
  return out;
}

/** 只解析 NPY 头，返回 `descr` / `fortran_order` / `shape` 与数据起点。 */
function parseNpyHeader(bytes: Uint8Array, key: string): {
  descr: string;
  fortranOrder: boolean;
  shape: number[];
  dataOffset: number;
} {
  if (bytes.byteLength < 10) throw new NpzFormatError(key, '成员太短，不是 npy');
  for (let index = 0; index < NPY_MAGIC.length; index += 1) {
    if (bytes[index] !== NPY_MAGIC[index]) throw new NpzFormatError(key, 'npy magic 不匹配');
  }
  const major = bytes[6];
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let headerLength: number;
  let headerStart: number;
  if (major === 1) {
    headerLength = view.getUint16(8, true);
    headerStart = 10;
  } else if (major === 2 || major === 3) {
    headerLength = view.getUint32(8, true);
    headerStart = 12;
  } else {
    throw new NpzFormatError(key, `不支持的 npy 版本 ${major}`);
  }
  const header = new TextDecoder('latin1').decode(bytes.subarray(headerStart, headerStart + headerLength));
  const descrMatch = /'descr'\s*:\s*'([^']*)'/.exec(header);
  const fortranMatch = /'fortran_order'\s*:\s*(True|False)/.exec(header);
  const shapeMatch = /'shape'\s*:\s*\(([^)]*)\)/.exec(header);
  if (!descrMatch || !fortranMatch || !shapeMatch) {
    throw new NpzFormatError(key, `npy 头字段解析失败：${header.trim().slice(0, 160)}`);
  }
  const shape = shapeMatch[1]
    .split(',')
    .map((part) => part.trim())
    .filter((part) => part.length > 0)
    .map((part) => Number.parseInt(part, 10));
  return {
    descr: descrMatch[1],
    fortranOrder: fortranMatch[1] === 'True',
    shape,
    dataOffset: headerStart + headerLength,
  };
}

const ELEMENT_SIZES: Record<string, number> = {
  f8: 8,
  f4: 4,
  i8: 8,
  i4: 4,
  i2: 2,
  i1: 1,
  u4: 4,
  u2: 2,
  u1: 1,
  b1: 1,
};

function bytesPerElement(descr: string, key: string): number {
  const kind = descr.replace(/^[<|=]/, '');
  const size = ELEMENT_SIZES[kind];
  if (!size) throw new NpzFormatError(key, `不支持的 dtype ${descr}`);
  return size;
}

function typedArrayFor(descr: string, buffer: ArrayBufferLike, byteOffset: number, length: number, key: string): NpyTypedArray {  if (descr.startsWith('>')) {
    throw new NpzFormatError(key, `大端数组 ${descr} 不支持：字节序读错会把数值弄错，宁可不显示`);
  }
  const kind = descr.replace(/^[<|=]/, '');
  switch (kind) {
    case 'f8':
      return new Float64Array(buffer, byteOffset, length);
    case 'f4':
      return new Float32Array(buffer, byteOffset, length);
    case 'i4':
      return new Int32Array(buffer, byteOffset, length);
    case 'i2':
      return new Int16Array(buffer, byteOffset, length);
    case 'i1':
      return new Int8Array(buffer, byteOffset, length);
    case 'u4':
      return new Uint32Array(buffer, byteOffset, length);
    case 'u2':
      return new Uint16Array(buffer, byteOffset, length);
    case 'u1':
    case 'b1':
      return new Uint8Array(buffer, byteOffset, length);
    case 'i8': {
      // 目标 ES2020 且 UI 不需要 64 位整数精度之外的语义；用 float64 承载，超出 2^53 会失真，
      // 因此这里只接受安全范围内的值，否则显式报错。
      const source = new DataView(buffer, byteOffset, length * 8);
      const out = new Float64Array(length);
      for (let index = 0; index < length; index += 1) {
        const raw = source.getBigInt64(index * 8, true);
        const value = Number(raw);
        if (!Number.isSafeInteger(value)) {
          throw new NpzFormatError(key, `int64 成员含超出 2^53 的索引（第 ${index} 项），本读取器不静默截断`);
        }
        out[index] = value;
      }
      return out;
    }
    default:
      throw new NpzFormatError(key, `不支持的 dtype ${descr}`);
  }
}

function decodeNpy(bytes: Uint8Array, key: string): NpyArray {
  const header = parseNpyHeader(bytes, key);
  if (header.fortranOrder) {
    throw new NpzFormatError(key, 'Fortran 序（列优先）数组不支持：按行优先读取会把数值读错');
  }
  const count = header.shape.reduce((product, value) => product * value, 1);
  const elementSize = bytesPerElement(header.descr, key);
  let source = bytes;
  if ((bytes.byteOffset + header.dataOffset) % elementSize !== 0) {
    // 兜底：数据段没有按元素大小对齐时先复制到独立缓冲，绝不静默按错误偏移读数。
    source = new Uint8Array(bytes);
  }
  const view = new DataView(source.buffer, source.byteOffset, source.byteLength);
  const data = typedArrayFor(header.descr, view.buffer, source.byteOffset + header.dataOffset, count, key);
  return { key, dtype: header.descr, shape: header.shape, data };
}

/** 解析一个真实 npz 字节流；返回按数组名索引的数值表。 */
export async function readNpz(buffer: ArrayBuffer): Promise<Map<string, NpyArray>> {
  const bytes = new Uint8Array(buffer);
  const view = new DataView(buffer);
  const entries = readCentralDirectory(view, bytes);
  const arrays = new Map<string, NpyArray>();
  for (const entry of entries) {
    if (entry.name.endsWith('/')) continue;
    if (!entry.name.endsWith('.npy')) continue;
    const start = localDataOffset(view, entry);
    const raw = bytes.subarray(start, start + entry.compressedSize);
    let payload: Uint8Array;
    if (entry.method === 0) {
      // 关键：必须拷贝成 byteOffset=0 的独立缓冲。npz 成员在 zip 里的起始偏移是任意的，
      // 直接 subarray 会让 npy 数据段的绝对偏移不是 8 的倍数，Float64Array 视图会抛 RangeError。
      payload = new Uint8Array(raw);
    } else if (entry.method === 8) {
      payload = await inflateRaw(raw);
    } else {
      throw new NpzFormatError(entry.name, `不支持的 ZIP 压缩方法 ${entry.method}`);
    }
    if (payload.byteLength !== entry.uncompressedSize) {
      throw new NpzFormatError(
        entry.name,
        `成员长度与中央目录不一致（${payload.byteLength} ≠ ${entry.uncompressedSize}）`,
      );
    }
    const key = entry.name.slice(0, -'.npy'.length);
    arrays.set(key, decodeNpy(payload, key));
  }
  return arrays;
}

/** 便捷读取：`payload.frames.0.depth_z` 这类名字在 TS 里用下标记更容易，故提供取值器。 */
export function npzGet(arrays: Map<string, NpyArray>, key: string): NpyArray | undefined {
  return arrays.get(key);
}

export function npzNumber(arrays: Map<string, NpyArray>, key: string): number | null {
  const found = arrays.get(key);
  if (!found || found.data.length === 0) return null;
  return Number(found.data[0]);
}

export function npzNumbers(arrays: Map<string, NpyArray>, key: string): number[] | null {
  const found = arrays.get(key);
  if (!found) return null;
  return Array.from(found.data, (value) => Number(value));
}

/** 2D 成员（单通道）读取；形状不符时返回 null 而不是猜。 */
export function npzScalar2d(
  arrays: Map<string, NpyArray>,
  key: string,
): { width: number; height: number; data: NpyTypedArray } | null {
  const found = arrays.get(key);
  if (!found || found.shape.length !== 2) return null;
  return { width: found.shape[1], height: found.shape[0], data: found.data };
}

/** `(N, 3)` 点集读取；形状不符时返回 null。 */
export function npzPoints(arrays: Map<string, NpyArray>, key: string): Float64Array | null {
  const found = arrays.get(key);
  if (!found || found.shape.length !== 2 || found.shape[1] !== 3) return null;
  const out = new Float64Array(found.data.length);
  for (let index = 0; index < found.data.length; index += 1) out[index] = Number(found.data[index]);
  return out;
}

/** `(N,)` 一维成员读取（bool/uint8 mask 会转成 0/1 数值）。 */
export function npzVector(arrays: Map<string, NpyArray>, key: string): Float64Array | null {
  const found = arrays.get(key);
  if (!found || found.shape.length !== 1) return null;
  const out = new Float64Array(found.data.length);
  for (let index = 0; index < found.data.length; index += 1) out[index] = Number(found.data[index]);
  return out;
}

/** `(N, 3)` 面索引读取（int32）。 */
export function npzFaces(arrays: Map<string, NpyArray>, key: string): Int32Array | null {
  const found = arrays.get(key);
  if (!found || found.shape.length !== 2 || found.shape[1] !== 3) return null;
  const out = new Int32Array(found.data.length);
  for (let index = 0; index < found.data.length; index += 1) out[index] = Number(found.data[index]);
  return out;
}
