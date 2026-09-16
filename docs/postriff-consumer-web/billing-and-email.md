# Billing (Stripe) and transactional email (Resend)

**Date:** 2026-09-16 · **Code:** `src/postriff_phase2/billing_stripe.py`, `src/postriff_phase2/email.py`, wiring in `hosted.py` / `hosted_app.py`, migration `008_billing_provider_notifications.sql`.

Nothing in this document is executed by the code without the founder-only steps below. Until they are done the deployment runs with `DisabledPaymentProvider` (every webhook → 503, no checkout) and `NullTransport` (emails recorded, never sent).

## How it works

| Piece | Behaviour |
|---|---|
| Plan availability | `pr_plan_terms.status='active'` **and** `provider_price_id` set. Checkout refuses anything else with 409 (decision D3). |
| Checkout | `POST /api/workspaces/{id}/billing/checkout` `{planTermsId, successPath?, cancelPath?}` → `201 {url, sessionId}`. Owner-only, 5/min per workspace. Paths must be relative; absolute URLs are refused. Stripe Checkout runs in `subscription` mode with `client_reference_id` and `subscription_data.metadata.{workspace_id, plan_terms_id}`. Nothing is written locally until the webhook arrives. |
| Portal | `POST /api/workspaces/{id}/billing/portal` `{returnPath?}` → `200 {url}`. Owner-only. Needs an existing Stripe customer (409 otherwise). Plan changes, payment method, cancellation and invoices all happen in the Stripe-hosted portal. |
| Webhook | `POST /api/billing/webhook` with `Stripe-Signature`. Verified (HMAC-SHA256, 300 s tolerance), replay-safe (`pr_billing_events`), out-of-order safe (`last_event_at`). Events without PostRiff workspace metadata are recorded as `ignored` and answered 200 so Stripe does not retry. |
| Event mapping | `checkout.session.completed` → active · `customer.subscription.{created,updated}` by status (active/trialing → active, past_due → past_due, unpaid → expired, canceled → cancelled) · `customer.subscription.deleted` → cancelled · `invoice.payment_failed` → past_due (7-day grace) · `invoice.paid` → active. Plan terms come from metadata or are resolved from the price id. |
| Usage view | `GET /api/workspaces/{id}/usage` now includes `billing: {provider, checkoutAvailable, portalAvailable}`. |
| Emails | invitation (accept link `/invite/{token}`), welcome (first workspace), subscription activated, payment failed, trial ending (2–3 days before), trial ended (within a day after). All deduped in `pr_notifications`; a failed send never fails the business action. Addresses come from Supabase Auth at send time and are not stored (D16). |
| Reminders | Run by `GET /api/cron/worker` after the publishing tick; ≤ 50 sends per run. |

## Founder-only setup (cannot be done by code)

### Stripe
1. Create two Products with monthly recurring Prices: **Studio** (USD 19.00) and **Studio Assist** (USD 39.00). Copy the `price_…` ids.
2. Enable the **Customer Portal** (Settings → Billing → Customer portal): allow plan switching between the two prices, cancellation at period end, payment-method updates, invoice history.
3. Add a webhook endpoint `https://<your-domain>/api/billing/webhook` with events: `checkout.session.completed`, `customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.paid`, `invoice.payment_failed`. Copy the signing secret.
4. Vercel env (production + preview as appropriate): `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`.
5. Make the plans purchasable — this is the commercial decision recorded in data:
   ```sql
   update public.pr_plan_terms set status='active', provider_price_id='price_XXXX', decided_at=now() where id='studio-v1';
   update public.pr_plan_terms set status='active', provider_price_id='price_YYYY', decided_at=now() where id='assist-v1';
   ```
6. Test mode first: `stripe listen --forward-to localhost:4331/api/billing/webhook` against the dev harness, then a real checkout with a test card on the preview deployment.

### Resend
1. Verify the sending domain (DNS records shown in the Resend dashboard).
2. Vercel env: `RESEND_API_KEY`, `EMAIL_FROM` (e.g. `PostRiff <hello@yourdomain>`), and `POSTRIFF_PUBLIC_BASE_URL` (required together).

### Migration
Apply `migrations/postriff/008_billing_provider_notifications.sql` after 001–007 on the hosted database (additive: one column, one service-only table).

## Tests
- Unit: `tests/test_postriff_stripe.py`, `tests/test_postriff_email.py`, route tests in `tests/test_postriff_billing.py`.
- PostgreSQL: `LC_ALL=C .venv/bin/python scripts/postriff_disposable_postgres.py tests/phase2/postgres_billing_stripe.py` — checkout gate, signed webhooks, notifications, invitation email, reminder dedupe on the real schema.
