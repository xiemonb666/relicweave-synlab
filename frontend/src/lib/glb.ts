/**
 * 派生展示 GLB 的加载与测量工具（SceneViewport / CompareViewport 共用）。
 *
 * 约定（计划 20.14.1）：
 * * 后端 `display_lod` 任务导出的 GLB 是 **米 / Y-up** 展示几何；
 * * 权威几何是 **毫米 / Z-up**，只能通过 `display_to_authority` 一次性换算；
 * * 因此这里测出来的包围盒**先按展示米记录**，再由调用方转成 mm 显示。
 */

import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';

import { ApiError, API_ROOT } from '../api/client';
import type { AssetRecord } from '../api/types';
import { displayExtentToAuthority, type Vec3 } from './display';

/** 派生展示 GLB 的真实资产 role（`synlab/roles.py::ROLE_DISPLAY_LOD`）。 */
export const DISPLAY_LOD_ROLE = 'display_lod_glb';

/**
 * 从资产的 `files` 映射里挑出 GLB 的 payload key。
 *
 * 后端真实产出的 key 是 `glb`（`handlers.run_display_lod` 提交 `payload={"glb": bytes}`），
 * 而 `synlab/api/routers/assets.py::FILE_KEY_PRIORITY` 里的 `"glb.bin"` 并不会命中。
 * 因此这里按“明确候选 → 后缀匹配 → 唯一候选”的顺序挑，避免猜错文件。
 */
export function pickGlbKey(files: Record<string, string> | undefined | null): string | null {
  if (!files) return null;
  const keys = Object.keys(files);
  if (keys.length === 0) return null;
  for (const candidate of ['glb', 'glb.bin', 'mesh.glb', 'scene.glb']) {
    if (keys.includes(candidate)) return candidate;
  }
  const glbish = keys.find((key) => /\.glb$/i.test(key) || /glb/i.test(key));
  if (glbish) return glbish;
  return keys.length === 1 ? keys[0] : null;
}

export interface GlbRef {
  assetId: string;
  role: string;
  fileKey: string;
}

/**
 * GLB 的取数来源。
 *
 * * `assets` —— 会话资产库的 `GET /assets/{id}/files/{role}`（U02–U12 用）；
 * * `showcase` —— 只读展示路由 `GET /showcase/asset/{id}/glb`（U13 用，资产住在
 *   独立的演示资产库里，不在会话 store_root 里）。
 */
export type GlbSource = 'assets' | 'showcase';

/** 生成 GLB 的下载 URL；两个来源的 key 语义不同，因此集中在这里构造，调用方不拼字符串。 */
export function glbFileUrl(
  assetId: string,
  role: string,
  fileKey: string,
  source: GlbSource = 'assets',
): string {
  if (source === 'showcase') {
    return `${API_ROOT}/showcase/asset/${encodeURIComponent(assetId)}/glb?name=${encodeURIComponent(
      fileKey,
    )}&download=false`;
  }
  return `${API_ROOT}/assets/${encodeURIComponent(assetId)}/files/${encodeURIComponent(
    role,
  )}?key=${encodeURIComponent(fileKey)}&download=false`;
}

/** 由真实资产记录得到可视口使用的 (assetId, role, fileKey)；不能确定时返回 null 并给出原因。 */
export function glbRefFrom(asset: AssetRecord | null | undefined): GlbRef | null {
  if (!asset) return null;
  const key = pickGlbKey(asset.files);
  if (!key) return null;
  return { assetId: asset.asset_id, role: asset.role, fileKey: key };
}

export function describeGlbRefFailure(asset: AssetRecord | null | undefined): string {
  if (!asset) return '未选择资产';
  const keys = Object.keys(asset.files ?? {});
  return `资产 ${asset.asset_id}（role=${asset.role}）的 payload key 为 [${
    keys.join(', ') || '空'
  }]，无法确定 GLB 文件；请确认它是 display_lod_glb 派生资产`;
}

