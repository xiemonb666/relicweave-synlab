# docs/a12/algorithm_registry.md — 能力注册表（自动生成）

> 本文件由 `tools/gen_status_matrix.py` 从代码内注册表、复用清单与验收结果生成，不要手工编辑。状态只反映实际实现的证据。

## 1. 状态汇总

| kind | count | by status |
|---|---|---|
| vessel | 24 | {'IMPLEMENTED': 24} |
| material | 12 | {'IMPLEMENTED': 12} |
| layer_combo | 4 | {'IMPLEMENTED': 4} |
| pattern | 16 | {'IMPLEMENTED': 16} |
| fracture_backend | 5 | {'MISSING': 1, 'IMPLEMENTED': 3, 'PENDING': 1} |
| axis | 31 | {'IMPLEMENTED': 31} |

## 2. 逐项注册表

### 器型（24 品种）

| ID | 名称 | 版本 | 状态 | 模块 | 适用/备注 |
|---|---|---|---|---|---|
| V01 | 碗 | 1.0 | IMPLEMENTED | `synlab.mothers.vessels.group_revolve` | family=revolve; requires_cavity=True; min_wall_mm=1.0 / thick revolved bowl, foot ring kept as a real contact band |
| V02 | 深盘 | 1.0 | IMPLEMENTED | `synlab.mothers.vessels.group_revolve` | family=revolve; requires_cavity=True; min_wall_mm=1.0 / deep dish: conical wall controlled by a real wall angle |
| V03 | 浅碟 | 1.0 | IMPLEMENTED | `synlab.mothers.vessels.group_revolve` | family=revolve; requires_cavity=True; min_wall_mm=0.9 / shallow saucer with a dished base and a wavy rim |
| V04 | 杯 | 1.0 | IMPLEMENTED | `synlab.mothers.vessels.group_revolve` | family=revolve+attachment; requires_cavity=True; min_wall_mm=1.0 / revolved cup with an optional swept handle (volumetric overlap at the root) |
| V05 | 高足杯 | 1.0 | IMPLEMENTED | `synlab.mothers.vessels.group_revolve` | family=revolve+revolve; requires_cavity=True; min_wall_mm=1.0 / cup shell on a closed high stem with a flared foot disc |
| V06 | 罐 | 1.0 | IMPLEMENTED | `synlab.mothers.vessels.group_revolve` | family=revolve; requires_cavity=True; min_wall_mm=1.2 / shoulder-belly-mouth jar profile with a real shoulder position |
| V07 | 瓶 | 1.0 | IMPLEMENTED | `synlab.mothers.vessels.group_revolve` | family=revolve; requires_cavity=True; min_wall_mm=1.2 / neck-shoulder-belly bottle; the cavity must survive the long neck |
| V08 | 双耳瓶 | 1.0 | IMPLEMENTED | `synlab.mothers.vessels.group_revolve` | family=revolve+attachment; requires_cavity=True; min_wall_mm=1.2 / bottle body with two swept ears; every ear has a volumetric root |
| V09 | 壶 | 1.0 | IMPLEMENTED | `synlab.mothers.vessels.group_composite` | family=revolve+attachment; requires_cavity=True; min_wall_mm=1.2 / ewer with a thick handle and a spout that keeps a real bore |
| V10 | 带盖壶 | 1.0 | IMPLEMENTED | `synlab.mothers.vessels.group_composite` | family=revolve+lid; requires_cavity=True; min_wall_mm=1.2 / body plus an independent pre-break lid component (contact is not R2) |
| V11 | 坛 | 1.0 | IMPLEMENTED | `synlab.mothers.vessels.group_revolve` | family=revolve; requires_cavity=True; min_wall_mm=1.4 / large belly with a short neck; belly/mouth ratio and shoulder arc are real |
| V12 | 盆 | 1.0 | IMPLEMENTED | `synlab.mothers.vessels.group_revolve` | family=revolve; requires_cavity=True; min_wall_mm=1.0 / wide thin-walled basin: base/mouth ratio and rim thickening are real |
| V13 | 盒 | 1.0 | IMPLEMENTED | `synlab.mothers.vessels.group_extrude` | family=prism; requires_cavity=True; min_wall_mm=1.0 / rounded rectangular extruded shell with a real wall and floor |
| V14 | 盖 | 1.0 | IMPLEMENTED | `synlab.mothers.vessels.group_composite` | family=revolve; requires_cavity=False; min_wall_mm=2.0 / closed lid solid: dome, seat skirt, real knob and polygon rim |
| V15 | 灯盏 | 1.0 | IMPLEMENTED | `synlab.mothers.vessels.group_composite` | family=revolve+spout; requires_cavity=True; min_wall_mm=1.0 / shallow lamp body with a real wick spout and a foot ring |
| V16 | 香炉 | 1.0 | IMPLEMENTED | `synlab.mothers.vessels.group_composite` | family=revolve+attachment; requires_cavity=True; min_wall_mm=1.2 / belly on real legs with optional vent holes cut through the shoulder |
| V17 | 花盆 | 1.0 | IMPLEMENTED | `synlab.mothers.vessels.group_composite` | family=revolve+pierced; requires_cavity=True; min_wall_mm=1.2 / tapered thick shell with drainage holes cut through the floor |
| V18 | 砖 | 1.0 | IMPLEMENTED | `synlab.mothers.vessels.group_extrude` | family=prism; requires_cavity=False; min_wall_mm=1.0 / rounded solid slab with real edge grooves, perforations and bed camber |
| V19 | 平瓦 | 1.0 | IMPLEMENTED | `synlab.mothers.vessels.group_extrude` | family=prism; requires_cavity=True; min_wall_mm=1.0 / thick parameterised tile: pan, side lips, slope and camber are real |
| V20 | 弧瓦 | 1.0 | IMPLEMENTED | `synlab.mothers.vessels.group_sheet` | family=arc_band; requires_cavity=False; min_wall_mm=3.0 / thick arc band: real radius, wrap angle, length and nose lift |
| V21 | 曲面板 | 1.0 | IMPLEMENTED | `synlab.mothers.vessels.group_sheet` | family=curved_shell; requires_cavity=False; min_wall_mm=3.0 / doubly curved B-spline panel with a real solidified thickness |
| V22 | 碑板 | 1.0 | IMPLEMENTED | `synlab.mothers.vessels.group_extrude` | family=prism; requires_cavity=False; min_wall_mm=3.0 / thick slab with a real chamfer and an engraved inscription band |
| V23 | 小雕像 | 1.0 | IMPLEMENTED | `synlab.mothers.vessels.group_composite` | family=superquadric; requires_cavity=False; min_wall_mm=2.0 / closed superquadric torso/head plus swept limbs with real root overlap |
| V24 | 装饰构件 | 1.0 | IMPLEMENTED | `synlab.mothers.vessels.group_sheet` | family=superquadric; requires_cavity=False; min_wall_mm=2.0 / superquadric base body with a real repetition field and relief pads |

