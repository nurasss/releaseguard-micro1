from metrics_exporter.exporter import format_metric


def test_format_metric():
    assert format_metric("requests_total", 42) == "requests_total 42"
