# 代码索引：脚本、关键函数、原理、自测

skill 只放**领域无关**的代码；具体物体的几何由执行模型按原理现写在项目里（SKILL "这份 skill 管什么"）。
用前先跑自测。纯 Python 的模块不依赖 Blender，可在系统 Python 里跑；标 bpy 的要在 Blender 里跑。
一键测几何原语层：`python scripts/primitives_selftest.py`。

## 方法层（识别、拟合、对比、审计、闸门）

| 脚本 | 做什么 | 关键函数 / 用法 | 原理 | 自测 | 状态 |
|---|---|---|---|---|---|
| `gate.py` | 流程闸门：每步交付物是否齐、有无依据 | `init` 写模板；`ident / selfcheck / measure / accept / all` | SKILL 流程表 | `--selftest` | [实测] |
| `ref_trace.py` | 从参考取密集特征线、去拍摄位姿、透视矫正、截图配准 | `trace`、`crop`（切局部放大证据图，原图坐标在上方标签条，`--raw` 原样切拼图子视图给掩膜 / IoU 用）、`sympose`（`sym_pose` / `unpose`）、`rectify`、`register`、`red_marks` | `math-form.md` 3.1 | `selftest` | [实测] |
| `formkit.py` | 曲线、拟合、残差、稳健损失、顺滑、扫掠、距离场、随机 | `kappa_curve`、`wing_curve`、`offset_curve`、`tapered_stroke`、`fillet_seg`、`fair_kappa`、`fit_multistart`、`huber`、`signed_dist`、`discrete_curvature`、`smoothmax`、`rmf_frames`、`sweep / loft`、`polygon_sdf / relief_height`、`rng / noise1 / fbm1`、`poisson_disk` | `math-form.md` | `--selftest` | 曲线 [已验证]，其余 [自检] |
| `multiview.py` | 多视图联合拟合：每视图一台相机、共享族参数；逐参数 1σ 不确定度（"这组视图定得了它吗"） | `View(fwd0, up0, target, f).cam(x)`（相对基准姿态的小扰动，无万向锁）、`OrthoView`（正交视图）、`lm`、`joint_fit` → `theta / std / per_view` | `fitting.md` §2b、§4 | `selftest` | [自检] |
| `profilefit.py` | 支承体从剪影宽度拟合：轴 + a(v)、b(v)（两端值 + 一个鼓包）+ 超椭圆截面；单视图用扁率先验，双视图两向分别拟合 | `bump`、`Body`（`ring / surface / polys`）、`widths`、`fit`（`linear=True` = 直管对照） | `fitting.md` §5 | `selftest`（约 30 s） | [自检] |
| `camkit.py` | 针孔相机、沿视线对位、最低可见边残差 | `Pinhole`（project / slide）、`look_at`、`front_cam / fit_front_cam`、`envelope`、`line_residual`、`residual_pair` | `fitting.md` §1，`math-form.md` 3.6–3.7 | `selftest` | [实测] |
| `silhouette_iou.py` | 同机位剪影 IoU、多出面积、最差列 / 行、叠图 | CLI：`A.png B.png --align none --out` | `fitting.md` §4 | 合成图 | [已验证] |
| `preview.py` | 不开 Blender 的 z-buffer 平涂预览（多方案 × 多视角） | `zrender`、`ortho / persp / from_camkit`、`mask / outline` | `math-form.md` 3.7 | `selftest` | [实测] |
| `variants.py` | 方案族登记、统一指标表、对比拼版 | `registry`、`metrics_table`、`sheet` | `math-form.md` 3.7 | `selftest` | [实测] |
| `polys_bpy.py` | 多边形汤 ↔ Blender：按组成件、焊点、活 Bevel、原点在接口 | `save`（系统 Python）、`build_from`（bpy）、`stats` | `geometry-math.md` §3 | — | [已验证] |
| `eval_audit.py` (bpy) | 求值后审计：非流形、退化、自交、法线 | `-- COL_X --out a.json`；`--make-copies / --clear-copies` | `geometry-math.md` §9 | — | [已验证] |
| `audit_instances.py` (bpy) | 实例间 / 对象间干涉 | `-- 载体…`；`-- --objects 对象或集合…` | `geometry-math.md` §9 | — | [实测] |
| `cold_check.py` | 冷启动前静态检查 | CLI | SKILL §6 | — | [已验证] |
| `shot_rig.py` (bpy) | 同机位出图（临时日光、临时关合成，渲完恢复） | `render_shots` | SKILL §6 | — | [已验证] |
| `layered_material.py` (bpy) | 成因分层材质，11 个预设 | `build`、`swatch`、预设函数 | `materials.md` | `swatch` | [已验证] |

