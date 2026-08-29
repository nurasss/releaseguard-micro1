import os

from toolbox.cli import add_numbers, load_config, slugify


def test_add_numbers():
    assert add_numbers(2, 3) == 5


def test_slugify_collapses_punctuation():
    assert slugify("Hello, World!!") == "hello-world"


def test_load_config_defaults(monkeypatch):
    monkeypatch.delenv("TOOLBOX_API_KEY", raising=False)
    monkeypatch.delenv("TOOLBOX_LOG_LEVEL", raising=False)
    monkeypatch.delenv("TOOLBOX_TIMEOUT_SECONDS", raising=False)
    config = load_config()
    assert config == {"api_key": "", "log_level": "INFO", "timeout_seconds": 30}
