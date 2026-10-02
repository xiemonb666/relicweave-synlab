/**
 * SceneViewport —— three.js + GLTFLoader 加载**真实派生 GLB**（`role=display_lod`）。
 *
 * 单位契约（计划 20.14.1）：GLB 是**米 / Y-up**，权威数据是**毫米 / Z-up**。
 * 视口里的量尺一律通过 `displayToAuthority` 换算回 mm 再显示；100 mm 解析立方体自检
 * 在 `src/lib/display.ts::cubeSelfCheck`，结果直接摆在面板上。
 *
 * 视口只改**展示状态**（相机、线框、剖切面），从不回写权威资产（计划 20.14.5）。
 * 没有 GLB 时显示真实空状态，不画任何示意几何。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

import { formatBytes, truncate } from '../lib/format';
import { cubeSelfCheck, displayToAuthority, scaleToAuthorityLength, type Vec3 } from '../lib/display';
import {
  DISPLAY_LOD_ROLE,
  describeGlbRefFailure,
  disposeObject,
  glbRefFrom,
  loadDerivedGlb,
  type GlbMeasurement,
  type GlbSource,
} from '../lib/glb';
import type { AssetRecord } from '../api/types';
import { Badge, EmptyState, ErrorState, LoadingState } from './states';

export type SceneLoadInfo = GlbMeasurement;

export interface SceneViewportProps {
  /** 真实资产记录（由 `GET /assets` 得到）；role 与 GLB payload key 从记录里自动确定。 */
  asset?: AssetRecord | null;
  /** 兼容写法：直接给 assetId；此时必须显式给出 role 与 fileKey。 */
  assetId?: string | null;
  /** 资产 role，必须与后端 `record.role` 完全一致（后端做 role mismatch 校验）。 */
  role?: string;
  /** payload key；缺省时由 `pickGlbKey(asset.files)` 推断，绝不猜错文件。 */
  fileKey?: string;
  title?: string;
  height?: number;
  onLoadInfo?: (info: SceneLoadInfo | null) => void;
  /** 附加说明（例如“展示简化 LOD”）。 */
  notice?: string | null;
  /**
   * GLB 的取数来源：默认 `assets`（会话资产库）；
   * 展示页（U13）用 `showcase`，因为演示资产住在独立的演示资产库里。
   */
  source?: GlbSource;
}

interface ViewportMetrics {
  displayExtentM: Vec3 | null;
  authorityExtentMm: Vec3 | null;
  displayCenterM: Vec3 | null;
  triangleCount: number;
  meshCount: number;
  gridMm: number | null;
  loadedAt: number | null;
}

const EMPTY_METRICS: ViewportMetrics = {
  displayExtentM: null,
  authorityExtentMm: null,
  displayCenterM: null,
  triangleCount: 0,
  meshCount: 0,
  gridMm: null,
  loadedAt: null,
};

/** 网格总宽取 1/2/5 序列的整毫米值（每格 = 总宽 / 10），保证标尺读数是整数 mm。 */
export function roundGridMm(extentMm: number): number {
  if (!Number.isFinite(extentMm) || extentMm <= 0) return 100;
  const raw = extentMm / 4;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const normalized = raw / magnitude;
  const step = (normalized >= 5 ? 5 : normalized >= 2 ? 2 : 1) * magnitude;
  return Math.max(10, step * 4);
}

