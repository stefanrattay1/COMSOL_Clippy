"""Daemon/shim plumbing tests — no torch/chromadb (CI stays light).

We exercise the wire protocol and the daemon's request dispatch by injecting a
fake engine, so nothing here loads the embedding model or ChromaDB.
"""
from __future__ import annotations

import socket
import threading

import pytest

from comsol_clippy.protocol import MAX_LINE_BYTES, recv_json, send_json


def _socketpair():
    a, b = socket.socketpair()
    return a, b


def test_protocol_roundtrip():
    a, b = _socketpair()
    try:
        send_json(a, {"method": "search", "params": {"query": "x", "top_k": 2}})
        got = recv_json(b)
        assert got == {"method": "search", "params": {"query": "x", "top_k": 2}}
    finally:
        a.close()
        b.close()


def test_protocol_clean_eof_returns_none():
    a, b = _socketpair()
    a.close()  # peer hangs up before sending anything
    try:
        assert recv_json(b) is None
    finally:
        b.close()


def test_protocol_rejects_oversized_line():
    a, b = _socketpair()
    try:
        # Send more than MAX_LINE_BYTES with no newline; recv_json must bail.
        blob = b"x" * (MAX_LINE_BYTES + 10)

        def pump():
            try:
                a.sendall(blob)
            except OSError:
                pass

        t = threading.Thread(target=pump, daemon=True)
        t.start()
        with pytest.raises(ValueError):
            recv_json(b)
    finally:
        a.close()
        b.close()


class _FakeEngine:
    def search(self, query, top_k=5):
        return [{"query": query, "top_k": top_k}]

    def list_sources(self):
        return [{"source": "A.pdf", "pages": 3, "chunks": 9}]


def _make_daemon():
    # Build a _Daemon without running load_config()/Engine.__init__: bypass __init__
    # and wire in the fake engine + the bits handle() touches.
    from comsol_clippy.daemon import _Daemon

    d = _Daemon.__new__(_Daemon)
    d.engine = _FakeEngine()
    return d


def test_daemon_dispatch_ping():
    d = _make_daemon()
    assert d.handle("ping", {}) == {"ok": True, "result": "pong"}


def test_daemon_dispatch_search():
    d = _make_daemon()
    resp = d.handle("search", {"query": "heat", "top_k": 3})
    assert resp == {"ok": True, "result": [{"query": "heat", "top_k": 3}]}


def test_daemon_dispatch_list_sources():
    d = _make_daemon()
    resp = d.handle("list_sources", {})
    assert resp["ok"] is True
    assert resp["result"][0]["source"] == "A.pdf"


def test_daemon_unknown_method():
    d = _make_daemon()
    resp = d.handle("frobnicate", {})
    assert resp["ok"] is False
    assert "unknown method" in resp["error"]


def test_daemon_errors_are_wrapped_not_raised():
    d = _make_daemon()

    class Boom:
        def search(self, *a, **k):
            raise RuntimeError("kaboom")

    d.engine = Boom()
    resp = d.handle("search", {"query": "q"})
    assert resp["ok"] is False
    assert "RuntimeError" in resp["error"] and "kaboom" in resp["error"]


def test_is_running_false_without_af_unix(monkeypatch):
    """On a platform with no AF_UNIX (native Windows), is_running short-circuits."""
    import socket as socket_mod

    from comsol_clippy import daemon

    monkeypatch.delattr(socket_mod, "AF_UNIX", raising=False)
    # Should return False without touching the filesystem/socket.
    assert daemon.is_running(object()) is False


def test_daemon_supported_requires_posix_and_af_unix(monkeypatch):
    from comsol_clippy import server

    monkeypatch.setattr("os.name", "nt")
    assert server._daemon_supported() is False


def test_code_fingerprint_tracks_newest_mtime(tmp_path, monkeypatch):
    """fingerprint must rise when a watched file is modified."""
    from comsol_clippy import daemon

    # Point PROJECT_ROOT at a temp dir holding a fake config.toml.
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text("x = 1\n")
    monkeypatch.setattr(daemon, "PROJECT_ROOT", tmp_path)

    import os
    import time

    fp1 = daemon.code_fingerprint(object())
    # Bump the config mtime to far-future so it dominates the package .py mtimes too.
    future = time.time() + 10_000
    os.utime(cfg_file, (future, future))
    fp2 = daemon.code_fingerprint(object())
    assert fp2 > fp1
    assert fp2 >= future - 1
