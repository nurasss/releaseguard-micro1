# path: app/tools/registry.py
from __future__ import annotations

from app.llm.types import ToolSpec


def build_tool_specs() -> list[ToolSpec]:
    """Build OpenAPI/Gemini-compatible tool declarations for read-only repository audit.

    Schema uses only type, properties, required, description, items, and enum.
    Contains no $ref, anyOf, oneOf, or additionalProperties.
    """
    return [
        ToolSpec(
            name="get_repository_metadata",
            description=(
                "Fetch normalized repository metadata including default branch, description, "
                "available branches, tags, releases, and repository topics."
            ),
            parameters={
                "type": "object",
                "properties": {},
            },
        ),
        ToolSpec(
            name="get_tree",
            description=(
                "List all file paths and sizes in the repository sorted lexicographically. "
                "Capped at 500 files for noise protection."
            ),
            parameters={
                "type": "object",
                "properties": {},
            },
        ),
        ToolSpec(
            name="read_file",
            description=(
                "Read file contents with exact line slicing and content hashing. "
                "Default window returns up to 400 lines and 40,000 characters with a total_lines "
                "indicator for subsequent range queries."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative file path within repository (e.g. 'pyproject.toml' or 'src/main.py')",
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "Optional 1-based start line number for range reading",
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "Optional 1-based end line number for range reading",
                    },
                },
                "required": ["path"],
            },
        ),
        ToolSpec(
            name="search_files",
            description=(
                "Search repository text files for a regex pattern or substring. "
                "Returns up to 50 matching lines truncated to 300 characters each."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Regular expression or substring pattern to search",
                    },
                    "glob": {
                        "type": "string",
                        "description": "Optional glob pattern to filter files (e.g. '*.py' or 'docs/*')",
                    },
                },
                "required": ["pattern"],
            },
        ),
        ToolSpec(
            name="get_workflow_files",
            description="List all GitHub Actions workflow configuration files under '.github/workflows/'.",
            parameters={
                "type": "object",
                "properties": {},
            },
        ),
        ToolSpec(
            name="get_workflow_runs",
            description=(
                "Retrieve recent CI/CD workflow run records including workflow name, path, branch, "
                "event trigger, conclusion status, and timestamp."
            ),
            parameters={
                "type": "object",
                "properties": {},
            },
        ),
        ToolSpec(
            name="get_test_report",
            description=(
                "Retrieve structured test execution summary with total/passed/failed counts and "
                "failure details (test name, error type, truncated error message). Returns null if unavailable."
            ),
            parameters={
                "type": "object",
                "properties": {},
            },
        ),
        ToolSpec(
            name="get_build_report",
            description="Retrieve build and packaging report if available. Returns null if unavailable.",
            parameters={
                "type": "object",
                "properties": {},
            },
        ),
    ]
