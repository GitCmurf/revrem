"""Dependency-free review-loop core (REVREM-TASK-003).

Modules here import only the standard library, ports, and other core modules —
never adapters, the CLI driver, ``argparse``, terminal codes, or ``profiles``
(Contract C4, machine-enforced by import-linter). The hexagon's functional core.
"""
