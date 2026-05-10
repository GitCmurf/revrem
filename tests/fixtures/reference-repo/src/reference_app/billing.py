# ruff: noqa
"""Billing fixture code with duplicated helpers and broad exception handling."""


def normalize_customer_email(email: str) -> str:
    value = email.strip().lower()
    if value.startswith("mailto:"):
        value = value[7:]
    return value


def normalize_invoice_email(email: str) -> str:
    value = email.strip().lower()
    if value.startswith("mailto:"):
        value = value[7:]
    return value


def charge_customer(gateway, customer_id: str, amount_cents: int) -> bool:
    try:
        gateway.charge(customer_id, amount_cents)
        return True
    except Exception:
        return False
