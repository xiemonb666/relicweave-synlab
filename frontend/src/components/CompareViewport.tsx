/**
 * CompareViewport —— baseline / level 的同视角比较画布（计划 20.6）。
 *
 * 实现要点：左右两侧共用**同一个相机与同一个 renderer**，所以“同视角 / 同 zoom / 同 crop 联动”
 * 是结构保证而不是靠事件同步：
 *
 * * `wipe`  —— 用 scissor 把同一视图切成两块，各画一侧（拖动分界线即真实擦除比较）；
 * * `side`  —— 左右各占一半 viewport，各自完整取景（aspect 按半宽重算，不拉伸）；
 * * `overlay` —— 两 mesh 叠加，右侧材质透明度可调。
 *
 * 这里只做**展示 GLB 几何**的差异读数（尺寸/面数），不生成误差热图：GLB 里没有逐点误差场。
 * 真实的误差热图与点云叠加在 `components/DegradationDiffPanel.tsx`（U05 页）里实现：
 * 它解码后端 `arrays` 资产的 depth/points，由前端计算差值并显式标注“非后端误差场”。
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

import { displayToAuthority, type Vec3 } from '../lib/display';
import { describeGlbRefFailure, disposeObject, glbRefFrom, loadDerivedGlb, type GlbMeasurement } from '../lib/glb';
import { formatBytes } from '../lib/format';
import type { AssetRecord } from '../api/types';
import { Badge, EmptyState, ErrorState, LoadingState, Tabs } from './states';

export interface CompareSide {
  /** 真实资产记录（由 GET /assets 得到）；role 与 GLB payload key 自动确定。 */
  asset: AssetRecord | null;
  label: string;
  role?: string;
  fileKey?: string;
}

export type CompareMode = 'wipe' | 'side' | 'overlay';

export interface CompareViewportProps {
  left: CompareSide;
  right: CompareSide;
  height?: number;
  /** 两侧都为空时的说明。 */
  emptyReason?: string;
}

function delta(a: number[] | null, b: number[] | null): string {
  if (!a || !b) return '—';
  return a.map((value, index) => (b[index] - value).toFixed(3)).join(' / ');
}