### 材料族（12）

| ID | 名称 | 版本 | 状态 | 模块 | 适用/备注 |
|---|---|---|---|---|---|
| M01 | 粗陶 | 1.0 | IMPLEMENTED | `synlab.materials.catalogue` | family=earthenware; grain_scale_mm=[0.8, 3.0]; porosity=high / large grog aggregate, visible pores and an uneven body colour |
| M02 | 细陶 | 1.0 | IMPLEMENTED | `synlab.materials.catalogue` | family=earthenware; grain_scale_mm=[0.2, 0.9]; porosity=medium / fine grain with a short correlation length; polished and eroded apart |
| M03 | 炻器 | 1.0 | IMPLEMENTED | `synlab.materials.catalogue` | family=stoneware; grain_scale_mm=[0.3, 1.2]; porosity=low / dense low-porosity body with an optional specular glaze state |
| M04 | 白瓷 | 1.0 | IMPLEMENTED | `synlab.materials.catalogue` | family=porcelain; grain_scale_mm=[0.05, 0.3]; porosity=very_low / pale body with a thin glaze and small-scale fracture statistics |
| M05 | 彩瓷 | 1.0 | IMPLEMENTED | `synlab.materials.catalogue` | family=porcelain; grain_scale_mm=[0.05, 0.3]; porosity=very_low / porcelain body with a mother-continuous painted layer; new sections expose the body, never the paint |
| M06 | 施釉陶 | 1.0 | IMPLEMENTED | `synlab.materials.catalogue` | family=earthenware; grain_scale_mm=[0.8, 3.0]; porosity=medium / pottery body with an independent glaze layer: the layer interface, glaze loss and body loss are separate records |
| M07 | 玻璃 | 1.0 | IMPLEMENTED | `synlab.materials.catalogue` | family=glass; grain_scale_mm=[0.02, 0.2]; porosity=none / transmissive high-specular body with smooth cut faces; legal scans may have missing measurements |
| M08 | 石材 | 1.0 | IMPLEMENTED | `synlab.materials.catalogue` | family=stone; grain_scale_mm=[0.5, 4.0]; porosity=low / mineral grain with a real bedding direction; anisotropic cut faces and weathering statistics |
| M09 | 石膏 | 1.0 | IMPLEMENTED | `synlab.materials.catalogue` | family=plaster; grain_scale_mm=[0.2, 1.2]; porosity=very_high / pale porous body with powdering and erosion statistics |
| M10 | 骨质 | 1.0 | IMPLEMENTED | `synlab.materials.catalogue` | family=bone; grain_scale_mm=[0.2, 1.5]; porosity=high / porous bone with an outer/inner layer difference and a directional field; procedural statistics, no biomechanical claim |
| M11 | 木质 | 1.0 | IMPLEMENTED | `synlab.materials.catalogue` | family=wood; grain_scale_mm=[1.0, 8.0]; porosity=medium / continuous fibre / growth-ring field with directional edges; procedural tear statistics, not a crack solver |
| M12 | 金属 | 1.0 | IMPLEMENTED | `synlab.materials.catalogue` | family=metal; grain_scale_mm=[0.05, 0.6]; porosity=none / reflective body with a corrosion layer and procedural cut statistics; plastic fracture is outside the core backends |