## 几何原语层（领域无关，纯 numpy，各带合成 selftest）

| 脚本 | 做什么 | 关键函数 | 原理 | 状态 |
|---|---|---|---|---|
| `support.py` | 支承查询：高度场 / 多边形汤射线；参数曲面支承 | `Support.from_func / from_polys / union`（`z`、`normal`、`room`、`drape`）；`Surface(f(u, v))`（`point / normal / frame / line_u / line_v / offset / grid_polys / shell_polys`） | `geometry-math.md` §1 | [实测] |
| `facets.py` | 绕支承的折面硬表面板；层间净距 | `clear_scale`、`facet_ring`、`split`、`loft_scale`、`min_gap`、`dirs_around`、`solve_up`、`rho`、`ray_hit` | `geometry-math.md` §2、§3、§6 | [实测] |
| `sweep.py` | 曲线网络 + 沿网络放样（2.5D / 3D 标架，斜接，闭合） | `Network`、`stations / stations3`、`join`、`decimate`、`limit_rate`、`slope`、`sweep`、`loft_polys` | `geometry-math.md` §4、§8 | [实测] |
| `arrange.py` | 面上 / 线上排布：起点、推进、停止、收口、成组随机 | `starts_along`、`march`（步长可为函数）、`fit`、`group_noise`、`gap_scale`、`ray_polyline` | `levels.md` §4 | [实测] |
| `instancing.py` | 实例记录、抖动、对称群、叠层下放、通用 GN 实例器 | `record`、`jitter`、`mirror`、`rotate_n`、`translate`、`stack_drop`、`instancer_bpy` | `geometry-math.md` §6 | [实测] |
| `parts.py` | 面上安装件与小件：安装面标架、落座、开窗块、回转件、铆钉；软件与小五金：皮带、带扣、带环、闭合截面环 | `frame`、`face_frame`、`seat_offset`、`surface_seat`、`block`、`lathe`、`rivet`、`tube_loop`、`rounded_rect`、`torus`、`angle_plate`、`tapered_bar`、`buckle`、`keeper`、`strap` | `geometry-math.md` §7、§7b、§8 | 铰座 / 销 / 铆钉 [实测，抽自护臂]；皮带 / 带扣 / 带环 [自检] |
| `bodies.py` | 剪影体（两视剪影 → 超椭圆截面放样）与浮雕板（轮廓台地 → 高度场闭合实体） | `superellipse`、`silhouette_body`、`width_from_mask`、`relief_slab` | `levels.md` §3、§5 | [自检] |
| `primitives_selftest.py` | 一键全测 + 串起来的合成场景（`--quick` 跳过 profilefit） | — | — | — |

回归：用 support / sweep / arrange / instancing 重写修仙牌楼 stage2 导出，产出与原版逐字节相同（md5 6b5f2e8c…）；用它们做非建筑的鳞甲护臂，0 自交、133 片实例 0 对（`case-bracer.md`）。

### 原语的跨领域用例

