# Agent instructions

These repository-wide instructions apply to automated coding agents. Read
[`docs/AGENT_GOVERNANCE.md`](docs/AGENT_GOVERNANCE.md) and
[`docs/BUSINESS_INVARIANTS.md`](docs/BUSINESS_INVARIANTS.md) before changing
business logic, tests, database policy, or deployment configuration.

- Work only within the requested scope. Do not broaden a task into unrelated
  refactors, dependency upgrades, or feature work.
- Preserve every protected business invariant and its acceptance coverage.
  Changes to tenant isolation, access control, payment/refund processing,
  pricing, state transitions, or auditability require explicit human approval.
- Never bypass, weaken, delete, or skip a failing test or CI/security check to
  make a change pass. Do not use production credentials, deploy, or make a real
  payment.
- Retry a failed command at most twice after the initial attempt, and only for
  plausibly transient failures. Stop and report the command, error, and
  attempts if it still fails; do not conceal or work around persistent failures.
- If scope, expected behavior, required access, or a protected rule is unclear,
  stop before making the consequential change and ask the maintainer.
- Do not merge, change repository settings, or bypass human review.
- Consult `.github/skills/manifest.json` for repository-local skills; do not
  treat application modules or environment-provided tools as installed skills.
- Run the existing relevant checks and report their results, including checks
  that could not run and why.
