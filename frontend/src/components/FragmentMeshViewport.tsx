/**
 * FragmentMeshViewport —— 从**权威碎片数组**（`fragment_mesh` 的 `arrays.npz`）直接渲染三维碎片，
 * 支持「原位 / 爆炸」与**断面高亮**。
 *
 * 与 `SceneViewport` / `FragmentAssemblyViewport` 的区别（为什么不能直接复用）：
 * 那两个视口渲染的是派生展示 GLB（米 / Y-up），断面分色依赖 GLB 导出时按材质分好的 primitive。
 * 本视口渲染权威 mm / Z-up 的逐面属性本身，因此可以：
 * * 按后端真实写入的 `mesh.face__origin_kind`（0=mother_surface / 1=interface / 2=ambiguous，
 *   见 `synlab/schemas/runtime.py::ORIGIN_*`）逐面着色；
 * * 按 `mesh.face__interface_id` 逐个断面对比色高亮；
 * * 按 `mesh.face__component_id`（不存在时退回 meta.component_id）做爆炸位移。
 *
 * 诚实规则：
 * * **没有** `mesh.face__origin_kind` 就显示「该资产缺断面属性」并且不做任何着色 —— 不会
 *   用几何法向或人工颜色假装断面存在；
 * * 爆炸是纯展示变换，不写回任何资产；
 * * 所有计数（面数 / 各 origin_kind 面数 / interface_id 个数）都是本页从数组里数出来的真实值，
 *   与 `qa.parent_qa` 里的后端计数并列显示以便互相核对。
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

import { loadAssetArrays } from '../lib/assetData';
import { npzFaces, npzPoints, npzVector } from '../lib/npz';
import { formatBytes, truncate } from '../lib/format';
import { Badge, EmptyState, ErrorState, LoadingState } from './states';
import type { AssetRecord } from '../api/types';

/** `synlab/schemas/runtime.py` 里的 ORIGIN_* 常量（权威语义）。 */
export const ORIGIN_MOTHER_SURFACE = 0;
export const ORIGIN_INTERFACE = 1;
export const ORIGIN_AMBIGUOUS = 2;

export const ORIGIN_NAMES: Record<number, string> = {
  [ORIGIN_MOTHER_SURFACE]: 'mother_surface（母体原表面）',
  [ORIGIN_INTERFACE]: 'interface（新断面）',
  [ORIGIN_AMBIGUOUS]: 'ambiguous（未判定）',
};

export const ORIGIN_COLORS: Record<number, string> = {
  [ORIGIN_MOTHER_SURFACE]: '#8c8c94',
  [ORIGIN_INTERFACE]: '#ff7a45',
  [ORIGIN_AMBIGUOUS]: '#f5d442',
};

export interface FragmentFaceStats {
  faces: number;
  vertices: number;
  /** 逐 origin_kind 的真实面数（键就是后端写入的数值）。 */
  originCounts: Map<number, number>;
  interfaceIds: number[];
  interfaceFaceCounts: Map<number, number>;
  components: number[];
  hasOriginKind: boolean;
  hasInterfaceId: boolean;
  hasComponentId: boolean;
  /** 权威包围盒尺寸（mm / Z-up）。 */
  extentMm: [number, number, number];
  keys: string[];
}

export interface LoadedFragmentMesh {
  assetId: string;
  role: string;
  stats: FragmentFaceStats;
  /** 逐面属性数组（与 faces 同长度）。 */
  originKind: Float64Array | null;
  interfaceId: Float64Array | null;
  componentId: Float64Array | null;
  bytes: number;
  serverSha256: string | null;
  unit: string;
  frame: string;
  qaStatus: string;
}

export interface FragmentMeshViewportProps {
  asset: AssetRecord | null;
  /** 爆炸位移（mm，权威单位）；0 = 原位。 */
  explodeMm?: number;
  /** 断面高亮：`null` = 按 origin_kind 分色；数字 = 只把该 interface_id 高亮成红色。 */
  highlightInterface?: number | null;
  height?: number;
  title?: string;
  /** 供父组件读取真实统计（用于“实测片数/断面数”等表格）。 */
  onLoaded?: (loaded: LoadedFragmentMesh | null) => void;
}

