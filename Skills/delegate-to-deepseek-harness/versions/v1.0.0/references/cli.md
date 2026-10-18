# 低 token CLI（dsh-cli）

`dsh-cli` 是已运行 DSH Web 实例的薄命令入口，适合 GPT 用少量输出驱动原生会话。它复用现有 `http://127.0.0.1:3080/mcp`，**不启动第二个 DSH 进程**，也不替代 Codex 里的 `dsh_harness` MCP 配置。

## 入口

- 脚本：`<skill-dir>/scripts/dsh-cli.mjs`（本技能内副本；源实现位于 `X:\Aiapp\dsh-mcp-control\cli\dsh-cli.mjs`）
- Node：`C:\Program Files\nodejs\node.exe`（也可用 PATH 中的 `node`）
- 无需安装依赖或添加全局命令。副本通过 `createRequire('X:/Aiapp/dsh-mcp-control/package.json')` 解析本机已安装的 `@modelcontextprotocol/client`，因此可从任意技能目录运行。
- 内置副本与外部源的行为一致；唯一差异是依赖解析方式（外部源直接 import）。不要为此重构 CLI。
- 认证只从 `C:\Users\13179\.codex\config.toml` 的 `[mcp_servers.dsh_harness]` 段读取 `http_headers` 里的 `Authorization`。CLI 不打印、不落盘 token。
- 前置条件：DSH Web 正在 `127.0.0.1:3080` 运行且 `/mcp` 路由可用；该段配置存在并提供 Bearer 凭据。

## 用法

PowerShell：

```powershell
$node = "C:\Program Files\nodejs\node.exe"
$cli  = "<skill-dir>\scripts\dsh-cli.mjs"

& $node $cli start --cwd X:\path\to\project --task-file X:\path\to\task.md
& $node $cli status --session <session_id>
& $node $cli result --session <session_id> --request <request_id> --wait-ms 20000
& $node $cli send --session <session_id> --task-file X:\path\to\followup.md
```

- `start` 默认权限 `danger-full-access`；需要别的原生预设时加 `--permission <preset>`。该权限不扩大用户授权的任务范围。
- `send` 默认 `queue`；加 `--steer` 改为插话。
- `--wait-ms` 默认 `20000`，单次至多 `20000`；`0` 表示立即返回。返回即处理，不要用固定 sleep 假装等待。
- task 文件按 UTF-8 读取，允许 BOM，空文件会被拒绝；`cwd` 必须是已存在的绝对目录（真实项目路径）。

## 输出约定

成功时 stdout **只有一行**紧凑 JSON：

```json
{"session_id":"session-...","request_id":"..."}
```

```json
{"session_id":"session-...","agent_status":"idle","head_seq":71,"turn":{"turn":3,"open":false,"reason":{"kind":"completed"}},"queue_count":0,"pending_approvals_count":0}
```

```json
{"state":"ended","reason":{"kind":"completed"},"final_message":"...","diagnostics":[]}
```

- `start`、`send` 返回 `session_id`、`request_id`，只代表 DSH 已接收，不代表完成。
- `status` 只给 Agent 状态、最新 turn、排队数和待审批数，不返回队列预览或事件。
- `result` 只给 `state`、`reason`、`final_message`、`diagnostics`（必要时附 `final_message_truncated`、`diagnostics_omitted`）；不输出原始事件、工具过程或思考链。
- `state` 取值：`ended`、`running`、`queued`、`blocked_on_approval`、`discarded`、`not_found`。`not_found` 是有效查询结果，退出码仍为 0。
- 失败时 stdout 为空，stderr 输出一行 `{"error":{"code":"...","message":"..."}}`；退出码：用法错误 `2`，其余 `1`。
- 精简输出是控制薄层的效果，不等于减少模型推理 token，不要作此宣称。

## 推荐循环

默认快速路径：只读当前任务必要资料，复用本会话已确认事实；简报限定执行者最终只返回交付路径、关键结果、阻塞。一次派工后直接 `result` 长轮询，完成即验收，不重复 `status`、不读完整聊天。简单任务由 GPT 检查交付必要内容并独立运行少量要求内用例；通过立即收尾。仅失败、证据矛盾或高风险时补读相关日志片段或扩大检查。可接续身份和结果合并保存到已有记录，不额外制造多套报告；不为验证规则或文档小改动另开聊天跑整条流程。

1. `start` 或复用现有 `session_id` 的 `send`，记下 `request_id`。
2. 用 `result --wait-ms 20000` 长轮询；不必每次先查询 `status`，需要独立状态或接管现场时再查。
3. `result --wait-ms 20000` 等到 `ended` 或 `blocked_on_approval`；`running` 时再查一次。
4. 验收由 GPT 检查真实文件和差异；返工用同一 `session_id` 的 `send`，再按新 `request_id` 查询。

`blocked_on_approval` 需要人在 Web UI 决定，CLI 不能审批或取消。需要取消、子代理或原始事件时，继续走原生 MCP 工具，不要用本 CLI。

## 限制

- 端点固定为 `http://127.0.0.1:3080/mcp`，配置路径固定为当前用户的 `C:\Users\13179\.codex\config.toml`。
- 只操作根会话；不支持取消、审批、子代理投递或原始事件读取，这些仍用原生 MCP 工具。
- `start`、`send` 只代表接收；不会自动轮询，也不会在回执丢失后复用旧 `request_id` 重试。超时后先 `status` 核对，不要盲目重发。
- `result` 的 `final_message` 可能仍较长；任务简报要求执行者简短汇报，完成后不重复读取。
- 单独拷贝本技能不会安装 SDK、启动 3080 服务或写入认证；这三项必须已由本机 Harness/Codex 配置提供。

## 既有验证记录（2026-10-18）

- 对运行中的 3080 实例做过只读验收：`status` 与 `result` 均成功返回单行 JSON；未知会话返回 `session/not-found` 且非零退出；缺失 task 文件与非法 `--wait-ms` 在联网前被拒绝；输出中未出现凭据。
- GPT 独立补验：`start` 创建 `session-bdd5bf89-a273-8380-8f84-0ce4f88c6837`，返回 `CLI_OK_42`；同会话 `send` 返回 `CLI_RESUME_OK`；两轮均为 `ended/completed`、diagnostics 为空；`status` 为 idle、turn=2、空队列和审批。回执位于 `X:/ReadAppRebuilt/evidence/mcp-control-20261018/cli-start.json` 与 `cli-send.json`。
- 本次合并另用管理目录 CLI 对当前只读会话做 `status` / `result`，结果见 `X:\SkillMaker\Checks\DelegateSkillMerge.json`。
