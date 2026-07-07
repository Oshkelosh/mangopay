# Mangopay (`mangopay`)

Accept payments via Mangopay.

## Overview

| | |
|---|---|
| Addon ID | `mangopay` |
| Category | payment |
| Version | 1.0.0 |
| Category guide | [../README.md](../README.md) |

Only **one** payment addon can be active at a time.

## Enable and configure

1. Install this package under `app/addons/payments/mangopay/`
2. Open **Admin → Payments → Mangopay** at `/admin/payments/mangopay`
3. Enter credentials and enable **Enable this payment processor**

## Configuration schema

| Field | Type | Description |
|-------|------|-------------|
| `client_id` | string | Mangopay client ID |
| `api_key` | secret | Mangopay API key |
| `webhook_secret` | secret | Webhook signature secret |
| `platform_wallet_id` | string | Platform wallet that receives pay-ins |
| `platform_user_id` | string | Platform user ID (pay-in author; optional) |
| `environment` | string | `sandbox` or `live` |
| `return_url` | string | Redirect after successful payment |
| `cancel_url` | string | Redirect when cancelled |

Secrets are stored in `addon_configs`, not in `.env`.

## Routes

### Public API

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/payments/mangopay/checkout` | Start checkout (optional; prefer generic order checkout) |
| POST | `/api/v1/payments/mangopay/webhook` | PSP webhook endpoint |

### Admin

| Method | Path | Description |
|--------|------|-------------|
| GET | `/admin/payments/mangopay` | Config form |
| POST | `/admin/payments/mangopay/save` | Save config |

## Core integration

- **Storefront checkout:** `POST /api/v1/orders/{order_id}/checkout` → `PaymentAddon.create_payment()` → redirect URL
- **Webhook:** `POST /api/v1/payments/mangopay/webhook` → `parse_webhook()` → core `process_payment_webhook()`
- **Amounts:** smallest currency unit (cents)

## Provider setup

Register webhook URL (replace `{PUBLIC_APP_URL}` with your public base URL):

```
{PUBLIC_APP_URL}/api/v1/payments/mangopay/webhook
```

Webhook signature header: **`x-mangopay-signature`**

1. Create a Mangopay platform account and obtain client ID + API key.
2. Configure a platform wallet to receive customer pay-ins.
3. Register the webhook URL in the Mangopay Dashboard.

## Package layout

```
mangopay/
├── README.md
├── addon.py
├── routes.py
└── templates/
```

## See also

- [Payment addon development](../README.md)
- [Oshkelosh addon guide](../../README.md)
