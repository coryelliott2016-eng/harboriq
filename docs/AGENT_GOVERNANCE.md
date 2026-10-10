# Agent governance, skills inventory, and measurement

## Instruction sources

- [`AGENTS.md`](../AGENTS.md) is the single repository-wide agent instruction
  entry point.
- [`BUSINESS_INVARIANTS.md`](BUSINESS_INVARIANTS.md) records business rules
  agents must preserve.
- `.github/skills/manifest.json` is the inventory and integrity lock for
  repository-local skills.

No repository-local skill definitions were present when this inventory was
created. The manifest is intentionally empty. Runtime-provided skills and tools
are environment-specific and are not installed or verified by this repository;
application services and test helpers are not agent skills.

### Runtime skills available in this agent environment

| Skill | Scope |
|---|---|
| `customize-cloud-agent` | Configure the Copilot cloud-agent environment and setup steps. |
| `merge-branch` | Fetch and merge/rebase another branch in a shallow agent checkout. |

This is an environment snapshot, not a repository installation or a CI-verified
inventory. Update it when the runtime's available skills change.

## Retry, scope, and escalation limits

- **Retries:** one initial attempt plus no more than two retries, and only for
  plausibly transient command failures. Persistent or deterministic failures
  are reported with the command and error; agents must not hide or route around
  them.
- **Scope:** change only files and behavior needed for the requested task.
  Unrequested refactors, features, dependency changes, and unrelated cleanup
  require separate approval.
- **Escalation:** stop and ask the maintainer before changing protected
  business invariants, tenant/RLS policies, authorization, payment or pricing
  semantics, production/deployment controls, or repository protection
  settings. Also escalate unclear requirements and any request to bypass tests,
  review, or security checks.
- **Authority:** agents may propose and implement approved changes but may not
  merge, deploy, use production credentials, or make real payments.

## Acceptance tests and ownership

The defect-oriented suite in `tests/acceptance/` exercises unsafe
cross-tenant access, overpayment handling, and client-forged pricing totals.
Changes to that suite require review from its CODEOWNER. CI runs it as part of
the existing full `pytest -ra` suite.

CODEOWNERS requests a review; it is enforced only when repository rules require
CODEOWNER approval. The `protect-master` ruleset is external to this checkout.
Configure it to require a pull request, CODEOWNER review for owned files,
conversation resolution, up-to-date required checks, and no bypass actors.
Include `repo-integrity` with the existing required checks. Verify the live
ruleset after changes; editing this repository cannot apply GitHub settings.

## 30-day outcome measurement

Record one row per week for 30 days, using the same definitions throughout.
Do not publish estimates as measured results. Capture an incident link or
measurement source for each nonzero value.

| Period | Agent-created regressions | Reviewer active minutes | Unsafe actions blocked | CI failures | Inference cost |
|---|---:|---:|---:|---:|---:|
| Days 1–7 | | | | | |
| Days 8–14 | | | | | |
| Days 15–21 | | | | | |
| Days 22–30 | | | | | |

Definitions:

- **Agent-created regressions:** confirmed regressions attributable to an
  agent-authored change, counted after merge.
- **Reviewer active minutes:** human review time spent on agent-authored
  changes; use one consistent source and distinguish active review from queue
  wait time.
- **Unsafe actions blocked:** attempted actions stopped by a documented human,
  CI, permission, or policy gate. Record the gate and link, not credentials or
  sensitive payloads.
- **CI failures:** failed CI runs for agent-authored changes, separating
  product failures from infrastructure/flaky failures.
- **Inference cost:** provider-reported cost for agent runs in the period,
  summed in one currency. Record unavailable data as unavailable, not zero.

At day 30, review the figures with the maintainer and decide whether to retain
or adjust agent scope, gates, and escalation rules.
