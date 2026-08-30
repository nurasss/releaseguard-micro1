from pathlib import Path

from app.sources.fixture import LocalFixtureSource
from app.sources.snapshot import SnapshotManager, SnapshotManifest, tree_digest


CASES_DIR = Path(__file__).resolve().parents[1] / "eval" / "cases"


def test_snapshot_manager_writes_content_free_manifest(tmp_path: Path) -> None:
    source = LocalFixtureSource(CASES_DIR / "case_01")
    resolved = source.resolve_ref("v1.4.0")
    output = tmp_path / "snapshot.json"

    manifest = SnapshotManager().capture(
        source=source,
        repository_url="https://github.com/eval/case_01",
        requested_ref="v1.4.0",
        resolved_ref=resolved,
        output_path=output,
    )

    loaded = SnapshotManifest.model_validate_json(output.read_text(encoding="utf-8"))
    assert loaded == manifest
    assert loaded.commit_sha == resolved.commit_sha
    assert loaded.file_count > 0
    assert loaded.tree_sha256 == tree_digest(source.get_tree())
    assert "PASSWORD" not in output.read_text(encoding="utf-8")
