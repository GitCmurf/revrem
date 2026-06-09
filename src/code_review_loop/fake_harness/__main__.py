"""``python -m code_review_loop.fake_harness`` and ``revrem-fake-harness``
console script entry point.

Delegates to :func:`code_review_loop.harnesses.run_fake_harness_command`,
which honours ``REVREM_ALLOW_FAKE_HARNESS=1`` and the same scenario / fixture
contract as the in-process interception path.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence

from code_review_loop.harnesses import run_fake_harness_command


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] != "revrem-fake-harness":
        args = ["revrem-fake-harness", *args]
    returncode, stdout, stderr = run_fake_harness_command(args)
    sys.stdout.write(stdout)
    sys.stderr.write(stderr)
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())
