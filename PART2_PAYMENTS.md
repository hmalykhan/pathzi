# Part 2 — Payments, Trial and Referrals

**For:** the project manager / mobile developer (same person supplying the store accounts and keys)
**From:** backend
**Date:** 2026-09-14
**Status:** decisions agreed, waiting on store setup and credentials before backend work can finish

This document has three parts:

1. [What was decided](#1-what-was-decided)
2. [**What we need from you**](#2-what-we-need-from-you) ← the action list
3. [What the backend will build, and what the app must do](#3-what-the-backend-will-build)

---

## 1. What was decided

| Decision | Detail |
|---|---|
| **Payments move to Apple + Google in-app purchase** | Stripe is no longer the payment route for the app. Same features, different provider. |
| **All payment happens inside the app** | The store's own payment sheet appears in the app. No web page, no browser, no checkout link. The backend never sees card details. |
| **Free trial: 7 days** | Starts at sign-up, no card needed. Set by the server, so reinstalling the app doesn't reset it. |
| **Referrals: email only** | No public or shareable code. Every invitation is emailed, carries **its own unique code**, works **once**, and is tied to the invited email address. |
| **Referrals are unlimited** | A user can invite as many people as they like. No cap. |
| **A referral counts when the invited person signs up using the code** | New accounts only. Signing in to an existing account earns nothing. |
| **Each new account can be credited once, to one referrer** | And nobody can use their own code. |
| **Rewards** | Invitee +14 days, referrer +7 days (please confirm — see [open questions](#5-open-questions)). |
| **Swipe limits: dropped** | No swipe limit at all. Free use is the 7-day trial, then a subscription. |
| **Deep links: later** | For now the emailed link opens the app if it's installed, otherwise the person types the code from the email at sign-up. |

**Free days are ours, not the stores'.** The trial and referral days are access we grant in our own database, so Apple and Google are not involved in them. The stores only handle **paid** subscriptions.

---

## 2. What we need from you

### 2.1 Apple — App Store Connect

| # | Item | Where to find / do it |
|---|---|---|
| 1 | **Bundle ID** of the app | App Store Connect → your app → App Information |
| 2 | **Subscription products created** | App Store Connect → your app → Subscriptions: create a subscription group, then one product per plan (see [2.3](#23-the-plans-to-create)) |
| 3 | **In-App Purchase key** — the `.p8` file | Users and Access → **Integrations → In-App Purchase** → generate a key. The file downloads **once** as `SubscriptionKey_XXXXXXX.p8` — it cannot be downloaded again. |
| 4 | **Key ID** | Shown next to the key you created (it's also in the file name) |
| 5 | **Issuer ID** | On the same Integrations → In-App Purchase page |
| 6 | **Server notification URL set to ours** | Your app → App Information → **App Store Server Notifications** → Production Server URL → choose **Version 2**. I'll give you the URL once Phase 2 starts. Apple allows only one URL, so tell me if something else already uses it. |
| 7 | **Sandbox tester account** | Users and Access → Sandbox Testers. Needed to test buying without real money. |
| 8 | **Banking and tax forms completed** | Business → Agreements, Tax and Banking. **Products can't be sold until these are approved — this usually takes the longest, so start it first.** |

### 2.2 Google — Play Console + Google Cloud

| # | Item | Where to find / do it |
|---|---|---|
| 1 | **Package name** of the app | e.g. `com.pathzi.app` |
| 2 | **Subscription products created** | Play Console → Monetise → Subscriptions: one subscription per plan, each with a base plan (see [2.3](#23-the-plans-to-create)) |
| 3 | **Service account JSON key** | Google Cloud Console → the project linked to Play → create a service account → create a JSON key. Send me the JSON file. |
| 4 | **That service account given access in Play Console** | Play Console → Users and permissions → invite the service account email → permissions: **View financial data** and **Manage orders and subscriptions** |
| 5 | **A Pub/Sub topic** (for change notifications) | Google Cloud Console → Pub/Sub → create a topic. Then in the topic's permissions, add `google-play-developer-notifications@system.gserviceaccount.com` with the role **Pub/Sub Publisher**. |
| 6 | **The topic name entered in Play Console** | Play Console → Monetise → Monetisation setup → Real-time developer notifications → paste the topic name |
| 7 | **Licence tester account** | Play Console → Setup → Licence testing. Needed to test buying without real money. |
| 8 | **Payments profile / banking complete** | Play Console → Setup → Payments profile. **Same as Apple — start early.** |

### 2.3 The plans to create

Create the **same two plans in both stores**, and send me the exact product IDs you used.

| Plan | Price shown in the design | Suggested product ID |
|---|---|---|
| Monthly | £9.99 / month | `pathzi_monthly` |
| Yearly | £29 / year | `pathzi_yearly` |

Notes:
- Stores use fixed price points, so the final price may be a penny different (for example £28.99). Tell me the exact prices chosen.
- The current backend has monthly / quarterly / yearly from the Stripe setup. **Quarterly is dropped** unless you want it kept.
- **Don't add a free trial inside the store products.** Our 7-day trial is handled by us, and having both would give some users 14 days.

### 2.4 How to send credentials — please don't email them

The `.p8` file and the service account JSON are **secrets**: anyone holding them can read your sales data and subscription records. Please send them through a password manager (1Password, Bitwarden) or an encrypted transfer, not plain email or WhatsApp. They will be stored in the server's `.env`, never in the app or in git.

### 2.5 Checklist to send back

```
Apple
[ ] Bundle ID:
[ ] Product IDs created:
[ ] SubscriptionKey_XXXX.p8 file (sent securely)
[ ] Key ID:
[ ] Issuer ID:
[ ] Sandbox tester email:
[ ] Banking/tax status:
[ ] Server notification URL set (after we send it):

Google
[ ] Package name:
[ ] Product IDs created:
[ ] Service account JSON (sent securely)
[ ] Service account granted Play permissions: yes/no
[ ] Pub/Sub topic name:
[ ] Publisher role granted to google-play-developer-notifications@system.gserviceaccount.com: yes/no
[ ] Licence tester email:
[ ] Payments profile status:
```

---

## 3. What the backend will build

### 3.1 Buying a subscription

```
1. App shows the paywall with prices read from the store
2. User taps Subscribe -> the store's payment sheet opens inside the app
3. Store charges the user and gives the app a receipt
4. App sends the receipt to us:  POST /api/billing/iap/verify/
5. We check it directly with Apple/Google: is it real, what was bought, when does it expire?
6. We save it and unlock access
```

### 3.2 Keeping it up to date, automatically

Apple and Google send us a message whenever something changes — renewed, cancelled, refunded, payment failed, grace period. We listen and update the user's access. This works even if the user never opens the app.

```
POST /api/billing/apple/notifications/    <- Apple App Store Server Notifications V2
POST /api/billing/google/notifications/   <- Google Real-Time Developer Notifications
```

Their notification only says *something changed*, so we then ask the store for the full state before updating anything.

### 3.3 One place that decides access

Everything — the trial, referral days, an Apple subscription, a Google subscription — feeds one answer the app reads:

```
GET /api/billing/status/   (or on the profile)
{
  "has_access": true,
  "source": "trial",                  // trial | referral | apple | google
  "access_until": "2026-09-21T10:00:00Z",
  "days_remaining": 7,
  "trial_active": true,
  "plan": null,                        // "pathzi_monthly" once subscribed
  "auto_renewing": false,
  "manage_url": "..."                  // opens the store's subscription screen
}
```

### 3.4 Referrals

```
POST /me/referral/invite            { "email": "sara@example.com" }   -> we email a unique code
GET  /me/referral                   -> invites sent, who joined, days earned, days left
POST /accounts/signup/              { ..., "referral_code": "PTH-K3M9QZ" }  -> credits both sides
POST /me/referral/credits/{id}/ack/ -> so "You've earned another week" shows once
```

Rules enforced on the server: one use per code, code tied to the invited email, 30-day expiry, no self-referral, one referrer per new account, unlimited invites.

### 3.5 What the app needs to do

| # | |
|---|---|
| 1 | **StoreKit 2** (iOS) and **Play Billing Library 8 or newer** (Android). Google requires version 8+ for new app updates from 31 August 2026. |
| 2 | Send the receipt to `POST /api/billing/iap/verify/` after every purchase **and** on app start (so a purchase is never lost). |
| 3 | Add a **Restore purchases** button (Apple requires it) — it sends the same receipt. |
| 4 | **Manage subscription** opens the store's own screen; cancelling and changing plan cannot happen inside the app (a store rule, not ours). |
| 5 | Send `referral_code` with sign-up when the user was invited. |
| 6 | Stop calling the old Stripe endpoints `/api/billing/subscribe/` and `/api/billing/portal/`. |
| 7 | Show trial and referral days from `has_access` / `access_until`, not from a hard-coded 7. |

---

## 4. Plan and timing

| Phase | What | Days | Needs from you |
|---|---|---|---|
| 0 | Store setup, banking, credentials | — | **Section 2** |
| 1 | 7-day trial + the access layer | 2 | nothing — **can start now** |
| 2 | Apple: verify receipts, notifications, sandbox testing | 2 | Apple items |
| 3 | Google: verify receipts, notifications, sandbox testing | 2 | Google items |
| 4 | Restore on a new phone, refunds, grace periods, duplicate-account protection | 1 | — |
| 5 | Referrals: invites, codes, credits, the screen's API | 3 | — |
| 6 | Full testing and handover notes for the app | 1 | test accounts |
| | **Total** | **11 days** | |

About **two and a half weeks** of backend work for one developer. **The store banking and tax approvals often take longer than the code, so please start Section 2 now** — Phase 1 runs in parallel and needs nothing from you.

---

## 5. Open questions

| # | Question | Why it matters |
|---|---|---|
| 1 | **Reward amounts** — invitee +14 days and referrer +7 days, as in the original design? | Fixed in the code and in the invitation email wording |
| 2 | **Exact prices** after store price points (e.g. £28.99 instead of £29)? | Must match the store products exactly |
| 3 | **Keep the quarterly plan** or drop it? | It exists from the Stripe setup |
| 4 | **Wording of the invitation email** — who writes it? | We send it from the backend |
| 5 | **What happens when the trial ends and the user hasn't subscribed** — read-only app, or paywall on open? | Decides what the access layer returns |
| 6 | Is there an existing App Store server notification URL in use? | Apple allows only one |

---

## 6. Also worth knowing

- **Money:** Apple and Google take 15–30% of each payment, against roughly 2–3% with Stripe, and they pay out monthly. That was accepted as the cost of shipping in-app payments.
- **The old Stripe code stays in the repo** but is no longer the payment path. 376 Stripe test-mode events and 53 billing records exist in the database from earlier testing; they'll be left untouched and simply ignored.
- **The keys currently in the server config are Stripe *test* keys**, so no real money has moved through it.
