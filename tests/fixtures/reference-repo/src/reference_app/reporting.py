# ruff: noqa
"""Reporting fixture code with avoidable performance issues."""


def build_user_report(users: list[dict], invoices: list[dict]) -> list[dict]:
    rows = []
    for user in users:
        total = 0
        for invoice in invoices:
            if invoice["user_id"] == user["id"]:
                total += invoice["amount_cents"]
        rows.append({"user_id": user["id"], "email": user["email"], "total_cents": total})
    return rows
