/**
 * CameraFrustumView —— 相机视锥 / 光轴导轨 / 物体与支撑 / 景深（计划 20.7 U06 画布）。
 *
 * 所有几何都从 `GET /camera-profiles` 的**真实 catalogue** 计算：
 *
 * * 相机位置：`u_position_mm`（沿光轴导轨）与 `working_distance_mm`；
 * * 视锥半角：由 `fov_mm`（工作距离处的物理视场）与 `working_distance_mm` 反算，等价于用 K；
 * * 像平面矩形：`fov_mm[0] × fov_mm[1]`（mm → m 只做一次 /1000）；
 * * 景深：`depth_of_field_mm = [near, far]`；
 * * 导轨可达范围：`meta.u_allowed_range_mm` 与 `u_step_mm`（滑块不得绕过）。
 *
 * 这里**不请求真实场景帧**：后端 `synlab.cameras.make_view_frames` 虽然可用，
 * 但 API 没有对应路由（见 docs/a12/api_ui.md 差异表），所以帧预览在 UI 上标为阻塞。
 */

import { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

import type { CameraCatalogueEntry } from '../api/types';
import { formatNumber, isRecord } from '../lib/format';

export interface CameraFrustumViewProps {
  entry: CameraCatalogueEntry | null;
  /** 当前滑块给出的 U 位置（mm），必须落在 u_allowed_range_mm 内。 */
  uPositionMm: number;
  height?: number;
}

function readK(k: unknown): { fx: number; fy: number; cx: number; cy: number } | null {
  if (!isRecord(k)) return null;
  const sample = k.sample ?? k.values;
  if (!Array.isArray(sample) || sample.length < 6) return null;
  const fx = Number(sample[0]);
  const cx = Number(sample[2]);
  const fy = Number(sample[4]);
  const cy = Number(sample[5]);
  if (![fx, fy, cx, cy].every((value) => Number.isFinite(value))) return null;
  return { fx, fy, cx, cy };
}

export function CameraFrustumView({ entry, uPositionMm, height = 320 }: CameraFrustumViewProps) {
  const mountRef = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<THREE.Scene | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const controlsRef = useRef<OrbitControls | null>(null);
  const dynamicRef = useRef<THREE.Group | null>(null);
  const frameRef = useRef<number | null>(null);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return undefined;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0f1319);
    sceneRef.current = scene;

    const camera = new THREE.PerspectiveCamera(45, 1, 0.001, 200);
    camera.position.set(0.25, 0.35, 0.65);
    cameraRef.current = camera;

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    mount.appendChild(renderer.domElement);
    rendererRef.current = renderer;

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.target.set(0, 0.15, 0.3);
    controlsRef.current = controls;

    scene.add(new THREE.AmbientLight(0xffffff, 0.9));
    const dir = new THREE.DirectionalLight(0xffffff, 1.2);
    dir.position.set(0.4, 1, 0.6);
    scene.add(dir);

    const dynamic = new THREE.Group();
    dynamic.name = 'frustum-dynamic';
    scene.add(dynamic);
    dynamicRef.current = dynamic;

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
      if (dynamicRef.current) {
        dynamicRef.current.traverse((child) => {
          const line = child as THREE.Line;
          const mesh = child as THREE.Mesh;
          line.geometry?.dispose();
          mesh.geometry?.dispose();
          const material = mesh.material as THREE.Material | THREE.Material[] | undefined;
          for (const item of Array.isArray(material) ? material : material ? [material] : []) item.dispose();
        });
        scene.remove(dynamicRef.current);
        dynamicRef.current = null;
      }
      renderer.dispose();
      if (renderer.domElement.parentElement === mount) mount.removeChild(renderer.domElement);
      sceneRef.current = null;
      cameraRef.current = null;
      rendererRef.current = null;
      controlsRef.current = null;
    };
  }, [height]);

  /* ---------------------------------------------------------------- 依据真实参数重建 */
  useEffect(() => {
    const dynamic = dynamicRef.current;
    if (!dynamic) return;

    // 清空旧对象
    for (const child of [...dynamic.children]) {
      dynamic.remove(child);
      const mesh = child as THREE.Mesh;
      mesh.geometry?.dispose();
      const material = mesh.material as THREE.Material | THREE.Material[] | undefined;
      for (const item of Array.isArray(material) ? material : material ? [material] : []) item.dispose();
    }

    if (!entry) return;

    // 单位换算：权威 mm → 展示 m，只做一次
    const mmToM = (value: number) => value / 1000;
    const workingDistanceM = mmToM(entry.working_distance_mm);
    const uM = mmToM(uPositionMm);
    const meta = entry.meta ?? {};
    const uRange = Array.isArray(meta.u_allowed_range_mm) ? (meta.u_allowed_range_mm as number[]) : null;

    const fovWidthM = mmToM(entry.fov_mm[0]);
    const fovHeightM = mmToM(entry.fov_mm[1]);
    const halfAngle = Math.atan(fovWidthM / 2 / workingDistanceM);

    // 物体（100 mm 立方体作为尺度参照）+ 支撑
    const target = new THREE.Mesh(
      new THREE.BoxGeometry(0.1, 0.1, 0.1),
      new THREE.MeshStandardMaterial({ color: 0xc9a227, roughness: 0.6, metalness: 0.1 }),
    );
    target.position.set(0, 0.05, 0);
    dynamic.add(target);

    const support = new THREE.Mesh(
      new THREE.BoxGeometry(0.5, 0.02, 0.5),
      new THREE.MeshStandardMaterial({ color: 0x2b3644, roughness: 0.9 }),
    );
    support.position.set(0, -0.01, 0);
    dynamic.add(support);

    // 光轴导轨（真实可达范围）
    if (uRange && uRange.length >= 2) {
      const railGeometry = new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(mmToM(uRange[0]), 0.08, workingDistanceM),
        new THREE.Vector3(mmToM(uRange[1]), 0.08, workingDistanceM),
      ]);
      dynamic.add(new THREE.Line(railGeometry, new THREE.LineBasicMaterial({ color: 0x4a9de0 })));
      for (const endpoint of uRange) {
        const marker = new THREE.Mesh(
          new THREE.SphereGeometry(0.004, 12, 12),
          new THREE.MeshStandardMaterial({ color: 0x4a9de0 }),
        );
        marker.position.set(mmToM(endpoint), 0.08, workingDistanceM);
        dynamic.add(marker);
      }
    }

    // 相机与视锥
    const cameraX = uM;
    const frustumCamera = new THREE.PerspectiveCamera(
      THREE.MathUtils.radToDeg(halfAngle) * 2,
      fovWidthM / Math.max(fovHeightM, 1e-6),
      0.01,
      workingDistanceM * 4,
    );
    frustumCamera.position.set(cameraX, 0.05, workingDistanceM);
    frustumCamera.lookAt(0, 0.05, 0);
    frustumCamera.updateMatrixWorld(true);
    const helper = new THREE.CameraHelper(frustumCamera);
    helper.setColors(
      new THREE.Color(0x9fd0ff),
      new THREE.Color(0x9fd0ff),
      new THREE.Color(0x9fd0ff),
      new THREE.Color(0x9fd0ff),
      new THREE.Color(0x9fd0ff),
    );
    dynamic.add(helper);

    const body = new THREE.Mesh(
      new THREE.BoxGeometry(0.03, 0.03, 0.04),
      new THREE.MeshStandardMaterial({ color: 0x9fd0ff, metalness: 0.4, roughness: 0.4 }),
    );
    body.position.set(cameraX, 0.05, workingDistanceM);
    dynamic.add(body);

    // 像平面矩形（工作距离处的真实视场）
    const imagePlane = new THREE.Mesh(
      new THREE.PlaneGeometry(fovWidthM, fovHeightM),
      new THREE.MeshBasicMaterial({ color: 0x9fd0ff, transparent: true, opacity: 0.12, side: THREE.DoubleSide }),
    );
    imagePlane.position.set(cameraX, 0.05, workingDistanceM);
    imagePlane.lookAt(0, 0.05, 0);
    dynamic.add(imagePlane);

    const imageOutline = new THREE.LineSegments(
      new THREE.EdgesGeometry(new THREE.PlaneGeometry(fovWidthM, fovHeightM)),
      new THREE.LineBasicMaterial({ color: 0x63b3ed }),
    );
    imageOutline.position.set(cameraX, 0.05, workingDistanceM);
    imageOutline.lookAt(0, 0.05, 0);
    dynamic.add(imageOutline);

    // 景深（真实 near/far）
    for (const [index, distance] of entry.depth_of_field_mm.entries()) {
      const plane = new THREE.Mesh(
        new THREE.PlaneGeometry(fovWidthM * (distance / entry.working_distance_mm), fovHeightM * (distance / entry.working_distance_mm)),
        new THREE.MeshBasicMaterial({ color: index === 0 ? 0x68d391 : 0xf6ad55, transparent: true, opacity: 0.1, side: THREE.DoubleSide }),
      );
      plane.position.set(cameraX, 0.05, mmToM(distance));
      plane.lookAt(0, 0.05, 0);
      dynamic.add(plane);
    }
  }, [entry, uPositionMm]);

  const meta = entry?.meta ?? {};
  const k = readK(entry?.K ?? null);

  return (
    <div className="viewport">
      <div className="viewport__head">
        <div className="viewport__title">
          相机视锥 / 光轴导轨
          <span className="badge badge--info">1 单位 = 1 m（权威 mm ÷ 1000，只做一次）</span>
        </div>
      </div>
      <div className="viewport__canvas" ref={mountRef} style={{ height: `${height}px` }} />
      <div className="viewport__foot">
        {entry ? (
          <dl className="viewport__info">
            <div>
              <dt>profile / tier</dt>
              <dd className="mono">
                {entry.profile_id}（rev {entry.revision}）· {entry.tier}
              </dd>
            </div>
            <div>
              <dt>工作距离</dt>
              <dd className="mono">{formatNumber(entry.working_distance_mm, 2)} mm</dd>
            </div>
            <div>
              <dt>U 位置</dt>
              <dd className="mono">
                {formatNumber(uPositionMm, 2)} mm
                {Array.isArray(meta.u_allowed_range_mm) ? `（可达 ${(meta.u_allowed_range_mm as number[]).join(' … ')} mm）` : ''}
                {typeof meta.u_step_mm === 'number' ? ` · 步长 ${meta.u_step_mm} mm` : ''}
              </dd>
            </div>
            <div>
              <dt>视场（工作距离处）</dt>
              <dd className="mono">
                {formatNumber(entry.fov_mm[0], 2)} × {formatNumber(entry.fov_mm[1], 2)} mm
              </dd>
            </div>
            <div>
              <dt>景深</dt>
              <dd className="mono">{entry.depth_of_field_mm.map((value) => formatNumber(value, 2)).join(' … ')} mm</dd>
            </div>
            <div>
              <dt>原分辨率 / 光圈</dt>
              <dd className="mono">
                {entry.image_size.join(' × ')} px · f/{entry.f_number}
              </dd>
            </div>
            <div>
              <dt>内参 K</dt>
              <dd className="mono">
                {k ? `fx=${k.fx.toFixed(3)} fy=${k.fy.toFixed(3)} cx=${k.cx} cy=${k.cy}` : '后端未提供可解析的 K'}
              </dd>
            </div>
            <div>
              <dt>标定</dt>
              <dd className="mono">
                {entry.calibrated ? '已标定' : '未标定'} · {(entry.calibration_refs ?? []).join(', ') || '无标定引用'}
              </dd>
            </div>
            <div>
              <dt>焦点档 / 动作成本</dt>
              <dd className="mono">
                {entry.focus_setting} · {formatNumber(entry.action_cost_seconds, 1)} s
              </dd>
            </div>
          </dl>
        ) : (
          <p className="muted">未选择 profile：画布与读数都不可用（不会绘制示意相机）。</p>
        )}
      </div>
    </div>
  );
}
