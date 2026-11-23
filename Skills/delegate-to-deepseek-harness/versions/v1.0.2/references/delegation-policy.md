# Delegation policy

Local default: the bundled `scripts/dsh-cli.mjs` against the existing 3080 Harness, with GPT retaining planning, review, and independent verification. The rules below are backend-agnostic.

For engineering development and delivery, delegate concrete implementation by default, including small tasks, with a self-contained scope and acceptance criteria. Match planning to complexity: a simple task needs only a goal, scope, and acceptance criteria. The host independently reviews and verifies the result.

GPT/Codex leads scientific and technical research, including source gathering, analysis, experiment design, comparing approaches, and conclusions; it may directly write and run exploratory code or scripts to test hypotheses. Larger experimental implementations or repetitive experiments may be delegated, while GPT/Codex retains experiment design and analysis. Explicit allocation of work in the current user request takes precedence.

Good worker tasks:

- implementation with clear acceptance criteria
- mechanical refactors and migrations
- test repair or test generation
- bounded repository exploration as an engineering subtask
- isolated second attempts

Keep in the host agent:

- architecture or product judgment
- final review and integration
- secrets and privileged credentials
- publishing, deployment, billing, or destructive external actions
- tasks whose success cannot be checked

For mutating parallel work, give each worker a separate worktree/cwd. Do not race two workers against the same checkout.
