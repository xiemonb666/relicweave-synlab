# 花纹显示一致性：根因、修复与数值验收（U13 `/synlab/showcase`）

用户报告：**"随机生成的花纹不连续，且与显示的器物上的花纹不一致。"**

本文记录复现步骤、代码级根因（带实测数值）、修复方案与三条硬指标的实测结果。
所有数字都来自仓库里真实模块的真实输出；每一步都能用文末的命令重跑。
**任何未达标的指标都保留真实数值**，已知局限见 §6。

---

## 0. 结论摘要

| 症状 | 根因（代码位置） | 修复 |
|---|---|---|
| 卡片 PNG"不连续" | `tools/build_demo_assets.py::_pattern_channel_images`（旧 589–704 行）用 **600000 个面积加权随机采样点分箱**到 256×128：每格平均只有 18.6 个样本 → 颗粒噪声；PAT12 有 **44.0%** 的格没有任何样本，被写成纯黑（空洞） | 换成**确定性周期栅格**：`u_k=(k+0.5)/W`、`s_j=s_lo+j·ds`，逐像素用图卡逆映射回到母体毫米坐标调用 `evaluate()`，2×2 超采样在线性空间取面积平均；无随机、无空洞 |
| 器物上没有花纹 | `_export_display_glb`（旧 415–492 行）只导出 `trimesh.Trimesh(vertices, faces)`；8 个母体 GLB 的实测属性都只有 **`POSITION`**（`materials: 0, textures: 0, images: 0`） | 新增 `_pattern_texture_bake` + `_export_display_glb(..., bake=...)`：把**与卡片同一份 albedo PNG** 作为 glTF `baseColorTexture` 贴到该母体真实图卡坐标 `(u,s)` 上，UV 显式给出并做接缝解缠 |
| 器物"碎块/不连续" | GLB 里没有 `NORMAL`：three.js `GLTFLoader` 在几何缺 NORMAL 时设 `flatShading = true`（`frontend/node_modules/three/examples/jsm/loaders/GLTFLoader.js:3522` + `:3581`）→ 每个三角面平色。实测面法线与平滑法线夹角：V04 中位 1.35°、P95 **13.45°**、最大 **29.82°**；V13/V18 中位 18.9°/22.3°（这两个母体本身是多面体，平面着色更接近正确，见 §6） | 导出时 `include_normals=True`，且法线**从完整母体网格算一次、两个 primitive 共用** → 平滑着色，且 tag 边界与 UV 解缠缝上都不会出现假折线 |
| 素面器物发暗/发灰 | GLB 里没有 `material`：glTF 规范默认材质 `metallic=1`，浏览器里是一块没有漫反射的金属 | `_export_display_glb` 无 `bake` 时也给一个**展示用**中性陶土色 `PBRMaterial(metallic=0, roughness=0.72)`，并在 meta 里注明"不是权威材质" |

---

## 1. 复现（修前）

```powershell
# 后端 + 前端
& .venv\Scripts\python.exe tests\a12\api_ui\_serve.py --store-root data\a12 --port 8077 --role researcher
cd frontend; $env:VITE_SYNLAB_PROXY_TARGET="http://127.0.0.1:8077"; node node_modules/vite/bin/vite.js preview --port 4188
# 浏览器打开 http://localhost:4188/synlab/showcase
```

修前的实测事实（`data/a12_demo` 里当时的产物）：

* 纹样卡片 PNG 256×128，`raster.method = "面元面积加权随机采样 → evaluate() → (x,s) 网格分箱算术平均…"`，
  `n_samples=600000`，每有效 bin 平均样本 18.3–32.7；
* 逐通道实测（对 PNG 直接统计）：

  | 族 | 黑像素占比 | albedo 列方向相邻差 mean/p95/max（8-bit） | 回绕列差 |
  |---|---|---|---|
  | PAT01 | 1.4% | 0.36 / 1.73 / 3.18 | 0.11 |
  | PAT02 | 6.5% | 0.45 / 2.34 / 5.84 | 1.28 |
  | PAT03 | 4.0% | 11.12 / 44.00 / 49.01 | 1.20 |
  | PAT06 | 7.1% | 7.56 / 19.73 / 25.57 | 2.58 |
  | PAT12 | **44.0%** | 3.03 / 8.60 / 13.10 | 7.61 |
  | PAT15 | 15.3% | 5.76 / 30.70 / 48.38 | 3.14 |

