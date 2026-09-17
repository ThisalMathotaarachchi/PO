"""Permission policy: GREEN (autonomous), YELLOW (approval), RED (blocked / explicit)."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel

from app.permissions.sandbox import PathSandbox


class PermissionLevel(StrEnum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


class PermissionDecision(BaseModel):
    level: PermissionLevel
    allowed: bool
    requires_approval: bool
    reason: str
    code: str = "ok"


_SENSITIVE_NAME_RE = re.compile(
    r"(^|\.|/)("
    r"id_rsa|id_ed25519|id_ecdsa|\.pem|\.pfx|\.p12|"
    r"credentials|secrets?|\.env(\..+)?|"
    r"authorized_keys|known_hosts"
    r")$",
    re.IGNORECASE,
)

_PRIVATE_KEY_HINTS = re.compile(
    r"(id_rsa|id_ed25519|\.pem$|\.key$|credentials\.json|secrets?\.(json|ya?ml))$",
    re.IGNORECASE,
)

_DESTRUCTIVE_CMD = re.compile(
    r"\b(format|mkfs|diskpart|reg\s+delete|shutdown|rmdir\s+/s|rm\s+-rf|del\s+/s|rd\s+/s)\b",
    re.IGNORECASE,
)

_FINANCIAL_LIVE = re.compile(
    r"\b("
    r"place_order|submit_order|place_trade|live_trade|live_order|"
    r"market_order|limit_order|send_order|execute_trade|execute_order|"
    r"buy_market|sell_market|transfer_funds|wire_transfer|"
    r"disable_safety|bypass_safety|enable_live_trading"
    r")\b",
    re.IGNORECASE,
)

_FINANCIAL_BYPASS = re.compile(
    r"\b(paper[_-]?trading|dry[_-]?run|simulate)\s*=\s*(false|0|off)\b|"
    r"\blive[_-]?trading\s*=\s*(true|1|on)\b|"
    r"\bsafety[_-]?(lock|switch|control)s?\s*=\s*(false|0|off)\b",
    re.IGNORECASE,
)

_YELLOW_CMD = re.compile(
    r"\b(pip\s+uninstall|npm\s+unpublish|"
    r"git\s+reset\s+--hard|git\s+clean\s+-fd|git\s+clean\s+-f|"
    r"git\s+push|"
    r"icacls|attrib\s+\+|Set-ExecutionPolicy)\b",
    re.IGNORECASE,
)

_SOURCE_EXT = {
    ".py",
    ".pyi",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".json",
    ".md",
    ".txt",
    ".toml",
    ".yml",
    ".yaml",
    ".css",
    ".html",
    ".css",
    ".rs",
    ".go",
    ".java",
    ".cs",
    ".sql",
    ".ini",
    ".cfg",
}


class PermissionPolicy:
    """Classifies tool invocations. Model output is untrusted."""

    def __init__(self, sandbox: PathSandbox, *, auto_approve_yellow: bool = False) -> None:
        self.sandbox = sandbox
        self.auto_approve_yellow = auto_approve_yellow
        self._approved: set[str] = set()

    def approve(self, fingerprint: str) -> None:
        self._approved.add(fingerprint)

    def fingerprint(self, tool: str, arguments: dict[str, Any]) -> str:
        return f"{tool}:{sorted(arguments.items())}"

    def evaluate(self, tool: str, arguments: dict[str, Any]) -> PermissionDecision:
        try:
            decision = self._classify(tool, arguments)
        except Exception as exc:
            return PermissionDecision(
                level=PermissionLevel.RED,
                allowed=False,
                requires_approval=False,
                reason=str(exc),
                code="permission_denied",
            )

        if decision.level == PermissionLevel.RED:
            return decision

        if decision.level == PermissionLevel.YELLOW:
            fp = self.fingerprint(tool, arguments)
            if self.auto_approve_yellow or fp in self._approved:
                return PermissionDecision(
                    level=PermissionLevel.YELLOW,
                    allowed=True,
                    requires_approval=False,
                    reason=decision.reason,
                    code="ok",
                )
            return PermissionDecision(
                level=PermissionLevel.YELLOW,
                allowed=False,
                requires_approval=True,
                reason=decision.reason,
                code="approval_required",
            )
        return decision

    def _classify(self, tool: str, arguments: dict[str, Any]) -> PermissionDecision:
        text_blob = " ".join(str(v) for v in arguments.values())
        if _FINANCIAL_LIVE.search(tool) or _FINANCIAL_LIVE.search(text_blob) or _FINANCIAL_BYPASS.search(text_blob):
            return PermissionDecision(
                level=PermissionLevel.RED,
                allowed=False,
                requires_approval=False,
                reason="Real-money trading and safety-control bypass are blocked",
                code="financial_blocked",
            )

        if tool in {"list_directory", "read_file", "file_exists", "search_files", "search_code",
                    "find_symbol", "find_references", "git_status", "git_diff", "git_log", "git_branch"}:
            return self._classify_read(tool, arguments)

        if tool in {"write_file", "create_file", "rename_file"}:
            return self._classify_write(tool, arguments)

        if tool == "delete_file":
            return self._classify_delete(arguments)

        if tool == "delete_directory":
            return self._classify_delete_directory(arguments)

        if tool == "create_directory":
            return self._classify_create_directory(arguments)

        if tool in {"run_terminal", "run_tests", "run_build", "run_linter"}:
            return self._classify_command(tool, arguments)

        return PermissionDecision(
            level=PermissionLevel.RED,
            allowed=False,
            requires_approval=False,
            reason=f"Unknown tool: {tool}",
            code="invalid_arguments",
        )

    def _classify_read(self, tool: str, arguments: dict[str, Any]) -> PermissionDecision:
        path = arguments.get("path")
        if path:
            resolved = self.sandbox.resolve(str(path))
            name = resolved.relative.replace("\\", "/")
            if _PRIVATE_KEY_HINTS.search(name) or name.endswith(".pem"):
                return PermissionDecision(
                    level=PermissionLevel.RED,
                    allowed=False,
                    requires_approval=False,
                    reason="Reading private keys or credential stores is blocked",
                    code="sensitive_blocked",
                )
            if _SENSITIVE_NAME_RE.search(name) or name.endswith(".env"):
                return PermissionDecision(
                    level=PermissionLevel.YELLOW,
                    allowed=False,
                    requires_approval=True,
                    reason="Reading sensitive configuration requires approval",
                    code="approval_required",
                )
        return _green("autonomous read/search")

    def _classify_write(self, tool: str, arguments: dict[str, Any]) -> PermissionDecision:
        path = str(arguments.get("path") or "")
        content = str(arguments.get("content") or arguments.get("new_path") or "")
        blob = f"{path} {content}"
        if _FINANCIAL_BYPASS.search(blob) or _FINANCIAL_LIVE.search(blob):
            return PermissionDecision(
                level=PermissionLevel.RED,
                allowed=False,
                requires_approval=False,
                reason="Modifying live-trading safety controls is blocked",
                code="financial_blocked",
            )
        resolved = self.sandbox.resolve(path)
        name = resolved.relative.replace("\\", "/")
        if _PRIVATE_KEY_HINTS.search(name):
            return PermissionDecision(
                level=PermissionLevel.RED,
                allowed=False,
                requires_approval=False,
                reason="Writing credential or key files is blocked",
                code="sensitive_blocked",
            )
        if name.endswith(".env") or "security" in name.lower() and name.endswith((".yml", ".yaml", ".json")):
            return PermissionDecision(
                level=PermissionLevel.YELLOW,
                allowed=False,
                requires_approval=True,
                reason="Modifying sensitive configuration requires approval",
                code="approval_required",
            )
        suffix = resolved.absolute.suffix.lower()
        if suffix and suffix not in _SOURCE_EXT and suffix in {".exe", ".dll", ".sys", ".bat", ".cmd", ".ps1"}:
            return PermissionDecision(
                level=PermissionLevel.YELLOW,
                allowed=False,
                requires_approval=True,
                reason="Writing executable/script files requires approval",
                code="approval_required",
            )
        return _green("autonomous source edit")

    def _classify_delete(self, arguments: dict[str, Any]) -> PermissionDecision:
        path = str(arguments.get("path") or ".")
        resolved = self.sandbox.resolve(path)
        rel = resolved.relative.replace("\\", "/")
        if rel in {"", ".", "/"}:
            return PermissionDecision(
                level=PermissionLevel.RED,
                allowed=False,
                requires_approval=False,
                reason="Deleting the entire workspace is blocked",
                code="destructive_blocked",
            )
        if resolved.exists and resolved.absolute.is_dir():
            return PermissionDecision(
                level=PermissionLevel.YELLOW,
                allowed=False,
                requires_approval=True,
                reason="Directory deletion requires approval",
                code="approval_required",
            )
        return _green("delete single file")

    def _classify_delete_directory(self, arguments: dict[str, Any]) -> PermissionDecision:
        """delete_directory is an explicit agent tool — always GREEN inside workspace."""
        path = str(arguments.get("path") or ".")
        resolved = self.sandbox.resolve(path)
        rel = resolved.relative.replace("\\", "/")
        if rel in {"", ".", "/"}:
            return PermissionDecision(
                level=PermissionLevel.RED,
                allowed=False,
                requires_approval=False,
                reason="Deleting the entire workspace root is blocked",
                code="destructive_blocked",
            )
        return _green("delete directory in workspace")

    def _classify_create_directory(self, arguments: dict[str, Any]) -> PermissionDecision:
        """create_directory is an autonomous workspace operation — always GREEN."""
        return _green("create directory in workspace")

    def _classify_command(self, tool: str, arguments: dict[str, Any]) -> PermissionDecision:
        command = str(arguments.get("command") or "")
        if tool in {"run_tests", "run_build", "run_linter"} and not command:
            return _green(f"autonomous {tool}")
        if _DESTRUCTIVE_CMD.search(command):
            return PermissionDecision(
                level=PermissionLevel.RED,
                allowed=False,
                requires_approval=False,
                reason="Destructive system command is blocked",
                code="destructive_blocked",
            )
        if _FINANCIAL_LIVE.search(command) or _FINANCIAL_BYPASS.search(command):
            return PermissionDecision(
                level=PermissionLevel.RED,
                allowed=False,
                requires_approval=False,
                reason="Real-money trading commands are blocked",
                code="financial_blocked",
            )
        if _YELLOW_CMD.search(command):
            return PermissionDecision(
                level=PermissionLevel.YELLOW,
                allowed=False,
                requires_approval=True,
                reason="Potentially destructive command requires approval",
                code="approval_required",
            )
        # Disallow path escape via command
        if re.search(r"(^|\s)(cd|pushd)\s+[A-Za-z]:\\", command) or ".." in command.split():
            # cd to another drive is yellow/red; .. in args is often relative within workspace
            if re.search(r"\b(cd|pushd)\s+[A-Za-z]:\\", command, re.IGNORECASE):
                return PermissionDecision(
                    level=PermissionLevel.RED,
                    allowed=False,
                    requires_approval=False,
                    reason="Commands that leave the workspace are blocked",
                    code="permission_denied",
                )
        return _green("autonomous development command")


def _green(reason: str) -> PermissionDecision:
    return PermissionDecision(
        level=PermissionLevel.GREEN,
        allowed=True,
        requires_approval=False,
        reason=reason,
        code="ok",
    )
