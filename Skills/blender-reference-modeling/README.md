# blender-reference-modeling

照参考图在 Blender 里做程序化硬表面建模的通用方法论，对象是有规律可循的人工构件（建筑与古建构件、家具、器物、护甲、载具外壳、机械件、规则纹饰）。skill 规定分阶段该做什么、用什么判、何时回退，附数学原理、代码索引和领域无关的几何原语；具体物体的几何代码由执行模型按原理现写。

- 来源：用户原创，无上游仓库。
- 许可：MIT，版权 (c) 2026 XRH66；见版本目录内 `LICENSE`。
- 当前本地版本：`v1.0.1`
- 版本说明：
  - `v1.0.1`（2026-11-22）：体检后的小修，流程不变。
    - SKILL 简介的定级口径改为 L0–L4 / skip（与正文一致），补上多视图联合、领域无关几何原语、执行通道。
    - §4 面上安装件指向 `parts.face_frame` / `surface_seat` / `block`；§8 原语层列出 `parts` `profilefit` `multiview` `bodies`。
    - `gate.py` 删去 3 个未用变量，行为不变。
  - `v1.0.0`（2026-11-22）：初始归档。
    - **流程**：识别（构件树 + 八问 + 视图清点）→ 检查点 A → 定级 → 拟合 → 构造 → 逐件对照与同机位对比（检查点 B）→ 成因分层材质（检查点 C）→ 验收、交付、沉淀，另附回退信号表。
    - **闸门**：`scripts/gate.py` 做结构化校验。
    - **执行通道**：`references/toolchain.md` 写了无头副本 / 主 GUI Blender 两种模式，以及"租约 → 执行 → 快照 → 释放"的流程（端口、接口以 DSH 插件为例）。
    - **与 agent 无关**：不绑定特定模型或 agent；冷读可由子代理、新会话或另一个人完成，不能联网时请用户提供资料。
    - **原理文档**：fitting、geometry-math、math-form、levels。
    - **代码**：code-index 列出全部脚本。
    - **案例记录**：古建牌楼、鳞甲护臂、科幻叠板护臂。
    - **验证程度**：
      - 方法层和曲线 / 屋面原语在牌楼与护臂项目上实测过。
      - `parts`、`profilefit`、`multiview`、`bodies` 四个新原语，以及多视图规则、软件与小五金，只通过了合成自测和两轮冷读审查，还没在真实项目里用过。
    - **本机项目路径**：文档里 `default-workspace/…` 开头的路径是作者本机的项目目录，不随本仓库发布。

入口：[versions/v1.0.1/SKILL.md](versions/v1.0.1/SKILL.md)

自测：`python versions/v1.0.1/scripts/primitives_selftest.py`（原语层全套，约 35 s；`--quick` 跳过 profilefit）、`python versions/v1.0.1/scripts/gate.py --selftest`。依赖 numpy、Pillow；标 bpy 的脚本要在 Blender 里跑。