/** GLB 里一个展示材质分组的真实三角面数（名字来自 glTF ``material.name``）。 */
export interface GlbMaterialGroup {
  /** glTF 材质名；GLB 没写名字时用 ``'(未命名材质)'``。 */
  material: string;
  /** 该材质在本次加载的几何里覆盖的三角面数（真实索引计数，不是估计）。 */
  triangles: number;
  /** 该材质的 baseColorFactor（十六进制，无颜色信息时为 null）——用于图例色块。 */
  colorHex: string | null;
}

export interface GlbMeasurement {
  assetId: string;
  role: string;
  fileKey: string;
  bytes: number;
  serverSha256: string | null;
  serverHashVerified: string | null;
  clientSha256: string | null;
  unit: string;
  frame: string;
  qaStatus: string;
  /** 展示空间包围盒尺寸（米 / Y-up）。 */
  displayExtentM: Vec3;
  /** 展示空间包围盒中心（米 / Y-up）。 */
  displayCenterM: Vec3;
  /** 由展示包围盒换算回的权威尺寸（毫米 / Z-up）。 */
  authorityExtentMm: Vec3;
  meshCount: number;
  triangleCount: number;
  /** 逐材质的真实三角面数（断面分色图例的数据源）。 */
  materialGroups: GlbMaterialGroup[];
  /** 带 ``NORMAL`` 属性的 mesh 数；没有 NORMAL 时 three.js 会 flatShading（每面平色块）。 */
  meshesWithNormal: number;
  /** 缺 ``NORMAL`` 的 mesh 数（>0 就是真的在走 flatShading，页面必须照实说）。 */
  meshesWithoutNormal: number;
}

export interface LoadedGlb {
  object: THREE.Group;
  measurement: GlbMeasurement;
}

async function sha256Of(buffer: ArrayBuffer): Promise<string | null> {
  try {
    if (!globalThis.crypto?.subtle) return null;
    const digest = await globalThis.crypto.subtle.digest('SHA-256', buffer);
    return `sha256:${Array.from(new Uint8Array(digest))
      .map((byte) => byte.toString(16).padStart(2, '0'))
      .join('')}`;
  } catch {
    return null;
  }
}

async function raiseFileError(
  response: Response,
  assetId: string,
  role: string,
  url?: string,
): Promise<never> {
  let code = `HTTP_${response.status}`;
  let message = `HTTP ${response.status} ${response.statusText}`;
  let stage = 'assets.files';
  let requestId = response.headers.get('X-Request-Id') ?? '';
  let details: Record<string, unknown> = {};
  try {
    const body = (await response.json()) as { error?: Record<string, unknown> };
    if (body?.error) {
      code = String(body.error.code ?? code);
      message = String(body.error.message ?? message);
      stage = String(body.error.stage ?? stage);
      requestId = String(body.error.request_id ?? requestId);
      details = (body.error.details as Record<string, unknown>) ?? {};
    }
  } catch {
    /* 非 JSON 错误体：保留 HTTP 状态 */
  }
  throw new ApiError(
    {
      code,
      status: response.status,
      stage,
      message,
      retryable: response.status >= 500,
      details,
      evidence_refs: [],
      request_id: requestId,
    },
    url ?? `/assets/${assetId}/files/${role}`,
  );
}

