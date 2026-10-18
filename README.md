# XRH66's Skill Repository

我个人制作的 Skill 仓库，用于优化我个人的工作流。

## Skills

### project-library

用于规划、建立和维护以索引为入口的项目文件库，按六类核心职责组织项目定义、规则、状态与历史，支持 agent 接续。用户原创。

当前版本：`v1.0.0`
路径：[Skills/project-library/versions/v1.0.0/](Skills/project-library/versions/v1.0.0/)

### delegate-to-deepseek-harness

用于把边界清晰的实现工作委派给 DeepSeek Harness，由 GPT 负责规划、审查和独立验收。基于 [LomoMao/delegate-to-deepseek-harness](https://github.com/LomoMao/delegate-to-deepseek-harness) 的本机定制，保留 MIT 许可。

当前版本：`v1.0.0`
路径：[Skills/delegate-to-deepseek-harness/versions/v1.0.0/](Skills/delegate-to-deepseek-harness/versions/v1.0.0/)

## 结构

```text
Skills/<name>/
  README.md              # 用途、来源、当前版本与版本说明
  versions/<version>/    # 该版本的完整技能内容
```

每个技能的当前版本由 `Skills/<name>/README.md` 指向。历史版本目录发布后不再覆写；更新时新增版本目录并更新入口说明。

## 维护

- 本仓库只保存 Skill 源码和必要文档，不作为安装目录。
- `Checks/`、`*.zip` 属于本地记录和打包产物，不纳入版本控制。
- 各版本目录内的来源说明、版权与许可文件随版本保留。