export function CompareViewport({ left, right, height = 340, emptyReason }: CompareViewportProps) {
  const mountRef = useRef<HTMLDivElement>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const controlsRef = useRef<OrbitControls | null>(null);
  const scenesRef = useRef<{ left: THREE.Scene; right: THREE.Scene } | null>(null);
  const objectsRef = useRef<{ left: THREE.Group | null; right: THREE.Group | null }>({ left: null, right: null });
  const modeRef = useRef<CompareMode>('wipe');
  const splitRef = useRef(0.5);
  const opacityRef = useRef(0.55);
  const frameRef = useRef<number | null>(null);

  const [mode, setMode] = useState<CompareMode>('wipe');
  const [split, setSplit] = useState(0.5);
  const [opacity, setOpacity] = useState(0.55);
  const [status, setStatus] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle');
  const [error, setError] = useState<unknown>(null);
  const [leftInfo, setLeftInfo] = useState<GlbMeasurement | null>(null);
  const [rightInfo, setRightInfo] = useState<GlbMeasurement | null>(null);
  const [revision, setRevision] = useState(0);

  modeRef.current = mode;
  splitRef.current = split;
  opacityRef.current = opacity;

  /* ---------------------------------------------------------------- 渲染器 */
  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return undefined;

    const leftScene = new THREE.Scene();
    const rightScene = new THREE.Scene();
    leftScene.background = new THREE.Color(0x10141a);
    rightScene.background = new THREE.Color(0x10141a);
    for (const [scene, tint] of [
      [leftScene, 0x9fd0ff],
      [rightScene, 0xffc98a],
    ] as Array<[THREE.Scene, number]>) {
      scene.add(new THREE.AmbientLight(0xffffff, 0.8));
      const key = new THREE.DirectionalLight(tint, 1.5);
      key.position.set(0.6, 1, 0.7);
      scene.add(key);
      const fill = new THREE.DirectionalLight(0xffffff, 0.35);
      fill.position.set(-0.5, -0.4, -0.8);
      scene.add(fill);
      scene.add(new THREE.GridHelper(0.5, 10, 0x2a3644, 0x1d2632));
    }
    scenesRef.current = { left: leftScene, right: rightScene };

    const camera = new THREE.PerspectiveCamera(45, 1, 0.0005, 5000);
    camera.position.set(0.3, 0.25, 0.32);
    cameraRef.current = camera;

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    mount.appendChild(renderer.domElement);
    rendererRef.current = renderer;

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.12;
    controlsRef.current = controls;

    const render = () => {
      frameRef.current = window.requestAnimationFrame(render);
      controls.update();
      const width = mount.clientWidth || 640;
      const heightPx = mount.clientHeight || height;
      const current = modeRef.current;

      renderer.setScissorTest(false);
      renderer.clear();

      if (current === 'side') {
        const half = Math.floor(width / 2);
        camera.aspect = half / heightPx;
        camera.updateProjectionMatrix();
        renderer.setScissorTest(true);
        renderer.setViewport(0, 0, half, heightPx);
        renderer.setScissor(0, 0, half, heightPx);
        renderer.render(leftScene, camera);
        renderer.setViewport(half, 0, width - half, heightPx);
        renderer.setScissor(half, 0, width - half, heightPx);
        renderer.render(rightScene, camera);
        renderer.setScissorTest(false);
        return;
      }

      camera.aspect = width / heightPx;
      camera.updateProjectionMatrix();

      if (current === 'wipe') {
        const cut = Math.max(0, Math.min(1, splitRef.current)) * width;
        renderer.setScissorTest(true);
        renderer.setViewport(0, 0, width, heightPx);
        renderer.setScissor(0, 0, Math.floor(cut), heightPx);
        renderer.render(leftScene, camera);
        renderer.setScissor(Math.floor(cut), 0, Math.ceil(width - cut), heightPx);
        renderer.render(rightScene, camera);
        renderer.setScissorTest(false);
        return;
      }

      // overlay：先左后右，右侧叠加（透明度由材质控制）
      renderer.setViewport(0, 0, width, heightPx);
      renderer.render(leftScene, camera);
      renderer.autoClear = false;
      renderer.render(rightScene, camera);
      renderer.autoClear = true;
    };
    render();

    const resize = () => {
      const width = mount.clientWidth || 640;
      renderer.setSize(width, mount.clientHeight || height, false);
    };
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(mount);

    return () => {
      if (frameRef.current !== null) window.cancelAnimationFrame(frameRef.current);
      observer.disconnect();
      controls.dispose();
      disposeObject(objectsRef.current.left);
      disposeObject(objectsRef.current.right);
      objectsRef.current = { left: null, right: null };
      renderer.dispose();
      if (renderer.domElement.parentElement === mount) mount.removeChild(renderer.domElement);
      scenesRef.current = null;
      rendererRef.current = null;
      cameraRef.current = null;
      controlsRef.current = null;
    };
  }, [height]);

  /* ---------------------------------------------------------------- 载入两侧 */
  useEffect(() => {
    const scenes = scenesRef.current;
    const camera = cameraRef.current;
    const controls = controlsRef.current;
    if (!scenes || !camera || !controls) return undefined;

    if (!left.asset && !right.asset) {
      setStatus('idle');
      setLeftInfo(null);
      setRightInfo(null);
      return undefined;
    }

    const leftRef = glbRefFrom(left.asset);
    const rightRef = glbRefFrom(right.asset);
    const refProblems = [
      left.asset && !leftRef ? describeGlbRefFailure(left.asset) : null,
      right.asset && !rightRef ? describeGlbRefFailure(right.asset) : null,
    ].filter((value): value is string => value !== null);
    if (refProblems.length > 0) {
      setStatus('error');
      setError(new Error(refProblems.join('；')));
      return undefined;
    }

    const controller = new AbortController();
    let cancelled = false;
    setStatus('loading');
    setError(null);

    const attach = (scene: THREE.Scene, side: 'left' | 'right', object: THREE.Group | null) => {
      const previous = objectsRef.current[side];
      if (previous) {
        scene.remove(previous);
        disposeObject(previous);
      }
      objectsRef.current[side] = object;
      if (object) scene.add(object);
    };

    const frameBoth = (measurements: GlbMeasurement[]) => {
      const extents = measurements.map((item) => new THREE.Vector3(...item.displayExtentM));
      const centers = measurements.map((item) => new THREE.Vector3(...item.displayCenterM));
      const radius = Math.max(...extents.map((value) => value.length() / 2), 0.02);
      const center = centers
        .reduce((accumulator, value) => accumulator.add(value), new THREE.Vector3())
        .divideScalar(centers.length);
      const distance = (radius / Math.tan((camera.fov * Math.PI) / 360)) * 1.8;
      camera.position.set(center.x + distance * 0.7, center.y + distance * 0.55, center.z + distance * 0.8);
      camera.near = Math.max(0.0005, radius / 200);
      camera.far = Math.max(10, radius * 400);
      camera.updateProjectionMatrix();
      controls.target.copy(center);
      controls.update();
    };

    const tasks: Array<Promise<void>> = [];
    const measurements: GlbMeasurement[] = [];

    if (left.asset) {
      tasks.push(
        loadDerivedGlb(left.asset.asset_id, { role: left.role ?? leftRef?.role, fileKey: left.fileKey ?? leftRef?.fileKey, signal: controller.signal }).then(
          ({ object, measurement }) => {
            if (cancelled) {
              disposeObject(object);
              return;
            }
            attach(scenes.left, 'left', object);
            setLeftInfo(measurement);
            measurements.push(measurement);
          },
        ),
      );
    } else {
      attach(scenes.left, 'left', null);
      setLeftInfo(null);
    }

    if (right.asset) {
      tasks.push(
        loadDerivedGlb(right.asset.asset_id, { role: right.role ?? rightRef?.role, fileKey: right.fileKey ?? rightRef?.fileKey, signal: controller.signal }).then(
          ({ object, measurement }) => {
            if (cancelled) {
              disposeObject(object);
              return;
            }
            attach(scenes.right, 'right', object);
            setRightInfo(measurement);
            measurements.push(measurement);
          },
        ),
      );
    } else {
      attach(scenes.right, 'right', null);
      setRightInfo(null);
    }

    void Promise.all(tasks)
      .then(() => {
        if (cancelled) return;
        if (measurements.length > 0) frameBoth(measurements);
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
  }, [
    left.asset?.asset_id,
    left.asset,
    left.role,
    left.fileKey,
    right.asset?.asset_id,
    right.asset,
    right.role,
    right.fileKey,
    revision,
  ]);

  /* ---------------------------------------------------------------- overlay 透明度 */
  useEffect(() => {
    const object = objectsRef.current.right;
    if (!object) return;
    object.traverse((child) => {
      const mesh = child as THREE.Mesh;
      if (!mesh.isMesh) return;
      const material = mesh.material as THREE.Material | THREE.Material[];
      for (const item of Array.isArray(material) ? material : [material]) {
        const standard = item as THREE.MeshStandardMaterial;
        standard.transparent = mode === 'overlay';
        standard.opacity = mode === 'overlay' ? opacity : 1;
        standard.depthWrite = mode !== 'overlay';
        item.needsUpdate = true;
      }
    });
  }, [mode, opacity, rightInfo]);

  const resetView = () => setRevision((value) => value + 1);

  const dimDelta = useMemo(
    () => delta(leftInfo?.authorityExtentMm ?? null, rightInfo?.authorityExtentMm ?? null),
    [leftInfo, rightInfo],
  );

  return (
    <div className="compare">
      <div className="viewport__head">
        <div className="viewport__title">
          比较视口
          <Badge tone="info">共享相机（结构联动）</Badge>
          <Badge tone="neutral">左：{left.label}</Badge>
          <Badge tone="neutral">右：{right.label}</Badge>
        </div>
        <div className="viewport__tools">
          <Tabs
            label="比较模式"
            active={mode}
            onChange={(id) => setMode(id as CompareMode)}
            tabs={[
              { id: 'wipe', label: 'RGB wipe' },
              { id: 'side', label: '并列' },
              { id: 'overlay', label: '叠加' },
            ]}
          />
          <label className="check check--range">
            分界 {Math.round(split * 100)}%
            <input
              type="range"
              min={0}
              max={1}
              step={0.01}
              value={split}
              onChange={(event) => setSplit(Number(event.target.value))}
              disabled={mode !== 'wipe'}
            />
          </label>
          <label className="check check--range">
            右侧透明度 {opacity.toFixed(2)}
            <input
              type="range"
              min={0.05}
              max={1}
              step={0.05}
              value={opacity}
              onChange={(event) => setOpacity(Number(event.target.value))}
              disabled={mode !== 'overlay'}
            />
          </label>
          <button type="button" className="btn btn--tiny" onClick={resetView}>
            重置视角
          </button>
        </div>
      </div>

      <div className="viewport__canvas viewport__canvas--compare" ref={mountRef} style={{ height: `${height}px` }}>
        {mode === 'side' ? (
          <>
            <span className="compare__label compare__label--left">{left.label}</span>
            <span className="compare__label compare__label--right">{right.label}</span>
          </>
        ) : null}
        {mode === 'wipe' ? (
          <span className="compare__divider" style={{ left: `${split * 100}%` }}>
            <span className="compare__label compare__label--left">{left.label}</span>
            <span className="compare__label compare__label--right">{right.label}</span>
          </span>
        ) : null}
      </div>

      {status === 'loading' ? (
        <div className="viewport__overlay">
          <LoadingState label="正在加载两侧派生 GLB…" />
        </div>
      ) : null}
      {status === 'error' ? (
        <div className="viewport__overlay">
          <ErrorState error={error} compact title="比较视口加载失败" onRetry={resetView} />
        </div>
      ) : null}
      {status === 'idle' ? (
        <div className="viewport__overlay">
          <EmptyState
            title="没有可比较的展示资产"
            reason={
              emptyReason ??
              '比较视口只加载真实的 display_lod GLB。请先在左侧资产列表里为两侧各选一个派生展示资产；不会用示意几何代替。'
            }
          />
        </div>
      ) : null}

      <div className="compare__table">
        <table className="table">
          <caption>实测读数（来自真实 GLB 与响应头，展示 m/Y-up → 权威 mm/Z-up 换算一次）</caption>
          <thead>
            <tr>
              <th scope="col">指标</th>
              <th scope="col">左：{left.label}</th>
              <th scope="col">右：{right.label}</th>
              <th scope="col">右 − 左</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <th scope="row">资产</th>
              <td className="mono">{leftInfo?.assetId ?? '未选择'}</td>
              <td className="mono">{rightInfo?.assetId ?? '未选择'}</td>
              <td>—</td>
            </tr>            <tr>
              <th scope="row">权威尺寸 (mm)</th>
              <td className="mono">{leftInfo ? leftInfo.authorityExtentMm.map((v) => v.toFixed(3)).join(' × ') : '—'}</td>
              <td className="mono">{rightInfo ? rightInfo.authorityExtentMm.map((v) => v.toFixed(3)).join(' × ') : '—'}</td>
              <td className="mono">{dimDelta}</td>
            </tr>
            <tr>
              <th scope="row">展示尺寸 (m)</th>
              <td className="mono">{leftInfo ? leftInfo.displayExtentM.map((v) => v.toFixed(5)).join(' × ') : '—'}</td>
              <td className="mono">{rightInfo ? rightInfo.displayExtentM.map((v) => v.toFixed(5)).join(' × ') : '—'}</td>
              <td>—</td>
            </tr>
            <tr>
              <th scope="row">三角面</th>
              <td className="mono">{leftInfo ? leftInfo.triangleCount : '—'}</td>
              <td className="mono">{rightInfo ? rightInfo.triangleCount : '—'}</td>
              <td className="mono">
                {leftInfo && rightInfo ? rightInfo.triangleCount - leftInfo.triangleCount : '—'}
              </td>
            </tr>
            <tr>
              <th scope="row">GLB 大小</th>
              <td className="mono">{leftInfo ? formatBytes(leftInfo.bytes) : '—'}</td>
              <td className="mono">{rightInfo ? formatBytes(rightInfo.bytes) : '—'}</td>
              <td>—</td>
            </tr>
            <tr>
              <th scope="row">QA / 坐标契约</th>
              <td className="mono">{leftInfo ? `${leftInfo.qaStatus} · ${leftInfo.frame}` : '—'}</td>
              <td className="mono">{rightInfo ? `${rightInfo.qaStatus} · ${rightInfo.frame}` : '—'}</td>
              <td>—</td>
            </tr>
            <tr>
              <th scope="row">中心 → 权威坐标 (mm)</th>
              <td className="mono">
                {leftInfo ? displayToAuthority(leftInfo.displayCenterM).map((v) => v.toFixed(3)).join(', ') : '—'}
              </td>
              <td className="mono">
                {rightInfo ? displayToAuthority(rightInfo.displayCenterM).map((v) => v.toFixed(3)).join(', ') : '—'}
              </td>
              <td>—</td>
            </tr>
          </tbody>
        </table>

        <div className="blockedlist">
          <h4>本视口（GLB 展示几何）不做的事（如实列出，不用假数据填充）</h4>
          <ul>
            <li>
              <strong>误差热图</strong>：本视口只比较 GLB 展示几何，不画误差场。真实数组的差异视图在 U05 页面下方的
              “误差热图与点云叠加（真实数组）”面板里，由后端 <code className="mono">depth_z</code> /{' '}
              <code className="mono">points</code> 在前端计算，并标注“非后端误差场”。
            </li>
            <li>
              <strong>点云 / mesh 叠加</strong>：本视口不解析点云资产（role 形如{' '}
              <code className="mono">obs_fused_geometry</code>）；点云叠加同样在上面的面板里实现（浏览器内解码 npz）。
            </li>
            <li>
              <strong>真实差分表</strong>：需要成对的实测指标。可用数据在{' '}
              <code className="mono">GET /assets?role=...</code> 的 <code className="mono">qa</code> 字段里，
              U05 页面下方按资产原样列出。
            </li>
          </ul>
        </div>
      </div>
    </div>
  );
}

export function authorityExtentOf(measurement: GlbMeasurement | null): Vec3 | null {
  return measurement ? measurement.authorityExtentMm : null;
}
