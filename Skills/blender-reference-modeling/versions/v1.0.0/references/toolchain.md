# 工具选型：每个阶段用什么（Cycles）

阶段编号同 SKILL 流程表。本 skill 自带脚本的函数与原理对照见 `code-index.md`；这里只讲插件 / 外部工具的选型与坑。

结论来自 2026-11-19 在 Blender 4.5.12 LTS 上的实测，对象是 xiuxian-gateway 牌楼工程（68 个网格，408 片瓦实例，22 个材质）。测法：在工程副本上逐个调用，给已知扰动，看工具能不能抓到。

工具分三层，**按顺序找，有就用**：

1. **环境里已有的工具插件**（下表以 DSH 插件为例：HTTP `:9877/plan`，`{holder, op, args}`）。先列目录，例如 `op="catalog"`、`<family>_help`。
2. **Blender 内置 + 用户已装的插件**：用 `addon_utils.modules()` 列出来，开工前清点。
3. **本 skill 的 `scripts/`**：纯 bpy / 纯 Python，任何 agent、任何机器都能跑，用来补前两层的缺口。

插件的 op 不是越多越好。判断标准只有一条：**它判的对象和判据，是不是我们这一步要判的东西**。

## 阶段 → 工具

| 阶段 | 首选 | 备选 / 补充 | 不要用 |
|---|---|---|---|
| 0 清点 | 插件 `catalog`；`addon_utils` 列已装插件 | — | — |
| 1 识别：读图分类 | `img_digest`（剪影框、宽高比、对称度、曲率特征点、开口检测、网格叠图）[已验证] | `shape_draft` 填 S0 表：尺寸级 A–F、形类、特征 [已验证]；`img_crop` 放大 ROI；无插件：`scripts/ref_trace.py crop` | `img_digest` 的 Hough 斜线：瓦纹会造成大量噪声，不能当结构线 |
| 1 识别：量尺寸 | `img_probe`（扫线找边、亚像素）→ `img_measure`（像素 → mm，与期望值比）[已验证：正交渲染上误差 0.22%，约 0.6 px] | `img_calib`：用已知长度做最小二乘标定 px/mm；多视图时检查各视图尺度是否一致 | 目测估尺寸；把透视照片当正交量（先 `img_rectify`） |
| 1b / 4b 大形对比 | `img_diff`（同机位两张图；IoU + 最差列）[已验证：桥墩加宽 10% 时 IoU 降到 0.915，最差列落在墩边] | 无插件：`scripts/silhouette_iou.py`（同一组图得出同样的 0.9147）；`qc_render_views` 带 `ref_path` 直接给 IoU | `visualreport_report` 用于有开口的建筑（见下文，会假通过） |
| 3 拟合：取特征线 / 曲线 | 先认线（`math-form.md` 3.1 第 3 步）→ 剪影边用 `scripts/ref_trace.py trace`（密集亚像素取边）；两区域分界线用连续路径法（`skimage.graph.route_through_array` / OpenCV `IntelligentScissorsMB`）→ `sympose`（对称物体去拍摄位姿）→ `scripts/formkit.py` 的 `fit_multistart` + `huber` [实测：密集取点 + 换对象族，误差降到 1/10，见 `case-xiuxian.md`] | `img_probe` 逐条扫线取点（点少，适合核几个尺寸，不适合拟合曲线） | 手取十几个点拟合；自写逐列阈值扫描（斜边上会整列丢失） |
| 3 拟合：结构歧义 / 方案族 | `scripts/camkit.py`（沿视线对位、最低可见边残差）+ `scripts/preview.py`（软件 z-buffer，五方案 × 五视角约 20 s）+ `scripts/variants.py`（登记、表、拼版）[实测：修仙牌楼翼角五方案] | 选定后再进 Blender 建样件 | 各方案各写一份取线 / 残差代码（口径漂移） |
| 3 拟合：参数反推 | 手动：改 spec → 出图 → `img_diff` 循环 | `shapesolve_solve`（要求参考图由同相机参数生成） | `shape_search`：**有 bug**（`loopStart is not defined`），不能用 |
| 4 构造：构件 / GN | 手写 bpy / bmesh + GN（插件没有古建构件类 op） | `generator_save/run` 存参数化件 | `blockout_*`：白模，不是精品件；`vehicle_*`：车壳专用 |
| 5 材质 | `scripts/layered_material.py`（成因分层，11 个预设，纯 bpy）[已验证] | Noise Nodes 插件的 Crackle / Streaks / Scratches 可作风化原语（**依赖插件**，没装就断） | `material_build` 预设（见下文） |
| 7 交付：材质烘焙 | `material_bake`（烘贴图，需先有 UV：`uv_smart_project`） | — | — |
| 6 验收：实例 / 件间干涉 | `scripts/audit_instances.py`（展开 GN 实例两两求交，只放本不该相交的阵列件）[实测：224 件椽，63 对 → 0] | — | 指望逐对象审计发现实例穿插 |
| 6 验收：审计（求值后） | `scripts/eval_audit.py` 直接审 [已验证]；要插件的逐壳法线 / 三态时，用 `eval_audit.py --make-copies` 建求值副本，交给 `audit_mesh`，审完 `--clear-copies` | `gate_preflight`：开工面数估计 | `audit_mesh` / `audit_scene` 直接审原对象（见下文） |
| 6 验收：出图 | `scripts/shot_rig.py`：评估光 + 临时关合成，渲完恢复 [已验证] | `qc_render_views`：几何 QC 用，有 md5 与相机解算 | 用 `qc_render_views` 判断材质（Standard 视图变换 + 外加三点光） |
| 6 验收：冷启动构建 | 重开 Blender 完整构建一次；`scripts/cold_check.py` 先做静态检查 [已验证] | `generator_run`（全新无头进程，约 10 s 复现整座建筑）[已验证可跑] | 只做热重载 |
| 6 验收：门 | `gate_run` 写内联 spec，读 verdict 三态 | `asm_*`：多文件、多会话合并时用 | 只看 `ok` 字段 |
| 1b / 4b / 检查点：拼图给人看 | `montage` | — | — |
| 7 交付 | `deliver_export(scope="COL_X", normalize=False)` → `deliver_verify` [已验证：导出求值后几何、真实尺寸、Z-up、带 md5 清单] | 程序化材质先 `material_bake`：OBJ 的 MTL 只带视口色 | `deliver_export` 默认值（归一化到单位盒）；`objects=[集合名]`（选不到对象） |

