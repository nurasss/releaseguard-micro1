"""Data transform functions."""


def normalize_records(records: list[dict]) -> list[dict]:
    return [{k.strip(): str(v).strip() for k, v in r.items()} for r in records]
