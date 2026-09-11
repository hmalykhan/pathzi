# billing

Stripe subscriptions: subscribe (Stripe PaymentSheet on mobile), subscription status, change plan
(upgrade now or downgrade at the end of the period), cancel / resume, the Stripe customer portal,
and the webhook that keeps the local state in sync with Stripe.

**Status:** the code works, but **nothing in the app is gated on a subscription yet** (the checks in
`careers/views.py` are commented out), and the plans in the new paywall design differ from the ones
configured here. The rest is Part 2 of BACKEND.md.

## Tables

| Model | Table | |
|---|---|---|
| `BillingProfile` | `billing_billingprofile` | One per user: `stripe_customer_id`, `stripe_subscription_id`, `plan_id` (`free` / `monthly` / `quarterly` / `yearly`), `stripe_price_id`, `pending_plan_id`, `pending_change_at`, `stripe_schedule_id`, `subscription_status` (`none` / `incomplete` / `trialing` / `active` / `past_due` / `canceled` / `unpaid`), `current_period_end`, `created_at`, `updated_at` |
| `StripeEvent` | `billing_stripeevent` | Every webhook event received (`event_id` unique), so each is processed once |

`BillingProfile.is_active` is `true` only for a paid plan with status `active` whose period hasn't
ended (a Stripe `trialing` status doesn't count).

## Endpoints

All under `/api/billing/`; all need login except the webhook.

| Method | Path | |
|---|---|---|
| POST | `subscribe/` | Start a subscription |
| GET | `status/` | Current subscription |
| POST | `change-plan/` | Upgrade or downgrade |
| POST | `cancel/` | Cancel (at period end by default) |
| POST | `resume/` | Undo a cancel-at-period-end |
| POST | `portal/` | Stripe customer portal link |
| POST | `webhook/` | Stripe → backend (signed) |

### `POST /api/billing/subscribe/`
```json
{ "plan_id": "monthly" }
```
`plan_id`: `monthly` (default), `quarterly`, `yearly` or `free`.

`200` — values for Stripe PaymentSheet:
```json
{
  "plan_id": "monthly",
  "customer_id": "cus_...",
  "ephemeral_key_secret": "ek_...",
  "subscription_id": "sub_...",
  "payment_intent_client_secret": "pi_..._secret_..."
}
```
Instead of `payment_intent_client_secret` there may be `setup_intent_client_secret`; if Stripe gives
neither, `hosted_invoice_url` (open in a WebView) plus a `detail` explaining it.

- `{"plan_id": "free"}` → `{"plan_id": "free", "detail": "Free plan selected."}`
- An unfinished subscription for the same plan is reused; a different plan replaces it.

Errors: `400 {"detail": "Invalid plan_id"}`, `400 {"detail": "You already have an active subscription."}`,
`502 {"detail": "Stripe error ...", "stripe_error": "..."}`.

### `GET /api/billing/status/`
```json
{ "is_active": true, "status": "active", "current_period_end": "2026-10-11T10:00:00Z",
  "plan_id": "monthly", "pending_plan_id": null, "pending_change_at": null }
```
With no billing record: `is_active: false`, `status: "none"`, `plan_id: "free"`, the rest `null`.
Re-syncs from Stripe when the local state looks out of date.

### `POST /api/billing/change-plan/`
`{"plan_id": "yearly"}`

- **More expensive plan → upgrade now:**
  `{"mode": "upgrade_now", "requested_plan_id", "requires_payment", "stripe_subscription_id", "status", "customer_id", "ephemeral_key_secret", ...}`
  (plus a client secret when a payment is needed)
- **Cheaper plan → at the end of the current period:**
  `{"mode": "downgrade_at_period_end", "pending_plan_id", "pending_change_at", "subscription_schedule_id", "current_period_end"}`
- Same plan → `{"detail": "Already on this plan.", "plan_id": "..."}`

Errors `400`: `"No subscription found."`, `"Invalid plan_id"`, `"Plan not configured."`,
`"Subscription has no items."`, `"Could not compare prices."`,
`"Missing current_period_end. Wait for webhook/status sync."`; `409` Stripe rejected; `502` Stripe error.

### `POST /api/billing/cancel/`
`{"cancel_at_period_end": true}` (default `true`; `false` cancels now)
→ `{"status", "cancel_at_period_end", "current_period_end"}`.
Already cancelled → `200 {"detail": "Subscription is already canceled.", ...}`.
`400 {"detail": "No subscription found."}`; `409` / `502` on Stripe errors.

### `POST /api/billing/resume/`
Undoes a cancel-at-period-end → `{"status", "cancel_at_period_end": false, "current_period_end"}`.
Fully cancelled → `409 {"detail": "Subscription already canceled. Subscribe again to resume.", "status": "canceled"}`.

### `POST /api/billing/portal/`
→ `{"url": "https://billing.stripe.com/..."}` (returns to `BILLING_RETURN_URL`).
`400 {"detail": "No Stripe customer found for this user."}`

### `POST /api/billing/webhook/` (Stripe only)
Checked with `STRIPE_WEBHOOK_SECRET` (`400` on a bad signature). Handles `customer.subscription.*`,
`subscription_schedule.*`, `invoice.paid`, `invoice.payment_failed`, `invoice.payment_action_required`.
Each event is stored once in `billing_stripeevent`; repeats are ignored. Answers `200`.

## Settings (names only)

`STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_API_VERSION`, `BILLING_RETURN_URL`,
`STRIPE_PRICE_ID_MONTHLY`, `STRIPE_PRICE_ID_QUARTERLY`, `STRIPE_PRICE_ID_YEARLY` → `STRIPE_PLANS`.

## Open items (Part 2 of BACKEND.md — waiting on the product spec)

- **Plans:** the paywall shows **£9.99/month** and **£29/year**; this module has monthly / quarterly / yearly. New Stripe prices are needed, and quarterly may go.
- **Stripe or in-app purchase?** For digital content Apple/Google may require in-app purchase, which needs receipt validation and store notifications (about 4–5 extra days). The biggest open decision.
- **7-day free trial** without a card — needs its own fields (a Stripe trial requires a card).
- **Entitlements** payload so the app can gate features, and switching on the commented-out gates in `careers/views.py`.
- **Referral system** (codes, credits, anti-abuse) — nothing built yet.
- Swipe limits (`usage_limits`) should follow the plan.
- `STRIPE_SECRET_KEY` is defined twice in `.env` — clean up.
