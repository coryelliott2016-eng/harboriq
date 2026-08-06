#!/usr/bin/env python3
"""provision_cloudflare.py -- idempotently apply the CDN/WAF configuration
docs/DEPLOYMENT.md's "CDN / WAF (Cloudflare)" section describes by hand.

*******************************************************************
** WARNING: UNTESTED AGAINST A LIVE CLOUDFLARE ACCOUNT.           **
** No Cloudflare account or zone existed in this project when     **
** this script was written -- it has never been run against a     **
** real zone. Review every change in --dry-run output (the        **
** default mode) carefully before ever passing --apply, and       **
** verify the result by hand in the Cloudflare dashboard           **
** afterward. Do not trust this blindly in production.            **
*******************************************************************

Uses plain `httpx` REST calls against the Cloudflare API v4
(https://api.cloudflare.com/), matching this codebase's established
no-SDK-for-a-simple-REST-integration pattern (see app/services/sms.py for
the same approach against Twilio). This does NOT create the Cloudflare
account, zone, or API token themselves -- those require Cory's own
identity in the Cloudflare dashboard (see docs/EXTERNAL_ACCOUNTS_SETUP.md).

What this script does, matching docs/DEPLOYMENT.md exactly:
  1. Sets the zone's SSL/TLS mode to "Full (strict)".
  2. Enables the WAF Managed Ruleset (Cloudflare's OWASP-equivalent
     managed rules) in Log mode -- DEPLOYMENT.md explicitly recommends
     starting in Log mode and only moving to Block after a burn-in period
     confirms no false positives against real HarborIQ traffic; this
     script does not silently choose Block on your behalf.
  3. Creates a Cache Rule caching static assets (/assets/*, /favicon.ico,
     /manifest.webmanifest) aggressively while explicitly bypassing cache
     for /api/* and the frontend's index.html -- the one rule
     DEPLOYMENT.md calls out as mattering most for correctness, not just
     performance (per-tenant API responses must never be cached at the
     edge).

Idempotent: each of the three actions checks current zone state first and
only makes a change if the desired state doesn't already exist, so
re-running this script (e.g. after a partial failure) does not create
duplicate cache rules or redundant API calls.

Usage:
    export CLOUDFLARE_API_TOKEN=<your API token>
    export CLOUDFLARE_ZONE_ID=<your zone ID>

    # Dry run (default) -- prints what WOULD change, changes nothing:
    python scripts/provision_cloudflare.py --domain example.com

    # Only after reviewing the dry-run output line by line:
    python scripts/provision_cloudflare.py --domain example.com --apply
"""
from __future__ import annotations

import argparse
import os
import sys

import httpx

_CF_API_BASE = "https://api.cloudflare.com/client/v4"

#: Path patterns to cache aggressively -- content-hashed build assets and
#: other clearly-static files, matching docs/DEPLOYMENT.md exactly.
_STATIC_CACHE_PATTERNS = ["/assets/*", "/favicon.ico", "/manifest.webmanifest"]

#: Path patterns that must NEVER be cached at the edge -- per-tenant API
#: responses and the always-revalidate index.html, matching
#: docs/DEPLOYMENT.md's explicit "never cache /api/*" warning.
_BYPASS_CACHE_PATTERNS = ["/api/*", "/index.html"]

_CACHE_RULE_DESCRIPTION = "harboriq-static-assets-cache (provisioned by provision_cloudflare.py)"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--api-token",
        default=os.environ.get("CLOUDFLARE_API_TOKEN", ""),
        help="Cloudflare API token (default: $CLOUDFLARE_API_TOKEN).",
    )
    parser.add_argument(
        "--zone-id",
        default=os.environ.get("CLOUDFLARE_ZONE_ID", ""),
        help="Cloudflare zone ID (default: $CLOUDFLARE_ZONE_ID).",
    )
    parser.add_argument(
        "--domain",
        required=True,
        help="Domain name the zone belongs to (used only for readable output).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Actually make changes via the Cloudflare API. Without this "
            "flag, the script only prints what it WOULD do (dry run)."
        ),
    )
    args = parser.parse_args(argv)
    if not args.api_token or not args.zone_id:
        parser.error("--api-token/--zone-id (or $CLOUDFLARE_API_TOKEN/$CLOUDFLARE_ZONE_ID) are required")
    return args


def _headers(api_token: str) -> dict:
    return {"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"}


def get_ssl_mode(client: httpx.Client, zone_id: str, api_token: str) -> str:
    url = f"{_CF_API_BASE}/zones/{zone_id}/settings/ssl"
    response = client.get(url, headers=_headers(api_token), timeout=15)
    response.raise_for_status()
    return response.json()["result"]["value"]


def set_ssl_mode(client: httpx.Client, zone_id: str, api_token: str, mode: str = "strict") -> None:
    """Cloudflare's API calls "Full (strict)" mode `strict`."""
    url = f"{_CF_API_BASE}/zones/{zone_id}/settings/ssl"
    response = client.patch(url, headers=_headers(api_token), json={"value": mode}, timeout=15)
    response.raise_for_status()


def get_managed_ruleset_status(client: httpx.Client, zone_id: str, api_token: str) -> str | None:
    """Returns the entrypoint ruleset's current execution status, or None if
    no entrypoint phase ruleset exists yet for http_request_firewall_managed."""
    url = f"{_CF_API_BASE}/zones/{zone_id}/rulesets/phases/http_request_firewall_managed/entrypoint"
    response = client.get(url, headers=_headers(api_token), timeout=15)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    rules = response.json().get("result", {}).get("rules", [])
    for rule in rules:
        if rule.get("action") == "execute":
            return rule.get("action_parameters", {}).get("id")
    return None