| 原语 | 接口要点 | 屋面里的用例 | 别处的用例 |
|---|---|---|---|
| 支承查询 | 高程 / 法向 / 边界 / 剩余距离；来源可以是函数，也可以是多边形汤（numpy 射线，不依赖 Blender） | 屋面壳射线取瓦的高程（替掉公式外推后，檐口瓦接上了瓦当） | 车身、船壳、桌面、甲面 |
| 曲线网络 | 节点 + 边，每边带顶线和两侧外向；节点处斜接 / 圆滑，斜接附近剔站 | 正脊 → 戗脊分叉 | 管路、栏杆、家具框架、护手 |
| 沿网络放样 | 截面 = f(站点, 支承, 剩余距离)；站距下限、宽度限坡、端头收口；同拓扑环 | 当沟、盖脊、连檐板 | 线脚、门框、包边、焊缝、密封条 |
| 面上排布 | 起点沿边界等弧长 → 方向场推进 → 停止场（离网络的距离）；成组随机；按对称群镜像 | 瓦垄 | 鳞片、木板、砖、铆钉、甲片、键帽 |
| 实例与对称群 | 记录 (位置, 标架 = 轴 + 法向提示, 缩放, 变体)；抖动规格；对称群展开；Blender 侧通用点云 + GN | 椽、瓦、瓦当、滴水四角展开 | 车轮、椅腿、灯具阵列 |
| 叠层净距 | 弯曲支承上多层直杆：弦拱高差 + 横滚下棱 + 抖动 / 微弯余量 → 下层让位量 | 飞椽压檐椽 | 甲板压龙骨、面板压框架、层叠甲片 |
| 浮雕 | 平面轮廓（参数曲线 × 对称群）× 高度剖面（台地 / 距离场拱起）；同拓扑环 | 瓦当 | 团花、回纹、徽标、铭牌 |
| 折面板 | 折线截面绕支承；数值外扩系数；同 f / 相似截面保共面；射线净距二分求倾角 | — | 科幻护臂叠板、护片、腕甲；家具框板、机壳面板 |
| 剪影体 | 多视剪影切片 → 超椭圆截面放样；单视深度出方案族；主轴可为曲线（`bodies.silhouette_body`） | 套兽 / 脊饰（待做） | 吻兽、器物把手、载具外壳粗形 |
| 面上安装件 | 专设平折面 → 四角标架 → 占地内实测最高点落座；柔性面用面帧（`parts.face_frame / seat_offset / surface_seat`） | — | 铰座、凸台、铭牌、开关、带扣、门把手座、合页 |
| 支承体拟合 | 轴 + 两向尺寸曲线（两端 + 鼓包）从剪影宽度拟合（`profilefit.fit`）；直线规整的刚性件不用它 | 柱身收分 | 手臂、腿（肢体）、瓶腹、机身 |
| 小五金 / 型材 | 圆环、折角片、收分方杆（`parts.torus / angle_plate / tapered_bar`） | — | 吊环拉手、包角、角码、家具腿、桁杆 |

## 领域包

| 脚本 | 做什么 | 状态 |
|---|---|---|
| `roofkit.py` | 中式翼角屋顶转角：刀锋族 / 真转角族（sag 连续），输出多边形汤与残差线 | [实测] |

## 项目里的参考写法（不在 skill 里，按原理现写时可参照）

下表路径都是作者本机的项目目录（`default-workspace/…`），不随 skill 发布；没有这些文件时只看原理文档和原语即可。

| 位置 | 演示什么 |
|---|---|
| `default-workspace/case-gauntlet/gen2.py` | 叠层链（从腕往肘逐件求倾角）、折面板放样、安装折面 + 落座 + 开窗铰座 + 回转销、肋纹壳（逐站厚度）、相似截面外翻 |
| `default-workspace/case-gauntlet/fit/fit_cam_sil.py` | 特征点 + 视角先验多起点 → 剪影微调的相机拟合 |
| `default-workspace/case-gauntlet/render_fit.py`、`fit/compare_v2.py`、`render_parts.py` | 拟合相机进 Blender、三联对比图 + IoU、按构件类上色的分件图 |
| `default-workspace/case-bracer/` | 只用原语层做鳞片排布、包边、系带 |
| `default-workspace/xiuxian-gateway/`（牌楼） | 曲线拟合、方案族、屋面原语回归 |

## 还没抽的原语（下一个案例用到时再抽，带合成 selftest）

2026-11-21 已抽：面上安装件、回转件与开窗块、软件与小五金（`parts.py`），支承体拟合（`profilefit.py`），多视图联合相机（`multiview.py`），剪影体与浮雕板（`bodies.py`）。都只过了合成自测，下一个真实项目里用到时要记读数、改状态。

- 剪影体的曲线主轴（现在只支持直轴）。
- 支承体截面扭转 φ(v)、轴线弯曲（`fitting.md` §5 表示里有，`profilefit` 还没实现）。
- 浮雕的锐利轮廓版本（台地放样而不是高度场，避免锯齿）。
- 剪影项进多视图联合拟合（现在 `multiview` 只用特征点；剪影微调参考 `case-gauntlet/fit/fit_cam_sil.py`）。
