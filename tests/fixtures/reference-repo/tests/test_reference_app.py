import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from reference_app.docs import public_total


def test_public_total():
    assert public_total([{"amount": 2}, {"amount": 3}]) == 5
