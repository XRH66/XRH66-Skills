# delegate-to-deepseek-harness

[简体中文](README.zh-CN.md)

> **Local authoritative copy (v1.0.0):** `X:\SkillMaker\Skills\delegate-to-deepseek-harness\versions\v1.0.0`, synced to `C:\Users\13179\.codex\skills\delegate-to-deepseek-harness` and `C:\Users\13179\.cc-switch\skills\delegate-to-deepseek-harness`. The local default is GPT planning/review/independent verification plus the bundled `scripts/dsh-cli.mjs` against the already-running 3080 Harness. The upstream MCP-first, 8090 bridge, and headless fallback below are historical/on-demand paths, not the local default. MIT license retained; upstream: https://github.com/LomoMao/delegate-to-deepseek-harness.

> Codex keeps the judgment. DeepSeek Harness does the bounded work.

```text
Codex              = orchestrator + reviewer
DeepSeek Harness   = worker
```

```text
User → Codex ── bounded work ──→ DeepSeek Harness worker
                                          │
                              changes + tests
                                          ↓
                                  Codex reviews ✓
```

`delegate-to-deepseek-harness` is a small Agent Skill for handing well-scoped coding work from Codex to DeepSeek Harness, then bringing the result back for review and verification.

It is deliberately not a framework. No task queues, no dashboards, no extra config format — just three questions, answered honestly: *should this be delegated, what exactly should the worker do, and how do you check the result before you believe it.*

The worker path used locally is the bundled `scripts/dsh-cli.mjs`, which drives the already-running 3080 Harness over loopback MCP. Upstream MCP-bridge and headless-CLI paths remain available on demand; they do not override the local CLI-first flow.

## Try it

```bash
git clone https://github.com/LomoMao/delegate-to-deepseek-harness.git
cd delegate-to-deepseek-harness
./scripts/install_skill.sh   # merges into $HOME/.agents/skills without deleting extra files
```

Then in Codex:

```text
Use $delegate-to-deepseek-harness to fix the failing parser tests.
Keep the public API unchanged, then review the diff and rerun the focused tests yourself.
```

## Why

Sometimes the expensive part of a coding task is not the final decision — it is reading a large repo, making repetitive edits, repairing tests, or implementing a clearly specified slice of work.

This skill keeps that split simple:

```text
You → Codex → DeepSeek Harness → workspace changes
              ↓
         Codex reviews
         diff + tests
```

Codex stays responsible for scope, risky judgment, integration, and the final answer.

**Methodology first, backend-agnostic.** The reusable part of this skill is the delegation contract and the review gate, not any particular worker path. If the MCP bridge changes or disappears, the headless CLI fallback (or any future Harness interface) keeps the same workflow intact.

## Good fits

- bounded implementation work
- mechanical refactors and migrations
- test repair and test generation
- repository exploration with a concrete question
- independent second attempts
- parallel work in separate worktrees

Not a good fit for architecture decisions, secrets, deployments, destructive operations, or work with no meaningful verification path.

## Other ways to install

Codex loads user skills from `$HOME/.agents/skills` (repo-local skills live in `.agents/skills`).

**Manual copy:** copy `SKILL.md`, `agents/`, `references/`, and `scripts/` into `$HOME/.agents/skills/delegate-to-deepseek-harness/`.

**Codex's built-in skill installer:**

```text
$skill-installer install https://github.com/LomoMao/delegate-to-deepseek-harness
```

## Worker backends

**Local default:** the bundled `scripts/dsh-cli.mjs`, using the existing `http://127.0.0.1:3080/mcp` endpoint and native `session_start` / `session_send` / `session_status` / `turn_result` tools. It starts no second Harness process and does not replace the Codex `dsh_harness` MCP configuration. See [cli](references/cli.md).

**On demand:** native MCP tools for cancel, approvals, subagents, or raw events. See [native-mcp](references/native-mcp.md).

**Historical / opt-in:** the upstream third-party MCP bridge and the official one-shot CLI:

```bash
dsh --profile headless "run the tests"
```

See [setup](references/setup.md) only when the upstream path or its connectivity matters; the 8090 bridge is not the local default.

## One rule that matters

A worker saying “done” is not evidence that the task is done.

After delegation, Codex checks the real files and runs the focused acceptance checks required by the task. A machine receipt from `scripts/verify_workspace.sh` is optional, not a default gate; the user's simplified acceptance rules take precedence.

**Delegate the work. Verify the evidence. Don't redo the work.**

Why that last sentence exists, from one real delegation run:

```text
planning         8%
worker          12%
manager review  80%   ← the worker had already passed 16/16 tests
```

The expensive part wasn't delegation. It was verification without a stopping rule.

## Status

Small on purpose, and staying that way. The core workflow — contract, delegation, verification — is stable. The DeepSeek Harness ecosystem around it moves fast, so MCP tool names are pinned to `@chushixixin/dsh-harness-mcp-server` v0.1.x in [setup](references/setup.md) and may need a quick re-check after upgrades.

Issues and small PRs are welcome.

## Security

A Harness worker may be able to edit files and run shell commands. Treat third-party Harness plugins as trusted local code, keep MCP endpoints on loopback, and scope writable workspaces as narrowly as practical. See [SECURITY.md](SECURITY.md).

## Acknowledgements

Inspired by the broader agent-delegation pattern used by projects such as `delegate-skills`, `delegate-to-pi`, and other reviewer/worker workflows.

This project is independent and is not affiliated with OpenAI or DeepSeek.

## License

MIT