### 层结构组合（4）

| ID | 名称 | 版本 | 状态 | 模块 | 适用/备注 |
|---|---|---|---|---|---|
| L01 | 坯体+釉 | 1.0 | IMPLEMENTED | `synlab.materials.layers` | mode=GEOMETRIC_LAYER; layers=2; body_material=M01 / body plus a real glaze body; delamination is a boolean quantity |
| L02 | 坯体+彩绘 | 1.0 | IMPLEMENTED | `synlab.materials.layers` | mode=SHADING_LAYER; layers=2; body_material=M05 / porcelain body plus appearance-only painting |
| L03 | 石质+表面涂层 | 1.0 | IMPLEMENTED | `synlab.materials.layers` | mode=GEOMETRIC_LAYER; layers=2; body_material=M08 / stone body plus a real surface coating |
| L04 | 木基体+涂饰 | 1.0 | IMPLEMENTED | `synlab.materials.layers` | mode=SHADING_LAYER; layers=2; body_material=M11 / wood body plus an appearance-only finish |

### 纹样族（16）

| ID | 名称 | 版本 | 状态 | 模块 | 适用/备注 |
|---|---|---|---|---|---|
| PAT01 | 素面 plain | 1.0 | IMPLEMENTED | `synlab.patterns.families` | geometry=False; appearance_only=True; complexity_tiers=[1, 2, 3] / constant colour with an optional low-frequency colour field; may be fully plain |
| PAT02 | 环带 bands | 1.0 | IMPLEMENTED | `synlab.patterns.families` | geometry=False; appearance_only=True; complexity_tiers=[1, 2, 3] / band centre lines in profile arc length, seamless in the azimuthal direction |
| PAT03 | 条纹 stripes | 1.0 | IMPLEMENTED | `synlab.patterns.families` | geometry=False; appearance_only=True; complexity_tiers=[1, 2, 3] / linear-phase stripes with an integer azimuthal count (the seam closes exactly) |
| PAT04 | 格网 grid | 1.0 | IMPLEMENTED | `synlab.patterns.families` | geometry=False; appearance_only=True; complexity_tiers=[1, 2, 3] / two (or three) stripe sets combined by union/intersection with explicit mix order |
| PAT05 | 波浪 waves | 1.0 | IMPLEMENTED | `synlab.patterns.families` | geometry=False; appearance_only=True; complexity_tiers=[1, 2, 3] / sine or Bezier centre line at an integer wave count, distance raster + EDT |
| PAT06 | 点阵 dots | 1.0 | IMPLEMENTED | `synlab.patterns.families` | geometry=False; appearance_only=True; complexity_tiers=[1, 2, 3] / crystal lattice or scipy PoissonDisk dots with an audited periodic seam extension |
| PAT07 | 三角 triangles | 1.0 | IMPLEMENTED | `synlab.patterns.families` | geometry=False; appearance_only=True; complexity_tiers=[1, 2, 3] / triangular tile with integer column count; line or solid barycentric fill |
| PAT08 | 回纹 meander | 1.0 | IMPLEMENTED | `synlab.patterns.families` | geometry=False; appearance_only=True; complexity_tiers=[1, 2, 3] / meander fret in a periodic tile with shared endpoints across tile borders |
| PAT09 | 交叉线 crosshatch | 1.0 | IMPLEMENTED | `synlab.patterns.families` | geometry=False; appearance_only=True; complexity_tiers=[1, 2, 3] / 2-3 layered line fields with deterministic missing strokes |
| PAT10 | 花叶 floral | 1.0 | IMPLEMENTED | `synlab.patterns.families` | geometry=False; appearance_only=True; complexity_tiers=[1, 2, 3] / bounded L-system/turtle skeleton plus svgpathtools Bezier leaf outlines |
| PAT11 | 局部徽记 medallion | 1.0 | IMPLEMENTED | `synlab.patterns.families` | geometry=False; appearance_only=True; complexity_tiers=[1, 2, 3] / programmatic vector symbol or a restricted, registered SVG path |
| PAT12 | 字符 glyphs | 1.0 | IMPLEMENTED | `synlab.patterns.families` | geometry=False; appearance_only=True; complexity_tiers=[1, 2, 3] / one-shot Pillow glyph layout with a SciPy distance map (font hash frozen) |
| PAT13 | 窑变 kiln | 1.0 | IMPLEMENTED | `synlab.patterns.families` | geometry=False; appearance_only=True; complexity_tiers=[1, 2, 3] / multi-scale continuous blotch field, independent roughness sub-stream |
| PAT14 | 浮雕 relief | 1.0 | IMPLEMENTED | `synlab.patterns.families` | geometry=True; appearance_only=False; complexity_tiers=[1, 2, 3] / smooth relief mask -> positive height -> real displacement of the whole body |
| PAT15 | 刻线 engrave | 1.0 | IMPLEMENTED | `synlab.patterns.families` | geometry=True; appearance_only=False; complexity_tiers=[1, 2, 3] / curve distance -> negative height -> real engraved displacement of the whole body |
| PAT16 | 组合 combination | 1.0 | IMPLEMENTED | `synlab.patterns.families` | geometry=False; appearance_only=True; complexity_tiers=[1, 2, 3] / region masks and a bounded composition of the layers above |

