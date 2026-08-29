from src.pipeline.transforms import normalize_records


def test_normalize_records():
    res = normalize_records([{" name ": "  alice "}])
    assert res == [{"name": "alice"}]