## 实测发现的坑（插件侧）

| 工具 | 现象 | 怎么用 |
|---|---|---|
| `audit_mesh` | 只审**未求值**网格：`ZW_Col` 被审的是 68 面，实际求值后 1672 面；没有 `evaluated` 参数 | 先建求值副本（`ob.evaluated_get(dg).to_mesh()` → 新对象，名字加前缀 `QC_`），审完删掉；或用 `eval_audit.py` |
| `audit_scene` / `gate_run(audit_scene)` | 在 GN 实例化工程里**误判 fail**：瓦片、铺作等是 GN 点云载体，被报为 455 / 408 个孤立点；库源件（开口瓦片）被报为开边界 | 只审最终几何（求值副本），用 `objects=` 指定，排除载体和库源件 |
| `gate_run` 里的 `material_scan` | 不给对象就报错（没有活动对象） | 写 `args={scope:"ALL"}` 或 `objects:[…]` |
| `material_scan` | 对 Object 坐标的程序化材质误报 `needs_uv: true` | 只在需要烘焙时才信这一项 |
| `material_build` | 预设只有 7–8 个节点，单层噪波；混凝土预设**有 bug**，会出彩虹色 Voronoi；漆面是纯白；锈、木各只有一个噪波 | 不用于风化建筑；需要时用 `layered_material.py` |
| `visualreport_report` | 掩膜填满外包络，内凹和门洞看不见：有洞的建筑 IoU 也给 1.0 | 只当包络检查；有开口时用 `img_diff` |
| `qc_render_views` | 自动取景把 24 m 地面也算进去，主体变小；默认 Standard 视图变换，并在场景灯上叠加三点光 | 给 `views` 明确机位，或临时隐藏地面；只看形，不看材质 |
| `shape_search` | 运行时 JS 错误：`loopStart is not defined` | 暂不可用 |
| `gate_checkpoint` | 报 `K.dsh_txn_api 不存在`，需要先预热 txn | 先跑一次 `blender_rt_txn`（或 preload `"txn"`）；拓扑改动前也可以直接用 `/txn` 快照 |
| `generator_run` | 非 kit 代码：构建实际跑通（回执 68 网格 / 408 瓦 / 22 材质），但尾部报"需要共享内核 K.dsh_kit"，结论判 `refuted` | 代码按插件 kit 约定写才能拿到 pass；否则当"冷启动复现"用，只读回执，不读 verdict |
| `deliver_export` | 默认 `normalize=True`，会缩到单位盒（记录了 scale / center 可反推）；坐标保持 Z-up | 建筑交付设 `normalize=False` |
| `deliver_export` | `objects:["COL_ZW"]` 报"挑到 0 个 mesh"：`objects` 只认对象名，不认集合名，和速查骨架写的不一样 | 按集合导出用 `scope:"COL_ZW"` |
| `deliver_export` | MTL 的 Kd 取视口色（`material_source: viewport_diffuse`），程序化纹理全部丢失 | 要带外观就先 `material_bake` 烘贴图 |
| `deliver_verify` | 刚导出的文件自己验不过：多个对象共用一个材质时，`usemtl` 行数（7）和清单里的材质数（4）对不上，判 fail | 其余 15 项都过时，这一条按已知误报处理；记进交付记录 |
| `img_probe` / `img_measure` / `img_calib` | 参数名和速查骨架不一致：probe 是 `op` + `y_px` / `x_px`；measure 是 `targets:[{key, p1_px, p2_px, expect_mm, tol_pct}]`；calib 是 `views:[{name, path, known:[…]}]` | 先发一个错误参数，回执的 `allowed` 会列出真实参数名 |
| 图像类 op | 走 Blender 桥：Blender 没开时报 `ECONNREFUSED :9876` | 先开 Blender；或用 `silhouette_iou.py`（普通 Python） |
| `/act` 执行的代码卡住 | 主线程被阻塞后，桥对后续所有调用都超时（`addon timeout: execute_code`），Blender 界面仍显示"响应"、CPU 不动。实测原因是我们自己的代码：边遍历 `all_objects` 边建对象 | 先在无头进程里复现（`blender -b file --python …`），确认不卡再进 GUI；卡住时只能结束进程，草稿文件以外的会话别这样试 |