* 注意：**回绕列差并没有系统性大于相邻列差**（例如 PAT12 回绕 7.61 vs 相邻 p95 8.60）。
  也就是说 `u` 的分箱索引本来就是周期正确的（`col = floor(u·W) mod W`），
  画面上的"不连续"来自**蒙特卡洛颗粒噪声 + 未覆盖格被写成黑色**，不是 `u` 端点处理错误。
  这一点很重要：**不能靠"修接缝公式"解决**。
* 器物 GLB（`GET /showcase/asset/{id}/glb`）实测：`attributes=["POSITION"]`、`materials=0`、
  `textures=0`、`images=0`（8 个母体全部如此）→ 器物上**根本没有花纹**，与卡片谈不上一致。

修前截图：`C:\Users\xiemo\AppData\Local\Temp\synlab_probe\before_full.png`（整页，2530×18584），
裁出的母体视口：`...\before_mother_viewport.png` —— 器物是一整块无花纹的灰色。

---

## 2. 根因（代码级）

### 2.1 卡片 PNG 用随机采样分箱（噪声 + 空洞），不是接缝公式错

旧实现（`_pattern_channel_images`）在母体 tagged 面上按面积加权抽 600000 个点，
把 `evaluate()` 的输出按 `(x,s)` 分箱求算术平均。分箱数是 256×128=32768，
所以每个格平均只有 18.6 个样本：均值本身带 ~24% 的采样标准差，
再加上**采样密度不均**（面积加权 + 图的 (u,s) 矩形只有一部分被 tagged 面占据），
PAT12 有 44.0% 的格连一个样本都没有——旧代码把这些格写成纯黑（`未覆盖像素为黑`），
视觉上就是"图案断了、有黑洞、到处是噪点"。

`docs/a12/patterns.md` 里记录的 6.7e-15 接缝误差是 `synlab.patterns.api.evaluate`
**场本身**的性质，与这里的栅格化无关（本次实测复现：`audit_pattern` 报
`seam.chart_space.max_abs_color_error = 0`，容差 1e-5，1000 对点）。

### 2.2 器物 GLB 只有位置，没有花纹

`_export_display_glb` 用 `trimesh.Trimesh(vertices=..., faces=...)` 直接 `scene.export(file_type="glb")`，
既没有顶点色、也没有 UV/贴图/材质。卡片按族生成、器物是素面几何，
两者当然对不上——这就是"花纹跟器物不一致"的直接原因。

### 2.3 没有 NORMAL → three.js 逐面平色；没有 material → 默认金属

`GLTFLoader.js`：

```js
3522:  const useFlatShading = geometry.attributes.normal === undefined;
...
3581:  if ( useFlatShading ) cachedMaterial.flatShading = true;
```

旧 GLB 的属性只有 `POSITION` → `flatShading = true` → 每个三角面一块平色。
实测"面法线 vs 平滑法线"夹角（tagged 外壁上）：

| 母体 | 中位 | P95 | 最大 |
|---|---|---|---|
| V01 | 1.31° | 4.21° | 9.66° |
| V04 | 1.35° | 13.45° | 29.82° |
| V13 | 18.94° | 45.38° | 45.92° |
| V18 | 22.32° | 63.21° | 79.26° |

平面着色的亮度跳变按 sin(夹角) 计：V04 的 P95 就有 0.23×光强，V18 最大接近 1.0×光强。
（V13/V18 的几何本身就是多面体，平面着色反而更接近正确——见 §6 的诚实说明。）

---

## 3. 修复

### 3.1 `tools/build_demo_assets.py`：确定性周期栅格

新增/替换（`tools/build_demo_assets.py`）：

