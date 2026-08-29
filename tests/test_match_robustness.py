from eval.check_probes import failing_negative_probes, failing_probes


def test_keyword_matching_is_robust_to_positive_and_negative_probes():
    failures = failing_probes() + failing_negative_probes()
    assert not failures, "\n".join(failures)
