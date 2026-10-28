# ADR 0007 — Trust `X-Forwarded-*` from the platform proxy

Status: Accepted (2026-10-18, v0.2.1)

## Context
The API image ran `uvicorn` with its defaults. Uvicorn only honours
`X-Forwarded-For` / `X-Forwarded-Proto` from peers listed in
`--forwarded-allow-ips`, which defaults to `127.0.0.1`
([uvicorn settings](https://uvicorn.dev/settings/)). On Render (the
selected host, `render.yaml`) and behind Cloudflare, the container's only peer
is the platform proxy, so `request.client.host` would be the proxy address for
every request.

Three things key on that address:

- the per-IP fixed-window limiters for login, password reset and the public
  marketing-lead form (`app/core/rate_limit.py`) — all customers would share
  **one** bucket and a handful of failed logins anywhere would 429 everyone;
- `audit_log.actor_ip` (auth, estimates, and the v0.2.1 invoice/user events);
- any future geo/abuse logic.

## Decision
Set `ENV FORWARDED_ALLOW_IPS="*"` in the runtime image and start uvicorn with
`--proxy-headers`. The literal `*` trusts forwarded headers from any peer.

## Consequences
- Correct client IPs behind Render/Cloudflare without per-platform config.
- If the API is ever exposed directly (no proxy in front), a client could
  spoof `X-Forwarded-For` to dodge per-IP limits. Mitigation: never publish the
  container port directly; if that changes, override `FORWARDED_ALLOW_IPS`
  with the proxy's CIDR list. The account lockout (per user) and token
  denylist are unaffected either way.
- `docker compose` local runs are unaffected (loopback peers).
