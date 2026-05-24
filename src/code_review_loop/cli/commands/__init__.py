"""Per-subcommand modules for the thin CLI driver (REVREM-TASK-003 Wave C1a).

Each module owns one ``revrem <subcommand>`` entry point. The dispatcher in
``code_review_loop.cli`` looks up the subcommand name in the registry
(Wave C1b) and calls the module's ``main`` function.

Module contents move from the legacy God-object ``cli/__init__.py`` (formerly
``cli.py``) one subcommand at a time; see
``docs/05-planning/tasks/task-003-reengineer-cli-py.md`` § Wave C1a.
"""