* `_chart_inverse(frame)`（:687）—— 只用图卡冻结时自带的数组重建 `(x_mm, s_mm) → 母体 mm`：
  revolve 用 `profile_rzs`、prism 用 `ring_xy`、sweep 用 `path_xyz`。
  （母体图卡**不提供** `chart.meta["uv_to_xyz"]`，只有 `synlab/patterns/fixtures.py` 的测试实体提供，
  所以逆映射必须自己从冻结数组重建——实测往返误差 ≤ **2.3e-13 mm**。）
* `_pattern_raster_plan`（:776）—— `u_k=(k+0.5)/W`（周期 `[0,1)`，**不含**端点 1）；
  `s_j=s_lo+j·ds`，`ds=(s_hi-s_lo)/(H-1)`（端点就是首末行中心）；
  texel 近似正方形，受采样预算 `PATTERN_RASTER_SAMPLE_BUDGET=1.2e6` 约束，
  且**不必细于场自带的特征尺度** `recipe.meta["footprint_mm"]`。
* `_pattern_chart_raster`（:900）—— 每像素 2×2 超采样 + 1 个像素中心点，
  全部点先在图卡 `(x,s)` 上构造、再逆映射成母体毫米坐标，**一次** `evaluate()` 调用出三通道
  （albedo/roughness/height 用同一网格、同一 recipe、同一次调用 → 逐像素对齐，不会互相错位）。
  超采样只在图卡合法范围内取样（边界按 clamp），否则图卡 `clip` 会让"逆映射往返"变成假误差。
* `_texel_face_coverage`（:833）—— 逐面点内测试，实测"图卡矩形里到底有多少 texel 真的被 tagged 面占据"，
  写进清单（`raster.face_coverage_fraction`）。没被占据的 texel 在网格上不可见，
  但仍按解析场求值——**不留黑洞，也不假装那些 texel 可见**。

栅格的连续性、抗锯齿低通量、逆映射往返误差都写进清单的 `metrics.raster`，页面原样展示。

### 3.2 器物三维：同一份栅格 → glTF baseColorTexture

`_pattern_texture_bake`（:1074）+ `_export_display_glb(..., bake=...)`（:418）：

* **UV 显式映射**：`TEXCOORD_0.u = x_mm / x_period_mm`（周期，采样器 `wrapS=REPEAT`）；
  `TEXCOORD_0.v = ((s_mm - s_lo)/ds + 0.5)/H`（texel 中心对齐，实测 `v ∈ [0.0032, 0.9968]`，
  严格落在 `(0,1)` 内 → `REPEAT`/`CLAMP` 在 v 上不可能造成差异）；
* **贴图就是卡片那张 PNG**：同一冻结 recipe、同一栅格、同一份字节，
  以 sRGB `baseColorTexture` 嵌进 GLB（实测内嵌图像与卡片 PNG **逐像素相同，最大差 0**）；
* **接缝**：跨 `u=0/1` 的面按面做 UV 解缠（给小于半周的一侧 `+1` 一整周）并把解缠角点拆成独立顶点
  （实测每族 39–73 个角点），三角形内不会"绕整张贴图倒着插值"；场本身周期，缝两侧色值本来相等；
* **未带纹样的面单独一个 primitive**：内壁与外壁共享同一个 `(u,s)`，拿外壁 UV 去采样会把图案画到内壁，
  所以 rim/foot/base/inner_wall 等面用 recipe 的 body 颜色（实测 PAT01：贴图 primitive 1728 面 / 931 顶点，
  body primitive 5280 面）；
* **法线**：从完整母体网格算一次、按索引给两个 primitive 共用（`_cache["vertex_normals"]`，
  trimesh 只在缓存里有该数组时才导出 `NORMAL`），tag 边界与解缠缝上都不会出现假折线；
* **材质**：`metallicFactor=0`（否则浏览器里渲染成一块黑金属），`roughnessFactor` 取 recipe 的 body 粗糙度。

`height_mm` 是几何通道（PAT14 relief / PAT15 engrave），属 `apply_pattern_geometry` 在断裂前作用于
完整母体的范畴，**展示 GLB 只烘焙 albedo、不做位移**（页面上原样写明）。

