# ADR 0006 — Protected `master` via repository ruleset

Status: Accepted (2026-09-22)

## Context
Recent history included direct pushes to `master` (see audit issues
#59–#67, #71, #72). Classic branch protection was unavailable on this
repository ("Branch protection has been disabled").

## Decision
Repository ruleset **`protect-master`** (id 23833728), active on the default
branch with no bypass actors: block deletion, block non-fast-forward,
require a pull request (0 approvals — single maintainer — with stale-review
dismissal and conversation resolution), and require the status checks
`secret-scan`, `lint`, `test`, `frontend`, `docker-build` to pass on an
up-to-date branch.

## Consequences
- Every change reaches `master` through a PR with green CI.
- When a second engineer joins, raise required approvals to 1 and add
  CODEOWNERS for `alembic/`, `app/db/`, and `app/services/stripe_*`.
