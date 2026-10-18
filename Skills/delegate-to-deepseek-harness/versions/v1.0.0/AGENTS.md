# 本技能仓库说明

本版本目录 `X:\SkillMaker\Skills\delegate-to-deepseek-harness\versions\v1.0.0` 是 v1.0.0 的完整内容；技能入口和当前版本指针在 `X:\SkillMaker\Skills\delegate-to-deepseek-harness\README.md`。两个安装目录 `C:\Users\13179\.codex\skills\delegate-to-deepseek-harness` 与 `C:\Users\13179\.cc-switch\skills\delegate-to-deepseek-harness` 是同步副本；修改后按文件合并同步，不做删除式镜像。

- `SKILL.md` 是产品。优先改指令，不要增加框架代码。
- 不削弱 GPT 独立审查和验收委派结果的规则。
- 不静默扩大授权到提交、推送、部署、凭据或破坏性操作。
- 保持 README 和运行示例与 `references/cli.md` 一致；`references/setup.md` 是上游历史说明，不是本机默认。
- `install_skill.sh` 采用覆盖式合并，不删除目标目录中的额外文件；保留破坏性目标路径守卫，`validate_skill.py` 检查该守卫。
- 保留 MIT 许可、上游来源和本地定制来源；不以时间戳盲选版本。
- 修改后运行 `./scripts/validate.sh`。