/** 从真实 npz 数组里解析出可渲染的碎片 + 真实统计。 */
export function readFragmentMesh(
  asset: AssetRecord,
  arrays: Map<string, import('../lib/npz').NpyArray>,
  meta: { bytes: number; serverSha256: string | null; unit: string; frame: string; qaStatus: string; role: string },
): { positions: Float32Array; faces: Int32Array; loaded: LoadedFragmentMesh } | null {
  const vertices = npzPoints(arrays, 'mesh.vertices');
  const faces = npzFaces(arrays, 'mesh.faces');
  if (!vertices || !faces) return null;
  const faceCount = Math.floor(faces.length / 3);
  const originKind = npzVector(arrays, 'mesh.face__origin_kind');
  const interfaceId = npzVector(arrays, 'mesh.face__interface_id');
  const componentId = npzVector(arrays, 'mesh.face__component_id');

  const originCounts = new Map<number, number>();
  const interfaceFaceCounts = new Map<number, number>();
  const components = new Set<number>();
  if (originKind && originKind.length === faceCount) {
    for (let index = 0; index < faceCount; index += 1) {
      const kind = originKind[index];
      originCounts.set(kind, (originCounts.get(kind) ?? 0) + 1);
    }
  }
  if (interfaceId && interfaceId.length === faceCount) {
    for (let index = 0; index < faceCount; index += 1) {
      const id = interfaceId[index];
      if (id < 0) continue;
      interfaceFaceCounts.set(id, (interfaceFaceCounts.get(id) ?? 0) + 1);
    }
  }
  if (componentId && componentId.length === faceCount) {
    for (let index = 0; index < faceCount; index += 1) components.add(componentId[index]);
  } else if (typeof asset.meta.component_id === 'number') {
    components.add(asset.meta.component_id);
  }

  // 权威 mm / Z-up → 视口 Y-up：绕 X 轴 -90°，与 SceneViewport 的展示约定一致。
  const positions = new Float32Array(vertices.length);
  let minX = Infinity; let minY = Infinity; let minZ = Infinity;
  let maxX = -Infinity; let maxY = -Infinity; let maxZ = -Infinity;
  for (let index = 0; index < vertices.length; index += 3) {
    const x = vertices[index];
    const y = vertices[index + 1];
    const z = vertices[index + 2];
    positions[index] = x;
    positions[index + 1] = z;
    positions[index + 2] = -y;
    if (x < minX) minX = x;
    if (y < minY) minY = y;
    if (z < minZ) minZ = z;
    if (x > maxX) maxX = x;
    if (y > maxY) maxY = y;
    if (z > maxZ) maxZ = z;
  }

  const stats: FragmentFaceStats = {
    faces: faceCount,
    vertices: Math.floor(vertices.length / 3),
    originCounts,
    interfaceIds: [...interfaceFaceCounts.keys()].sort((a, b) => a - b),
    interfaceFaceCounts,
    components: [...components].sort((a, b) => a - b),
    hasOriginKind: Boolean(originKind && originKind.length === faceCount),
    hasInterfaceId: Boolean(interfaceId && interfaceId.length === faceCount),
    hasComponentId: Boolean(componentId && componentId.length === faceCount),
    extentMm: [maxX - minX, maxY - minY, maxZ - minZ],
    keys: [...arrays.keys()].sort(),
  };

  const loaded: LoadedFragmentMesh = {
    assetId: asset.asset_id,
    role: meta.role,
    stats,
    originKind: originKind && originKind.length === faceCount ? originKind : null,
    interfaceId: interfaceId && interfaceId.length === faceCount ? interfaceId : null,
    componentId: componentId && componentId.length === faceCount ? componentId : null,
    bytes: meta.bytes,
    serverSha256: meta.serverSha256,
    unit: meta.unit,
    frame: meta.frame,
    qaStatus: meta.qaStatus,
  };
  return { positions, faces: Int32Array.from(faces), loaded };
}

