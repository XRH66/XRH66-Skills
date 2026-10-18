# delegate-to-deepseek-harness

用于把边界清晰、可独立验收的实现工作委派给 DeepSeek Harness，由 GPT 负责规划、架构、审查和独立验收；本机默认通过精简 CLI 执行。

- 来源：基于 [LomoMao/delegate-to-deepseek-harness](https://github.com/LomoMao/delegate-to-deepseek-harness) 的本机定制；MIT 许可，见版本目录内 `LICENSE`。
- 当前本地版本：`v1.0.0`
- 版本说明：
  - `v1.0.0`（2026-10-18）：初始本地归档。以中文 `SKILL.md`、内置 `scripts/dsh-cli.mjs`、CLI/原生 MCP 参考为主，保留上游安全边界、并行写隔离、安装与校验脚本及 MIT 许可；与上游 `0.2.0` 版本号独立。

入口：[versions/v1.0.0/SKILL.md](versions/v1.0.0/SKILL.md)