### 3.3 前端：卡片与器物成对展示

`frontend/src/components/showcase/sections.tsx::PatternsSection`：
在卡片下方新增一个 `SceneViewport`，展示 `artifacts.pattern_glb`（同一母体 + 该族），
标题写明"器物 V0X + 族 PATYY"，并列出 UV 映射、贴图资产 id、albedo sha256、
primitive 面数/顶点数、解缠角点数、`v` 实测范围；卡片 `<img>` 的宽高改成清单里的真实栅格尺寸
（不再是写死的 256×128）。新增指标行：网格周期规则、回绕列差 vs 相邻列差、逆映射往返误差、
`texel/footprint`、亚 texel 抗锯齿低通量、provenance 四元组。

---

## 4. 数值验收（硬指标实测）

数据：`data/a12_demo`（本次重跑 `--only mothers --force` + `--only patterns --force` 后的产物）。

### 4.1 接缝：同一 chart 随机 1000 对 `u=0/1` 点

| 指标 | 要求 | 实测 |
|---|---|---|
| `evaluate` 场本身（chart 空间，1000 对） | ≤1e-5 | **0.0**（容差 1e-5，`audit_pattern.seam.chart_space`） |
| PNG / GLB 采样路径（`u=0` 与 `u=1` 的 1000 对点，走同一张栅格的双线性采样） | ≤1e-5 | **0.0**（逐对完全相等：`u=0` 与 `u=1` 落在同一列上） |
| GLB 的 `TEXCOORD_0.v` 范围 | 落在 `(0,1)` | PAT01 **0.00325…0.99675**，PAT15 **0.0185…0.9815**（= `0.5/H … 1-0.5/H`） |

### 4.2 PNG 网格连续：回绕列差与相邻列差同阶

| 族 | 网格 | texel mm | footprint mm | texel/fp | 面覆盖 | 回绕/相邻(线性) | 回绕/相邻(8-bit) | 黑像素 | 亚 texel 低通 max |
|---|---|---|---|---|---|---|---|---|---|
| PAT01 | 1280×154 | 0.4478×0.4501 | 0.4277 | 1.48 | 0.977 | 0.00012 / 0.00057 | 0.013 / 0.216 | 0 | 0.0008 |
| PAT02 | 1280×138 | 0.7208×0.7250 | 0.4131 | 2.47 | 0.941 | 0.00001 / 0.00001 | 0.005 / 0.014 | 0 | 0.0216 |
| PAT03 | 1280×140 | 0.5902×0.5940 | 0.4644 | 1.80 | 0.950 | 0.00019 / 0.28612 | 0.045 / 58.010 | 0 | 0.0518 |
| PAT06 | 906×93 | 0.3774×0.3804 | 0.3775 | 1.42 | 0.957 | 0.00219 / 0.06776 | 0.323 / 14.900 | 0 | 0.0477 |
| PAT10 | 757×316 | 0.2927×0.2940 | 0.1207 | 3.44 | 0.994 | 0.00000 / 0.04733 | 0.000 / 7.717 | 0 | 0.4334 |
| PAT12 | 1280×58 | 0.3253×0.3312 | 0.2250 | 2.06 | 0.604 | 0.01014 / 0.01105 | 2.356 / 2.569 | 0 | 0.0976 |
| PAT14 | 1280×75 | 0.4729×0.4795 | 0.3635 | 1.85 | 0.999 | 0.00000 / 0.00000 | 0.000 / 0.000 | 0 | 0.0000 |
| PAT15 | 903×27 | 0.4239×0.4357 | 0.4242 | 1.43 | 0.917 | 0.00000 / 0.06011 | 0.000 / 25.691 | 0 | 0.0074 |

* 每一族的**回绕列差都 ≤ 最大相邻列差**（最紧的是 PAT12：0.01014 vs 0.01105，同一量级），
  与修前"回绕差被噪声淹没/画面有 44% 黑洞"形成直接对比；
