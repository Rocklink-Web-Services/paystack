# Paystack for ERPNext / Frappe

A custom Paystack payment gateway for **ERPNext v16** (Frappe Framework v16), built directly on the official `frappe/payments` framework. It plugs into the standard **Payment Request** flow, so Sales Invoices, Sales Orders, Web Forms and custom doctypes can all be paid through Paystack and reconciled automatically.

- Hosted Paystack checkout (cards, bank, M-Pesa where enabled, etc.)
- Automatic completion: a successful payment marks the Payment Request as **Paid** and creates the Payment Entry
- Server-to-server **webhook** with HMAC-SHA512 signature verification (source of truth)
- Browser **callback** for instant customer feedback
- Amount + currency are re-checked against Paystack before any document is marked paid
- Idempotent: a payment is never processed twice

Supported currencies: **NGN, GHS, ZAR, KES, USD**.

---

## 1. Install

This app depends on the Frappe **Payments** app. Install both on your bench, then install on your site.

```bash
cd /path/to/your-bench

# dependency (skip if already installed)
bench get-app payments https://github.com/frappe/payments

# this app
bench get-app paystack /path/to/paystack      # local folder, or your git URL

# install on the site
bench --site your-site.com install-app payments   # if not already installed
bench --site your-site.com install-app paystack

# apply schema
bench --site your-site.com migrate

# rebuild assets so the settings screen loads its script
bench build --app paystack
bench --site your-site.com clear-cache
```

> If you run via supervisor/production, restart after install: `bench restart`.

---

## 2. Insert your keys  ← (this is the step you asked about)

You do **not** put keys in any file. They go into the ERPNext UI:

1. Log in as a user with **System Manager** role.
2. Search the awesomebar for **Paystack Settings** and open it.
3. From the **Paystack Dashboard → Settings → API Keys & Webhooks**, copy:
   - **Public Key** → paste into *Public Key*
   - **Secret Key** → paste into *Secret Key* (stored encrypted)
4. Tick **Enabled**.
5. Click **Save**.

Use your **test** keys first — they start with `pk_test_` / `sk_test_`. Live keys start with `pk_live_` / `sk_live_`. The key itself decides test vs live mode; there is no separate toggle.

The settings screen shows your exact **Webhook URL** to copy — see the next step.

---

## 3. Configure the Paystack webhook

In the same **Paystack Dashboard → Settings → API Keys & Webhooks** page, set the **Webhook URL** to:

```
https://your-site.com/api/method/paystack.api.webhook
```

(The Paystack Settings screen prints this URL for you with your real domain filled in.)

The webhook is what guarantees an order is completed even if the customer closes the browser before being redirected back.

---

## 4. Create a Payment Gateway Account (one-time)

So ERPNext knows which ledger account to post Paystack receipts to:

1. Open **Payment Gateway Account** (New).
2. **Payment Gateway**: `Paystack` (already registered by this app on install).
3. **Payment Account**: pick the bank/cash account that receives Paystack settlements.
4. **Currency**: e.g. `KES` (must be one of the supported currencies).
5. Save.

---

## 5. Take a test payment

1. Create and **Submit** a Sales Invoice (currency = one of the supported list).
2. From the invoice: **Create → Payment Request**.
3. On the Payment Request set **Payment Gateway Account** = your Paystack account, then **Submit**.
4. Click **Pay** (or send the email link and open it). You are redirected to Paystack.
5. Pay using a [Paystack test card](https://paystack.com/docs/payments/test-payments/) (e.g. `4084 0840 8408 4081`, any future expiry, any CVV, OTP `123456`).
6. You are redirected to `/payment-success`. The **Payment Request** flips to **Paid** and a **Payment Entry** is created against the invoice.

Check **Integration Request** (search the awesomebar) to see each attempt and its status — `Queued → Authorized → Completed`, or `Failed` with the error captured.

When everything works on test keys, swap in your live keys and go live.

---

## How it works

```
Sales Invoice  ──►  Payment Request  ──►  get_payment_url()
                                            │  creates Integration Request (reference)
                                            │  POST /transaction/initialize  to Paystack
                                            ▼
                                   redirect to Paystack checkout
                                            │
                          customer pays ────┤
                                            ├─► browser callback  /api/method/paystack.api.callback
                                            └─► webhook (POST)     /api/method/paystack.api.webhook
                                                        │  verify signature (HMAC-SHA512)
                                                        ▼
                                            verify_transaction(reference)
                                                GET /transaction/verify/{ref}
                                                check amount + currency
                                                run_method("on_payment_authorized", "Completed")
                                                        ▼
                                            Payment Request → Paid, Payment Entry created
```

- **Integration Request** tracks one attempt; its name is used as the Paystack `reference`.
- **`verify_transaction`** is shared by both the callback and the webhook, is idempotent, and re-checks amount + currency straight from Paystack before trusting anything.
- All amounts are sent in the smallest subunit (×100: kobo / pesewas / cents).

---

## Uninstall

```bash
bench --site your-site.com uninstall-app paystack
```

This removes the `Paystack` Payment Gateway record. Your historical Integration Requests and Payment Entries are left untouched.

---

## Notes & limitations

- Paystack determines test vs live from the key prefix; keep test and live keys straight.
- Partial payments follow whatever the Payment Request is set to; Paystack is charged the Payment Request grand total.
- This is a self-maintained app — review the code before processing live money, and test thoroughly on test keys.
