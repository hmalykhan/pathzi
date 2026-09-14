# Part 2 — Payments, Trial and Referrals

**For:** the project manager / mobile developer
**From:** backend
**Version:** 2 — 2026-09-14 (replaces version 1 of the same day)
**Status:** all decisions settled. Backend Phase 1 starting now; the rest needs the store setup in [section 3](#3-what-we-need-from-you).

**Version 2 answers the app-side review and changes several things — please read [section 1](#1-what-changed-since-version-1) before starting any setup.**

---

## Contents

1. [What changed since version 1](#1-what-changed-since-version-1)
2. [The agreed design](#2-the-agreed-design)
3. [**What we need from you**](#3-what-we-need-from-you)
4. [How a purchase works](#4-how-a-purchase-works)
5. [The API the app will use](#5-the-api-the-app-will-use)
6. [What happens when the trial ends](#6-what-happens-when-the-trial-ends)
7. [What the app must do](#7-what-the-app-must-do)
8. [Plan and timing](#8-plan-and-timing)
9. [Still open](#9-still-open)

---

## 1. What changed since version 1

| Change | Detail |
|---|---|
| **RevenueCat is approved** | It handles receipt checking, store notifications, restores, refunds and grace periods for both stores. Saves about 3.5 days and removes the most bug-prone work. |
| **Credentials now go to RevenueCat, not our server** | The Apple key and Google service account are entered in **RevenueCat's dashboard**. Our server only needs RevenueCat's keys. |
| **Store notification URLs point at RevenueCat** | Not at us. RevenueCat's docs give the exact URLs. |
| **No landing page, no deep links for v1** | Messages carry the **code as text** plus store links. Nothing to build on `pathzi.com`. |
| **Referral codes work differently** | No permanent code. **Every share generates a new unique code**, and the **first account to use it expires it**. |
| **No email matching, no verification delay** | A code can be used by whoever gets it, and the referrer is credited immediately. |
| **Rewards fixed** | Invitee **+7 bonus days** (14 with the trial). Referrer **+7 days**. |
| **After the trial: a free tier, not a locked app** | The home screen shows **only careers the user already explored**. |
| **Added, from your review** | In-app account deletion, an account UUID for purchase linking, trial + `referral_code` on all three sign-up paths, `is_new_user` from Google/Apple, sandbox notification URL, a trial for accounts that already exist. |
| **Quarterly plan** | Dropped. |

### Answers to your confirmation list

| Your item | Answer |
|---|---|
| Personal share code plus email invites | ✅ Both, but **every share makes a new single-use code** — no permanent code |
| No strict email match | ✅ Agreed |
| Trial + `referral_code` on Google/Apple sign-up, `is_new_user` | ✅ All three paths. Both endpoints already work out internally whether they created the account, so this is a small change |
| `GET /me/referral` shape | ✅ As you specified, plus a "generate code" call |
| Temporary `/join` landing page | ❌ Dropped — code as text instead |
| Extra access fields + trial for existing accounts | ✅ Agreed |
| Access layer can support a free tier later | ✅ Built that way from the start, and the free tier is now decided |
| Banking referral and trial days | ✅ Referral days are banked. Trial days need no banking — see [4.3](#43-buying-during-the-trial) |
| Account UUID for purchase linking | ✅ Agreed |
| Verify endpoint shape | ⚠️ Simpler with RevenueCat — see [5.4](#54-after-a-purchase) |
| RevenueCat | ✅ Yes |

---

## 2. The agreed design

| | |
|---|---|
| **Payments** | Apple + Google in-app purchase, through RevenueCat. Stripe is retired. |
| **Where payment happens** | Inside the app, on the store's own payment sheet. No web page, no card data anywhere near us. |
| **Trial** | 7 days, set by the server at sign-up, no card. Reinstalling doesn't reset it. |
| **After the trial** | Free tier: only the user's already-explored careers on the home screen. |
| **Referrals** | Every share creates a new unique code. Single use — first account to use it consumes it. 30-day expiry. Unlimited codes per user. Can't use your own. One referrer per new account. New accounts only. |
| **Rewards** | Invitee +7 bonus days (14 total with the trial); referrer +7 days. |
| **Sharing** | Email invitations sent by the backend, or the user copies a code and sends it however they like. |
| **Swipe limits** | Dropped entirely. The 5-card guest preview stays in the app and needs no API. |

**Free days are ours.** The trial and referral days live in our database — the stores know nothing about them. The stores only handle paid subscriptions.

---

## 3. What we need from you

### 3.1 RevenueCat

| # | Item | Where |
|---|---|---|
| 1 | **RevenueCat account + a project for Pathzi** | revenuecat.com |
| 2 | **Public SDK keys** (one for iOS, one for Android) | Project settings → API keys. The app uses these. |
| 3 | **Secret API key** | Same page. Our backend uses this to double-check subscriptions. |
| 4 | **Webhook set to our URL + a shared secret** | Integrations → Webhooks. I'll send the URL when Phase 2 starts. |
| 5 | **Entitlement named `premium`** with both products attached | Entitlements section |
| 6 | **Apple + Google credentials entered into RevenueCat** | See 3.2 and 3.3 — the files go **into RevenueCat**, not to us |

### 3.2 Apple — App Store Connect

| # | Item | Where |
|---|---|---|
| 1 | **Bundle ID confirmed** (`hello.pathzi.co.uk` vs App Store Connect) | It can't change after products are created |
| 2 | **Subscription products** `pathzi_monthly`, `pathzi_yearly` | Your app → Subscriptions (one group, two products) |
| 3 | **In-App Purchase key** (`SubscriptionKey_XXXX.p8`) + **Key ID** + **Issuer ID** | Users and Access → Integrations → In-App Purchase. Downloads once. **Upload into RevenueCat.** |
| 4 | **App Store Server Notifications → RevenueCat's URL**, Version 2, **production *and* sandbox** | Your app → App Information |
| 5 | **Sandbox tester account** | Users and Access → Sandbox Testers |
| 6 | **Banking and tax forms approved** | Business → Agreements, Tax and Banking. **Start this first — it takes the longest.** |

### 3.3 Google — Play Console + Google Cloud

| # | Item | Where |
|---|---|---|
| 1 | **Package name** (`com.pathzi.app`) | |
| 2 | **Subscription products** `pathzi_monthly`, `pathzi_yearly` with base plans | Play Console → Monetise → Subscriptions |
| 3 | **Service account JSON key** | Google Cloud Console → service account → JSON key. **Upload into RevenueCat.** |
| 4 | **That service account given Play access** | Play Console → Users and permissions → **View financial data** + **Manage orders and subscriptions** |
| 5 | **Pub/Sub topic for notifications** — RevenueCat's docs give the topic to use | Play Console → Monetisation setup → Real-time developer notifications |
| 6 | **Licence tester account** | Play Console → Setup → Licence testing |
| 7 | **Payments profile complete** | Play Console → Setup. **Start early.** |

### 3.4 Prices

Set the same two plans in both stores and send the exact product IDs and final prices. The app reads prices from the store, so the backend doesn't hard-code them.

| Plan | Design price | Product ID |
|---|---|---|
| Monthly | £9.99 / month | `pathzi_monthly` |
| Yearly | £29 / year | `pathzi_yearly` |

**Don't add a free trial inside the store products** — ours is server-side, and both together would give 14 days.

### 3.5 Sending secrets

The `.p8` file and the service account JSON give access to your sales data. Send them through a password manager or encrypted transfer, never plain email or WhatsApp. Most go into RevenueCat; only RevenueCat's own keys reach our server config.

### 3.6 Checklist to send back

```
RevenueCat
[ ] Project created
[ ] iOS public SDK key:
[ ] Android public SDK key:
[ ] Secret API key (sent securely):
[ ] Entitlement "premium" created with both products:
[ ] Webhook URL set (after we send it) + shared secret:

Apple
[ ] Bundle ID confirmed:
[ ] Products created:
[ ] .p8 + Key ID + Issuer ID uploaded to RevenueCat:
[ ] Notification URLs set (production + sandbox):
[ ] Sandbox tester:
[ ] Banking/tax status:

Google
[ ] Package name:
[ ] Products created:
[ ] Service account JSON uploaded to RevenueCat:
[ ] Play permissions granted:
[ ] Pub/Sub notifications configured:
[ ] Licence tester:
[ ] Payments profile status:
```

---

## 4. How a purchase works

### 4.1 Buying

```
1. App shows the paywall, prices read from the store
2. User taps Subscribe -> the store's payment sheet opens inside the app
3. Apple/Google charge the user
4. RevenueCat checks the purchase with the store
5. RevenueCat tells our backend: "this user has premium until <date>"
6. Our backend updates the user's access
```

The app does **not** send us receipts — RevenueCat handles that. The app only has to be logged in to RevenueCat as the right user (see [5.4](#54-after-a-purchase)).

### 4.2 Afterwards

RevenueCat tells us about renewals, cancellations, refunds, billing problems and grace periods. If a message is ever missed, our backend can ask RevenueCat directly and correct itself.

### 4.3 Buying during the trial

Access is always **the later of** the trial end and the subscription end, so buying on day 3 loses nothing and no banking is needed.

**Referral days earned while already subscribed** are different — they're banked (`banked_referral_days`) and applied when the subscription ends without renewing.

---

## 5. The API the app will use

### 5.1 Access — the one question that matters

```
GET /api/billing/status/
{
  "has_access": true,
  "source": "trial",                  // trial | referral | subscription | none
  "access_until": "2026-09-21T10:00:00Z",
  "days_remaining": 7,
  "trial_active": true,
  "trial_days": 7,
  "plan": null,                       // "pathzi_monthly" | "pathzi_yearly"
  "store": null,                      // "apple" | "google"
  "auto_renewing": false,
  "banked_referral_days": 0,
  "features": ["recommendations", "routes", "reports", "search"],
  "account_uuid": "7f3c…",            // used when buying (see 5.4)
  "manage_url": "…"                   // opens the store's subscription screen
}
```

The same object is included on `GET /accounts/user_profile/`, so the app doesn't need a second call at start-up.

### 5.2 Referrals

```
POST /me/referral/codes/            -> { "code": "PTH-9QK2TM", "expires_at": "…" }   // new code per share
POST /me/referral/invite            { "email": "sara@example.com" }                  // we email a new code
GET  /me/referral                   -> codes and invites with status, friends joined, days earned, unseen credits
POST /me/referral/credits/{id}/ack/                                                  // popup shown once
```

`GET /me/referral` returns, per your review: `friends_joined`, `days_earned`, the invite list with `pending | joined | expired`, and `unseen_credits` carrying the real `days_awarded` from the ledger.

### 5.3 Sign-up

All three paths accept `referral_code` and start the 7-day trial:

```
POST /accounts/signup/        { …, "referral_code": "PTH-9QK2TM" }
POST /accounts/auth/google/   { "id_token": "…", "referral_code": "…" }   -> also returns "is_new_user"
POST /accounts/auth/apple/    { "identity_token": "…", "referral_code": "…" } -> also returns "is_new_user"
```

A code is only applied when the call actually creates a new account.

### 5.4 After a purchase

The app **logs into RevenueCat using `account_uuid`** (from 5.1) as the RevenueCat user ID, and passes it to the store as `appAccountToken` (iOS) / `obfuscatedAccountId` (Android). That's what ties a purchase to the right Pathzi account and stops one subscription unlocking two accounts.

There's a short gap between paying and our webhook arriving. So:

```
POST /api/billing/refresh/    -> asks RevenueCat now and returns the same object as 5.1
```

Call it right after a purchase. The app may also unlock immediately from the purchase result and let this confirm it.

### 5.5 Account deletion (Apple requirement)

```
DELETE /accounts/me/
```
If the account still has an active store subscription, the response says so, so the app can tell the user to cancel in the store — deleting the account does not stop Apple or Google billing them.

---

## 6. What happens when the trial ends

Not a locked app — a **limited free tier**:

| Still works | Locked |
|---|---|
| Careers the user already explored (the home screen) | New recommendations |
| Their saved careers and saved pathways | Courses / jobs / apprenticeships for a career |
| Their progress screen | Search and filter |

This is enforced **on the server**, so an edited app can't unlock it, and the `features` list tells the app what to grey out.

⚠️ **Please confirm the locked column** — particularly whether saved pathways and route lists should stay open.

---

## 7. What the app must do

| # | |
|---|---|
| 1 | Buy through **RevenueCat's SDK** (StoreKit 2 / Play Billing 8+ underneath) |
| 2 | **Log into RevenueCat with `account_uuid`** and pass it to the store as `appAccountToken` / `obfuscatedAccountId` |
| 3 | **Ask our backend for access** (`/api/billing/status/`), not RevenueCat — trial and referral days only exist with us |
| 4 | Call `POST /api/billing/refresh/` right after a purchase |
| 5 | Add a **Restore purchases** button (Apple requires it) |
| 6 | **Manage subscription** opens the store's own screen |
| 7 | Add a **referral code field** to sign-up, and send `referral_code` on all three paths |
| 8 | Referral screen: a **generate-code action per share**, the invite list, no "up to 5" limit |
| 9 | Show trial and referral days from the API, never a hard-coded 7 |
| 10 | Add **in-app account deletion** |
| 11 | Remove the old swipe constants and dead billing code |

---

## 8. Plan and timing

| Phase | What | Days | Needs from you |
|---|---|---|---|
| 1 | Trial, access layer with `features`, account UUID, `is_new_user`, trial for existing accounts | 3 | nothing — **starting now** |
| 2 | RevenueCat: webhook, entitlement sync, refresh endpoint, sandbox testing | 2 | RevenueCat + store setup |
| 3 | Purchase linking and duplicate-account protection, refunds, grace periods | 0.5 | test accounts |
| 4 | Referrals: codes, email invites, ledger, credits, the screen's API, unsubscribe + 30-day cleanup | 3.5 | email wording |
| 5 | Account deletion | 1 | — |
| 6 | Testing, migrations, handover notes | 1 | — |
| | **Total** | **11 days** | |

**Please start section 3 now.** Banking and tax approval usually takes longer than the code, and Phase 2 can't be tested without it.

---

## 9. Still open

| # | Question |
|---|---|
| 1 | **Confirm the locked list** in [section 6](#6-what-happens-when-the-trial-ends) |
| 2 | **Invitation email wording** — placeholder text is in use for now (below); send the real copy when ready |
| 3 | **Final store prices** once the price points are chosen |

### Placeholder invitation email

To be replaced by the PM. Placeholders in `{{ }}`:

```
Subject: {{ inviter_name }} gave you 14 days of Pathzi

Hi,

{{ inviter_name }} thinks Pathzi could help you find the right career.

Your code:  {{ code }}

1. Install Pathzi:  iOS {{ app_store_url }}   Android {{ play_store_url }}
2. Enter the code when you sign up
3. You get 14 days free — 7 day trial plus 7 bonus days

This code works once and expires on {{ expires_at }}.

Don't want these emails? {{ unsubscribe_url }}
```

---

## 10. Also worth knowing

- **Money:** Apple and Google take 15–30% of each payment and pay out monthly. RevenueCat is free up to about $2,500/month of tracked revenue, then roughly 1%.
- **Data:** RevenueCat processes customer purchase data, so it needs a line in the privacy policy and a processor agreement. Some users are under 18, which is worth a deliberate check.
- **Invite emails:** an unsubscribe link is included, and invited email addresses are deleted after the 30-day code lifetime.
- **Stripe:** the code stays in the repo but is no longer the payment path. The 376 test-mode events and 53 billing records in the database are historic test data and are left untouched. No real money ever moved through it — the keys were test keys.
