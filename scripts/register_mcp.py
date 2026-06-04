#!/usr/bin/env python3
"""Safely merge the comsol-clippy MCP server into Claude client config files.

Merges into `mcpServers["comsol-clippy"]` without clobbering other entries
(e.g. an existing `legalgpt`). Writes atomically and keeps a .bak.

Usage:
    register_mcp.py --command <cmd> (--args <json-array> | --arg <value> --arg <value> ...) [--cwd <dir>] [--target <path> ...]

If no --target is given, sensible defaults for the current OS are auto-detected.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

SERVER_KEY = "comsol-clippy"


def default_targets() -> list[Path]:
    targets: list[Path] = []
    if os.name == "nt":  # native Windows
        appdata = os.environ.get("APPDATA")
        if appdata:
            targets.append(Path(appdata) / "Claude" / "claude_desktop_config.json")
        home = Path.home()
        targets.append(home / ".claude.json")  # Claude Code (Windows)
    else:  # Linux / WSL
        home = Path.home()
        targets.append(home / ".config" / "claude" / "claude_desktop_config.json")
        targets.append(home / ".claude.json")  # Claude Code
        # If launched from Windows-side Claude Desktop into WSL, also try the
        # Windows Claude Desktop config via /mnt/c.
        win_user = os.environ.get("WIN_USER")
        if win_user:
            win_cfg = Path(f"/mnt/c/Users/{win_user}/AppData/Roaming/Claude/claude_desktop_config.json")
            targets.append(win_cfg)
    return targets


def _write_atomic(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def merge_into(path: Path, entry: dict) -> str:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return f"skip (could not create parent dir: {e}): {path}"

    data: dict = {}
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            return f"skip (unreadable: {e}): {path}"
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))

    servers = data.setdefault("mcpServers", {})
    existing = servers.get(SERVER_KEY)
    servers[SERVER_KEY] = entry

    _write_atomic(path, data)
    verb = "updated" if existing else "added"
    others = [k for k in servers if k != SERVER_KEY]
    return f"{verb} in {path} (preserved: {others or 'none'})"


def remove_from(path: Path) -> str:
    """Remove our SERVER_KEY entry, preserving every other server. Idempotent."""
    if not path.exists():
        return f"skip (not present): {path}"
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        return f"skip (unreadable: {e}): {path}"

    servers = data.get("mcpServers", {})
    if SERVER_KEY not in servers:
        return f"already absent in {path}"
    shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    del servers[SERVER_KEY]
    _write_atomic(path, data)
    others = list(servers)
    return f"removed from {path} (preserved: {others or 'none'})"


def parse_server_args(args_json: str | None, repeated_args: list[str]) -> list[str]:
    if repeated_args:
        return repeated_args
    if not args_json:
        raise ValueError("missing server args")
    try:
        raw = json.loads(args_json)
    except json.JSONDecodeError:
        # PowerShell native command invocation can strip the inner quotes from a
        # JSON array argument, turning ["main.py","serve"] into [main.py,serve].
        # Accept that legacy form so old callers still register correctly.
        text = args_json.strip()
        if text.startswith("[") and text.endswith("]"):
            parts = [part.strip().strip('"\'') for part in text[1:-1].split(",")]
            raw = [part for part in parts if part]
        else:
            raise ValueError("--args must decode to a JSON array of strings") from None
    if not isinstance(raw, list) or not all(isinstance(x, str) for x in raw):
        raise ValueError("--args must decode to a JSON array of strings")
    return raw


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--command", help="server command (required unless --remove)")
    ap.add_argument("--args", help="JSON array of args (required unless --remove)")
    ap.add_argument("--arg", action="append", default=[], help="one server arg; may be passed multiple times")
    ap.add_argument("--cwd", default=None)
    ap.add_argument("--target", action="append", default=[], help="config path(s)")
    ap.add_argument("--remove", action="store_true", help="unregister the server instead of adding it")
    a = ap.parse_args()

    targets = [Path(t) for t in a.target] or default_targets()

    if a.remove:
        for t in targets:
            print(f"[register] {remove_from(t)}")
        return

    if not a.command or (not a.args and not a.arg):
        ap.error("--command and either --args or at least one --arg are required unless --remove is given")

    try:
        server_args = parse_server_args(a.args, a.arg)
    except ValueError as e:
        ap.error(str(e))

    entry: dict = {"command": a.command, "args": server_args}
    if a.cwd:
        entry["cwd"] = a.cwd

    print(f"[register] entry: {json.dumps(entry)}", file=sys.stderr)
    success = False
    for t in targets:
        msg = merge_into(t, entry)
        print(f"[register] {msg}")
        if msg.startswith("added") or msg.startswith("updated"):
            success = True
    if not success:
        raise SystemExit("[register] ERROR: could not register in any Claude config target")


if __name__ == "__main__":
    main()
