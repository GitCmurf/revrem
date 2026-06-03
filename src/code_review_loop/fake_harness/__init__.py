"""Internal fake harness used to drive deterministic review/triage/remediation
flows without a real model CLI.

The harness is normally invoked in-process by the subprocess runner (see
``code_review_loop.adapters.subprocess_runner``), but a thin ``__main__``
shim is provided so that the ``revrem-fake-harness`` console script entry
exists on ``PATH`` after ``pip install revrem``. The shim delegates to
``code_review_loop.harnesses.run_fake_harness_command`` and is only useful
when the in-process interception is bypassed (for example, when an external
process shells out to the binary directly).
"""

from code_review_loop.harnesses import run_fake_harness_command

__all__ = ["main", "run_fake_harness_command"]
