"""
Mangopay payment integration.

Collects card pay-ins and handles payment webhooks.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal

import httpx
from fastapi import APIRouter
from pydantic import BaseModel, Field, SecretStr

from app.addons.payments.base import PaymentAddon
from app.addons.payments.helpers import effective_redirect_url, extract_order_id, mock_checkout
from schemas.payment import PaymentWebhookOutcome
from app.addons.log import info, warning
from app.addons.config_serialization import dump_addon_config

MangopayEnvironment = Literal["sandbox", "live"]

_API_BASES: dict[MangopayEnvironment, str] = {
    "sandbox": "https://api.sandbox.mangopay.com",
    "live": "https://api.mangopay.com",
}


class MangopayConfig(BaseModel):
    client_id: str = Field(default=..., description="Mangopay client ID")
    api_key: SecretStr = Field(default=..., description="Mangopay API key")
    webhook_secret: SecretStr = Field(
        default=...,
        description="Webhook signature secret",
    )
    platform_wallet_id: str = Field(
        default=...,
        description="Platform wallet that receives pay-ins",
    )
    platform_user_id: str = Field(
        default="",
        description="Platform user ID used as pay-in author",
    )
    environment: MangopayEnvironment = Field(default="sandbox")
    return_url: str = Field(
        default="",
        description="Optional override for return redirect (leave blank to use Site URL)",
    )
    cancel_url: str = Field(
        default="",
        description="Optional override for cancel redirect (leave blank to use Site URL)",
    )

    @classmethod
    def config_model(cls):
        return cls


class MangopayAddon(PaymentAddon):
    addon_id: str = "mangopay"
    addon_name: str = "Mangopay"
    addon_description: str = "Accept payments via Mangopay."
    addon_category: str = "payment"
    version: str = "1.0.0"
    is_enabled: bool = False

    _config: Dict[str, Any] | None = None
    _client_id: str | None = None
    _api_key: str | None = None
    _webhook_secret: str | None = None
    _platform_wallet_id: str = ""
    _platform_user_id: str = ""
    _environment: MangopayEnvironment = "sandbox"
    _return_url: str = ""
    _cancel_url: str = ""
    _api_base: str = _API_BASES["sandbox"]

    @classmethod
    def config_schema(cls):
        return MangopayConfig

    async def initialize(self, config: dict) -> None:
        validated = self.config_schema()(**config)
        self._config = dump_addon_config(validated)
        self._client_id = validated.client_id
        self._api_key = validated.api_key.get_secret_value()
        self._webhook_secret = validated.webhook_secret.get_secret_value()
        self._platform_wallet_id = validated.platform_wallet_id
        self._platform_user_id = validated.platform_user_id
        self._environment = validated.environment
        self._return_url = validated.return_url
        self._cancel_url = validated.cancel_url
        self._api_base = _API_BASES[self._environment]
        self.is_enabled = True
        info("Mangopay", "Initialized (environment={})", self._environment)

    async def validate_config(self, config: dict) -> None:
        from app.core.exceptions import ValidationError

        validated = self.config_schema()(**config)
        api_key = validated.api_key.get_secret_value()
        if not api_key:
            return
        api_base = _API_BASES[validated.environment]
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{api_base}/v2.01/{validated.client_id}",
                auth=(validated.client_id, api_key),
            )
        if resp.status_code == 401:
            raise ValidationError(message="Invalid API key — check your credentials")
        if resp.status_code == 403:
            raise ValidationError(
                message="API key is valid but missing required permissions: clients:read"
            )
        if resp.status_code >= 400:
            raise ValidationError(message="Mangopay rejected the API key")

    async def shutdown(self) -> None:
        self._client_id = None
        self._api_key = None
        self._webhook_secret = None
        self.is_enabled = False

    def _api_root(self) -> str:
        return f"{self._api_base}/v2.01/{self._client_id}"

    async def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self._client_id or not self._api_key:
            raise RuntimeError("Mangopay credentials not configured")

        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.request(
                method,
                f"{self._api_root()}{path}",
                auth=(self._client_id, self._api_key),
                json=body,
            )
            resp.raise_for_status()
            return resp.json()

    async def create_payment(
        self,
        amount: int,
        currency: str,
        order_id: str,
        customer_email: str,
        *,
        return_url: str | None = None,
        cancel_url: str | None = None,
    ) -> Dict[str, Any]:
        if not self._client_id or not self._api_key or not self._platform_wallet_id:
            return mock_checkout("mangopay", order_id, amount, currency)

        body: dict[str, Any] = {
            "Tag": order_id,
            "AuthorId": self._platform_user_id or self._platform_wallet_id,
            "CreditedWalletId": self._platform_wallet_id,
            "DebitedFunds": {"Currency": currency.upper(), "Amount": amount},
            "Fees": {"Currency": currency.upper(), "Amount": 0},
            "CardType": "CB_VISA_MASTERCARD",
            "SecureModeReturnURL": effective_redirect_url(
                self._return_url, fallback=return_url or ""
            ),
            "SecureMode": "DEFAULT",
            "Metadata": {"order_id": order_id},
        }
        if customer_email:
            body["StatementDescriptor"] = f"Order {order_id}"

        try:
            data = await self._request("POST", "/payins/card/web", body=body)
            payment_id = data.get("Id", "")
            return {
                "success": True,
                "payment_id": payment_id,
                "session_id": payment_id,
                "url": data.get("RedirectURL", ""),
                "order_id": order_id,
            }
        except Exception as exc:
            warning("Mangopay", "create_payment error: {}", exc)
            return mock_checkout("mangopay", order_id, amount, currency)

    async def confirm_payment(self, payment_id: str) -> Dict[str, Any]:
        status = await self.get_payment_status(payment_id)
        if status.get("status") == "error":
            return {"success": False, "error": status.get("detail", "Unknown error")}
        return {
            "success": True,
            "payment_id": payment_id,
            "status": status.get("status", "unknown"),
            "amount": status.get("amount", 0),
        }

    async def refund_payment(self, payment_id: str, amount: int) -> Dict[str, Any]:
        if not self._client_id or not self._api_key:
            return {"success": False, "error": "Mangopay credentials not configured"}

        body = {
            "AuthorId": self._platform_user_id or self._platform_wallet_id,
            "DebitedFunds": {
                "Currency": "EUR",
                "Amount": amount,
            },
        }
        try:
            data = await self._request(
                "POST",
                f"/payins/{payment_id}/refunds",
                body=body,
            )
            return {
                "success": True,
                "refund_id": data.get("Id", ""),
                "amount": amount,
                "status": data.get("Status", "SUCCEEDED"),
            }
        except Exception as exc:
            warning("Mangopay", "refund_payment({}) error: {}", payment_id, exc)
            return {"success": False, "error": str(exc)}

    async def get_payment_status(self, payment_id: str) -> Dict[str, Any]:
        if not self._client_id or not self._api_key:
            return {"payment_id": payment_id, "status": "error", "detail": "Not configured"}

        try:
            data = await self._request("GET", f"/payins/{payment_id}")
            debited = data.get("DebitedFunds", {})
            return {
                "payment_id": payment_id,
                "status": data.get("Status", "unknown"),
                "amount": debited.get("Amount", 0),
                "currency": debited.get("Currency", "eur"),
            }
        except Exception as exc:
            warning("Mangopay", "get_payment_status({}) error: {}", payment_id, exc)
            return {"payment_id": payment_id, "status": "error", "detail": str(exc)}

    def webhook_signature_header(self) -> str:
        return "x-mangopay-signature"

    async def parse_webhook(
        self, payload: Dict[str, Any], signature: str
    ) -> PaymentWebhookOutcome:
        try:
            event_type = payload.get("EventType", payload.get("type", ""))
            event_data = payload.get("Ressource", payload.get("data", payload))
            event_id = str(payload.get("Id", payload.get("id", "")))
            info("Mangopay", "Webhook received: {}", event_type)

            if event_type in ("PAYIN_NORMAL_SUCCEEDED", "PAYIN_NORMAL_CREATED"):
                metadata = event_data.get("Metadata", event_data.get("metadata", {}))
                order_id = extract_order_id(metadata)
                payment_id = event_data.get("Id") or event_data.get("id")
                return PaymentWebhookOutcome(
                    handled=True,
                    event_id=event_id,
                    event_type=event_type,
                    mark_paid=order_id is not None and event_type == "PAYIN_NORMAL_SUCCEEDED",
                    order_id=order_id,
                    payment_id=str(payment_id) if payment_id else None,
                )

            return PaymentWebhookOutcome(
                handled=True,
                event_id=event_id,
                event_type=event_type,
            )
        except Exception as exc:
            warning("Mangopay", "parse_webhook error: {}", exc)
            return PaymentWebhookOutcome(handled=False, error=str(exc))

    def get_routers(self) -> List[APIRouter]:
        from app.addons.payments.mangopay.routes import api_router

        return [api_router]

    def get_admin_routes(self) -> List[APIRouter]:
        from app.addons.payments.mangopay.routes import admin_router

        return [admin_router]

    def get_admin_templates(self) -> str:
        from pathlib import Path

        return str(Path(__file__).resolve().parent / "templates")

    def get_admin_static(self) -> str:
        from pathlib import Path

        return str(Path(__file__).resolve().parent / "static")
