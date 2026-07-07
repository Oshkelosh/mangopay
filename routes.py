"""Mangopay addon routes — thin delegates to shared payment route factory."""

from __future__ import annotations

from typing import Any

from app.addons.payments.shared_routes import build_payment_routers


def _parse_mangopay_config_form(form: Any) -> tuple[dict[str, Any], bool]:
    return (
        {
            "client_id": form.get("client_id", ""),
            "api_key": form.get("api_key", ""),
            "webhook_secret": form.get("webhook_secret", ""),
            "platform_wallet_id": form.get("platform_wallet_id", ""),
            "platform_user_id": form.get("platform_user_id", ""),
            "environment": form.get("environment", "sandbox"),
            "return_url": form.get("return_url", ""),
            "cancel_url": form.get("cancel_url", ""),
        },
        form.get("is_enabled") == "on",
    )


admin_router, api_router, jinja_env = build_payment_routers(
    "mangopay",
    template_name="mangopay_config.html",
    page_title="Mangopay Settings",
    secret_keys=("api_key", "webhook_secret"),
    signature_header="x-mangopay-signature",
    parse_config_form=_parse_mangopay_config_form,
)