## 好用、契合流程的（插件侧）

- **`img_digest` + `shape_draft`**：正好对应"读图先分类"。前者出数字，后者逼你先回答"是什么 / 几块 / 哪凸哪凹"，不出 mm。
- **`img_diff`**：大形阶段的主判据。它能看见内凹和开口，`visualreport` 看不见。
- **求值副本 + `audit_mesh`**：逐壳法线、三态 verdict，比自写的审计信息多；前提是喂求值副本。
- **`gate_run` 内联 spec**：把一个项目的验收条件写成一份 spec，每阶段跑同一份。skipped 和 degraded 都会把顶层结论压成 degraded，这一点是对的。
- **`generator_run`**：用全新无头进程复现构建（约 10 s），可以替代"手动重开 Blender"做冷启动验证。注意它的 verdict 口径，见上表。
- **`material_bake`**：要交付 OBJ / glTF 贴图时用。

## 用户已装的 Blender 插件（本机，参考）

Noise Nodes v0.7（风化噪波组：Crackle / Streaks / Scratches / Dent / Fluid / Fractal / Cranal）、Node Wrangler、Ramp Generator、Hot Node、NodePreview、LightPainter（灯光，归用户）、Render Raw（合成调色，归用户）、Quad Remesher、Bool Tool、Edit Mesh Tools、Fill Mesh。

- 构建脚本**不依赖**任何第三方节点。Noise Nodes 只在"本机交互调材质"时用；要交付的 .blend，最终材质里不留它的节点组。
- 灯光、合成相关的插件归用户，构建不碰。

