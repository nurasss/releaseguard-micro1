# path: app/sources/github.py
from __future__ import annotations

import base64
import fnmatch
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from app.schemas.evidence import content_hash_of
from app.sources.base import (
    MAX_GITHUB_SEARCH_FILES,
    MAX_READ_FILE_CHARS,
    MAX_READ_FILE_LINES,
    MAX_SEARCH_HITS,
    MAX_SEARCH_LINE_CHARS,
    MAX_TEST_ERROR_MESSAGE_CHARS,
    MAX_TREE_ENTRIES,
    FileSlice,
    RepositorySource,
    ResolvedRef,
    SearchHit,
    TreeEntry,
)
from app.sources.errors import (
    FileNotFoundInRepoError,
    GitHubAPIError,
    InvalidPathError,
    PathEscapeError,
    SourceError,
    UnknownRefError,
)


class GitHubSource(RepositorySource):
    """Read-only repository source adapter for live GitHub repositories.

    Guarantees NFR-04: strictly read-only HTTP GET requests only.
    All content queries are bound to the immutable resolved commit SHA.
    """

    BASE_URL = "https://api.github.com"

    def __init__(
        self,
        repo_url: str,
        token: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.repo_url = repo_url
        # A token copied into .env often carries surrounding whitespace. Sending
        # it verbatim produces a malformed Authorization header and a 401 that
        # looks like a missing repository, so normalise it to empty here.
        self.token = token.strip() if token else token
        self.owner, self.repo = self._parse_repo_url(repo_url)
        self._resolved_commit_sha: str | None = None
        self._resolved_ref_name: str | None = None

        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "ReleaseGuard/0.1.0",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        self._client = httpx.Client(
            base_url=self.BASE_URL,
            headers=headers,
            transport=transport,
            timeout=30.0,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> GitHubSource:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    @staticmethod
    def _parse_repo_url(url_or_slug: str) -> tuple[str, str]:
        raw = url_or_slug.strip().rstrip("/")
        if raw.startswith("http://") or raw.startswith("https://"):
            parsed = urlparse(raw)
            parts = [p for p in parsed.path.strip("/").split("/") if p]
            if len(parts) >= 2:
                repo_name = parts[1]
                if repo_name.endswith(".git"):
                    repo_name = repo_name[:-4]
                return parts[0], repo_name
        elif "/" in raw:
            parts = raw.split("/")
            if len(parts) == 2:
                repo_name = parts[1]
                if repo_name.endswith(".git"):
                    repo_name = repo_name[:-4]
                return parts[0], repo_name
        raise InvalidPathError(f"Invalid GitHub repository URL: {url_or_slug}")

    def _get(self, endpoint: str, params: dict | None = None) -> httpx.Response:
        """Perform a read-only HTTP GET request against the GitHub API."""
        clean_endpoint = endpoint.lstrip("/")
        # The repository endpoint itself is addressed with an empty endpoint.
        # It must not carry a trailing slash: GitHub answers /repos/o/r with 200
        # and /repos/o/r/ with 404, which fails every live audit on its first call.
        full_path = f"/repos/{self.owner}/{self.repo}"
        if clean_endpoint:
            full_path = f"{full_path}/{clean_endpoint}"
        try:
            response = self._client.get(full_path, params=params)
        except Exception as exc:
            raise GitHubAPIError(f"GitHub API connection error: {exc}") from exc
        return response

    def _api_error(self, what: str, response: httpx.Response) -> GitHubAPIError:
        """Describe a failed GitHub call in terms the operator can act on.

        A bare status code is not actionable: the most common live failure is
        the 60-requests-per-hour anonymous quota, which a reader cannot
        distinguish from a missing repository (NFR-10).
        """
        status = response.status_code
        remaining = response.headers.get("X-RateLimit-Remaining")
        if status in (403, 429) and remaining == "0":
            reset_note = ""
            reset_at = response.headers.get("X-RateLimit-Reset")
            if reset_at and reset_at.isdigit():
                reset_utc = datetime.fromtimestamp(int(reset_at), tz=timezone.utc)
                reset_note = f" The quota resets at {reset_utc:%H:%M} UTC."
            limit = response.headers.get("X-RateLimit-Limit", "60")
            hint = (
                "Set GITHUB_TOKEN to raise the limit to 5000 requests per hour"
                if not self.token
                else "Wait for the reset or use a token with more remaining quota"
            )
            return GitHubAPIError(
                f"{what}: GitHub API rate limit exceeded "
                f"({limit} requests/hour for this credential).{reset_note} {hint}."
            )
        if status == 401:
            return GitHubAPIError(
                f"{what}: GitHub rejected the credential (401). "
                "Clear GITHUB_TOKEN to read public repositories anonymously, "
                "or replace it with a valid token."
            )
        return GitHubAPIError(f"{what}: status {status}")

    def resolve_ref(self, ref: str) -> ResolvedRef:
        # S2: Priority order: branches -> tags -> releases -> commits

        # 1. Check branches
        branch_res = self._get(f"branches/{ref}")
        if branch_res.status_code == 200:
            branch_data = branch_res.json()
            commit_sha = branch_data.get("commit", {}).get("sha", "")
            self._resolved_commit_sha = commit_sha
            self._resolved_ref_name = ref
            return ResolvedRef(
                requested_ref=ref,
                commit_sha=commit_sha,
                ref_type="branch",
            )

        # 2. Check tags
        tag_res = self._get(f"git/ref/tags/{ref}")
        if tag_res.status_code == 200:
            tag_data = tag_res.json()
            commit_sha = self._resolve_tag_object(tag_data)
            self._resolved_commit_sha = commit_sha
            self._resolved_ref_name = ref
            return ResolvedRef(
                requested_ref=ref,
                commit_sha=commit_sha,
                ref_type="tag",
            )

        # 3. Check releases
        rel_res = self._get(f"releases/tags/{ref}")
        if rel_res.status_code == 200:
            rel_data = rel_res.json()
            tag_name = rel_data.get("tag_name", ref)
            tag_lookup = self._get(f"git/ref/tags/{tag_name}")
            if tag_lookup.status_code == 200:
                commit_sha = self._resolve_tag_object(tag_lookup.json())
                self._resolved_commit_sha = commit_sha
                self._resolved_ref_name = ref
                return ResolvedRef(
                    requested_ref=ref,
                    commit_sha=commit_sha,
                    ref_type="release",
                )

        # 4. Check commits
        commit_res = self._get(f"commits/{ref}")
        if commit_res.status_code == 200:
            commit_data = commit_res.json()
            commit_sha = commit_data.get("sha", "")
            self._resolved_commit_sha = commit_sha
            self._resolved_ref_name = ref
            return ResolvedRef(
                requested_ref=ref,
                commit_sha=commit_sha,
                ref_type="commit",
            )

        # A 404 on every lookup means the ref is absent. A quota or credential
        # failure means the lookups never happened, and reporting that as
        # "ref not found" sends the operator hunting a nonexistent typo.
        for probe in (branch_res, tag_res, rel_res, commit_res):
            if probe.status_code in (401, 403, 429):
                raise self._api_error(f"Failed to resolve ref {ref!r}", probe)

        raise UnknownRefError(f"Ref {ref!r} not found in GitHub repository {self.owner}/{self.repo}")

    def _resolve_tag_object(self, tag_data: dict, _seen: set[str] | None = None) -> str:
        """Resolve lightweight and annotated tags to the underlying commit SHA."""
        obj = tag_data.get("object", {}) if isinstance(tag_data, dict) else {}
        sha = str(obj.get("sha", ""))
        obj_type = obj.get("type")
        if obj_type != "tag":
            return sha
        seen = _seen or set()
        if not sha or sha in seen:
            raise GitHubAPIError("Annotated Git tag contains a cycle or empty target")
        seen.add(sha)
        tag_res = self._get(f"git/tags/{sha}")
        if tag_res.status_code != 200:
            raise GitHubAPIError(f"Failed to resolve annotated Git tag object: status {tag_res.status_code}")
        return self._resolve_tag_object(tag_res.json(), seen)

    def get_repository_metadata(self) -> dict:
        repo_res = self._get("")
        if repo_res.status_code != 200:
            raise self._api_error("Failed to fetch repository metadata", repo_res)
        repo_data = repo_res.json()
        is_private = bool(repo_data.get("private", False))
        if is_private:
            # Do not enumerate refs or request any repository content for a
            # private target. The runner turns this metadata signal into a
            # rejected audit.
            return {
                "private": True,
                "default_branch": repo_data.get("default_branch", "main"),
                "description": repo_data.get("description") or "",
                "branches": [],
                "tags": [],
                "releases": [],
                "topics": [],
            }

        # Each of the three listings below answers 200 with an empty array when
        # the repository genuinely has none. A non-200 therefore carries no
        # information about absence, and substituting [] would let a rate limit
        # become a finding such as "no tags or releases" (SPEC 24, NFR-10).
        def _listing(endpoint: str) -> list:
            res = self._get(endpoint)
            if res.status_code != 200:
                raise self._api_error(f"Failed to fetch repository {endpoint}", res)
            payload = res.json()
            return payload if isinstance(payload, list) else []

        branches = [b["name"] for b in _listing("branches") if isinstance(b, dict) and "name" in b]

        tags = [t["name"] for t in _listing("tags") if isinstance(t, dict) and "name" in t]

        releases = [
            r.get("tag_name", r.get("name", "")) for r in _listing("releases") if isinstance(r, dict)
        ]

        default_branch = repo_data.get("default_branch", "main")
        if default_branch not in branches:
            branches.insert(0, default_branch)

        return {
            "private": bool(repo_data.get("private", False)),
            "default_branch": default_branch,
            "description": repo_data.get("description") or "",
            "branches": branches,
            "tags": tags,
            "releases": [rel for rel in releases if rel],
            "topics": repo_data.get("topics", []),
        }

    def get_tree(self) -> list[TreeEntry]:
        # S1: Tree must be fetched using resolved_commit_sha
        if not self._resolved_commit_sha:
            raise SourceError("Repository ref must be resolved via resolve_ref() before calling get_tree()")

        tree_res = self._get(f"git/trees/{self._resolved_commit_sha}", params={"recursive": "1"})
        if tree_res.status_code != 200:
            # An API failure must never be reported as "this repository has no
            # files": that turns a rate limit or an outage into a confident
            # negative finding such as "no CI workflows exist" (SPEC 24, NFR-10).
            # GitHub answers an genuinely empty tree with 200 and an empty list.
            raise self._api_error(
                f"Failed to fetch repository tree at {self._resolved_commit_sha[:7]}", tree_res
            )

        tree_data = tree_res.json().get("tree", [])
        entries: list[TreeEntry] = []
        for item in tree_data:
            if item.get("type") == "blob":
                path = item.get("path", "")
                size = item.get("size", 0)
                entries.append(TreeEntry(path=path, size_bytes=size))

        entries.sort(key=lambda e: e.path)
        return entries[:MAX_TREE_ENTRIES]

    def read_file(
        self,
        path: str,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> FileSlice:
        # S1: File content must be fetched at the resolved_commit_sha
        if not self._resolved_commit_sha:
            raise SourceError("Repository ref must be resolved via resolve_ref() before calling read_file()")

        if not path or not isinstance(path, str):
            raise InvalidPathError("Path must be a non-empty string")
        if path.startswith("/") or ".." in path.split("/"):
            raise PathEscapeError(f"Path escape attempted: {path}")

        res = self._get(f"contents/{path}", params={"ref": self._resolved_commit_sha})
        if res.status_code == 404:
            raise FileNotFoundInRepoError(f"File not found on GitHub at {self._resolved_commit_sha[:7]}: {path}")
        if res.status_code != 200:
            raise self._api_error(f"GitHub contents error for {path}", res)

        data = res.json()
        if data.get("type") != "file":
            raise InvalidPathError(f"Path is not a file: {path}")

        content_raw = data.get("content", "")
        encoding = data.get("encoding", "base64")
        if encoding == "base64":
            content_bytes = base64.b64decode(content_raw)
        else:
            content_bytes = content_raw.encode("utf-8")

        text = content_bytes.decode("utf-8", errors="replace")
        lines = text.splitlines()
        total_lines = len(lines)

        if start_line is not None or end_line is not None:
            s_line = start_line if start_line is not None else 1
            e_line = end_line if end_line is not None else total_lines
            s_line = max(1, s_line)
            e_line = min(total_lines, max(s_line, e_line))

            selected_lines = lines[s_line - 1 : e_line] if total_lines > 0 else []
            slice_text = "\n".join(selected_lines)
            truncated = False

            if len(slice_text) > MAX_READ_FILE_CHARS:
                slice_text = slice_text[:MAX_READ_FILE_CHARS]
                truncated = True

            content_hash = content_hash_of(slice_text)
            return FileSlice(
                path=path,
                start_line=s_line if total_lines > 0 else 0,
                end_line=e_line if total_lines > 0 else 0,
                total_lines=total_lines,
                content=slice_text,
                truncated=truncated,
                content_hash=content_hash,
            )

        truncated = False
        selected_lines = lines[:MAX_READ_FILE_LINES]
        if total_lines > MAX_READ_FILE_LINES:
            truncated = True

        slice_text = "\n".join(selected_lines)
        if len(slice_text) > MAX_READ_FILE_CHARS:
            slice_text = slice_text[:MAX_READ_FILE_CHARS]
            truncated = True

        end_l = min(total_lines, MAX_READ_FILE_LINES) if total_lines > 0 else 0
        content_hash = content_hash_of(slice_text)
        return FileSlice(
            path=path,
            start_line=1 if total_lines > 0 else 0,
            end_line=end_l,
            total_lines=total_lines,
            content=slice_text,
            truncated=truncated,
            content_hash=content_hash,
        )

    def search_files(
        self,
        pattern: str,
        glob: str | None = None,
    ) -> list[SearchHit]:
        # S3: Cap files searched to MAX_GITHUB_SEARCH_FILES, prioritized by glob
        tree = self.get_tree()
        if not tree or not pattern:
            return []

        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error:
            regex = re.compile(re.escape(pattern), re.IGNORECASE)

        matching_entries = [
            entry for entry in tree if not glob or fnmatch.fnmatch(entry.path, glob)
        ]
        candidates = matching_entries[:MAX_GITHUB_SEARCH_FILES]

        hits: list[SearchHit] = []
        for entry in candidates:
            try:
                slice_res = self.read_file(entry.path)
                lines = slice_res.content.splitlines()
            except Exception:
                continue

            for idx, line in enumerate(lines, start=1):
                if regex.search(line):
                    hits.append(
                        SearchHit(
                            path=entry.path,
                            line_number=idx,
                            line=line[:MAX_SEARCH_LINE_CHARS],
                        )
                    )
                    if len(hits) >= MAX_SEARCH_HITS:
                        return hits

        return hits

    def get_workflow_files(self) -> list[str]:
        tree = self.get_tree()
        wf_files = [
            e.path
            for e in tree
            if e.path.startswith(".github/workflows/") and not e.path.endswith("/")
        ]
        return sorted(wf_files)

    def get_workflow_runs(self) -> list[dict]:
        # S4: Fetch workflow runs and prioritize matching head_sha
        params = {"per_page": 50}
        if self._resolved_ref_name:
            params["branch"] = self._resolved_ref_name

        runs_res = self._get("actions/runs", params=params)
        if runs_res.status_code != 200:
            # Fallback without branch parameter
            runs_res = self._get("actions/runs", params={"per_page": 50})
            if runs_res.status_code != 200:
                # Same rule as get_tree: an unavailable Actions API is not
                # evidence that no CI run exists (SPEC 24, NFR-10).
                raise self._api_error("Failed to fetch GitHub Actions runs", runs_res)

        data = runs_res.json()
        runs = data.get("workflow_runs", [])
        normalized: list[dict] = []

        # Sort so runs matching resolved commit SHA appear first
        def run_sort_key(r: dict) -> int:
            if self._resolved_commit_sha and r.get("head_sha") == self._resolved_commit_sha:
                return 0
            return 1

        sorted_runs = sorted(runs, key=run_sort_key)

        for r in sorted_runs:
            normalized.append(
                {
                    "workflow_name": r.get("name", ""),
                    "path": r.get("path", ""),
                    "head_branch": r.get("head_branch", ""),
                    "head_sha": r.get("head_sha", ""),
                    "event": r.get("event", ""),
                    "conclusion": r.get("conclusion", ""),
                    "created_at": r.get("created_at", ""),
                }
            )
        return normalized

    def get_test_report(self) -> dict | None:
        return None

    def get_build_report(self) -> dict | None:
        return None