def enable_managed_ruleset(client: httpx.Client, zone_id: str, api_token: str) -> None:
    """Enables Cloudflare's Managed Ruleset in Log mode, per DEPLOYMENT.md's
    explicit "start in Log mode, move to Block only after a burn-in period"
    guidance -- this script deliberately does not choose Block on your
    behalf."""
    url = f"{_CF_API_BASE}/zones/{zone_id}/rulesets/phases/http_request_firewall_managed/entrypoint"
    body = {
        "rules": [
            {
                "action": "execute",
                "action_parameters": {
                    "id": "efb7b8c949ac4650a09736fc376e9aee",  # Cloudflare Managed Ruleset ID
                    "overrides": {"action": "log"},
                },
                "description": "HarborIQ: Cloudflare Managed Ruleset (Log mode, per docs/DEPLOYMENT.md)",
            }
        ]
    }
    response = client.put(url, headers=_headers(api_token), json=body, timeout=15)
    response.raise_for_status()


def list_cache_rules(client: httpx.Client, zone_id: str, api_token: str) -> list[dict]:
    url = f"{_CF_API_BASE}/zones/{zone_id}/rulesets/phases/http_request_cache_settings/entrypoint"
    response = client.get(url, headers=_headers(api_token), timeout=15)
    if response.status_code == 404:
        return []
    response.raise_for_status()
    return response.json().get("result", {}).get("rules", [])


def cache_rule_exists(client: httpx.Client, zone_id: str, api_token: str) -> bool:
    rules = list_cache_rules(client, zone_id, api_token)
    return any(r.get("description") == _CACHE_RULE_DESCRIPTION for r in rules)


def create_cache_rules(client: httpx.Client, zone_id: str, api_token: str) -> None:
    """Creates the static-asset cache rule + the /api/* + index.html bypass
    rule described in docs/DEPLOYMENT.md, appended to the existing ruleset
    rather than replacing it (a PUT here would clobber any other rules an
    operator has already configured by hand)."""
    existing_rules = list_cache_rules(client, zone_id, api_token)

    static_expr = " or ".join(f'http.request.uri.path wildcard "{p}"' for p in _STATIC_CACHE_PATTERNS)
    bypass_expr = " or ".join(f'http.request.uri.path wildcard "{p}"' for p in _BYPASS_CACHE_PATTERNS)

    new_rules = [
        {
            "description": _CACHE_RULE_DESCRIPTION,
            "expression": bypass_expr,
            "action": "set_cache_settings",
            "action_parameters": {"cache": False},
        },
        {
            "description": f"{_CACHE_RULE_DESCRIPTION}-static",
            "expression": static_expr,
            "action": "set_cache_settings",
            "action_parameters": {
                "cache": True,
                "edge_ttl": {"mode": "override_origin", "default": 31536000},
            },
        },
    ]

    url = f"{_CF_API_BASE}/zones/{zone_id}/rulesets/phases/http_request_cache_settings/entrypoint"
    response = client.put(
        url, headers=_headers(api_token), json={"rules": existing_rules + new_rules}, timeout=15
    )
    response.raise_for_status()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"== HarborIQ Cloudflare provisioning for {args.domain} ({mode}) ==")
    print(
        "!! This script is UNVALIDATED against a live Cloudflare account. "
        "Review carefully. !!\n"
    )

    with httpx.Client() as client:
        try:
            # --- 1. SSL/TLS mode -> Full (strict) ---
            current_ssl = get_ssl_mode(client, args.zone_id, args.api_token)
            if current_ssl == "strict":
                print(f"[ok] SSL/TLS mode already 'Full (strict)' for {args.domain}")
            elif args.apply:
                print(f"[apply] setting SSL/TLS mode to 'Full (strict)' (was: {current_ssl})")
                set_ssl_mode(client, args.zone_id, args.api_token)
            else:
                print(f"[would apply] set SSL/TLS mode to 'Full (strict)' (currently: {current_ssl})")

            # --- 2. WAF Managed Ruleset (Log mode) ---
            ruleset_id = get_managed_ruleset_status(client, args.zone_id, args.api_token)
            if ruleset_id:
                print("[ok] WAF Managed Ruleset already enabled")
            elif args.apply:
                print("[apply] enabling WAF Managed Ruleset in Log mode")
                enable_managed_ruleset(client, args.zone_id, args.api_token)
            else:
                print("[would apply] enable WAF Managed Ruleset in Log mode (not Block -- see docs/DEPLOYMENT.md)")

            # --- 3. Cache Rule: static assets cached, /api/* + index.html bypassed ---
            if cache_rule_exists(client, args.zone_id, args.api_token):
                print("[ok] HarborIQ cache rules already present")
            elif args.apply:
                print(f"[apply] creating cache rules: cache {_STATIC_CACHE_PATTERNS}, bypass {_BYPASS_CACHE_PATTERNS}")
                create_cache_rules(client, args.zone_id, args.api_token)
            else:
                print(
                    f"[would apply] create cache rules: cache {_STATIC_CACHE_PATTERNS} "
                    f"aggressively, bypass {_BYPASS_CACHE_PATTERNS} entirely"
                )
        except httpx.HTTPStatusError as exc:
            print(f"Cloudflare API error: {exc}", file=sys.stderr)
            print(exc.response.text, file=sys.stderr)
            return 1
        except httpx.HTTPError as exc:
            print(f"Network error contacting Cloudflare: {exc}", file=sys.stderr)
            return 1

    print()
    if args.apply:
        print("Done. Verify every change by hand in the Cloudflare dashboard --")
        print("this script has not been validated against a live account.")
    else:
        print("DRY RUN complete -- nothing was changed. Re-run with --apply once")
        print("you have reviewed the above and are ready to make live changes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
