"""Detect project structure and technology stack without loading all files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

MANIFEST_FILES = (
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "pyproject.toml",
    "requirements.txt",
    "Pipfile",
    "setup.py",
    "tsconfig.json",
    "vite.config.ts",
    "vite.config.js",
    "vite.config.mts",
    "dockerfile",
    "Dockerfile",
    "README.md",
    "README.txt",
    "go.mod",
    "Cargo.toml",
    "pom.xml",
)

SOURCE_HINTS = ("src", "app", "lib", "backend", "frontend", "server", "client")
TEST_HINTS = ("tests", "test", "__tests__", "spec")


class ProjectProfile(BaseModel):
    root: str
    name: str
    languages: list[str] = Field(default_factory=list)
    frameworks: list[str] = Field(default_factory=list)
    manifests: list[str] = Field(default_factory=list)
    source_dirs: list[str] = Field(default_factory=list)
    test_dirs: list[str] = Field(default_factory=list)
    docs: list[str] = Field(default_factory=list)
    entry_points: list[str] = Field(default_factory=list)
    summary: str = ""

    def as_prompt(self) -> str:
        parts = [
            f"Project: {self.name}",
            f"Languages: {', '.join(self.languages) or 'unknown'}",
            f"Frameworks: {', '.join(self.frameworks) or 'none detected'}",
            f"Manifests: {', '.join(self.manifests) or 'none'}",
            f"Source dirs: {', '.join(self.source_dirs) or '.'}",
            f"Tests: {', '.join(self.test_dirs) or 'none detected'}",
        ]
        return "\n".join(parts)


def inspect_project(root: Path, ignore: set[str] | None = None) -> ProjectProfile:
    ignore = ignore or set()
    name = root.name
    languages: set[str] = set()
    frameworks: list[str] = []
    manifests: list[str] = []
    source_dirs: list[str] = []
    test_dirs: list[str] = []
    docs: list[str] = []
    entry_points: list[str] = []

    if not root.exists():
        return ProjectProfile(root=str(root), name=name, summary="Workspace does not exist")

    for item in root.iterdir():
        if item.name in ignore:
            continue
        lname = item.name
        if item.is_file():
            lower = lname.lower()
            if lower in {m.lower() for m in MANIFEST_FILES} or lname in MANIFEST_FILES:
                manifests.append(item.name)
            if lower.startswith("readme"):
                docs.append(item.name)
            if lname in {"main.py", "app.py", "index.js", "index.ts", "main.ts", "manage.py"}:
                entry_points.append(item.name)
            languages.update(_lang_from_suffix(item.suffix))
        elif item.is_dir():
            if lname.lower() in SOURCE_HINTS:
                source_dirs.append(item.name)
            if lname.lower() in TEST_HINTS:
                test_dirs.append(item.name)

    if "package.json" in manifests:
        languages.add("javascript")
        package = _read_text(root / "package.json")
        if "react" in package:
            frameworks.append("react")
        if "vite" in package:
            frameworks.append("vite")
        if "typescript" in package or (root / "tsconfig.json").exists():
            languages.add("typescript")
            frameworks.append("typescript")
    if any(m in manifests for m in ("pyproject.toml", "requirements.txt", "setup.py")):
        languages.add("python")
        if (root / "pyproject.toml").exists() and "fastapi" in _read_text(root / "pyproject.toml").lower():
            frameworks.append("fastapi")

    # shallow language scan of top-level and src
    for directory in [root, *[root / s for s in source_dirs]]:
        if not directory.exists():
            continue
        for child in directory.iterdir():
            if child.is_file():
                languages.update(_lang_from_suffix(child.suffix))

    profile = ProjectProfile(
        root=str(root),
        name=name,
        languages=sorted(languages),
        frameworks=frameworks,
        manifests=manifests,
        source_dirs=source_dirs,
        test_dirs=test_dirs,
        docs=docs,
        entry_points=entry_points,
    )
    profile.summary = profile.as_prompt()
    return profile


def _lang_from_suffix(suffix: str) -> set[str]:
    mapping = {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".rs": "rust",
        ".go": "go",
        ".java": "java",
        ".cs": "csharp",
    }
    lang = mapping.get(suffix.lower())
    return {lang} if lang else set()


def _read_text(path: Path, limit: int = 8000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""
