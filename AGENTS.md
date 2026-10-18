# 仓库说明

- 本仓库是 `X:\SkillMaker` 的 Skill 源码仓库。技能入口为 `Skills/<name>/README.md`，当前版本内容位于 `Skills/<name>/versions/<version>/`。
- 当前维护两份技能：`project-library`（用户原创）与 `delegate-to-deepseek-harness`（基于 LomoMao 上游的本机定制，MIT）。
- 版本目录一经发布不得覆写。更新技能时新建版本目录，并同步更新 `Skills/<name>/README.md` 的当前版本和版本说明。
- 版本目录内保持完整可运行内容；相对引用必须能从该版本目录解析，新增或移动文件时一并修正。
- 保留各技能的来源说明、版权与许可；修改时不得移除上游归属。
- 本机安装目录仍位于 `C:\Users\13179\.codex\skills\` 与 `C:\Users\13179\.cc-switch\skills\`；按需同步，不修改安装目录中的本机配置。
- 非用户明确要求，不新增管理软件、管理技能、同步工具、文件库、CI 或网站。
- 没有明确授权不提交、不推送、不发布。
- `Checks/`、`*.zip` 是本地记录和产物，保持忽略，不上传。
- `Skills/delegate-to-deepseek-harness/versions/v1.0.0/.github/` 是上游技能自带的仓库脚手架，不搬到根目录启用。
