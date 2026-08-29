# path: tests/test_redaction.py
from app.security.redaction import find_secrets, redact, redact_obj


def test_redact_single_strings() -> None:
    text = "Secret: ghp_123456789012345678901234567890123456 and sk-123456789012345678901234"
    res = redact(text)
    assert "[REDACTED:GitHub PAT (classic)]" in res
    assert "[REDACTED:OpenAI API Key]" in res
    assert "ghp_" not in res
    assert "sk-" not in res


def test_redact_fine_grained_pat_and_slack() -> None:
    text = "Tokens: github_pat_11AABBCCDDEEFFGGHHIIJJ_1234567890 and xoxb-1234567890-1234567890-abcdefg"
    res = redact(text)
    assert "[REDACTED:GitHub PAT (fine-grained)]" in res
    assert "[REDACTED:Slack Token]" in res
    assert "github_pat_" not in res
    assert "xoxb-" not in res


def test_redact_empty_and_non_string_types() -> None:
    assert redact("") == ""
    assert redact(None) is None  # type: ignore[arg-type]


def test_redact_obj_nested_structures() -> None:
    nested = {
        "ghp_key_name_is_not_redacted": "ghp_123456789012345678901234567890123456",
        "nested_dict": {
            "token": "AIzaSyD12345678901234567890123456789012",
            "normal_number": 42,
            "normal_bool": True,
            "normal_none": None,
        },
        "nested_list": [
            "AKIAIOSFODNN7EXAMPLE",
            {"inner": "-----BEGIN RSA PRIVATE KEY-----"},
        ],
    }

    cleaned = redact_obj(nested)

    assert "ghp_key_name_is_not_redacted" in cleaned
    assert cleaned["ghp_key_name_is_not_redacted"] == "[REDACTED:GitHub PAT (classic)]"
    assert cleaned["nested_dict"]["token"] == "[REDACTED:Google API Key]"
    assert cleaned["nested_dict"]["normal_number"] == 42
    assert cleaned["nested_dict"]["normal_bool"] is True
    assert cleaned["nested_dict"]["normal_none"] is None
    assert cleaned["nested_list"][0] == "[REDACTED:AWS Access Key]"
    assert cleaned["nested_list"][1]["inner"] == "[REDACTED:Private Key Header]"


def test_redact_obj_tuples_and_sets() -> None:
    tup = ("ghp_123456789012345678901234567890123456", "clean")
    redacted_tup = redact_obj(tup)
    assert redacted_tup == ("[REDACTED:GitHub PAT (classic)]", "clean")

    st = {"AKIA1234567890ABCDEF"}
    redacted_st = redact_obj(st)
    assert redacted_st == {"[REDACTED:AWS Access Key]"}


def test_short_and_safe_strings_not_redacted() -> None:
    safe_data = {
        "short_ghp": "ghp_short",
        "normal_text": "This is a clean string without secrets.",
        "code_snippet": "def test_function(): pass",
    }
    assert redact_obj(safe_data) == safe_data
