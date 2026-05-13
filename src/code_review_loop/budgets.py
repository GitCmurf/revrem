"""Run budget accounting for bounded RevRem execution."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from time import monotonic


@dataclass(frozen=True)
class BudgetConfig:
    max_wall_seconds: float | None = None
    max_tokens: int | None = None
    max_usd: Decimal | None = None
    soft_warn_fraction: float = 0.8


@dataclass
class BudgetState:
    started_at_monotonic: float
    wall_warning_emitted: bool = False
    tokens_used: int = 0
    tokens_reported: bool = False
    usd_used: Decimal = Decimal("0")
    usd_reported: bool = False


class BudgetExceeded(Exception):
    """Raised when a configured run ceiling has already been reached."""

    def __init__(self, *, ceiling: str, limit: str, actual: str):
        super().__init__(f"{ceiling} budget exceeded: {actual} >= {limit}")
        self.ceiling = ceiling
        self.limit = limit
        self.actual = actual


def started_now() -> BudgetState:
    return BudgetState(started_at_monotonic=monotonic())


def parse_usd(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("--max-usd must be a decimal number") from exc
    if amount < 0:
        raise ValueError("--max-usd must be 0 or greater")
    return amount


def validate_config(config: BudgetConfig) -> None:
    if config.max_wall_seconds is not None and config.max_wall_seconds < 0:
        raise ValueError("--max-wall-seconds must be 0 or greater")
    if config.max_tokens is not None and config.max_tokens < 0:
        raise ValueError("--max-tokens must be 0 or greater")
    if config.max_usd is not None and config.max_usd < 0:
        raise ValueError("--max-usd must be 0 or greater")
    if not 0 < config.soft_warn_fraction <= 1:
        raise ValueError("--soft-warn-fraction must be greater than 0 and no more than 1")


def wall_elapsed_seconds(state: BudgetState, *, now: float | None = None) -> float:
    current = monotonic() if now is None else now
    return max(0.0, current - state.started_at_monotonic)


def wall_warning_due(
    config: BudgetConfig,
    state: BudgetState,
    *,
    now: float | None = None,
) -> tuple[bool, float]:
    if config.max_wall_seconds is None or state.wall_warning_emitted:
        return False, wall_elapsed_seconds(state, now=now)
    elapsed = wall_elapsed_seconds(state, now=now)
    return elapsed >= config.max_wall_seconds * config.soft_warn_fraction, elapsed


def check_wall_budget(
    config: BudgetConfig,
    state: BudgetState,
    *,
    now: float | None = None,
) -> float:
    elapsed = wall_elapsed_seconds(state, now=now)
    if config.max_wall_seconds is not None and elapsed >= config.max_wall_seconds:
        raise BudgetExceeded(
            ceiling="wall",
            limit=f"{config.max_wall_seconds:g}",
            actual=f"{elapsed:g}",
        )
    return elapsed


def record_charge(
    config: BudgetConfig,
    state: BudgetState,
    *,
    tokens: int | None = None,
    usd: Decimal | None = None,
) -> None:
    if tokens is not None:
        if tokens < 0:
            raise ValueError("token charge must be 0 or greater")
        state.tokens_reported = True
        state.tokens_used += tokens
    if usd is not None:
        if usd < 0:
            raise ValueError("USD charge must be 0 or greater")
        state.usd_reported = True
        state.usd_used += usd
    if config.max_tokens is not None and state.tokens_used >= config.max_tokens:
        raise BudgetExceeded(
            ceiling="tokens",
            limit=str(config.max_tokens),
            actual=str(state.tokens_used),
        )
    if config.max_usd is not None and state.usd_used >= config.max_usd:
        raise BudgetExceeded(
            ceiling="usd",
            limit=str(config.max_usd),
            actual=str(state.usd_used),
        )
