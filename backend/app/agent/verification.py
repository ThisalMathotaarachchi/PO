"""
Completion verification for agent tasks.

A referenced path is valid only when it exists, is a real FILE (not a directory),
and is not trivially empty. Missing HTML/CSS/JS local references fail verification
so the agent can continue and fix the work.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import socket
import urllib.request
import urllib.error
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class _HTMLStructureValidator(HTMLParser):
    """Conservative HTML structure validator.
    
    Checks for basic document structure without enforcing specific design elements.
    """
    
    def __init__(self) -> None:
        super().__init__()
        self.has_doctype = False
        self.has_html = False
        self.has_head = False
        self.has_body = False
        self.tag_stack: list[str] = []
    
    def handle_decl(self, decl: str) -> None:
        if decl.strip().lower().startswith("doctype html"):
            self.has_doctype = True
    
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tag_stack.append(tag.lower())
        if tag.lower() == "html":
            self.has_html = True
        elif tag.lower() == "head":
            self.has_head = True
        elif tag.lower() == "body":
            self.has_body = True
    
    def handle_endtag(self, tag: str) -> None:
        if self.tag_stack and self.tag_stack[-1] == tag.lower():
            self.tag_stack.pop()
    
    def is_valid_structure(self) -> bool:
        """Return True if basic HTML document structure is present."""
        return self.has_html and self.has_head and self.has_body


def _validate_html_structure(content: str) -> str | None:
    """Validate that HTML content has basic document structure.
    
    Returns None if valid, error message if invalid.
    Conservative check - only verifies doctype, html, head, body presence.
    """
    if not content.strip():
        return "HTML content is empty"
    
    validator = _HTMLStructureValidator()
    try:
        validator.feed(content)
    except Exception as exc:
        return f"HTML parsing failed: {exc}"
    
    if not validator.has_doctype:
        return "Missing DOCTYPE declaration"
    if not validator.is_valid_structure():
        missing = []
        if not validator.has_html:
            missing.append("<html>")
        if not validator.has_head:
            missing.append("<head>")
        if not validator.has_body:
            missing.append("<body>")
        return f"Missing required HTML elements: {', '.join(missing)}"
    return None


def _is_static_site(workspace: Path, files: set[str]) -> bool:
    """Check if the project appears to be a static website."""
    return any(f.endswith((".html", ".htm")) for f in files)


def _find_free_port() -> int:
    """Find a free port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _verify_static_site_runtime(
    workspace: Path,
    files: set[str],
    readiness_timeout: float,
    port: int = 0,
    *,
    process_manager: Optional["ProcessManager"] = None,
    context: Optional["ToolContext"] = None,
) -> tuple[bool, str, list[str]]:
    """Runtime verification for static sites.
    
    Starts a local HTTP server, verifies the site and its local assets,
    then stops the server. Returns (passed, message, missing_files).
    
    For testing, a mock ProcessManager can be injected via the process_manager parameter.
    """
    if not _is_static_site(workspace, files):
        return True, "Not a static site, skipping runtime verification", []
    
    # Find index.html
    index_files = [f for f in files if f.endswith((".html", ".htm"))]
    if not index_files:
        return True, "No HTML files found, skipping runtime verification", []
    
    index_file = index_files[0]
    
    # Extract local CSS/JS references from index.html
    index_path = workspace / index_file
    try:
        index_content = index_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return False, f"Failed to read {index_file}: {exc}", [index_file]
    
    local_assets = _extract_file_references(index_content, ".html")
    # Also check CSS for @import and url() references
    for css_file in [f for f in files if f.endswith(".css")]:
        css_path = workspace / css_file
        try:
            css_content = css_path.read_text(encoding="utf-8", errors="replace")
            local_assets.extend(_extract_file_references(css_content, ".css"))
        except OSError:
            pass
    
    # Separate assets that exist from those that are missing
    # Missing referenced assets should cause runtime verification to fail
    assets_to_check = []
    missing_referenced_assets = []
    for asset in local_assets:
        asset_path = workspace / asset
        if asset_path.exists() and asset_path.is_file():
            assets_to_check.append(asset)
        else:
            missing_referenced_assets.append(asset)
    
    # If there are missing referenced assets, fail immediately
    if missing_referenced_assets:
        return False, f"Missing referenced assets: {', '.join(missing_referenced_assets)}", missing_referenced_assets
    
    # Determine port
    if port == 0:
        port = _find_free_port()
    
    server_process_id = f"po-verify-{port}"
    server_url = f"http://127.0.0.1:{port}"
    
    # Use injected process manager for testing, or create real one
    if process_manager is None:
        from app.tools.processes import ProcessManager
        from app.permissions.sandbox import PathSandbox
        from app.events.bus import EventBus
        
        sandbox = PathSandbox(workspace)
        bus = EventBus()
        process_manager = ProcessManager(sandbox, bus)
        own_process_manager = True
    else:
        own_process_manager = False
    
    if context is None:
        from app.tools.base import ToolContext
        context = ToolContext(workspace_root=str(workspace), task_id="verify")
    
    # Start the HTTP server
    server_command = f"{_python_executable()} -m http.server {port}"
    
    try:
        start_result = await process_manager.start_process({
            "command": server_command,
            "process_id": server_process_id,
        }, context)
        
        if start_result.status != "success":
            return False, f"Failed to start verification server: {start_result.error}", [index_file]
        
        # Wait for server readiness
        ready = await _wait_for_server_ready(server_url, readiness_timeout)
        if not ready:
            return False, f"Verification server did not become ready within {readiness_timeout}s", [index_file]
        
        # Perform HTTP checks
        problems = []
        missing_files = []
        
        # Check root
        try:
            req = urllib.request.Request(server_url + "/", method="HEAD")
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status >= 400:
                    problems.append(f"GET / returned HTTP {response.status}")
                    missing_files.append(index_file)
        except urllib.error.HTTPError as exc:
            problems.append(f"GET / returned HTTP {exc.code}")
            missing_files.append(index_file)
        except Exception as exc:
            problems.append(f"GET / failed: {exc}")
            missing_files.append(index_file)
        
        # Check local assets
        for asset in assets_to_check:
            asset_url = f"{server_url}/{asset}"
            try:
                req = urllib.request.Request(asset_url, method="HEAD")
                with urllib.request.urlopen(req, timeout=5) as response:
                    if response.status >= 400:
                        problems.append(f"GET {asset} returned HTTP {response.status}")
                        missing_files.append(asset)
            except urllib.error.HTTPError as exc:
                problems.append(f"GET {asset} returned HTTP {exc.code}")
                missing_files.append(asset)
            except Exception as exc:
                problems.append(f"GET {asset} failed: {exc}")
                missing_files.append(asset)
        
        if problems:
            return False, " ".join(problems), missing_files
        
        return True, "Runtime verification passed", []
    
    finally:
        # Always stop the server
        try:
            await process_manager.stop_process({"process_id": server_process_id})
        except Exception:
            pass