* 黑像素占比全部为 **0**（修前 PAT12 是 44.0%）；
* "面覆盖"是实测的"图卡矩形里真被 tagged 面占据的 texel 比例"（PAT12 只有 0.604：
  V07 的外壁并没有铺满整个展开矩形——这是几何事实，不是缺陷）；
* "亚 texel 低通"是**超采样面积均值 vs 像素中心解析值**的实测差（抗锯齿低通量，不是掩盖误差）：
  PAT10 最大 0.4334（它的 `footprint_mm=0.1207` 比 texel 细 3.4 倍，属欠采样，见 §6）。

### 4.3 三维与二维一致：≥200 个母体表面顶点

顶点在 GLB 贴图上的颜色 vs 按同一 `(u,s)` 在卡片 albedo PNG 上双线性采样的颜色，
统一换算到显示编码 8-bit（`round(255·clip(linear,0,1)^(1/2.2))`）：

| 族 | 参与比较的顶点数 | max | p99 | p90 | p50 |
|---|---|---|---|---|---|
| PAT01 | 931 | **0.0**/255 | 0.0 | 0.0 | 0.0 |
| PAT02 | 686 | **0.0**/255 | 0.0 | 0.0 | 0.0 |
| PAT03 | 1029 | **0.0**/255 | 0.0 | 0.0 | 0.0 |
| PAT06 | 784 | **0.0**/255 | 0.0 | 0.0 | 0.0 |
| PAT10 | 784 | **0.0**/255 | 0.0 | 0.0 | 0.0 |
| PAT12 | 735 | **0.0**/255 | 0.0 | 0.0 | 0.0 |
| PAT14 | 707 | **0.0**/255 | 0.0 | 0.0 | 0.0 |
| PAT15 | 285 | **0.0**/255 | 0.0 | 0.0 | 0.0 |

要求 ≤2/255：**全部族最大误差 0.0/255**。为什么是 0 而不是"大概相等"：
GLB 内嵌的贴图与卡片 PNG 是**同一份像素**（测试里逐像素断言 `max|Δ|=0`），
而 UV 与图卡坐标的映射误差实测 `< 1e-6`（float32 精度；一个 texel 是 `1/H`≈1e-2 量级）。
换句话说：三维与二维不是"看起来差不多"，而是**同一份数据的两条采样路径**。
这条检查不是自证——它同时校验了 (a) 贴图像素与卡片一致、(b) UV 与母体真实 `(u,s)` 一致、
(c) 采样约定（texel 中心对齐 + 周期回绕）一致，三者任一错位都会立刻在 8-bit 上暴露。
（开发过程中它确实抓到过一次错位：测试端行采样差了半个 texel，PAT06 立刻报 46.8/255。）

### 4.4 provenance：族名 / recipe hash / PNG 文件名 / 贴图 GLB

每个 `pattern:*` 条目都写进 `metrics.provenance`，并在资产 meta 里可逐项核对：

| 检查项 | 位置 | 实测 |
|---|---|---|
| 族名 | `entry.family_id` = `metrics.family_id` = `metrics.provenance.family_id` = GLB meta `family_id` = PNG 资产 meta `family_id` | 8/8 一致 |
| recipe hash | 清单 `metrics.recipe_hash` = recipe 资产 meta = **PNG 资产 meta** = **GLB 资产 meta** = `recipe.meta.recipe_hash` | 8/8 一致（如 PAT01 `sha256:867896b71968b1e6…`） |
| PNG 文件名 | `artifacts.channels.keys = {albedo: albedo_png, roughness: roughness_png, height_mm: height_png}`，且三个 payload 文件真实存在 | 8/8 一致 |
| albedo 哈希 | `sha256(资产里的 albedo_png 字节)` = `metrics.texture_bake.texture_sha256` = `provenance.albedo_png_sha256` = GLB meta `uv.texture_sha256` | 8/8 一致 |
| 贴图 ↔ 栅格 | GLB meta `raster_asset` = `artifacts.pattern_glb.raster_asset` = `artifacts.channels.asset_id` | 8/8 一致 |
| 血缘 | GLB 资产 `source_asset` = 该条目 `metrics.mother_asset`（同一个母体 mm/Z-up 权威资产） | 8/8 一致 |
| 内嵌贴图 | GLB 里 `images[0]` 解码后的像素 vs 卡片 PNG | 逐像素相同（max 0） |

