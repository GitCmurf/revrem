"""Phase iteration / retry label helpers.

The runner shell and the inner-check-retry path share two related but
distinct label shapes:

* **On-disk artifact stems** use the operator-visible
  ``{iteration}-retry-{retry_count}`` form (e.g.
  ``remediation-1-retry-1.txt``, ``check-1-retry-1-2.txt``). Operators
  rely on this shape to locate retry artifacts in the run directory.
* **Schema-compatible ``iteration`` values** for ``phase_start`` and
  ``phase_result`` events use a dotted numeric sub-index (e.g. ``"1.1"``,
  ``"1.1.1"``) so the produced ``events.jsonl`` validates against
  ``docs/52-api/schemas/events-v1.schema.json``.

These helpers centralize that split so the runner shell, the events
schema, and the devex guide can be updated in lockstep.
"""

from __future__ import annotations


def artifact_label(iteration: int, retry_count: int) -> str:
    """Return the on-disk artifact stem for one ``(iteration, retry)`` pair.

    The ``{iteration}-retry-{retry_count}`` form is part of the operator-
    visible contract (e.g. ``remediation-1-retry-1.txt``). Do not change
    the shape without updating ``docs/70-devex/devex-001-using-code-review-loop.md``.
    """
    return f"{iteration}-retry-{retry_count}" if retry_count else str(iteration)


def event_iteration_label(iteration: int, retry_count: int) -> str:
    """Return the schema-compatible ``iteration`` value for one retry.

    RevRem's ``events-v1`` schema restricts ``iteration`` to integers,
    the literal ``"final"``, or dotted numeric strings (e.g.
    ``"1"``, ``"1.1"``, ``"1.1.1"``). Retry sub-attempts are encoded as
    a dotted sub-index so the emitted labels stay schema-compatible even
    when the checks phase appends its own sub-index, while the on-disk
    artifact stem keeps the operator-friendly ``-retry-N`` suffix.
    """
    return f"{iteration}.{retry_count}" if retry_count else str(iteration)
