from __future__ import annotations

from enum import StrEnum


class TaskState(StrEnum):
    IDLE = "IDLE"
    UNDERSTANDING = "UNDERSTANDING"
    EXPLORING = "EXPLORING"
    PLANNING = "PLANNING"
    EXECUTING = "EXECUTING"
    TESTING = "TESTING"
    DEBUGGING = "DEBUGGING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    ERROR = "ERROR"
    CANCELLED = "CANCELLED"


TERMINAL_STATES = {TaskState.COMPLETED, TaskState.ERROR, TaskState.CANCELLED}


def state_for_tool(tool: str, success: bool) -> TaskState:
    if tool in {"list_directory", "read_file", "search_files", "search_code", "find_symbol", "find_references", "file_exists"}:
        return TaskState.EXPLORING
    if tool in {"git_status", "git_diff", "git_log", "git_branch"}:
        return TaskState.EXPLORING
    if tool in {"write_file", "create_file", "delete_file", "rename_file", "delete_directory"}:
        return TaskState.EXECUTING
    if tool in {"run_tests"}:
        return TaskState.TESTING if not success else TaskState.VERIFYING
    if tool in {"run_build", "run_linter", "run_terminal"}:
        return TaskState.EXECUTING if success else TaskState.DEBUGGING
    return TaskState.EXECUTING
