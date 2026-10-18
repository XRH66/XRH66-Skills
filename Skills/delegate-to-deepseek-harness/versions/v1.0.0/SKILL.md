---
name: delegate-to-deepseek-harness
description: "本机默认实施工作流：GPT 负责需求、规划、架构、审查与独立验收；DeepSeek（大肥鱼）通过本机 dsh-cli 执行所有具体编码、脚本、配置和排查任务，包括小任务，默认完全访问并复用已有 Harness 会话。用于需要实际执行而非纯讨论的任务，也用于新聊天接管已有任务；普通问答、纯方案讨论或用户另行指定分工时不使用。"
---

# 本机 GPT × 大肥鱼协作

把执行交给大肥鱼，把责任留在 GPT。执行者的汇报只是声明，不是证据；GPT 必须检查真实文件、差异和与任务对应的验证结果。

## 分工

- GPT：理解需求、定义目标与架构、划定范围、写验收条件、审查结果、独立验收、对用户负责。
- 大肥鱼：在指定 cwd 内完成具体实现、修改、命令执行和自检，返回精简交付说明。
- 所有具体实现默认交给大肥鱼，包括小脚本、小修改和小任务；不要因为简单就悄悄收回实现。
- 架构/产品判断、集成决策和最终验收不外包；验收必须由 GPT 独立完成，不能只转述执行者的成功报告。

## 授权边界

- `cwd` 必须是用户真实项目的绝对路径且已存在；不要用工具默认工作区或临时目录替代。
- `start` 默认 `danger-full-access`。它只扩大执行权限，不扩大任务范围；提交、推送、发布、改标签、删除无关数据仍需用户明确授权。
- 使用已配置的 `deepseek-official / deepseek-flash / high`。CLI 不提供模型切换，不擅自修改模型或配置，也不要声称已切换到别的模型；界面或会话证据显示路由异常时先核实再报告。
- 认证只从 `C:\Users\13179\.codex\config.toml` 的 `[mcp_servers.dsh_harness]` 读取；CLI 不打印、不落盘凭据。MCP 保持 loopback，第三方插件按可信本地代码对待。
- 并行可变任务必须使用不同 worktree/cwd，绝不对同一 checkout 并发写入；并行只用于互不冲突的独立任务。

## 何时使用

任务自包含，且至少满足一项：实现机械、重复或上下文重；验收条件清楚；需要仓库探查；需要独立第二实现或诊断；多个独立任务可并行。

不用于：普通问答、纯方案讨论、用户明确要求 GPT 自己做，或任务缺少可执行范围与验收标准。

## 默认路径：本机 CLI

入口：`node <skill-dir>/scripts/dsh-cli.mjs`。它复用已运行的 `http://127.0.0.1:3080/mcp`，不启动第二个 DSH 进程，也不替代 Codex 里的 `dsh_harness` MCP 配置。本机 CLI 优先于上游的 MCP-first 和 headless 兜底说明。

```powershell
$node = "C:\Program Files\nodejs\node.exe"
$cli  = "<skill-dir>\scripts\dsh-cli.mjs"

& $node $cli start  --cwd X:\path\to\project --task-file X:\path\to\task.md
& $node $cli result --session <session_id> --request <request_id> --wait-ms 20000
& $node $cli status --session <session_id>
& $node $cli send   --session <session_id> --task-file X:\path\to\followup.md
```

- `start` 默认 `danger-full-access`；task 文件按 UTF-8 读取，允许 BOM，空文件拒绝；`cwd` 必须存在。
- `start`/`send` 只返回 `session_id`、`request_id`，代表 DSH 已接收，不代表完成。
- 等待用 `result --wait-ms 20000` 长轮询，单次至多 20000ms，返回即处理；不要用固定 sleep 假装等待。只在接管现场或需要独立状态时先查 `status`。
- 输出只有一行精简 JSON，不含原始事件、工具过程或思考链。`state=ended` 后再验收；`blocked_on_approval` 需要人在 Web UI 决定。
- CLI 是控制薄层，减少往返和上下文噪声；不等于减少模型推理 token，不要作此宣称。
- CLI 不支持取消、审批、子代理投递或原始事件；这些改用 [原生 MCP](references/native-mcp.md)。

