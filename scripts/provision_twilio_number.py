#!/usr/bin/env python3
"""provision_twilio_number.py -- search for and (optionally) purchase a
Twilio SMS-capable local phone number for app/services/sms.py.

Mirrors app/services/sms.py's own pattern deliberately: plain `httpx` REST
calls against the Twilio API with HTTP Basic auth (Account SID / Auth
Token), no `twilio` SDK dependency -- `httpx` is already a dependency of
this codebase (see pyproject.toml), so adding the Twilio SDK for one
provisioning script would be a new dependency for a provider this repo
already talks to via plain HTTP.

This does NOT create the Twilio account itself -- that requires Cory's own
identity, email/phone verification, and (for production sending limits) a
payment method in the Twilio Console (see docs/EXTERNAL_ACCOUNTS_SETUP.md).
This script is the step that runs *after* the account exists and an
Account SID + Auth Token are in hand.

Safety: purchasing a number spends real money on the connected Twilio
account. This script defaults to a DRY RUN -- it searches for available
numbers and prints them with Twilio's own (best-effort) pricing hint, but
purchases NOTHING unless `--confirm` is passed explicitly.

Usage:
    export TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
    export TWILIO_AUTH_TOKEN=<your auth token>

    # Dry run (default) -- lists available numbers, purchases nothing:
    python scripts/provision_twilio_number.py --area-code 617

    # Actually purchase the first available match:
    python scripts/provision_twilio_number.py --area-code 617 --confirm
"""
from __future__ import annotations

import argparse
import os
import sys

import httpx

_TWILIO_API_BASE = "https://api.twilio.com/2010-04-01"

#: Twilio's own published starting rate for US local (long code) numbers,
#: used only as a human-readable estimate in dry-run output -- the
#: authoritative, current number should always be checked at
#: https://www.twilio.com/en-us/sms/pricing/us before purchasing at scale.
_ESTIMATED_MONTHLY_NUMBER_COST_USD = 1.15


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--account-sid",
        default=os.environ.get("TWILIO_ACCOUNT_SID", ""),
        help="Twilio Account SID (default: $TWILIO_ACCOUNT_SID).",
    )
    parser.add_argument(
        "--auth-token",
        default=os.environ.get("TWILIO_AUTH_TOKEN", ""),
        help="Twilio Auth Token (default: $TWILIO_AUTH_TOKEN).",
    )
    parser.add_argument(
        "--area-code",
        required=True,
        help="US area code to search for an SMS-capable local number in, e.g. 617.",
    )
    parser.add_argument(
        "--country",
        default="US",
        help="ISO country code to search in (default: US).",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help=(
            "Actually purchase the first matching number. Without this "
            "flag, the script only searches and prints results (dry run) "
            "-- no money is spent."
        ),
    )
    args = parser.parse_args(argv)
    if not args.account_sid or not args.auth_token:
        parser.error("--account-sid/--auth-token (or $TWILIO_ACCOUNT_SID/$TWILIO_AUTH_TOKEN) are required")
    return args


def search_available_numbers(
    client: httpx.Client, account_sid: str, auth_token: str, country: str, area_code: str
) -> list[dict]:
    """GET the AvailablePhoneNumbers resource, filtered to SMS-capable numbers."""
    url = f"{_TWILIO_API_BASE}/Accounts/{account_sid}/AvailablePhoneNumbers/{country}/Local.json"
    response = client.get(
        url,
        params={"AreaCode": area_code, "SmsEnabled": "true"},
        auth=(account_sid, auth_token),
        timeout=15,
    )
    response.raise_for_status()
    return response.json().get("available_phone_numbers", [])


def purchase_number(
    client: httpx.Client, account_sid: str, auth_token: str, phone_number: str
) -> dict:
    """POST to IncomingPhoneNumbers to actually buy the number. Spends money."""
    url = f"{_TWILIO_API_BASE}/Accounts/{account_sid}/IncomingPhoneNumbers.json"
    response = client.post(
        url,
        data={"PhoneNumber": phone_number},
        auth=(account_sid, auth_token),
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    with httpx.Client() as client:
        try:
            numbers = search_available_numbers(
                client, args.account_sid, args.auth_token, args.country, args.area_code
            )
        except httpx.HTTPStatusError as exc:
            print(f"Twilio API error searching numbers: {exc}", file=sys.stderr)
            print(exc.response.text, file=sys.stderr)
            return 1
        except httpx.HTTPError as exc:
            print(f"Network error contacting Twilio: {exc}", file=sys.stderr)
            return 1

        if not numbers:
            print(
                f"No SMS-capable numbers found for area code {args.area_code} "
                f"in {args.country}. Try a different area code."
            )
            return 1

        print(f"== Available SMS-capable numbers in area code {args.area_code} ({args.country}) ==")
        for n in numbers[:10]:
            print(f"  {n.get('phone_number')}  ({n.get('friendly_name', '')})")
        print()
        print(
            f"Estimated monthly rental: ~${_ESTIMATED_MONTHLY_NUMBER_COST_USD:.2f}/month "
            "for a US local number (verify current pricing at "
            "https://www.twilio.com/en-us/sms/pricing/us), plus per-SMS "
            "usage once sending."
        )

        if not args.confirm:
            print()
            print(
                "DRY RUN (default) -- no number was purchased. Re-run with "
                "--confirm to actually buy the first number listed above. "
                "This spends real money on the connected Twilio account."
            )
            return 0

        chosen = numbers[0]["phone_number"]
        print()
        print(f"--confirm passed: purchasing {chosen} now...")
        try:
            purchased = purchase_number(client, args.account_sid, args.auth_token, chosen)
        except httpx.HTTPStatusError as exc:
            print(f"Twilio API error purchasing number: {exc}", file=sys.stderr)
            print(exc.response.text, file=sys.stderr)
            return 1
        except httpx.HTTPError as exc:
            print(f"Network error contacting Twilio: {exc}", file=sys.stderr)
            return 1

    purchased_number = purchased.get("phone_number", chosen)
    print()
    print("== Purchased ==")
    print(f"Phone number: {purchased_number}")
    print()
    print("Add these to your .env:")
    print(f"  TWILIO_ACCOUNT_SID={args.account_sid}")
    print("  TWILIO_AUTH_TOKEN=<your auth token>")
    print(f"  TWILIO_FROM_NUMBER={purchased_number}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
