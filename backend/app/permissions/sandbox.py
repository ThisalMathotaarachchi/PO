"""Workspace path confinement. Prevents traversal, absolute escape, and symlink escape."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel


class PathResolutionError(ValueError):
    def __init__(self, message: str, *, code: str = "path_error") -> None:
        super().__init__(message)
        self.code = code


class ResolvedPath(BaseModel):
    requested: str
    absolute: Path
    relative: str
    is_dir: bool = False
    exists: bool = False


class PathSandbox:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()

    def contains(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self.workspace)
            return True
        except ValueError:
            return False

    def resolve(self, requested: str, *, must_exist: bool = False) -> ResolvedPath:
        if requested is None or str(requested).strip() == "":
            raise PathResolutionError("Path is required", code="invalid_arguments")

        raw = str(requested).strip()
        # Reject UNC and drive-letter escapes unless they resolve inside the workspace
        candidate = Path(raw)
        if candidate.is_absolute():
            resolved = candidate.resolve()
        else:
            # Normalize .. and mixed separators before joining
            resolved = (self.workspace / raw).resolve()

        try:
            relative = resolved.relative_to(self.workspace)
        except ValueError as exc:
            raise PathResolutionError(
                "Path is outside the authorized workspace",
                code="permission_denied",
            ) from exc

        exists = resolved.exists()
        if must_exist and not exists:
            raise PathResolutionError(f"Path does not exist: {relative.as_posix()}", code="unavailable")

        # If a symlink exists, the resolved target must still be inside the workspace
        if exists:
            try:
                resolved.relative_to(self.workspace)
            except ValueError as exc:
                raise PathResolutionError(
                    "Resolved path escapes the authorized workspace",
                    code="permission_denied",
                ) from exc

        return ResolvedPath(
            requested=raw,
            absolute=resolved,
            relative=relative.as_posix(),
            is_dir=resolved.is_dir() if exists else False,
            exists=exists,
        )
