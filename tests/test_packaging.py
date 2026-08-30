# path: tests/test_packaging.py
"""Guards against .env / runtime-artifact leakage into the submission archive.

Does not print or assert on any secret value — only checks which file names end
up inside the archive.
"""
from __future__ import annotations
import zipfile
from pathlib import Path

from scripts.package_submission import build_archive

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_submission_archive_excludes_secrets_and_runtime_artifacts(tmp_path: Path) -> None:
    output = tmp_path / "submission.zip"
    build_archive(REPO_ROOT, output)

    assert output.exists()
    with zipfile.ZipFile(output) as zf:
        names = zf.namelist()

    assert names, "archive must not be empty"

    for name in names:
        base = Path(name).name
        assert not (base.startswith(".env") and base not in {".env.example", ".env.sample", ".env.template"}), (
            f"secret-like dotenv file leaked into archive: {name}"
        )
        assert not name.endswith((".sqlite3", ".sqlite3-wal", ".sqlite3-shm")), f"local database leaked into archive: {name}"

    assert not any(n.startswith(".git/") or n == ".git" for n in names)
    assert not any("__pycache__" in n for n in names)
    assert not any(n.startswith(".pytest_cache/") for n in names)
    assert not any(n.startswith("runs/") for n in names)
    assert not any(n.startswith("trajectories/") for n in names)
    assert not any(n.startswith("artifacts/") for n in names)

    # Frozen benchmark fixtures nested under eval/ must NOT be excluded just
    # because their directory is also named "artifacts".
    assert any(n.startswith("eval/cases/") for n in names)


def test_submission_archive_keeps_dotenv_templates(tmp_path: Path) -> None:
    source = tmp_path / "proj"
    (source / "eval" / "cases").mkdir(parents=True)
    (source / ".env").write_text("GEMINI_API_KEY=super-secret\nGITHUB_TOKEN=super-secret\n", encoding="utf-8")
    (source / ".env.example").write_text("GEMINI_API_KEY=\nGITHUB_TOKEN=\n", encoding="utf-8")
    (source / "eval" / "cases" / "gold.json").write_text("{}", encoding="utf-8")
    (source / "runs").mkdir()
    (source / "runs" / "leaked.json").write_text("{}", encoding="utf-8")
    (source / "eval" / "cases" / "artifacts").mkdir()
    (source / "eval" / "cases" / "artifacts" / "fixture.json").write_text("{}", encoding="utf-8")

    output = tmp_path / "out.zip"
    build_archive(source, output)

    with zipfile.ZipFile(output) as zf:
        names = set(zf.namelist())

    assert ".env" not in names
    assert ".env.example" in names
    assert not any(n.startswith("runs/") for n in names)
    assert "eval/cases/artifacts/fixture.json" in names


def test_build_archive_is_idempotent_when_output_lives_inside_source(tmp_path: Path) -> None:
    # Regression test: output_path defaults to <source>/dist/releaseguard_submission.zip,
    # i.e. inside source_dir. A naive walk would then archive its own previous
    # output on a second run, growing unboundedly.
    source = tmp_path / "proj"
    (source / "eval" / "cases").mkdir(parents=True)
    (source / "app").mkdir()
    (source / "app" / "main.py").write_text("print('hi')\n", encoding="utf-8")
    (source / "eval" / "cases" / "gold.json").write_text("{}", encoding="utf-8")

    output = source / "dist" / "releaseguard_submission.zip"

    build_archive(source, output)
    with zipfile.ZipFile(output) as zf:
        first_names = set(zf.namelist())
        first_size = output.stat().st_size

    assert "dist/releaseguard_submission.zip" not in first_names
    assert not any(n.startswith("dist/") for n in first_names)

    # Second run must not pick up the ZIP written by the first run.
    build_archive(source, output)
    with zipfile.ZipFile(output) as zf:
        second_names = set(zf.namelist())
        second_size = output.stat().st_size

    assert second_names == first_names
    assert not any(n.startswith("dist/") for n in second_names)
    # Sizes should match exactly (not merely "not huge") since the input tree
    # did not change between runs.
    assert second_size == first_size
