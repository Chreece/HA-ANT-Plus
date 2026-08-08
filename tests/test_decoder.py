from custom_components.antplus.decoder import _pace_metric


def test_pace_unknown_when_stationary():
    metric = _pace_metric(0.0)
    assert metric.value is None


def test_pace_from_speed():
    metric = _pace_metric(10 / 3.6)
    assert metric.value == 6.0
    assert metric.unit == "min/km"