### 4.5 回归测试

```
& .venv\Scripts\python.exe -m pytest tests/a12/showcase -q          # 退出码 0（31 passed, 1 skipped）
& .venv\Scripts\python.exe -m pytest tests/a12/showcase/test_pattern_consistency.py -q   # 退出码 0（11 passed）
& .venv\Scripts\python.exe -m pytest tests/a12/showcase/test_generator.py -q             # 退出码 0（9 passed）
& .venv\Scripts\python.exe -m pytest tests/a12/showcase/test_showcase_api.py -q          # 退出码 0（12 passed, 1 skipped）
& .venv\Scripts\python.exe tests\a12\showcase\check_showcase_frontend.py --skip-build    # 退出码 0（OVERALL: PASS）
```

`tests/a12/showcase/test_pattern_consistency.py`（新）覆盖：

1. `test_pattern_raster_grid_is_periodic_and_hole_free` —— 网格周期（回绕 ≤ 最大相邻 + ≤3×P95）
   + 无空洞像素 + 逆映射往返 <1e-6 mm + 与清单记录一致；
2. `test_seam_is_closed_in_field_png_and_glb_path` —— 1000 对 `u=0/1`：场 ≤1e-5、
   PNG/GLB 采样路径完全相等、GLB 的 `v` 落在 texel 中心范围内；
3. `test_vertex_colour_matches_the_card_png[0..7]` —— 每族 ≥200 个顶点（实际 285–1029）的
   8-bit 颜色误差 ≤2/255 + 贴图像素与卡片一致 + UV 与图卡坐标一致 + 材质非金属；
4. `test_provenance_family_recipe_png_glb_are_consistent` —— §4.4 的全部条目。

---

## 5. 截图核验（chrome-devtools，`http://localhost:4188/synlab/showcase`）

