# 本机官方 Harness 原生 MCP

来源：复用 mochgolf/dsh-mcp-control；本文件仅适配工具名称和用户已确认的使用偏好。MCP 名为 `dsh_harness`，地址 `http://127.0.0.1:3080/mcp`。复用运行中的官方 Harness，不启动第二个服务。

仅按需使用：常规派工优先走 `references/cli.md` 的 `dsh-cli`；需要取消、审批、子代理投递或原始事件时再用本文件的原生工具。

## 新任务

由 GPT 明确目标、架构、允许修改路径、必要上下文及验收条件，再调用 `session_start`：

- `cwd` 为用户实际项目根目录，已有 Harness 工作区会自动归组。
- 默认显式传 `permission_preset="danger-full-access"`；用户本次另有要求时遵从本次要求。完全访问不扩大任务范围，也不授权提交、推送、发布或删除无关内容。
- 使用部署已确认的 `deepseek-official/deepseek-flash/high`；官方当前映射至 1017。此插件不提供模型切换工具；若界面或真实会话证据显示路由变化，先核实，不假称已经选到正确模型。
- 任务简报必须自包含，限定交付与检查；环境失败直接汇报，避免执行者自行改环境或派生子代理。
- 为新任务生成 `request_id`，保留接受回执中的 `session_id`、`request_id`、`cwd`、权限。一次失败不自动重发未知结果的请求。

回执后立即把身份记录到现有项目状态或对应任务的机器记录。若项目无现成记录入口，用 `.agents/deepseek-tasks.json` 维护小型索引（目标、cwd、session_id、request_id、状态、证据路径）。不把密钥、对话全文或内部推理放入索引。

## 等待、验收及返工

用 `turn_result(address={kind:"session",session_id},request_id,wait_ms=20000)` 等待。`accepted` 只代表接收；直到 `state="ended"` 再检查 reason、final_message 和 diagnostics。运行中继续合理等待；需要细节时用 `session_status` 或从已持有游标开始的 `events_read`。不重复读取完整日志。

GPT 检查实际交付文件/差异，并进行与结果对应的独立验证。有问题用 `session_send(session_id,message,request_id)` 在同一会话返工，再按新 request_id 等待和验收。必要时 `session_cancel` 仅取消已确认属于本任务的工作。

## 新 Codex 对话接管

先从用户指定的任务、项目状态或上述机器索引读取准确 session_id、cwd 和最近 request_id。调用 `session_status`，需要旧结果时调用 `turn_result`；确认身份和状态后，用 `session_send` 在同一个会话继续。插件没有会话搜索工具，不能凭标题猜 ID。会话身份不明或有并行工作时先澄清或只读核对，不能随便创建替代会话并声称已接管。

对用户区分模型执行结束与 GPT 验收通过。完成后记录实际结果和下一步，使新对话能继续使用同一原生会话。
