from notifier.message import format_subject


def test_format_subject():
    assert format_subject("password_reset", "acct_42") == "[acct_42] password_reset"