/** 拉取并解析一个派生 GLB，返回 three 对象与真实测量值。 */
export async function loadDerivedGlb(
  assetId: string,
  options: { role?: string; fileKey?: string; signal?: AbortSignal; source?: GlbSource } = {},
): Promise<LoadedGlb> {
  const role = options.role ?? DISPLAY_LOD_ROLE;
  const fileKey = options.fileKey ?? 'glb';
  const source: GlbSource = options.source ?? 'assets';
  const url = glbFileUrl(assetId, role, fileKey, source);
  const response = await fetch(url, { signal: options.signal, cache: 'no-store' });
  if (!response.ok) await raiseFileError(response, assetId, role, url);
  const buffer = await response.arrayBuffer();
  const clientSha256 = await sha256Of(buffer);

  const loader = new GLTFLoader();
  const gltf = await new Promise<{ scene: THREE.Group }>((resolve, reject) => {
    loader.parse(
      buffer,
      '',
      (result) => resolve(result as unknown as { scene: THREE.Group }),
      (event) => reject(new Error(`GLTFLoader 解析失败：${(event as ErrorEvent)?.message ?? String(event)}`)),
    );
  });

  let meshCount = 0;
  let triangleCount = 0;
  let meshesWithNormal = 0;
  let meshesWithoutNormal = 0;
  const groups = new Map<string, GlbMaterialGroup>();
  const box = new THREE.Box3();
  gltf.scene.updateMatrixWorld(true);
  gltf.scene.traverse((child) => {
    const mesh = child as THREE.Mesh;
    if (!mesh.isMesh) return;
    meshCount += 1;
    const geometry = mesh.geometry as THREE.BufferGeometry;
    const index = geometry.getIndex();
    const position = geometry.getAttribute('position');
    const meshTriangles = index ? index.count / 3 : position ? position.count / 3 : 0;
    triangleCount += meshTriangles;
    if (geometry.getAttribute('normal')) meshesWithNormal += 1;
    else meshesWithoutNormal += 1;
    for (const item of Array.isArray(mesh.material) ? mesh.material : [mesh.material]) {
      const standard = item as THREE.MeshStandardMaterial | undefined;
      const name = standard?.name ? standard.name : '(未命名材质)';
      const existing = groups.get(name);
      const colorHex = standard?.color ? `#${standard.color.getHexString()}` : null;
      if (existing) {
        existing.triangles += meshTriangles;
      } else {
        groups.set(name, { material: name, triangles: meshTriangles, colorHex });
      }
    }
    geometry.computeBoundingBox();
    if (geometry.boundingBox) box.union(geometry.boundingBox.clone().applyMatrix4(mesh.matrixWorld));
  });

  const size = new THREE.Vector3();
  const center = new THREE.Vector3();
  box.getSize(size);
  box.getCenter(center);
  const displayExtentM: Vec3 = [size.x, size.y, size.z];
  const displayCenterM: Vec3 = [center.x, center.y, center.z];

  return {
    object: gltf.scene,
    measurement: {
      assetId,
      role,
      fileKey,
      bytes: buffer.byteLength,
      serverSha256: response.headers.get('X-SynLab-File-Sha256'),
      serverHashVerified: response.headers.get('X-SynLab-Hash-Verified'),
      clientSha256,
      unit: response.headers.get('X-SynLab-Unit') ?? 'unknown',
      frame: response.headers.get('X-SynLab-Frame') ?? 'unknown',
      qaStatus: response.headers.get('X-SynLab-QA-Status') ?? 'unknown',
      displayExtentM,
      displayCenterM,
      authorityExtentMm: displayExtentToAuthority(displayExtentM),
      meshCount,
      triangleCount: Math.round(triangleCount),
      materialGroups: [...groups.values()]
        .map((group) => ({ ...group, triangles: Math.round(group.triangles) }))
        .sort((a, b) => b.triangles - a.triangles),
      meshesWithNormal,
      meshesWithoutNormal,
    },
  };
}

/** 递归销毁 GPU 资源。 */
export function disposeObject(object: THREE.Object3D | null): void {
  if (!object) return;
  object.traverse((child) => {
    const mesh = child as THREE.Mesh;
    mesh.geometry?.dispose();
    const material = mesh.material as THREE.Material | THREE.Material[] | undefined;
    for (const item of Array.isArray(material) ? material : material ? [material] : []) {
      for (const value of Object.values(item as unknown as Record<string, unknown>)) {
        if (value instanceof THREE.Texture) value.dispose();
      }
      item.dispose();
    }
  });
}
