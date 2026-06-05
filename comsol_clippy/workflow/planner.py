"""Pluggable planner adapters for :class:`WorkflowAgent`.

The agent is intentionally model-agnostic: it builds a grounded prompt and hands it to a
``WorkflowPlanner`` callable. ``CommandPlanner`` is the default concrete adapter — it
forwards the prompt to an external command (e.g. ``claude -p``) over stdin and reads the
JSON plan back from stdout. Stdlib only, so it adds no dependencies and stays out of the
heavy import path.
"""
from __future__ import annotations

import shlex
import subprocess
from typing import Any


class PlannerError(RuntimeError):
    """Raised when the external planner command fails to produce a plan."""


class CommandPlanner:
    """Run an external command as the planner, piping the prompt on stdin.

    ``command`` may be a shell-style string (split with :func:`shlex.split`) or an
    explicit argv list. The command's stdout is returned verbatim; the
    :class:`WorkflowAgent` is responsible for extracting the JSON plan from it (so
    fenced/prose-wrapped responses are handled by the existing parser).
    """

    def __init__(self, command: str | list[str], *, timeout: float | None = 600.0):
        if isinstance(command, str):
            argv = shlex.split(command)
        else:
            argv = list(command)
        if not argv:
            raise ValueError("planner command must not be empty")
        self.argv = argv
        self.timeout = timeout

    def __call__(self, prompt: str, context: Any) -> str:
        try:
            completed = subprocess.run(
                self.argv,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except FileNotFoundError as exc:
            raise PlannerError(f"planner command not found: {self.argv[0]}") from exc
        except subprocess.TimeoutExpired as exc:
            raise PlannerError(f"planner command timed out after {self.timeout}s") from exc

        if completed.returncode != 0:
            stderr = (completed.stderr or "").strip()
            raise PlannerError(
                f"planner command exited with code {completed.returncode}"
                + (f": {stderr}" if stderr else "")
            )
        if not completed.stdout.strip():
            raise PlannerError("planner command produced no output")
        return completed.stdout
