"""
Completion verification for agent tasks.

A referenced path is valid only when it exists, is a real FILE (not a directory),
and is not trivially empty. Missing HTML/CSS/JS local references fail verification
so the agent can continue and fix the work.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_SKIP_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    "dist",
    "build",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
}

_CHECK_SUFFIXES = {
    ".html",
    ".htm",
    ".css",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".md",
    ".py",
    ".java",
    ".cpp",
    ".c",
    ".h",
}


class VerificationResult:
    """Result of completion verification."""

    def __init__(self, passed: bool, message: str = "", missing_files: list[str] | None = None):
        self.passed = passed
        self.message = message
        self.missing_files = missing_files or []


def verify_completion(
    workspace_path: str,
    task_prompt: str,
    files_created: set[str],
    files_modified: set[str],
) -> VerificationResult:
    workspace = Path(workspace_path)
    all_files = set(files_created) | set(files_modified)
    if workspace.is_dir():
        all_files |= _discover_checkable_files(workspace)

    if not all_files:
        if _requires_files(task_prompt):
            return VerificationResult(
                passed=False,
                message="Task appears to require creating files, but no files were created or modified.",
            )
        return VerificationResult(passed=True, message="Task completion verified.")

    problems = _check_file_references(workspace, all_files)
    if problems:
        return VerificationResult(
            passed=False,
            message=" ".join(problems),
            missing_files=problems,
        )

    return VerificationResult(passed=True, message="Task completion verified.")


def _discover_checkable_files(workspace: Path) -> set[str]:
    found: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(workspace):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for name in filenames:
            path = Path(dirpath) / name
            if path.suffix.lower() in _CHECK_SUFFIXES:
                found.add(path.relative_to(workspace).as_posix())
    return found


def _requires_files(task_prompt: str) -> bool:
    prompt_lower = task_prompt.lower()
    non_file_indicators = [
        "explain",
        "describe",
        "what is",
        "how does",
        "why",
        "analyze",
        "compare",
        "list",
        "summarize",
    ]
    if any(indicator in prompt_lower for indicator in non_file_indicators):
        return False
    file_indicators = [
        "create",
        "build",
        "implement",
        "add",
        "write",
        "file",
        "website",
        "page",
        "component",
        "module",
        "html",
        "css",
        "js",
        "py",
        "java",
        "cpp",
    ]
    return any(indicator in prompt_lower for indicator in file_indicators)


def _posix(workspace: Path, path: Path) -> str:
    try:
        return path.relative_to(workspace).as_posix()
    except ValueError:
        return path.as_posix()


def _path_problem(workspace: Path, referenced: Path) -> str | None:
    """Return a problem description if the referenced path is not a usable file."""
    rel = _posix(workspace, referenced)
    if not referenced.exists():
        return f"missing file '{rel}'"
    if referenced.is_dir():
        return f"'{rel}' exists but is a directory, not a file"
    if not referenced.is_file():
        return f"'{rel}' is not a regular file"
    try:
        text = referenced.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return f"'{rel}' could not be read"
    if not text.strip():
        return f"'{rel}' is empty"
    return None


def _check_file_references(workspace: Path, file_paths: set[str]) -> list[str]:
    """Validate local references. Existing-but-directory and empty files fail."""
    problems: list[str] = []

    def _add(message: str) -> None:
        if message not in problems:
            problems.append(message)

    for file_path_str in sorted(file_paths):
        file_path = workspace / file_path_str
        if not file_path.exists():
            continue
        if file_path.is_dir():
            _add(f"'{file_path_str}' exists but is a directory, not a file")
            continue
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() not in _CHECK_SUFFIXES:
            continue
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            logger.warning("Error reading %s: %s", file_path, exc)
            continue
        if not content.strip() and file_path.suffix.lower() in {".html", ".htm", ".css", ".js"}:
            _add(f"'{file_path_str}' is empty")
        file_dir = file_path.parent
        for ref in _extract_file_references(content, file_path.suffix.lower()):
            referenced_path = (file_dir / ref).resolve()
            try:
                referenced_path.relative_to(workspace.resolve())
            except ValueError:
                continue
            issue = _path_problem(workspace.resolve(), referenced_path)
            if issue:
                _add(issue)
    return problems


def _extract_file_references(content: str, file_ext: str) -> list[str]:
    references: list[str] = []

    if file_ext in {".html", ".htm"}:
        patterns = [
            r'<link[^>]+href=["\']([^"\']+\.css)["\']',
            r'<script[^>]+src=["\']([^"\']+\.js)["\']',
            r'<img[^>]+src=["\']([^"\']+\.(?:png|jpg|jpeg|gif|svg|webp))["\']',
            r'<link[^>]+href=["\']([^"\']+\.(?:png|jpg|jpeg|gif|svg|ico))["\']',
        ]
        for pattern in patterns:
            for match in re.findall(pattern, content, re.IGNORECASE):
                if not match.startswith(("http://", "https://", "//", "data:", "#")):
                    match = re.sub(r"[?#].*$", "", match)
                    if match:
                        references.append(match)

    elif file_ext == ".css":
        patterns = [
            r'@import\s+["\']([^"\']+)["\']',
            r'url\(["\']?([^"\'()]+)["\']?\)',
        ]
        for pattern in patterns:
            for match in re.findall(pattern, content, re.IGNORECASE):
                if not match.startswith(("http://", "https://", "//", "data:", "#")):
                    match = re.sub(r"[?#].*$", "", match)
                    if match and not match.startswith("data:"):
                        references.append(match)

    elif file_ext in {".js", ".jsx", ".ts", ".tsx"}:
        patterns = [
            r'import\s+.*?from\s+["\'](\.[^"\']+)["\']',
            r'import\s+["\'](\.[^"\']+)["\']',
            r'require\(["\'](\.[^"\']+)["\']\)',
        ]
        for pattern in patterns:
            for match in re.findall(pattern, content):
                if not Path(match).suffix:
                    for ext in [".js", ".jsx", ".ts", ".tsx", ".json"]:
                        references.append(match + ext)
                else:
                    references.append(match)

    return references