export function SceneViewport({
  asset,
  assetId: assetIdProp,
  role: roleProp,
  fileKey: fileKeyProp,
  title = '三维视口',
  height = 360,
  onLoadInfo,
  notice,
  source = 'assets',
}: SceneViewportProps) {
  const ref = useMemo(() => glbRefFrom(asset), [asset]);
  const assetId = asset ? asset.asset_id : (assetIdProp ?? null);
  const role = roleProp ?? ref?.role ?? DISPLAY_LOD_ROLE;
  const fileKey = fileKeyProp ?? ref?.fileKey ?? 'glb';
  const refFailure = asset && !ref ? describeGlbRefFailure(asset) : null;

  /** 从真实资产 meta 推导“是否简化”提示，而不是无条件写“展示简化 LOD”。 */
  const derivedNotice = useMemo(() => {
    const meta = asset?.meta ?? {};
    const levels = meta.lod_levels;
    const notes = Array.isArray(meta.lod_notes) ? (meta.lod_notes as unknown[]).map(String) : [];
    const table = levels && typeof levels === 'object' ? (levels as Record<string, any>) : {};
    const levelKeys = Object.keys(table);
    // 只有 `exported_as_scene_node !== false` 的层级真的在这个 GLB 的场景里；
    // 清单可能额外记录了"量过但没放进场景"的层级（视口会同时渲染所有节点，重叠会 z-fighting）
    const sceneNodes = levelKeys.filter((key) => table[key]?.exported_as_scene_node !== false);
    const measuredOnly = levelKeys.filter((key) => !sceneNodes.includes(key));
    if (sceneNodes.length > 1) return `展示简化 LOD（${sceneNodes.join('/')}）`;
    if (sceneNodes.length === 1 && measuredOnly.length > 0) {
      return `场景仅 ${sceneNodes[0]}（清单另记录 ${measuredOnly.join('/')} 的简化指标，未放进场景）`;
    }
    if (sceneNodes.length === 1 && notes.length > 0) return `仅 ${sceneNodes[0]}：未简化（${notes[0]}）`;
    if (sceneNodes.length === 1) return `仅 ${sceneNodes[0]}（无简化层级）`;
    return null;
  }, [asset]);
  const badgeNotice = notice ?? derivedNotice;
  const mountRef = useRef<HTMLDivElement>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const sceneRef = useRef<THREE.Scene | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const controlsRef = useRef<OrbitControls | null>(null);
  const rootRef = useRef<THREE.Group | null>(null);
  const gridRef = useRef<THREE.GridHelper | null>(null);
  const clipRef = useRef<THREE.Plane>(new THREE.Plane(new THREE.Vector3(-1, 0, 0), 0));
  const frameRef = useRef<number | null>(null);
  const infoCallbackRef = useRef(onLoadInfo);
  infoCallbackRef.current = onLoadInfo;

  const [status, setStatus] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle');
  const [error, setError] = useState<unknown>(null);
  const [info, setInfo] = useState<SceneLoadInfo | null>(null);
  const [metrics, setMetrics] = useState<ViewportMetrics>(EMPTY_METRICS);
  const [wireframe, setWireframe] = useState(false);
  const [clipEnabled, setClipEnabled] = useState(false);
  const [clipOffsetMm, setClipOffsetMm] = useState(0);

  const selfCheck = useMemo(() => cubeSelfCheck(100), []);

  /* ------------------------------------------------------------ 渲染器（挂载一次） */
  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return undefined;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x11151c);
    sceneRef.current = scene;

    const camera = new THREE.PerspectiveCamera(45, 1, 0.001, 5000);
    camera.position.set(0.28, 0.22, 0.28);
    cameraRef.current = camera;

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.localClippingEnabled = true;
    mount.appendChild(renderer.domElement);
    rendererRef.current = renderer;

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.12;
    controls.screenSpacePanning = true;
    controlsRef.current = controls;

    scene.add(new THREE.AmbientLight(0xffffff, 0.75));
    const key = new THREE.DirectionalLight(0xffffff, 1.6);
    key.position.set(0.5, 1, 0.8);
    scene.add(key);
    const fill = new THREE.DirectionalLight(0x88aaff, 0.5);
    fill.position.set(-0.6, 0.3, -0.7);
    scene.add(fill);
    scene.add(new THREE.AxesHelper(0.15));

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
        disposeObject(rootRef.current);
        rootRef.current = null;
      }
      if (gridRef.current) {
        scene.remove(gridRef.current);
        gridRef.current.geometry.dispose();
        (gridRef.current.material as THREE.Material).dispose();
        gridRef.current = null;
      }
      renderer.dispose();
      if (renderer.domElement.parentElement === mount) mount.removeChild(renderer.domElement);
      rendererRef.current = null;
      sceneRef.current = null;
      cameraRef.current = null;
      controlsRef.current = null;
    };
  }, [height]);

  /* ------------------------------------------------------------ 载入 GLB */
  useEffect(() => {
    const scene = sceneRef.current;
    const camera = cameraRef.current;
    const controls = controlsRef.current;
    if (!scene || !camera || !controls) return undefined;

    infoCallbackRef.current?.(null);

    if (!assetId) {
      setStatus('idle');
      setInfo(null);
      setMetrics(EMPTY_METRICS);
      if (rootRef.current) {
        scene.remove(rootRef.current);
        disposeObject(rootRef.current);
        rootRef.current = null;
      }
      return undefined;
    }

    if (refFailure) {
      setStatus('error');
      setError(new Error(refFailure));
      setInfo(null);
      setMetrics(EMPTY_METRICS);
      return undefined;
    }

    const controller = new AbortController();
    let cancelled = false;
    setStatus('loading');
    setError(null);

    loadDerivedGlb(assetId, { role, fileKey, signal: controller.signal, source })
      .then(({ object, measurement }) => {
        if (cancelled) {
          disposeObject(object);
          return;
        }
        if (rootRef.current) {
          scene.remove(rootRef.current);
          disposeObject(rootRef.current);
          rootRef.current = null;
        }
        object.name = `display_lod:${assetId}`;
        scene.add(object);
        rootRef.current = object;

        const gridMm = roundGridMm(Math.max(...measurement.authorityExtentMm));
        if (gridRef.current) {
          scene.remove(gridRef.current);
          gridRef.current.geometry.dispose();
          (gridRef.current.material as THREE.Material).dispose();
        }
        const grid = new THREE.GridHelper(gridMm / 1000, 10, 0x334455, 0x223344);
        grid.name = 'mm-grid';
        scene.add(grid);
        gridRef.current = grid;

        const [cx, cy, cz] = measurement.displayCenterM;
        const radius = Math.max(new THREE.Vector3(...measurement.displayExtentM).length() / 2, 0.02);
        const distance = (radius / Math.tan((camera.fov * Math.PI) / 360)) * 1.6;
        camera.position.set(cx + distance * 0.7, cy + distance * 0.55, cz + distance * 0.8);
        camera.near = Math.max(0.0005, radius / 200);
        camera.far = Math.max(10, radius * 400);
        camera.updateProjectionMatrix();
        controls.target.set(cx, cy, cz);
        controls.update();

        setInfo(measurement);
        infoCallbackRef.current?.(measurement);
        setMetrics({
          displayExtentM: measurement.displayExtentM,
          authorityExtentMm: measurement.authorityExtentMm,
          displayCenterM: measurement.displayCenterM,
          triangleCount: measurement.triangleCount,
          meshCount: measurement.meshCount,
          gridMm,
          loadedAt: Date.now(),
        });
        setClipOffsetMm(0);
        setStatus('ready');
      })
      .catch((caught: unknown) => {
        if (cancelled) return;
        if (caught instanceof DOMException && caught.name === 'AbortError') return;
        setError(caught);
        setStatus('error');
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [assetId, role, fileKey, refFailure, source]);

  /* ------------------------------------------------------------ 线框 / 剖切面（只改展示） */
  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    root.traverse((child) => {
      const mesh = child as THREE.Mesh;
      if (!mesh.isMesh) return;
      const material = mesh.material as THREE.Material | THREE.Material[];
      for (const item of Array.isArray(material) ? material : [material]) {
        const standard = item as THREE.MeshStandardMaterial;
        if ('wireframe' in standard) standard.wireframe = wireframe;
        const clipped = item as THREE.Material & { clippingPlanes: THREE.Plane[] | null };
        clipped.clippingPlanes = clipEnabled ? [clipRef.current] : [];
        item.needsUpdate = true;
      }
    });
  }, [wireframe, clipEnabled, info]);

  useEffect(() => {
    // 剖切位置以展示坐标（米）表示；权威数字（mm）只用于 UI 读数（÷1000）。
    clipRef.current.constant = clipOffsetMm / 1000;
  }, [clipOffsetMm]);

  const resetView = useCallback(() => {
    const camera = cameraRef.current;
    const controls = controlsRef.current;
    if (!camera || !controls) return;
    const center = metrics.displayCenterM;
    const extent = metrics.displayExtentM;
    if (!center || !extent) {
      camera.position.set(0.28, 0.22, 0.28);
      controls.target.set(0, 0, 0);
      controls.update();
      return;
    }
    const radius = Math.max(new THREE.Vector3(...extent).length() / 2, 0.02);
    const distance = (radius / Math.tan((camera.fov * Math.PI) / 360)) * 1.6;
    camera.position.set(center[0] + distance * 0.7, center[1] + distance * 0.55, center[2] + distance * 0.8);
    controls.target.set(center[0], center[1], center[2]);
    controls.update();
    setWireframe(false);
    setClipEnabled(false);
    setClipOffsetMm(0);
  }, [metrics]);

  const authorityMax = metrics.authorityExtentMm ? Math.max(...metrics.authorityExtentMm) : 0;
  const authorityCenterMm = metrics.displayCenterM ? displayToAuthority(metrics.displayCenterM) : null;

  return (
    <div className="viewport">
      <div className="viewport__head">
        <div className="viewport__title">
          {title}
          <Badge tone="info">展示：m / Y-up</Badge>
          <Badge tone="neutral">权威：mm / Z-up</Badge>
          {badgeNotice ? <Badge tone="warn">{badgeNotice}</Badge> : null}
        </div>
        <div className="viewport__tools">
          <label className="check">
            <input
              type="checkbox"
              checked={wireframe}
              onChange={(event) => setWireframe(event.target.checked)}
              disabled={!assetId || status !== 'ready'}
            />
            线框
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={clipEnabled}
              onChange={(event) => setClipEnabled(event.target.checked)}
              disabled={!assetId || authorityMax === 0}
            />
            剖切平面
          </label>
          <label className="check check--range">
            剖切位置 {clipOffsetMm.toFixed(0)} mm
            <input
              type="range"
              min={metrics.authorityExtentMm ? metrics.authorityExtentMm[0] / -2 : -50}
              max={metrics.authorityExtentMm ? metrics.authorityExtentMm[0] / 2 : 50}
              step={1}
              value={clipOffsetMm}
              onChange={(event) => setClipOffsetMm(Number(event.target.value))}
              disabled={!clipEnabled}
            />
          </label>
          <button type="button" className="btn btn--tiny" onClick={resetView} disabled={!assetId}>
            重置视角
          </button>
        </div>
      </div>

      <div className="viewport__canvas" ref={mountRef} style={{ height: `${height}px` }} />

      {status === 'loading' ? (
        <div className="viewport__overlay">
          <LoadingState label={`正在加载派生 GLB：${assetId}`} />
        </div>
      ) : null}
      {status === 'error' ? (
        <div className="viewport__overlay">
          <ErrorState error={error} compact title="无法加载派生 GLB" />
        </div>
      ) : null}
      {status === 'idle' ? (
        <div className="viewport__overlay">
          <EmptyState
            title="没有可显示的展示资产"
            reason={
              <>
                视口只加载真实的 <code className="mono">{DISPLAY_LOD_ROLE}</code> GLB 资产。当前没有选择资产，或本工作区还没派生过展示
                LOD。派生的 <code className="mono">display_lod</code> 任务需要 trimesh 环境能力，且当前 HTTP API
                没有创建它的路由（见 docs/a12/api_ui.md 差异表），可用 worker/CLI 路径产生。这里不会绘制任何示意几何。
              </>
            }
          />
        </div>
      ) : null}

      <div className="viewport__foot">
        <div className="viewport__scale">
          <span className="viewport__scalebar" aria-hidden="true" />
          {metrics.gridMm ? (
            <span>
              mm 标尺：网格总宽 {metrics.gridMm} mm，每格 {metrics.gridMm / 10} mm（展示 {metrics.gridMm / 1000} m / 格）
            </span>
          ) : (
            <span>mm 标尺：无模型时不可用</span>
          )}
        </div>
        <div className="viewport__selfcheck">
          <Badge tone={selfCheck.ok ? 'ok' : 'bad'}>{selfCheck.ok ? '100 mm 解析立方体自检通过' : '立方体自检失败'}</Badge>
          <span className="mono">{selfCheck.detail}</span>
        </div>
        {info ? (
          <dl className="viewport__info">
            <div>
              <dt>权威尺寸</dt>
              <dd className="mono">{info.authorityExtentMm.map((value) => value.toFixed(3)).join(' × ')} mm</dd>
            </div>
            <div>
              <dt>展示尺寸</dt>
              <dd className="mono">{info.displayExtentM.map((value) => value.toFixed(5)).join(' × ')} m</dd>
            </div>
            <div>
              <dt>三角面 / Mesh</dt>
              <dd className="mono">
                {info.triangleCount} / {info.meshCount}
              </dd>
            </div>
            <div>
              <dt>GLB 大小</dt>
              <dd className="mono">{formatBytes(info.bytes)}</dd>
            </div>
            <div>
              <dt>服务端 sha256</dt>
              <dd className="mono" title={info.serverSha256 ?? ''}>
                {info.serverSha256 ? truncate(info.serverSha256, 24) : '响应头未提供'}
                {info.serverHashVerified ? ` · 校验=${info.serverHashVerified}` : ''}
              </dd>
            </div>
            <div>
              <dt>浏览器重算 sha256</dt>
              <dd className="mono" title={info.clientSha256 ?? ''}>
                {info.clientSha256 ? truncate(info.clientSha256, 24) : '当前环境无 crypto.subtle'}
              </dd>
            </div>
            <div>
              <dt>坐标契约</dt>
              <dd className="mono">
                unit={info.unit} · frame={info.frame} · qa={info.qaStatus}
              </dd>
            </div>
            <div>
              <dt>包围盒中心 → 权威坐标</dt>
              <dd className="mono">{authorityCenterMm ? authorityCenterMm.map((v) => v.toFixed(4)).join(', ') : '—'} mm</dd>
            </div>
          </dl>
        ) : null}
        {metrics.displayExtentM ? (
          <p className="muted">
            剖切/线框/相机只改展示状态，不写回权威资产；量尺长度 = 展示米 × 1000 → mm（
            {scaleToAuthorityLength(1).toFixed(0)} mm/m）。当前最大边 {authorityMax.toFixed(3)} mm。
          </p>
        ) : null}
      </div>
    </div>
  );
}
