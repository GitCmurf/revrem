from reference_app.docs import public_total


def test_public_total():
    assert public_total([{"amount": 2}, {"amount": 3}]) == 5
