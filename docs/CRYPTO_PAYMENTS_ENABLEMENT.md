# Phase 18 — Crypto Payments Enablement Runbook

Operational guide for turning on HarborIQ's licensed-processor stablecoin
invoice rail. Companion to the architecture decision in the HarborIQ project
file repo (`reports/HarborIQ_Tokenization_Crypto_Architecture_2026-08-05.md`)
and the code shipped in migrations `0020` / Phase 18.

## What this is (and is not)

| Is | Is not |
|---|---|
| Accepting customer payment of a HarborIQ invoice via Stripe-hosted stablecoin/crypto Checkout | HarborIQ holding wallets, private keys, or on-chain custody |
| Settling through a licensed processor (Stripe) so HarborIQ is not the money transmitter | DIY crypto acceptance that would trigger FinCEN MSB / Florida Ch. 560 licensing |
| Extending the existing `InvoiceSM` + webhook/idempotency path | A separate billing system or new invoice state machine |
| Feature-flagged off by default | Automatically live just because the code is on `master` |

Phase 19 (asset tokenization of vessels/slips/equipment/receivables) is a
**separate** track. It stays disabled (`ASSET_TOKENIZATION_ENABLED=false`)
as a placeholder pending securities counsel — see README "Asset tokenization
layer". Do not enable it as part of this runbook.

## Prerequisites (in order)

1. **Migration head includes `0020_crypto_payment_rail`.**
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.prod.yml exec app alembic current
   # expect: 0021 (head) or at least 0020
   docker compose ... exec app alembic upgrade head
   ```
2. **Stripe account has crypto/stablecoin Checkout enabled.**
   This is a Stripe-side product enablement, not a HarborIQ flag. Confirm in
   the Stripe Dashboard (or with Stripe support) that `payment_method_types`
   may include `crypto` for Checkout Sessions on the platform account and any
   Connect accounts you will charge through.
3. **Existing Stripe integration already works for card Checkout.**
   `STRIPE_API_KEY` and `STRIPE_WEBHOOK_SECRET` are set; card invoice pay links
   already mark invoices paid via `POST /api/v1/webhooks/stripe`.
4. **Webhook endpoint registered in Stripe Dashboard** (if not already):
   - URL: `https://<your-public-host>/api/v1/webhooks/stripe`
   - Events at minimum: `checkout.session.completed`, `payment_intent.succeeded`,
     `charge.refunded` (existing), plus whatever you already use for Connect.
   - Phase 18 does **not** require a separate Stripe endpoint for crypto —
     crypto Checkout completions use `metadata.kind = crypto_invoice_payment`
     on the same Stripe webhook path.

## Environment variables

On the host (`.env` next to compose, or your secrets manager — **never commit**):

```bash
# Required for the rail to create Checkout Sessions
CRYPTO_PAYMENTS_ENABLED=true
STRIPE_API_KEY=sk_live_...          # or sk_test_... in staging
STRIPE_WEBHOOK_SECRET=whsec_...     # from Stripe Dashboard → Webhooks

# Optional: only if you also expose the generic non-Stripe crypto webhook
# (local tests / future non-Stripe processor). Generate, do not reuse the
# Stripe whsec_ value:
#   openssl rand -hex 32
CRYPTO_WEBHOOK_SECRET=<64-hex-chars>

# Leave OFF — Phase 19 placeholder, securities-law gated
ASSET_TOKENIZATION_ENABLED=false
```

Redeploy / restart the `app` (and any worker) containers after setting env.

## Production payment path

```
Operator: POST /api/v1/invoices/{id}/crypto-payment-intent
    → crypto_payments row (pending)
    → Stripe Checkout Session (payment_method_types=["crypto"],
         metadata.kind=crypto_invoice_payment)
    → invoices.stripe_checkout_session_id stamped

Customer: pays on Stripe-hosted page (USDC/stablecoin via Stripe)

Stripe: POST /api/v1/webhooks/stripe  (Stripe-Signature)
    → handle_stripe_webhook
    → kind == crypto_invoice_payment
    → crypto_payments.status = confirmed
    → invoices.mark_paid_from_webhook (same path as card)
```

The generic `POST /api/v1/webhooks/crypto` (HMAC `X-Crypto-Signature`) is
retained for non-Stripe processors and automated tests. **Do not point a
Stripe Dashboard endpoint at it** — Stripe signs with `Stripe-Signature`, not
our HMAC scheme.

## Smoke test (staging)

1. Ensure `CRYPTO_PAYMENTS_ENABLED=true` and Stripe test keys are loaded.
2. As an operations user, create/send an invoice, then:
   ```bash
   curl -sS -X POST "$API/api/v1/invoices/$INVOICE_ID/crypto-payment-intent" \
     -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d '{"amount":"25.00","currency":"usdc"}'
   ```
3. Open the returned `checkout_url_or_address` and complete payment with a
   Stripe test crypto method (or Stripe CLI trigger if crypto test rails
   are unavailable — see fallback below).
4. Confirm:
   - `GET /api/v1/crypto-payments/{id}` → `status=confirmed`
   - Invoice → `status=paid` (or `partial`)
   - One `payments` row; no double-pay on webhook replay

**CLI fallback** (if Stripe test crypto UI is unavailable): after creating
the intent, use the generic crypto webhook with `CRYPTO_WEBHOOK_SECRET` to
simulate confirmation in staging only — never use this to bypass Stripe in
production for real money.

## Rollback

```bash
CRYPTO_PAYMENTS_ENABLED=false
# restart app
```

Existing confirmed rows and paid invoices are unchanged. Pending intents
simply stop being creatable; open Stripe Checkout links may still complete
and will still be applied if `STRIPE_WEBHOOK_SECRET` verification remains on
(desired — money that already moved should still book).

## Security checklist (before go-live)

- [ ] `APP_ENV=production`
- [ ] `STRIPE_WEBHOOK_SECRET` set; card webhook already verifying signatures
- [ ] `CRYPTO_PAYMENTS_ENABLED=true` only after Stripe crypto product enabled
- [ ] `CRYPTO_WEBHOOK_SECRET` set if `/webhooks/crypto` is reachable publicly
- [ ] `ASSET_TOKENIZATION_ENABLED=false`
- [ ] TLS terminated at reverse proxy; webhook URL is HTTPS
- [ ] Connect accounts (if used) also approved for crypto by Stripe
- [ ] Ops runbook known: how to read `crypto_payments` + Stripe Dashboard
      for a disputed stablecoin payment

## Phase 19 placeholder (do not enable here)

`ASSET_TOKENIZATION_ENABLED` remains `false`. Enabling it only exposes
admin draft-registration of intent-to-tokenize records; it still cannot
issue or transfer tokens (DB `CHECK (status = 'draft')` + no mutation
routes). Securities counsel review is still required before any production
enablement — see SEC Release 33-11412 / Corp Fin tokenized-securities
statement context in the architecture report.