## 没有任何插件时

最低配也能走完整流程。阶段 0–1b（识别到检查点 A）不用开 Blender：
`ref_trace.py crop` 切证据图 → `ref_trace.py trace` 量剪影宽度 / 边线 → `gate.py ident` → 粗模写成多边形汤（numpy）→ `preview.py` 按各视图相机出平涂与掩膜 → `silhouette_iou.py` 对比 → `gate.py selfcheck`。


- 审计：`scripts/eval_audit.py`
- 出图：`scripts/shot_rig.py`
- 大形对比：`scripts/silhouette_iou.py`
- 静态检查：`scripts/cold_check.py`
- 材质：`scripts/layered_material.py`
- 取特征线、去位姿：`scripts/ref_trace.py`（普通 Python）
- 曲线、拟合、残差、扫掠、距离场：`scripts/formkit.py`（普通 Python，Blender 内也能 import）
- 参考相机、沿视线对位、最低可见边残差：`scripts/camkit.py`
- 多方案平涂预览、掩膜叠图：`scripts/preview.py`；方案登记、指标表、拼版：`scripts/variants.py`
- 中式翼角屋顶转角（刀锋族 / 真转角族，sag 连续）：`scripts/roofkit.py`（输出 preview 的多边形汤；项目给 body / dims / par）
- 多边形汤 → Blender 对象：`scripts/polys_bpy.py`（`save` 在系统 Python 写 .npz/.json，`build_from` 在 Blender 里成件；`stats` 报面数、三角占比、开口边位置）
- 冷启动构建：`blender --background --factory-startup --python build.py`

量尺寸时，渲染一张正交图（Film → Transparent，`ortho_scale` 已知，所以 px/mm 已知），再用 `silhouette_iou.py` 输出的外框换算。

## 现成库可以替代的自研部分（已装就换，没装不强求）

只在它能直接替掉我们要维护的代码时才用，不为它新建环境。

| 我们的 | 现成替代 | 说明 |
|---|---|---|
| `formkit.fit_multistart`（Nelder–Mead） | `scipy.optimize.least_squares` | 自带 Huber / soft_l1 损失、边界约束，参数多时更快更稳 |
| σ 的默认档（"数据还容得下的最顺"） | `scipy.interpolate.make_smoothing_spline`（不给 `lam` 时按广义交叉验证自动定） | 只用来估"数据允许多平滑"；真正的顺滑仍用 `fair_kappa`，因为它保持转角和末端切角 |
| 截图配准（缩放 × 平移网格搜索） | OpenCV `findTransformECC`、skimage `phase_cross_correlation` | — |
| 两区域分界线的连续路径 | skimage `route_through_array`、OpenCV `IntelligentScissorsMB` | — |

## 参考是真实透视照片时（本 skill 不接入，知道有这些）

参考接近正视、或是插画时，用自己的模型对相机就够（`math-form.md` 3.6），不需要下面这些。它们都在照片上训练或依赖照片里的平行线，对插画不可靠；还要另建环境、下载权重。只有面对真实透视照片、且对相机拿不准时才考虑，用之前联网核对版本和协议（以下为 2026-11 查到的情况）：

| 工具 | 做什么 | 协议 |
|---|---|---|
| fSpy（及 Blender 导入器；Blender 4.2+ 可用社区版 fSpy NG，或 extensions 上的 Simple Camera Match） | 按灭点手动做相机匹配 | GPL-3（当外部工具用） |
| GeoCalib（ETH，ECCV 2024） | 单张图估焦距、仰俯、侧倾，带不确定度 | 代码 Apache-2.0，权重 CC-BY-4.0 |
| MoGe-2（微软） | 单张图出深度、点云、法线、视场角；可帮助区分"前沿"和"往后退的面" | MIT；远处尺度有偏小的已知问题 |
| SAM 2（Meta） | 点选出区域掩膜，掩膜交界即分界线 | Apache-2.0 |


## 几何原语层

已移到 `code-index.md`（接口、原理、回归与通用度检验记录）。
