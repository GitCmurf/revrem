# ruff: noqa


def public_total(items):
    total = 0
    for item in items:
        total += item["amount"]
    return total
