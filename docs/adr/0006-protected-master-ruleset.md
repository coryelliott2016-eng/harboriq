# ADR 0006 — Protected `master` via repository ruleset

Status: Accepted (2026-09-22)

## Context
Recent history included direct pushes to `master` (see audit issues
#59–#67, #71, #72). Classic branch protection was unavailable on this
repository ("Branch protection has been disabled").

## Decision
Repository ruleset **`protect-master`** (id 23833728) is documented as active
on the default branch with no bypass actors: block deletion, block
non-fast-forward, require a pull request (currently 0 approvals, with
stale-review dismissal and conversation resolution), and require the status
checks `secret-scan`, `lint`, `test`, `frontend`, and `docker-build` to pass on
an up-to-date branch.

The repository now adds the required `repo-integrity` status check and explicit
CODEOWNERS for `tests/acceptance/`. Update the live ruleset to require
`repo-integrity` and require CODEOWNER approval for owned paths; the repository
files cannot apply or verify GitHub settings. Until that settings change is
confirmed, ownership is declared but is not an enforced acceptance-test review
gate.

## Consequences
- Every change reaches `master` through a PR with green CI.
- When a second engineer joins, raise general required approvals to 1 and add
  further CODEOWNERS for `alembic/`, `app/db/`, and `app/services/stripe_*`.
