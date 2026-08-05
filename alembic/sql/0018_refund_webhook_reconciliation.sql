-- Phase 17, Area E: refund webhook reconciliation.
--
-- A refund issued directly in the Stripe Dashboard (bypassing HarborIQ's own
-- `POST /invoices/{id}/refund`) is reconciled via the `charge.refunded`
-- webhook (see `app.services.invoices.reconcile_refund_from_webhook`). That
-- path -- like every other webhook handler in this codebase -- must be safe
-- against duplicate/replayed deliveries. `stripe_refund_id` was previously
-- just an (optional, nullable) audit column with no uniqueness guarantee;
-- this adds a partial unique index (ignoring NULLs, since HarborIQ-created
-- refunds prior to Phase 8's Stripe wiring could have a NULL id) so a
-- concurrent duplicate delivery can rely on `ON CONFLICT (stripe_refund_id)
-- DO NOTHING` rather than a plain existence check racing another connection.
CREATE UNIQUE INDEX uq_refunds_stripe_refund_id
    ON refunds (stripe_refund_id)
    WHERE stripe_refund_id IS NOT NULL;