def _python_executable() -> str:
    """Get the current Python executable."""
    import sys
    return sys.executable


async def _wait_for_server_ready(url: str, timeout: float) -> bool:
    """Poll the server until it responds or timeout expires."""
    start = asyncio.get_event_loop().time()
    while asyncio.get_event_loop().time() - start < timeout:
        try:
            req = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(req, timeout=2) as response:
                if response.status < 500:
                    return True
        except Exception:
            pass
        await asyncio.sleep(0.2)
    return False


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


async def verify_completion(
    workspace_path: str,
    task_prompt: str,
    files_created: set[str],
    files_modified: set[str],
    *,
    verify_runtime: bool = False,
    runtime_readiness_timeout: float = 10.0,
    runtime_port: int = 0,
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

    # Verify that explicitly created/modified paths are actually files, not directories
    for f in files_created | files_modified:
        path = workspace / f
        if path.exists() and path.is_dir():
            return VerificationResult(
                passed=False,
                message=f"Created path '{f}' is a directory, not a file. Use write_file or create_file for files.",
                missing_files=[f],
            )

    problems, missing_files = _check_file_references(workspace, all_files)
    if problems:
        return VerificationResult(
            passed=False,
            message=" ".join(problems),
            missing_files=missing_files,
        )

    # Optional runtime verification for static sites
    if verify_runtime:
        try:
            runtime_passed, runtime_message, runtime_missing = await _verify_static_site_runtime(
                workspace,
                all_files,
                runtime_readiness_timeout,
                runtime_port,
            )
            if not runtime_passed:
                return VerificationResult(
                    passed=False,
                    message=f"Runtime verification failed: {runtime_message}",
                    missing_files=runtime_missing,
                )
        except Exception as exc:
            return VerificationResult(
                passed=False,
                message=f"Runtime verification error: {exc}",
                missing_files=[],
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


def _check_file_references(workspace: Path, file_paths: set[str]) -> tuple[list[str], list[str]]:
    """Validate local references. Existing-but-directory and empty files fail.
    Returns (problem_messages, missing_filenames)."""
    problems: list[str] = []
    missing_files: list[str] = []

    def _add(message: str, missing_filename: str | None = None) -> None:
        if message not in problems:
            problems.append(message)
        if missing_filename and missing_filename not in missing_files:
            missing_files.append(missing_filename)

    for file_path_str in sorted(file_paths):
        file_path = workspace / file_path_str
        if not file_path.exists():
            continue
        if file_path.is_dir():
            _add(f"'{file_path_str}' exists but is a directory, not a file", file_path_str)
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
            _add(f"'{file_path_str}' is empty", file_path_str)
        # Validate basic HTML structure for HTML files
        if file_path.suffix.lower() in {".html", ".htm"}:
            html_issue = _validate_html_structure(content)
            if html_issue:
                _add(f"'{file_path_str}': {html_issue}", file_path_str)
        file_dir = file_path.parent
        for ref in _extract_file_references(content, file_path.suffix.lower()):
            referenced_path = (file_dir / ref).resolve()
            try:
                referenced_path.relative_to(workspace.resolve())
            except ValueError:
                continue
            issue = _path_problem(workspace.resolve(), referenced_path)
            if issue:
                # Extract the filename from the issue message for missing_files
                missing_name = _extract_filename_from_issue(issue)
                _add(issue, missing_name)
    return problems, missing_files


def _extract_filename_from_issue(issue: str) -> str | None:
    """Extract the filename from an issue message."""
    import re
    # Match patterns like "missing file 'styles.css'" or "'styles.css' is empty" or "'styles.css' exists but is a directory"
    match = re.search(r"'([^']+)'", issue)
    if match:
        return match.group(1)
    return None


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
