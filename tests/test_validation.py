from validation.target import compute


def test_compute_basic():
    assert compute(5) == 10


def test_compute_custom_multiplier():
    assert compute(3, multiplier=4) == 12