截图都存在 `C:\Users\xiemo\AppData\Local\Temp\synlab_probe\`（仓库写入范围只允许本文档，故不放仓库内）：

| 文件 | 内容 | 观察结论 |
|---|---|---|
| `before_full.png` / `before_mother_viewport.png` | 修前整页 / 母体视口 | 器物是**一整块无花纹的灰色**；卡片 PNG 有明显噪点与黑洞（PAT12 44% 黑格） |
| `after_patterns_PAT01.png` | 修后「2 · 纹样通道」分区 | 卡片图例写明"网格 1280×154（texel 0.4478×0.4501 mm)，每像素 2×2 超采样…**没有空洞像素**"；新增"器物三维：带该族花纹（同一 albedo 栅格贴图）"徽标与器物视口 |
| `after_vessel_PAT01.png` | 母体 V01 + PAT01 器物视口 | 器物表面出现与卡片同一份花纹（素面族的淡蓝色晕斑），**没有黑色金属感、没有逐面碎块**；`三角面/Mesh = 7008 / 2`（贴图 + body 两个 primitive），GLB 195.8 KiB |
| `after_pair_PAT03_low.png` | 卡片 + 器物在同一屏（浏览器缩放到 0.5） | 卡片条纹与器物壁面条纹是同一条纹（同一 `asset_5225766889643cb84713`）；UV 面板列出映射公式、albedo sha256、primitive 面数、解缠角点 60 |
| `after_vessel_PAT03_tight.png` / `after_vessel_PAT03_zoom.png` / `final_pair_PAT03.png` | 母体 V03 + PAT03 器物（近距离 / 卡片与器物同屏） | 卡片条纹与器物壁面条纹是同一条纹（同一 `asset_5225766889643cb84713`）；壁面条纹**沿整周连续**、间距均匀、跨接缝处无错位、无空洞、无逐面平色块；表面为平滑着色（法线来自完整网格）；UV 面板列出映射公式、albedo sha256、primitive 面数（1920 面/1029 顶点 + 3744 面 body 色）、解缠角点 60 |
| `after_mother_smooth2.png` | 修后母体库视口（V01） | 素面器物现在是**平滑着色 + 非金属展示材质**：`三角面/Mesh = 7008/1`、权威尺寸 `182.739 × 66.244 × 182.447 mm`（与 `audit_mother` 一致）、GLB 165.5 KiB |
| `after_vessel_PAT12.png` | 母体 V07 + PAT12（浅盘） | 卡片上的字符纹样同样出现在盘壁（该母体壁很矮，默认视角以顶面为主；页面标注了 UV 与贴图来源） |

观察要点（与硬指标对应）：器物上的花纹**连续**（无周向接缝错位、无逐面碎块）、
**与卡片图一致**（同一份栅格字节），且页面把这些事实所需的 provenance 全部显示出来。

---

## 6. 仍未解决 / 已知局限（保留真实数值）

1. **PAT10（花叶 floral）的亚 texel 欠采样**：其场自带 `footprint_mm=0.1207`，
   而栅格 texel 是 0.2927×0.2940（`texel/footprint = 3.44`），
   `analytic_deviation.albedo_max_abs = 0.4334`（超采样面积均值 vs 像素中心解析值）。
   要按 footprint 采样需要约 1847×772 个 texel（≈7.1e6 次 `evaluate`，是本机演示预算的 6 倍，
   会显著拉长生成时间并抬高内存）。当前选择：**如实记录 `texel/footprint` 与低通量**，
   不假装它已经足够细。PAT03/PAT12 也在 2.0–2.1 倍，其余族 1.4–2.5 倍。
2. **贴图分辨率 = 卡片分辨率**：展示 GLB 的花纹清晰度上限就是这张栅格
   （这是"卡片与器物必然一致"的代价；提升需要同时提高两者，见上一条）。
3. **只烘焙 albedo**：`roughness`/`height_mm` 通道只以 PNG 展示；
   `height` 是几何通道（`apply_pattern_geometry` 在断裂前作用于完整母体），
   展示 GLB 不做位移。页面与资产 meta 里都写明了这一点。
4. **不是所有 texel 都可见**：`face_coverage_fraction` 实测 0.604–0.999
   （PAT12 最低）。图卡是 `(u,s)` 展开矩形，真实网格只占据其中一部分；
   未被占据的 texel 仍按解析场求值（不留黑洞），但在三维上不可见——页面写出了这个比例。
5. **V13/V18 的"平面着色"问题**：这两个母体的外壁本身是多面体（面法线与平滑法线中位差
   18.9°/22.3°）。现在 GLB 带上 NORMAL 后会做平滑着色，对真正的折面来说**不如平面着色准确**；
   本次修复解决的是"光滑回转体被渲染成一格格平色"，对多面体没有做几何感知的法线分割。
   （原先它们连 NORMAL 都没有，浏览器一律平面着色，属于歪打正着。）
6. **碎裂 / 退化分区的 GLB 未重跑**：它们仍是旧字节（没有 NORMAL、没有材质）。
   重跑 `--only fracture --force` / `--only degrade --force` 后新导出的 GLB 会自动带上法线与材质；
   本次只重跑了 `--only mothers --force` 与 `--only patterns --force`（用户报告的是纹样分区）。
7. **本机的能力事实不变**：`rough_shared_cut` 仍按真实结局记为 FAILED/BLOCKED。
8. **生成期间环境发生了变化（如实记录）**：本次会话中途（2026-10-02 01:39）
   venv 里出现了 `fast_simplification 0.2.0`（此前 `_export_display_glb` 的 L1/L2 简化一直以
   `ModuleNotFoundError` 跳过）。因此重跑母体后，L1/L2 **真的**被算出来了。
   但展示页的视口会把 GLB 场景里的所有节点一起渲染（没有 LOD 选择器），
   三个层级重叠会 z-fighting，而 L2 实测外扩到 `193.95 mm`（L0 是 `182.45 mm`）会直接穿出器壁——
   实测样例（V01）：
   `L0 182.739×66.244×182.447` / `L1 184.285×66.473×182.640` / `L2 188.354×67.298×193.953` mm。
   处理：`_export_display_glb` **照实测量并记录** L1/L2 的面数、顶点数与外廓尺寸，
   但只把 **L0** 放进场景（meta 里 `exported_as_scene_node` 标明），
   `SceneViewport` 的提示改为按"真的在场景里的层级"生成文案。
   修复前该视口实测会读成 `三角面/Mesh = 9670 / 3`、权威尺寸 `198.941 mm`（把 L2 也算进去），
   修复后是 `7008 / 1`、`182.739 mm`（与 `audit_mother` 一致）。
9. **碎裂 / 退化分区的 GLB 仍没有 NORMAL**：它们没被重跑（见第 6 条），
   所以在浏览器里仍是平面着色；这与纹样分区无关，但若要整页一致，需要重跑那两个步骤。

---

## 7. 复现命令

```powershell
cd C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab

