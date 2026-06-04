"""Tiny newline-delimited JSON protocol shared by the daemon and the stdio shim.

One request = one JSON object on a single line, terminated by ``\n``. One response
likewise. Keeping it stdlib-only (json + sockets) means the thin shim never has to
import torch/chromadb, which is the whole point: the shim stays ~tens of MB while a
single daemon holds the one ~700 MB model.

Wire shapes
-----------
request:  {"method": "search" | "list_sources" | "ping", "params": {...}}
response: {"ok": true,  "result": <json>}            on success
          {"ok": false, "error": "<message>"}        on failure
"""
from __future__ import annotations

import json
import socket

# Framing limit so a corrupt peer can't make us buffer unboundedly.
MAX_LINE_BYTES = 8 * 1024 * 1024


def send_json(sock: socket.socket, obj: dict) -> None:
    """Serialize ``obj`` and write it as one newline-terminated line."""
    data = json.dumps(obj, separators=(",", ":")).encode("utf-8") + b"\n"
    sock.sendall(data)


def recv_json(sock: socket.socket) -> dict | None:
    """Read one newline-terminated JSON line. Returns None on clean EOF.

    Raises ValueError on oversized or malformed input so callers can fail loudly
    rather than hang.
    """
    buf = bytearray()
    while True:
        chunk = sock.recv(65536)
        if not chunk:
            if not buf:
                return None
            raise ValueError("connection closed mid-message")
        buf.extend(chunk)
        nl = buf.find(b"\n")
        if nl != -1:
            line = bytes(buf[:nl])
            return json.loads(line.decode("utf-8"))
        if len(buf) > MAX_LINE_BYTES:
            raise ValueError("message exceeded MAX_LINE_BYTES without a newline")