### 断裂后端（4 必做 + 1 选配）

| ID | 名称 | 版本 | 状态 | 模块 | 适用/备注 |
|---|---|---|---|---|---|
| fracture_modes | fracture-modes 物理插件 | 1.0 | MISSING | `synlab.fracture.api` | author code not fetched; license and units unverified, so the backend is registered as MISSING and never approximated |
| plane_shared_cut | 共享平面切割 | 1.0 | IMPLEMENTED | `synlab.fracture.api` | shell=True; solid=True / analytic plane cut with one shared closed cutter body |
| rough_shared_cut | 共享粗糙切割 | 1.0 | IMPLEMENTED | `synlab.fracture.api` | shell=True; solid=True / finite Fourier height field frozen once, shared by both sides |
| secondary_fracture | 二次破碎 | 1.0 | IMPLEMENTED | `synlab.fracture.api` | shell=True; solid=True / child event on the largest piece; adjacency is rebuilt from interface samples so old patches are clipped by membership |
| warped_partition | 共享形变 Voronoi/Power 分区 | 1.0 | PENDING | `synlab.fracture.api` | shell=True; solid=True / weighted Power cells via scipy Qhull are implemented in the spec; the conformal gmsh PLC + shared warp stage is NOT implemented in this build (capability p |

### 退化轴（31）

| ID | 名称 | 版本 | 状态 | 模块 | 适用/备注 |
|---|---|---|---|---|---|
| G01 | G01 | 1.0 | IMPLEMENTED | `synlab.degrade.axes` | low-frequency correlated field x distance/incidence variance x a fixed outlier probability; the deployment estimate is reported separately from the audit reference RMS. |
| G02 | G02 | 1.0 | IMPLEMENTED | `synlab.degrade.axes` | fixed nested prefix of the frozen order with a point budget; an effective N0 source keeps its real size at level 0 (no upsampling to a nominal budget). |
| G03 | G03 | 1.0 | IMPLEMENTED | `synlab.degrade.axes` | connected holes on the observed lattice: the seed positions are frozen in the basis and only the hole radius grows with the level, so the removed sets are nested by construction an |
| G04 | G04 | 1.0 | IMPLEMENTED | `synlab.degrade.axes` | per-frame SE(3) perturbation followed by a real re-fusion of the per-view depth; translation and rotation are separate single-factor variants and pose_drift_profile is the explicit |
| G05 | G05 | 1.0 | IMPLEMENTED | `synlab.degrade.axes` | Open3D quadric edge collapse with a measured Hausdorff budget and an ROI retention constraint; level 0 bypasses the decimator entirely. |
| G06 | G06 | 1.0 | IMPLEMENTED | `synlab.degrade.axes` | only the observation frame and the legal scale fields change; the truth reference hash must stay identical (plan 15.4). |
| G07 | G07 | 1.0 | IMPLEMENTED | `synlab.degrade.axes` | focal / principal point / distortion are separate single-factor variants; the perturbation is applied before back-projection and the frames are re-fused. calibration_profile change |
| G08 | G08 | 1.0 | IMPLEMENTED | `synlab.degrade.axes` | three spurious-surface variants (support bump, warped hole lid, connecting bridge) reuse synlab.observe.spurious.apply_spurious; only the observed entity changes and spurious_mask  |
| I01 | I01 | 1.0 | IMPLEMENTED | `synlab.degrade.axes` | Gaussian PSF in the plane, applied to the linear signal before the response; the depth-dependent variant blends two PSFs by depth and needs per-frame depth. |
| I02 | I02 | 1.0 | IMPLEMENTED | `synlab.degrade.axes` | single-exposure directional kernel by default; the exposure_integration variant integrates a frozen number of sub-exposures along the same trajectory. |
| I03 | I03 | 1.0 | IMPLEMENTED | `synlab.degrade.axes` | linear sensor noise y = Poisson(g*x)/g + N(0,sigma^2) with x = max(L*2^EV, 0); photon_scale varies the photon gain with the read noise fixed, read_sigma does the opposite, and came |
| I04 | I04 | 1.0 | IMPLEMENTED | `synlab.degrade.axes` | exposure_gain acts before the photon count; digital_gain is registered separately (it is not interchangeable). The negative sub-configuration is its own variant and the dark and br |
| I05 | I05 | 1.0 | IMPLEMENTED | `synlab.degrade.axes` | one frozen gain-direction vector; the developed profile is frozen after calibration |
| I06 | I06 | 1.0 | IMPLEMENTED | `synlab.degrade.axes` | scene light/BRDF re-render; the zero level is the same-source baseline scene and does not claim the physical glaze has no highlight. Changing BRDF, exposure and light angle togethe |
| I07 | I07 | 1.0 | IMPLEMENTED | `synlab.degrade.axes` | 3-D occluder bodies are added to the scene and the views are re-rendered; a delivered-pixel patch would not be an occluder. |
| I08 | I08 | 1.0 | IMPLEMENTED | `synlab.degrade.axes` | fixed-priority nested deletion; the baseline V0 source is returned unchanged at level 0 and every level is a subset of the previous one. |
| I09 | I09 | 1.0 | IMPLEMENTED | `synlab.degrade.axes` | baseline long edge is kept at level 0; non-zero levels apply an anti-aliased downsample and update K through the frozen pixel transform. 1/8 is the extra stress level of the plan's |
| I10 | I10 | 1.0 | IMPLEMENTED | `synlab.degrade.axes` | level 0 does not re-encode at all; non-zero levels run a real JPEG encode/decode and report bytes, error RMS and blockiness. |
| P01 | P01 | 1.0 | IMPLEMENTED | `synlab.degrade.axes` | fixed filter radius and full recession basis; only recession_strength moves. The radius scan is a separate variant and never claims the same-basis nesting. radius_mm=2.0 is the res |
| P02 | P02 | 1.0 | IMPLEMENTED | `synlab.degrade.axes` | edge-distance driven inward fillet built from the analytic rolling-ball section of every convex edge on the ROI boundary and subtracted from the source; never a whole-patch Laplaci |
| P03 | P03 | 1.0 | IMPLEMENTED | `synlab.degrade.axes` | non-negative smooth recession over the interface ROI with a wall-thickness guard; the depth field is frozen in the basis and pinned to zero on the ROI rim, so the five levels are n |
| P04 | P04 | 1.0 | IMPLEMENTED | `synlab.degrade.axes` | fixed cutter position/direction frozen in the basis; the cutter size is found by a 1-D geometric search that brackets the declared contact loss and then bisects, subject to the fro |
| P05 | P05 | 1.0 | IMPLEMENTED | `synlab.degrade.axes` | nested paint masks from one frozen rank field; the geometry hash must stay identical (appearance-only axis). |
| P06 | P06 | 1.0 | IMPLEMENTED | `synlab.degrade.axes` | smooth patch coverage of one frozen field; the core variant changes appearance only (geometry hash unchanged) and dirt_geometry adds an explicit contamination body registered as it |
| P07 | P07 | 1.0 | IMPLEMENTED | `synlab.degrade.axes` | original outer-surface ROI only; hidden surfaces are never backfilled |
| P08 | P08 | 1.0 | IMPLEMENTED | `synlab.degrade.axes` | three single-factor variants (crack width, coat area, painted-coat loss) plus one explicitly bundled stress variant; crack width, crack length and layer area are never mixed into o |
| X01 | X01 | 1.0 | IMPLEMENTED | `synlab.degrade.axes` | modalities are removed from the payload (presence=false) 闂?never replaced by a zero image that claims to be valid data. |
| X02 | X02 | 1.0 | IMPLEMENTED | `synlab.degrade.axes` | boundary px error / missing blob / false positive are separate variants; every crop or ROI change updates K and the pixel transform, and the research mask (mask_reference) is never |
| X03 | X03 | 1.0 | IMPLEMENTED | `synlab.degrade.axes` | missing context and conflicting context are separate variants; a missing context is never constructed as a necessary conflict (plan 15.5). |
| X04 | X04 | 1.0 | IMPLEMENTED | `synlab.degrade.axes` | only the real OBS_EST fields are perturbed (never an oracle intensity). The regression variant shifts the estimate by a frozen multiple of its own measured spread, so the bias is c |
| X05 | X05 | 1.0 | IMPLEMENTED | `synlab.degrade.axes` | baseline plus four held-out camera/light/ISP presets; this is a categorical shift, so no scalar monotonicity is claimed between levels. |

## 3. 复用与自编缺口

| module | selected dependency | version | mode |
|---|---|---|---|
| parameters_random | numpy + scipy.stats.qmc | numpy 2.5.3 / scipy 1.18.1 | DIRECT+ADAPTER |
| profile_interpolation | scipy.interpolate | scipy 1.18.1 | DIRECT |
| revolve_extrude_sweep | trimesh | trimesh 5.1.0 | DIRECT+ADAPTER |
| solid_boolean_and_components | manifold3d + trimesh.boolean | manifold3d 3.5.4 / trimesh 5.1.0 | DIRECT+ADAPTER |
| manifold_source_attributes | manifold3d MeshGLP attributes + project-owned source keys | manifold3d 3.5.4 | EXTENSION |
| conformal_shared_mesh | gmsh | gmsh 4.15.2 (PyPI wheel with bundled binary) | DIRECT+ADAPTER |
| voronoi_power_partition | scipy.spatial + scipy.optimize | scipy 1.18.1 | DIRECT+EXTENSION |
| physical_fracture_plugin | - | - | ADAPTER |
| noise_fields | numpy + scipy.ndimage | numpy 2.5.3 / scipy 1.18.1 | DIRECT+EXTENSION |
| poisson_disk_sampling | scipy.stats.qmc.PoissonDisk + scipy.spatial.cKDTree | scipy 1.18.1 | DIRECT+EXTENSION |
| bezier_svg_2d | svgpathtools + shapely + Pillow | svgpathtools 1.8.0 / shapely 2.1.2 / pillow 12.3.0 | DIRECT+EXTENSION |
| text_rendering | Pillow | pillow 12.3.0 | DIRECT+ADAPTER |
| voxel_damage_isosurface | scipy.ndimage + scikit-image | scipy 1.18.1 / scikit-image 0.26.0 | DIRECT+EXTENSION |
| image_filters_and_codecs | opencv-python-headless | opencv-python-headless 5.0.0.93 | DIRECT+ADAPTER |
| gpu_differentiable_filters | - | - | DIRECT |
| rendering | Blender 5.2.2 LTS portable driven as a subprocess worker (primary path); project software rasterizer retained as the declared comparison/fallback backend | Blender 5.2.2 LTS portable (build hash d13f752e3b9c, bundled Python 3.13.13) at third_party/blender-5.2.2-windows-x64/blender.exe; worker blender_scripts/render_worker.py | ADAPTER (Blender is the primary imaging path via backend='BLENDER_CYCLES'; the in-process software rasteriser stays as the measured comparison/fallback and is still labelled SOFTWARE_RASTERIZER) |
| pointcloud_processing | open3d + scipy.spatial.cKDTree + trimesh | open3d 0.19.0 / scipy 1.18.1 / trimesh 5.1.0 | DIRECT+EXTENSION |
| photogrammetry_mvs | pycolmap | pycolmap 3.11.1 | DIRECT+ADAPTER |
| training_and_retrieval | torch + numpy (+ faiss optional) | torch 2.5.1+cpu / numpy 2.5.3 / faiss-cpu 1.15.1 | DIRECT+EXTENSION |
| statistics | scipy.stats + numpy | scipy 1.18.1 / numpy 2.5.3 | DIRECT+EXTENSION |
| schema_api_cli | pydantic + fastapi + typer | pydantic 2.13.5 / fastapi 0.142.2 / typer 0.27.2 | DIRECT+ADAPTER |
| execution_and_metadata | sqlite3 (stdlib) + concurrent.futures | CPython 3.12.14 stdlib | DIRECT+EXTENSION |
| forms_and_ui | react + typescript + vite (+ three.js, echarts) | see frontend/package-lock.json | DIRECT+ADAPTER |
| three_d_display | three.js + GLTFLoader | see frontend/package-lock.json | DIRECT+EXTENSION |
| array_and_table_storage | pyarrow + numpy npz shards (+ zarr for chunked caches) | pyarrow 25.0.1 / zarr 3.4.0 | DIRECT+ADAPTER |

### CUSTOM_GAP 明细

- **rendering**: project-side adapter around the installed Blender (external portable binary; bpy is still not importable into the venv) — 证据：Blender 5.2.2 LTS portable is present (third_party/blender-5.2.2-windows-x64/blender.exe, build hash d13f752e3b9c) and passes the doctor check; `pip install bpy` still reports no distribution for Windows/CPython 3.12, so Blender is driven as a subprocess with blender_scripts/render_worker.py
- **patterns**: periodic and variable-radius Poisson disk contract — 证据：scipy.stats.qmc.PoissonDisk has no periodic/variable-radius options
- **fracture**: shared cutter truth, origin mapping and event tree on top of generic booleans — 证据：Manifold exposes only auxiliary run/face ids; the plan requires explicit per-triangle source keys and barycentric patches
- **scheduler**: lease/fencing/reservation protocol over SQLite — 证据：no project queue or ORM exists in this workspace

