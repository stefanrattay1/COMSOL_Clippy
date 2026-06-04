"""Tests for the Claude-config merge/remove logic (scripts/register_mcp.py).

Pure JSON file manipulation — no heavy deps.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "register_mcp", Path(__file__).resolve().parent.parent / "scripts" / "register_mcp.py"
)
register_mcp = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(register_mcp)


def _write(p: Path, data: dict) -> None:
    p.write_text(json.dumps(data))


def test_merge_preserves_other_servers(tmp_path):
    cfg = tmp_path / "cfg.json"
    _write(cfg, {"mcpServers": {"legalgpt": {"command": "x", "args": []}}})
    register_mcp.merge_into(cfg, {"command": "py", "args": ["main.py", "serve"]})
    data = json.loads(cfg.read_text())
    assert set(data["mcpServers"]) == {"legalgpt", "comsol-clippy"}
    assert data["mcpServers"]["comsol-clippy"]["args"] == ["main.py", "serve"]


def test_merge_is_idempotent_overwrite(tmp_path):
    cfg = tmp_path / "cfg.json"
    _write(cfg, {})
    register_mcp.merge_into(cfg, {"command": "a", "args": []})
    register_mcp.merge_into(cfg, {"command": "b", "args": []})
    data = json.loads(cfg.read_text())
    assert list(data["mcpServers"]) == ["comsol-clippy"]
    assert data["mcpServers"]["comsol-clippy"]["command"] == "b"


def test_remove_deletes_only_our_key(tmp_path):
    cfg = tmp_path / "cfg.json"
    _write(
        cfg,
        {"mcpServers": {"legalgpt": {"command": "x", "args": []}, "comsol-clippy": {"command": "y", "args": []}}},
    )
    msg = register_mcp.remove_from(cfg)
    data = json.loads(cfg.read_text())
    assert "removed" in msg
    assert list(data["mcpServers"]) == ["legalgpt"]


def test_remove_is_idempotent(tmp_path):
    cfg = tmp_path / "cfg.json"
    _write(cfg, {"mcpServers": {"legalgpt": {"command": "x", "args": []}}})
    msg = register_mcp.remove_from(cfg)
    assert "already absent" in msg
    # File untouched aside from being valid.
    assert list(json.loads(cfg.read_text())["mcpServers"]) == ["legalgpt"]


def test_remove_missing_file_is_safe(tmp_path):
    cfg = tmp_path / "nope.json"
    assert "not present" in register_mcp.remove_from(cfg)
