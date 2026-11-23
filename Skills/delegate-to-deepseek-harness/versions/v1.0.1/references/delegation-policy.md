# Delegation policy

Local default: the bundled `scripts/dsh-cli.mjs` against the existing 3080 Harness, with GPT retaining planning, review, and independent verification. The rules below are backend-agnostic.

Use delegation when the worker can receive a self-contained brief and the host can verify the result afterward.

Good worker tasks:

- implementation with clear acceptance criteria
- mechanical refactors and migrations
- test repair or test generation
- bounded repository exploration
- isolated second attempts

Keep in the host agent:

- architecture or product judgment
- final review and integration
- secrets and privileged credentials
- publishing, deployment, billing, or destructive external actions
- tasks whose success cannot be checked

For mutating parallel work, give each worker a separate worktree/cwd. Do not race two workers against the same checkout.
