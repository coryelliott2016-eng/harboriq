# Security Policy

## Supported versions

HarborIQ is pre-general-availability software. Only the latest commit on the
protected `master` branch (and the most recent tagged release) receives
security fixes.

| Version | Supported |
|---|---|
| `master` / latest `v0.x` tag | Yes |
| Older commits and tags | No |

## Reporting a vulnerability

Please report suspected vulnerabilities **privately** through GitHub's
private vulnerability reporting:
[Report a vulnerability](https://github.com/coryelliott2016-eng/harboriq/security/advisories/new).

Do not open a public issue, pull request, or discussion for a security
problem, and do not include real customer data in a report.

What to expect:

- Acknowledgement within 3 business days.
- An initial severity assessment (critical / high / medium / low) and next
  steps within 7 business days.
- Critical and high issues are fixed before any other release work; you will
  be told when a fix ships and whether a public advisory will be published.
- If a report is declined (not reproducible, out of scope, or accepted risk),
  you will be told why.

In scope: this repository's backend (`app/`), web client (`frontend/`),
migrations, CI configuration, and the production configuration it documents.
Out of scope: denial-of-service volume testing, social engineering, and
third-party services (Stripe, Vercel, Cloudflare, GitHub) themselves.

Please act in good faith: only test against accounts and data you own, stop
and report as soon as you can demonstrate an issue, and give us reasonable
time to fix it before disclosure.

## Certifications

HarborIQ does **not** hold SOC 2, ISO 27001, PCI DSS, HIPAA, or any other
security certification or attestation. Card data is handled by Stripe
(Stripe Checkout / Stripe-hosted pages); HarborIQ does not store card
numbers. See [`docs/SECURITY_OVERVIEW.md`](docs/SECURITY_OVERVIEW.md) for
the controls that actually exist in code.
