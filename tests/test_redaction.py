# path: tests/test_redaction.py
from app.security.redaction import find_secrets, is_sensitive_path, redact, redact_file_content, redact_obj


_PAT_CLASSIC = "gh" + "p_" + "123456789012345678901234567890123456"
_OPENAI_KEY = "s" + "k-" + "123456789012345678901234"
_PAT_FINE = "gith" + "ub_pat_" + "11AABBCCDDEEFFGGHHIIJJ_1234567890"
_SLACK_TOKEN = "xo" + "xb-" + "1234567890-1234567890-abcdefg"
_GOOGLE_KEY = "AI" + "za" + "SyD12345678901234567890123456789012"
_AWS_KEY = "AK" + "IA" + "IOSFODNN7EXAMPLE"
_PRIVATE_KEY = "---" + "--BEGIN RSA PRIVATE KEY-----"


def test_redact_single_strings() -> None:
    text = f"Secret: {_PAT_CLASSIC} and {_OPENAI_KEY}"
    res = redact(text)
    assert "[REDACTED:GitHub PAT (classic)]" in res
    assert "[REDACTED:OpenAI API Key]" in res
    assert _PAT_CLASSIC not in res
    assert _OPENAI_KEY not in res


def test_redact_fine_grained_pat_and_slack() -> None:
    text = f"Tokens: {_PAT_FINE} and {_SLACK_TOKEN}"
    res = redact(text)
    assert "[REDACTED:GitHub PAT (fine-grained)]" in res
    assert "[REDACTED:Slack Token]" in res
    assert _PAT_FINE not in res
    assert _SLACK_TOKEN not in res


def test_redact_empty_and_non_string_types() -> None:
    assert redact("") == ""
    assert redact(None) is None  # type: ignore[arg-type]


def test_redact_obj_nested_structures() -> None:
    nested = {
        "dict_key_name_not_redacted": _PAT_CLASSIC,
        "nested_dict": {
            "token": _GOOGLE_KEY,
            "normal_number": 42,
            "normal_bool": True,
            "normal_none": None,
        },
        "nested_list": [
            _AWS_KEY,
            {"inner": _PRIVATE_KEY},
        ],
    }

    cleaned = redact_obj(nested)

    assert "dict_key_name_not_redacted" in cleaned
    assert cleaned["dict_key_name_not_redacted"] == "[REDACTED:GitHub PAT (classic)]"
    assert cleaned["nested_dict"]["token"] == "[REDACTED:Google API Key]"
    assert cleaned["nested_dict"]["normal_number"] == 42
    assert cleaned["nested_dict"]["normal_bool"] is True
    assert cleaned["nested_dict"]["normal_none"] is None
    assert cleaned["nested_list"][0] == "[REDACTED:AWS Access Key]"
    assert cleaned["nested_list"][1]["inner"] == "[REDACTED:Private Key Header]"


def test_redact_obj_tuples_and_sets() -> None:
    tup = (_PAT_CLASSIC, "clean")
    redacted_tup = redact_obj(tup)
    assert redacted_tup == ("[REDACTED:GitHub PAT (classic)]", "clean")

    st = {_AWS_KEY}
    redacted_st = redact_obj(st)
    assert redacted_st == {"[REDACTED:AWS Access Key]"}


def test_short_and_safe_strings_not_redacted() -> None:
    safe_data = {
        "short_ghp": "gh" + "p_short",
        "normal_text": "This is a clean string without secrets.",
        "code_snippet": "def test_function(): pass",
    }
    assert redact_obj(safe_data) == safe_data


def test_secret_file_detection_and_content_omission() -> None:
    secret = "PASSWORD=not-a-provider-token"
    assert is_sensitive_path(".env") is True
    assert is_sensitive_path("config/prod_credentials.json") is True
    assert is_sensitive_path(".env.example") is False
    cleaned = redact_file_content("config/prod_credentials.json", secret)
    assert secret not in cleaned
    assert "secret file contents omitted" in cleaned