依赖本机已安装的 `@modelcontextprotocol/client`（脚本通过 `createRequire('X:/Aiapp/dsh-mcp-control/package.json')` 解析，因此可从任意技能目录运行）、运行中的 3080 Web，以及上述 Codex 配置。单独拷贝本技能不等于安装完整 Harness。完整用法与输出契约见 [CLI 参考](references/cli.md)。

## 派发简报

给执行者一份自包含契约，不要把整个宿主对话倒进去：

```text
Objective: <一个可验收的结果>
Scope: <允许修改的路径；明确不做什么>
Constraints: <兼容性、API、依赖、风格、用户约束>
Acceptance criteria: <可观察条件>
Verification: <要运行的检查/命令>
Rules:
- 只在给定 cwd 内工作；先读后改；保留无关修改。
- 不提交、不推送、不发布、不删除无关内容。
- 环境失败或受阻直接报告，不自行改环境、不派生子代理。
- 最终只回复：交付路径、关键结果、验证命令与结果、阻塞。
```

任务文件用 UTF-8；只给目标、范围、必要上下文和验收条件。默认读取精简 JSON 状态和最终结果，不重复拉取完整日志或对话。

## 等待与验收

1. `start` 或复用会话 `send`，记下 `request_id`。
2. 直接 `result --wait-ms 20000` 长轮询；`running` 时再查一次，不做固定睡眠。
3. `ended` 后检查 `reason`、`diagnostics` 和实际交付物；失败或阻塞必须明确报告，不得静默。
4. 验收按风险比例：小任务只查交付必要内容和少量要求内用例，一次针对性验收通过即停止；普通功能看关键差异；认证、支付、迁移、并发、安全、公共 API 才读完整 diff。
5. 合同通过即停：不顺手重构、不扩大范围、不重复跑无关全量测试。
6. 返工用同一 `session_id` 的 `send`，再按新 `request_id` 验收；同一失败模式两次后重新定位并报告阻塞，不得悄悄改成 GPT 自行实现。确需 GPT 接管时，明确说明原因和已完成的验证。

不要用上游旧测试门槛覆盖用户要求的精简验收；`scripts/verify_workspace.sh` 只是可选机器核验工具，不是默认门槛。

## 接管已有会话

从任务记录、项目状态或机器索引读取准确 `session_id`、`cwd` 和最近 `request_id`；先 `status`，确认身份且会话空闲后再 `send`。复用准确闲置会话，不凭标题猜 ID，不创建替代会话冒充接管，也不反复查状态。

复用已有记录和已验证事实，只读当前任务相关段落；不默认整篇读取状态、历史或交接正文，不重复全量读取。完成结果和下一步写回已有记录，使新对话能继续同一会话；简单任务不生成多套报告。

## 参考与遗留路径

- [CLI 参考](references/cli.md)：默认入口、输出契约和推荐循环。
- [原生 MCP](references/native-mcp.md)：取消、审批、子代理、原始事件，以及会话接管细节。
- [委派边界](references/delegation-policy.md)：路由和并行 worktree 规则。
- [上游 setup](references/setup.md)：仅在上游安装方式或连通性排障时按需阅读；其中的 8090 MCP 桥和 headless 兜底不是本机默认。
- `scripts/dsh_headless.sh`：历史兜底，仅在 CLI 与 3080 都不可用且用户同意时考虑，不得覆盖 CLI 优先。
- `scripts/verify_workspace.sh`：上游 0.2.0 的可选机器验收器，仅在契约明确要求机器回执时使用。

## 最终回复

只讲任务结果，不讲管道细节；区分“执行者声称”与“GPT 已独立验证”，列出未验证项或客观限制。
