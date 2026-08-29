# path: tests/test_no_secrets.py
import subprocess
from pathlib import Path

import pytest

from app.security.redaction import find_secrets


ROOT_DIR = Path(__file__).resolve().parents[1]


def test_no_secrets_in_git_tracked_files() -> None:
    try:
        proc = subprocess.run(
            ["git", "ls-files"],
            cwd=ROOT_DIR,
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception as exc:
        pytest.skip(f"git command not available: {exc}")

    if proc.returncode != 0:
        pytest.skip(f"git ls-files failed (not a git repository or git error): {proc.stderr}")

    tracked_files = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    if not tracked_files:
        pytest.skip("git ls-files returned empty list")

    leaks: list[str] = []
    for rel_path in tracked_files:
        normalized_path = rel_path.replace("\\", "/")
        if normalized_path.endswith("tests/test_no_secrets.py") or normalized_path.endswith("app/security/redaction.py"):
            continue

        file_path = ROOT_DIR / rel_path
        if not file_path.is_file():
            continue

        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        findings = find_secrets(content)
        for line_num, name, masked in findings:
            leaks.append(f"{rel_path}:{line_num} [{name}] -> {masked}")

    assert not leaks, "Found potential secrets in git-tracked files:\n" + "\n".join(leaks)


def test_find_secrets_positive_and_negative() -> None:
    # 1. Positive: ghp_ with 36 chars is detected
    sample_ghp = "ghp_" + "a" * 36
    hits = find_secrets(f"TOKEN = '{sample_ghp}'")
    assert len(hits) == 1
    assert hits[0][1] == "GitHub PAT (classic)"
    assert hits[0][2].startswith("ghp_...")

    # 2. Negative: short ghp_ is NOT detected
    hits_short = find_secrets("TOKEN = 'ghp_short'")
    assert len(hits_short) == 0

    # 3. Positive: Google API Key
    sample_aiza = "AIza" + "B" * 35
    hits_aiza = find_secrets(f"KEY = '{sample_aiza}'")
    assert len(hits_aiza) == 1
    assert hits_aiza[0][1] == "Google API Key"

    # 4. Positive: OpenAI Key
    sample_sk = "sk-" + "c" * 24
    hits_sk = find_secrets(f"OPENAI_KEY = '{sample_sk}'")
    assert len(hits_sk) == 1
    assert hits_sk[0][1] == "OpenAI API Key"

    # 5. Positive: AWS Access Key
    sample_aws = "AKIA" + "1234567890ABCDEF"
    hits_aws = find_secrets(f"AWS_KEY = '{sample_aws}'")
    assert len(hits_aws) == 1
    assert hits_aws[0][1] == "AWS Access Key"

    # 6. Positive: Private Key
    hits_pk = find_secrets("-----BEGIN RSA PRIVATE KEY-----")
    assert len(hits_pk) == 1
    assert hits_pk[0][1] == "Private Key Header"

    # 7. Positive: Slack token
    sample_slack = "xoxb-" + "1234567890abc"
    hits_slack = find_secrets(f"SLACK = '{sample_slack}'")
    assert len(hits_slack) == 1
    assert hits_slack[0][1] == "Slack Token"