/**
 * 逐面分 primitive：每个 `(origin_kind, interface_id)` 组合一个材质组。
 * 用真实面的顺序重建索引，确保“显示三角面数”等于权威面数（不做任何抽稀）。
 */
export function buildFragmentGeometry(
  positions: Float32Array,
  faces: Int32Array,
  groupKey: (faceIndex: number) => string,
): { geometry: THREE.BufferGeometry; groups: Array<{ key: string; triangles: number; indices: number[] }> } {
  const faceCount = Math.floor(faces.length / 3);
  const buckets = new Map<string, number[]>();
  for (let face = 0; face < faceCount; face += 1) {
    const key = groupKey(face);
    const list = buckets.get(key) ?? [];
    list.push(face);
    buckets.set(key, list);
  }
  const indices: number[] = [];
  const groups: Array<{ key: string; triangles: number; indices: number[] }> = [];
  for (const key of [...buckets.keys()].sort()) {
    const faceList = buckets.get(key) as number[];
    const start = indices.length;
    for (const face of faceList) {
      indices.push(faces[face * 3], faces[face * 3 + 1], faces[face * 3 + 2]);
    }
    groups.push({ key, triangles: faceList.length, indices: indices.slice(start) });
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geometry.setIndex(indices);
  // 非索引化语义下的逐面平坦法线：不合并顶点，所以每个三角面拿到自己的法向，
  // 断面与原表面之间的折痕不会被平滑掉。
  geometry.computeVertexNormals();
  return { geometry, groups };
}

function colorFor(key: string, highlight: number | null): string {
  const [kindRaw, interfaceRaw] = key.split('|');
  const kind = Number(kindRaw);
  const interfaceId = Number(interfaceRaw);
  if (highlight !== null && Number.isFinite(interfaceId)) {
    return interfaceId === highlight ? '#ff2d55' : '#5a5a63';
  }
  if (kind === ORIGIN_INTERFACE && Number.isFinite(interfaceId) && interfaceId >= 0) {
    // interface 面按 id 在橙→紫之间取一个**确定性**色相（图例里逐个列出真实 id）。
    const hue = (interfaceId * 47) % 360;
    const color = new THREE.Color();
    color.setHSL(hue / 360, 0.65, 0.58);
    return `#${color.getHexString()}`;
  }
  return ORIGIN_COLORS[kind] ?? '#b0b0b8';
}

export function FragmentMeshViewport({
  asset,
  explodeMm = 0,
  highlightInterface = null,
  height = 360,
  title = '碎片三维视图（权威数组）',
  onLoaded,
}: FragmentMeshViewportProps) {
  const mountRef = useRef<HTMLDivElement>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const sceneRef = useRef<THREE.Scene | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const controlsRef = useRef<OrbitControls | null>(null);
  const rootRef = useRef<THREE.Group | null>(null);
  const frameRef = useRef<number | null>(null);
  const payloadRef = useRef<{ positions: Float32Array; faces: Int32Array; loaded: LoadedFragmentMesh } | null>(null);
  const callbackRef = useRef(onLoaded);
  callbackRef.current = onLoaded;

  const [status, setStatus] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle');
  const [error, setError] = useState<unknown>(null);
  const [loaded, setLoaded] = useState<LoadedFragmentMesh | null>(null);
  const [legend, setLegend] = useState<Array<{ key: string; triangles: number; color: string }>>([]);
  const [wireframe, setWireframe] = useState(false);
  const [missingAttributes, setMissingAttributes] = useState<string[]>([]);

  /* ------------------------------------------------------------ 渲染器（挂载一次） */
  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return undefined;
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x11151c);
    sceneRef.current = scene;
    const camera = new THREE.PerspectiveCamera(45, 1, 0.001, 50000);
    camera.position.set(0.3, 0.24, 0.3);
    cameraRef.current = camera;
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    mount.appendChild(renderer.domElement);
    rendererRef.current = renderer;
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.12;
    controlsRef.current = controls;
    scene.add(new THREE.AmbientLight(0xffffff, 0.8));
    const key = new THREE.DirectionalLight(0xffffff, 1.5);
    key.position.set(0.5, 1, 0.8);
    scene.add(key);
    const fill = new THREE.DirectionalLight(0x88aaff, 0.5);
    fill.position.set(-0.6, 0.3, -0.7);
    scene.add(fill);
    const resize = () => {
      const width = mount.clientWidth || 480;
      const heightPx = mount.clientHeight || height;
      renderer.setSize(width, heightPx, false);
      camera.aspect = width / heightPx;
      camera.updateProjectionMatrix();
    };
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(mount);
    const tick = () => {
      frameRef.current = window.requestAnimationFrame(tick);
      controls.update();
      renderer.render(scene, camera);
    };
    tick();
    return () => {
      if (frameRef.current !== null) window.cancelAnimationFrame(frameRef.current);
      observer.disconnect();
      controls.dispose();
      if (rootRef.current) {
        scene.remove(rootRef.current);
        rootRef.current.traverse((child) => {
          const mesh = child as THREE.Mesh;
          if (mesh.isMesh) {
            mesh.geometry.dispose();
            const material = mesh.material as THREE.Material | THREE.Material[];
            for (const entry of Array.isArray(material) ? material : [material]) entry.dispose();
          }
        });
        rootRef.current = null;
      }
      renderer.dispose();
      if (renderer.domElement.parentElement === mount) mount.removeChild(renderer.domElement);
      rendererRef.current = null;
      sceneRef.current = null;
      cameraRef.current = null;
      controlsRef.current = null;
    };
  }, [height]);

  /* ------------------------------------------------------------ 载入权威数组 */
  const assetId = asset?.asset_id ?? null;
  useEffect(() => {
    const scene = sceneRef.current;
    const camera = cameraRef.current;
    const controls = controlsRef.current;
    if (!scene || !camera || !controls) return undefined;
    if (!assetId || !asset) {
      payloadRef.current = null;
      setLoaded(null);
      setLegend([]);
      setStatus('idle');
      callbackRef.current?.(null);
      return undefined;
    }
    let cancelled = false;
    setStatus('loading');
    setError(null);
    const load = async () => {
      try {
        const arrays = await loadAssetArrays(asset.asset_id, asset.role, 'arrays');
        if (cancelled) return;
        const parsed = readFragmentMesh(asset, arrays.arrays, {
          bytes: arrays.bytes,
          serverSha256: arrays.headers['x-synlab-file-sha256'] ?? null,
          unit: asset.unit,
          frame: asset.frame,
          qaStatus: asset.qa_status,
          role: asset.role,
        });
        if (!parsed) {
          setMissingAttributes(['mesh.vertices', 'mesh.faces']);
          setError(new Error(
            `该资产缺 mesh.vertices / mesh.faces；实际键：${[...arrays.arrays.keys()].join(', ') || '（空）'}`,
          ));
          setStatus('error');
          return;
        }
        payloadRef.current = parsed;
        setMissingAttributes([]);
        setLoaded(parsed.loaded);
        setStatus('ready');
        callbackRef.current?.(parsed.loaded);
      } catch (caught) {
        if (cancelled) return;
        if (caught instanceof DOMException && caught.name === 'AbortError') return;
        setError(caught);
        setStatus('error');
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assetId, asset?.role]);

  /* ------------------------------------------------------------ 建几何（含断面分组） */
  useEffect(() => {
    const scene = sceneRef.current;
    const camera = cameraRef.current;
    const controls = controlsRef.current;
    const payload = payloadRef.current;
    if (!scene || !camera || !controls) return undefined;
    if (rootRef.current) {
      scene.remove(rootRef.current);
      rootRef.current.traverse((child) => {
        const mesh = child as THREE.Mesh;
        if (mesh.isMesh) {
          mesh.geometry.dispose();
          const material = mesh.material as THREE.Material | THREE.Material[];
          for (const entry of Array.isArray(material) ? material : [material]) entry.dispose();
        }
      });
      rootRef.current = null;
    }
    if (!payload || status !== 'ready') return undefined;

    const keyOf = (face: number): string => {
      const kind = payload.loaded.originKind ? payload.loaded.originKind[face] : -1;
      const interfaceId = payload.loaded.interfaceId ? payload.loaded.interfaceId[face] : -1;
      return `${kind}|${interfaceId}`;
    };
    const { geometry, groups } = buildFragmentGeometry(payload.positions, payload.faces, keyOf);
    const root = new THREE.Group();
    const materials: THREE.Material[] = [];
    // 一个 primitive 一个真实分组：显示三角面数 = 权威面数（不抽稀、不重排）。
    let offset = 0;
    for (const group of groups) {
      const material = new THREE.MeshStandardMaterial({
        color: new THREE.Color(colorFor(group.key, highlightInterface)),
        metalness: 0.05,
        roughness: 0.72,
        side: THREE.DoubleSide,
      });
      materials.push(material);
      geometry.addGroup(offset, group.indices.length, materials.length - 1);
      offset += group.indices.length;
    }
    const mesh = new THREE.Mesh(geometry, materials);
    mesh.name = `fragment:${payload.loaded.assetId}`;
    root.add(mesh);
    scene.add(root);
    rootRef.current = root;

    setLegend(groups.map((group) => ({
      key: group.key,
      triangles: group.triangles,
      color: colorFor(group.key, highlightInterface),
    })));

    // 相机按权威包围盒自适应（单位 mm，视口里 1000 mm = 1 单位）。
    const box = new THREE.Box3().setFromObject(mesh);
    const size = new THREE.Vector3();
    const center = new THREE.Vector3();
    box.getSize(size);
    box.getCenter(center);
    mesh.position.sub(center);
    const radius = Math.max(size.length() / 2, 1);
    const distance = (radius / Math.tan((camera.fov * Math.PI) / 360)) * 1.7;
    camera.position.set(distance * 0.7, distance * 0.55, distance * 0.8);
    camera.near = Math.max(0.01, radius / 500);
    camera.far = Math.max(1000, radius * 100);
    camera.updateProjectionMatrix();
    controls.target.set(0, 0, 0);
    controls.update();
    return undefined;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, loaded?.assetId, highlightInterface]);

  /* ------------------------------------------------------------ 爆炸（纯展示变换） */
  useEffect(() => {
    const payload = payloadRef.current;
    const root = rootRef.current;
    if (!payload || !root) return;
    const mesh = root.children[0] as THREE.Mesh | undefined;
    if (!mesh) return;
    const componentId = payload.loaded.componentId;
    const count = payload.loaded.stats.components.length || 1;
    const positions = mesh.geometry.getAttribute('position') as THREE.BufferAttribute;
    // 爆炸按**面**所属连 component 的质心方向平移；没有 component_id 时按整体质心方向平移。
    const centroids = new Map<number, THREE.Vector3>();
    for (let face = 0; face < payload.loaded.stats.faces; face += 1) {
      const component = componentId ? componentId[face] : 0;
      if (centroids.has(component)) continue;
      const centroid = new THREE.Vector3();
      for (let corner = 0; corner < 3; corner += 1) {
        const vertex = payload.faces[face * 3 + corner];
        centroid.x += positions.getX(vertex);
        centroid.y += positions.getY(vertex);
        centroid.z += positions.getZ(vertex);
      }
      centroids.set(component, centroid.multiplyScalar(1 / 3));
    }
    const source = new Float32Array(payload.positions.length);
    source.set(payload.positions);
    const scale = explodeMm / Math.max(1, count - 1 || 1);
    if (explodeMm > 0) {
      for (let face = 0; face < payload.loaded.stats.faces; face += 1) {
        const component = componentId ? componentId[face] : 0;
        const centroid = centroids.get(component) as THREE.Vector3;
        const direction = centroid.clone();
        if (direction.lengthSq() < 1e-9) direction.set(0, 1, 0);
        direction.normalize().multiplyScalar(scale * (componentId ? 1 : 0.5));
        for (let corner = 0; corner < 3; corner += 1) {
          const vertex = payload.faces[face * 3 + corner];
          positions.setXYZ(
            vertex,
            source[vertex * 3] + direction.x,
            source[vertex * 3 + 1] + direction.y,
            source[vertex * 3 + 2] + direction.z,
          );
        }
      }
    } else {
      // 原位：把每个顶点写回它自己的权威坐标（同一顶点被多个面共享时结果一致）。
      for (let index = 0; index < source.length; index += 3) {
        positions.setXYZ(index / 3, source[index], source[index + 1], source[index + 2]);
      }
    }
    positions.needsUpdate = true;
    mesh.geometry.computeVertexNormals();
    mesh.geometry.computeBoundingSphere();
  }, [explodeMm, status, loaded?.assetId]);

  /* ------------------------------------------------------------ 线框（只改展示） */
  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    root.traverse((child) => {
      const mesh = child as THREE.Mesh;
      if (!mesh.isMesh) return;
      const material = mesh.material as THREE.Material | THREE.Material[];
      for (const entry of Array.isArray(material) ? material : [material]) {
        const standard = entry as THREE.MeshStandardMaterial;
        if ('wireframe' in standard) standard.wireframe = wireframe;
        entry.needsUpdate = true;
      }
    });
  }, [wireframe, status, loaded?.assetId]);

  const stats = loaded?.stats ?? null;
  const originRows = useMemo(() => {
    if (!stats) return [];
    return [...stats.originCounts.entries()].sort((a, b) => a[0] - b[0]);
  }, [stats]);
  const interfaceSum = useMemo(
    () => (stats ? [...stats.interfaceFaceCounts.values()].reduce((sum, value) => sum + value, 0) : 0),
    [stats],
  );

  return (
    <div className="viewport">
      <div className="viewport__head">
        <div className="viewport__title">
          {title}
          <Badge tone="neutral">权威：mm / Z-up</Badge>
          <Badge tone={explodeMm > 0 ? 'warn' : 'ok'}>
            {explodeMm > 0 ? `爆炸（展示位移 ${explodeMm.toFixed(1)} mm）` : '原位'}
          </Badge>
          {stats ? (
            <Badge tone={stats.hasOriginKind ? 'ok' : 'bad'}>
              {stats.hasOriginKind
                ? `断面属性存在（origin_kind 覆盖 ${stats.faces} 面）`
                : '该资产缺断面属性'}
            </Badge>
          ) : null}
        </div>
        <div className="viewport__tools">
          <label className="check">
            <input
              type="checkbox"
              checked={wireframe}
              onChange={(event) => setWireframe(event.target.checked)}
              disabled={status !== 'ready'}
            />
            线框
          </label>
        </div>
      </div>

      <div className="viewport__canvas" ref={mountRef} style={{ height: `${height}px` }} />

      {status === 'loading' ? (
        <div className="viewport__overlay">
          <LoadingState label="正在下载并解码 arrays.npz…" />
        </div>
      ) : null}
      {status === 'idle' ? (
        <div className="viewport__overlay">
          <EmptyState
            title="未选择碎片"
            reason="选择一个 fragment_mesh 资产后，这里从**权威数组**渲染逐面断面属性；没有资产时不画任何示意几何。"
          />
        </div>
      ) : null}
      {status === 'error' ? (
        <div className="viewport__overlay">
          <ErrorState
            error={error}
            compact
            title={missingAttributes.length > 0 ? '该资产缺必需数组' : '无法读取权威碎片数组'}
          />
        </div>
      ) : null}

      {stats ? (
        <div className="viewport__foot">
          <dl className="viewport__info">
            <div>
              <dt>权威面数 / 顶点数</dt>
              <dd className="mono">{stats.faces} / {stats.vertices}</dd>
            </div>
            <div>
              <dt>权威尺寸（mm）</dt>
              <dd className="mono">{stats.extentMm.map((value) => value.toFixed(2)).join(' × ')}</dd>
            </div>
            <div>
              <dt>interface_id 个数</dt>
              <dd className="mono">{stats.interfaceIds.length}</dd>
            </div>
            <div>
              <dt>arrays 字节 / 服务端 sha256</dt>
              <dd className="mono">
                {formatBytes(loaded?.bytes)} · {loaded?.serverSha256 ? truncate(loaded.serverSha256, 18) : '未提供'}
              </dd>
            </div>
            <div>
              <dt>单位 / 坐标系 / QA</dt>
              <dd className="mono">{loaded?.unit} / {loaded?.frame} / {loaded?.qaStatus}</dd>
            </div>
          </dl>

          {!stats.hasOriginKind ? (
            <div className="state state--blocked" role="status">
              <div className="state__title">
                该资产缺断面属性
                <Badge tone="warn">mesh.face__origin_kind 不存在</Badge>
              </div>
              <div className="state__detail">
                本视图不做任何断面着色：没有 <code className="mono">mesh.face__origin_kind</code> 就
                无法区分“新断面 / 母体原表面 / 未判定面”，用几何法向猜一个颜色等于伪造审计结论。
                该资产的真实键：
                <span className="mono">{stats.keys.join(', ')}</span>
              </div>
            </div>
          ) : (
            <div className="surface-legend">
              <div className="surface-legend__title">
                断面图例 —— 分组与计数都是本页从 <code className="mono">mesh.face__origin_kind</code> /{' '}
                <code className="mono">mesh.face__interface_id</code> 数出来的真实值
              </div>
              <ul className="surface-legend__list">
                {originRows.map(([kind, count]) => (
                  <li key={`origin-${kind}`}>
                    <span
                      className="surface-legend__swatch"
                      style={{ background: ORIGIN_COLORS[kind] ?? '#b0b0b8' }}
                      aria-hidden="true"
                    />
                    <span className="surface-legend__label">
                      {ORIGIN_NAMES[kind] ?? `origin_kind=${kind}（后端写入了未在本页登记的值）`}
                    </span>
                    <span className="mono small">面数 {count}</span>
                  </li>
                ))}
              </ul>
              {stats.interfaceIds.length > 0 ? (
                <details>
                  <summary>
                    逐个 interface_id 的实测面数（共 {stats.interfaceIds.length} 个，合计 {interfaceSum} 面）
                  </summary>
                  <table className="table table--tight">
                    <thead>
                      <tr>
                        <th scope="col">interface_id</th>
                        <th scope="col">面数（本页从数组数出）</th>
                        <th scope="col">高亮</th>
                      </tr>
                    </thead>
                    <tbody>
                      {stats.interfaceIds.map((id) => (
                        <tr key={id}>
                          <th scope="row" className="mono">{id}</th>
                          <td className="mono">{stats.interfaceFaceCounts.get(id) ?? 0}</td>
                          <td className="mono small">
                            {highlightInterface === id ? '当前高亮' : '—'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </details>
              ) : null}
              <p className="muted small">
                着色只按后端写入的面属性分组；爆炸位移（{explodeMm.toFixed(1)} mm）与线框都是纯展示变换，
                不写回任何权威资产。图例里出现的面数合计 {legend.reduce((sum, row) => sum + row.triangles, 0)} 面
                = 权威面数 {stats.faces}（无抽稀）。
              </p>
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}
