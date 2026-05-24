"""Command-level outcome ADT for subcommands (REVREM-TASK-003 Wave C1a).

Each subcommand returns a closed sum type whose variants carry their own
``exit_code`` field. The dispatcher (``cli.main``) calls
``outcome.exit_code`` rather than reading a bare ``int`` literal, keeping
exit-code authority centralised and consistent with ``RunOutcome``
(Contract C5).

The plan (Wave C1a step 2) calls for the two minimal variants below; new
variants may be added per subcommand as their migrations land. See
``docs/05-planning/tasks/task-003-reengineer-cli-py.md`` § Wave C1a.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CommandOk:
    """A successful subcommand result; defaults to exit code 0."""

    exit_code: int = 0


@dataclass(frozen=True)
class CommandFailed:
    """A failed subcommand result; carries a non-zero exit code and a message.

    The message is optional and is intended for the operator-facing stderr
    line; control flow must not branch on it.
    """

    exit_code: int = 1
    message: str = ""


CommandOutcome = CommandOk | CommandFailed
"""Closed sum type of subcommand terminal results.

Per Contract C5 each subcommand owns its own ``CommandOutcome``; this module
provides the minimal pair used by every existing subcommand. Variants with
more structure (e.g. doctor's strict-warnings result) may be added without
disturbing the dispatcher, which only reads ``.exit_code``.
"""


__all__ = ["CommandOk", "CommandFailed", "CommandOutcome"]
