from datasync.merge import diff_keys, merge_records


def test_merge_records_overrides_target():
    assert merge_records({"a": 1}, {"a": 0, "b": 2}) == {"a": 1, "b": 2}


def test_diff_keys():
    assert diff_keys({"a": 1, "c": 3}, {"a": 1}) == {"c"}
