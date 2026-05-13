from __future__ import annotations

from decimal import Decimal

import pytest

from code_review_loop import budgets


def test_wall_budget_warns_before_hard_ceiling():
    config = budgets.BudgetConfig(max_wall_seconds=10, soft_warn_fraction=0.8)
    state = budgets.BudgetState(started_at_monotonic=100)

    due, elapsed = budgets.wall_warning_due(config, state, now=108)

    assert due is True
    assert elapsed == 8


def test_wall_budget_exceeded_reports_limit_and_actual():
    config = budgets.BudgetConfig(max_wall_seconds=10)
    state = budgets.BudgetState(started_at_monotonic=100)

    with pytest.raises(budgets.BudgetExceeded) as excinfo:
        budgets.check_wall_budget(config, state, now=111)

    assert excinfo.value.ceiling == "wall"
    assert excinfo.value.limit == "10"
    assert excinfo.value.actual == "11"


def test_parse_usd_preserves_decimal_money():
    assert budgets.parse_usd("1.2300") == Decimal("1.2300")


def test_validate_config_rejects_invalid_values():
    with pytest.raises(ValueError, match="--soft-warn-fraction"):
        budgets.validate_config(budgets.BudgetConfig(soft_warn_fraction=1.5))


def test_record_charge_enforces_token_ceiling():
    state = budgets.BudgetState(started_at_monotonic=0)
    config = budgets.BudgetConfig(max_tokens=10)

    with pytest.raises(budgets.BudgetExceeded) as excinfo:
        budgets.record_charge(config, state, tokens=10)

    assert excinfo.value.ceiling == "tokens"
    assert excinfo.value.actual == "10"


def test_record_charge_enforces_usd_ceiling():
    state = budgets.BudgetState(started_at_monotonic=0)
    config = budgets.BudgetConfig(max_usd=Decimal("1.25"))

    with pytest.raises(budgets.BudgetExceeded) as excinfo:
        budgets.record_charge(config, state, usd=Decimal("1.25"))

    assert excinfo.value.ceiling == "usd"
    assert excinfo.value.actual == "1.25"
