#!/usr/bin/env python3
"""Safely merge the comsol-clippy MCP server into Claude client config files.

Merges into `mcpServers["comsol-clippy"]` without clobbering other entries
(e.g. an existing `legalgpt`). Writes atomically and keeps a .bak.

Usage:
    register_mcp.py --command <cmd> --args <json-array> [--cwd <dir>] [--target <path> ...]

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


def merge_into(path: Path, entry: dict) -> str:
    if not path.parent.exists():
        return f"skip (parent dir missing): {path}"

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

    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)
    verb = "updated" if existing else "added"
    others = [k for k in servers if k != SERVER_KEY]
    return f"{verb} in {path} (preserved: {others or 'none'})"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--command", required=True)
    ap.add_argument("--args", required=True, help="JSON array of args")
    ap.add_argument("--cwd", default=None)
    ap.add_argument("--target", action="append", default=[], help="config path(s)")
    a = ap.parse_args()

    entry: dict = {"command": a.command, "args": json.loads(a.args)}
    if a.cwd:
        entry["cwd"] = a.cwd

    targets = [Path(t) for t in a.target] or default_targets()
    print(f"[register] entry: {json.dumps(entry)}", file=sys.stderr)
    for t in targets:
        print(f"[register] {merge_into(t, entry)}")


if __name__ == "__main__":
    main()
