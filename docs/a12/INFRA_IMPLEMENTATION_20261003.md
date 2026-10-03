# 独立 VesselForge / PG-Frag 接入实施记录（2026-10-03）

## 主代理决策

- VesselForge Core 与 PG-Frag Core 分别独立代码库、版本、CLI/Python API 与 CI；A12 保持 RelicWeave 的观测、退化、关系/检索、预训练与诊断平台。
- 从最小纵向链路接入 A12：VF 资产 → 版本化适配 → PG solver → 结果/状态回到 A12。不要等两边完成后再集成，也不要求每阶段先复制完整 Web/UI/数据库。
- 求解器进程和 A12 API/worker 环境隔离。A12 接入层通过文件包/manifest、进度、错误、结果验证和资产引用交互；PG 不导入 VF 或 SynLab。
- VF/PG 双方内置同版本 neutral schema validator；本次不创建第四个共享仓库。字段调整先由主代理决策。
- 当前执行 owner：VesselForge 实现代理仅写 ShardForge/vesselforge/**、ShardForge/third_party/vesselforge-runtime/**、SynLab tmp/review_20261003/implementation/vf/**，以及本文件。其他代理不得写这些路径；PG、SynLab 生产实现/冻结配置各由其 owner 负责。

## forge.asset.v1 最小公共契约

- 根字段：schema=forge.asset.v1；units={length:mm,time:s,mass:kg}；frame=right_handed_z_up。
- geometry={surface_npz:geometry/surface.npz,solid_step:可选相对包内路径}。surface NPZ keys: vertices_mm float[N,3]、faces int[F,3]。
- fields={surface_fields_npz:fields/surface.npz}。字段 NPZ keys: face_region int[F,]、albedo_linear_rgb float[F,3]、roughness float[F,]。外观字段不是 truth/GT。
- material={mechanics:{rho_kg_m3,E_pa,nu,Gc_j_m2},calibration_status:UNVALIDATED_PROTOTYPE,provenance:参数来源}。不得把示例参数描述成实测陶瓷。
- ornament={kind:painted,recipe:规则配置}；paint 外观与几何 relief 分开，历史纹样/文化风格须明示未验证。
- files={相对包内路径:{sha256,bytes}}；manifest.json 自身不进入自身 hash。拒绝绝对路径、.. 逃逸与软链接逃逸。
- provenance={producer,version,backend,backend_version,seed,spec}。
- validation={report:相对 JSON 路径,status:PASS/FAIL/PENDING,scope:geometry_only}。几何 PASS 不代表材料标定或物理正确。
- 同 seed 的 canonical mesh/参数须可复现；STEP header 时间戳可造成逐字节差异，报告不能承诺全包逐位复现。asset_id 是内容身份，不是几何/物理验收结论。

## 证据与状态

- 2026-10-03：目标项目目录 ShardForge/vesselforge 已初始化为空 Git 仓库，无 remote、无提交。
- 新隔离环境位于 ShardForge/third_party/vesselforge-runtime/venv，未动 SynLab venv。ensurepip 首次因 Windows TEMP ACL 失败；将 TEMP/TMP 定向到授权的独立 runtime 临时目录后，bootstrap exit 0。尚未安装 CadQuery/OCP。
- 其余实现与验证状态以后续测试和资产包为准。本记录不会把 plan/候选 backend 当作已实现功能。

