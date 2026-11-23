# delegate-to-deepseek-harness

用于把边界清晰、可独立验收的实现工作委派给 DeepSeek Harness，由 GPT 负责规划、架构、审查和独立验收；本机默认通过精简 CLI 执行。

- 来源：基于 [LomoMao/delegate-to-deepseek-harness](https://github.com/LomoMao/delegate-to-deepseek-harness) 的本机定制；MIT 许可，见版本目录内 `LICENSE`。
- 当前本地版本：`v1.0.2`
- 版本说明：
  - `v1.0.2`（2026-11-03）：明确研究与工程实施的分工、探索性验证及实验委派边界，并强调简单任务的方案与复杂度相称和当前任务的用户指定优先。
  - `v1.0.1`（2026-10-18）：同步默认模型偏好。默认优先 `opencode-go / deepseek-v4.1-flash / high`（与 Harness `agent-default-model` 一致）；仅在额度用尽、订阅失效或 Go 不可用且有可核对证据时，说明原因并请用户确认切到 `deepseek-official / deepseek-flash / high`，不静默切换、不动用官方余额；网络/地区/认证故障不等于额度用尽；接管旧会话先核对已知模型证据。同步修改 `SKILL.md`、`references/native-mcp.md`、`references/cli.md` 及版本路径引用。内容由 `v1.0.0` 复制而来，`v1.0.0` 未改动。
  - `v1.0.0`（2026-10-18）：初始本地归档。以中文 `SKILL.md`、内置 `scripts/dsh-cli.mjs`、CLI/原生 MCP 参考为主，保留上游安全边界、并行写隔离、安装与校验脚本及 MIT 许可；与上游 `0.2.0` 版本号独立。

入口：[versions/v1.0.2/SKILL.md](versions/v1.0.2/SKILL.md)
