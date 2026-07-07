"""Minimal unit tests for the mangopay addon."""

from app.addons.payments.mangopay.addon import MangopayAddon


def test_addon_identity():
    assert MangopayAddon.addon_id == "mangopay"
    assert MangopayAddon.addon_category == "payment"