# 1) 重烘焙器物（法线 + 展示材质）与纹样（栅格 + 贴图 GLB）
& .venv\Scripts\python.exe tools\build_demo_assets.py --only mothers --force     # 8/8 OK，约 30 s
& .venv\Scripts\python.exe tools\build_demo_assets.py --only patterns --force    # 8/8 OK，约 90 s
& .venv\Scripts\python.exe tools\build_demo_assets.py --only patterns            # 全部 [skip]（幂等）

# 2) 回归测试（退出码 0）
& .venv\Scripts\python.exe -m pytest tests/a12/showcase/test_pattern_consistency.py -q
& .venv\Scripts\python.exe -m pytest tests/a12/showcase -q

# 3) 展示页
& .venv\Scripts\python.exe tests\a12\api_ui\_serve.py --store-root data\a12 --port 8077 --role researcher
cd frontend; $env:VITE_SYNLAB_PROXY_TARGET="http://127.0.0.1:8077"; node node_modules/vite/bin/vite.js build
node node_modules/vite/bin/vite.js preview --port 4188
# http://localhost:4188/synlab/showcase → 「2 · 纹样通道」
```

生成器退出码：`--only mothers --force` 与 `--only patterns --force` 都返回 **1**，
因为演示集里还有 4 个**真实的**非 OK 条目（2 个 `rough_shared_cut` 的
`PRECISION_BUDGET_EXCEEDED` + 2 个 PENDING/MISSING 后端的 `OPERATOR_NOT_REALIZED`），
这是生成器的既定语义（`0` 才是"全部 OK"），与本次修复无关，页面照实展示。

---

## 8. 改动文件

| 文件 | 改动 |
|---|---|
| `tools/build_demo_assets.py` | 新增 `_chart_inverse` / `_pattern_raster_plan` / `_pattern_chart_raster` / `_texel_face_coverage` / `_pattern_texture_bake`；重写 `_pattern_channel_images` 为确定性周期栅格；`_export_display_glb` 支持 `bake=`（贴图 + UV + 共用平滑法线 + 展示材质）、始终导出 NORMAL、只把 L0 放进场景（L1/L2 只记录指标）；`task_pattern` 增加 `pattern_glb` 产物与 `provenance`/`texture_bake` 指标 |
| `frontend/src/components/showcase/sections.tsx` | 纹样分区新增"器物 + 该族"三维视口、UV/贴图 provenance 面板、网格周期与一致性指标行；卡片 `<img>` 尺寸取真实栅格尺寸 |
| `frontend/src/components/SceneViewport.tsx` | LOD 提示改为按"真的在场景里的层级"（`exported_as_scene_node`）生成，不再无条件写"展示简化 LOD（L0/L1/L2）" |
| `tests/a12/showcase/test_pattern_consistency.py`（新） | 三条硬指标 + 网格周期 + provenance 的回归测试（11 项） |
| `docs/a12/pattern_consistency.md`（本文） | 根因、修复与实测证据 |
| `data/a12_demo/**` | 生成器输出（8 个母体 GLB 重烘焙 + 8 个纹样条目重生成及其贴图 GLB） |

**未改动**：`synlab/**`（场的数学、图卡语义、审计口径全部原样复用）、`data/a12/**`、
其它测试与文档。
