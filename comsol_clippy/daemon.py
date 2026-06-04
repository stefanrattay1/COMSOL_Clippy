"""Long-lived search daemon: one process holds the single model + store.

Why this exists
---------------
The MCP transport is stdio, so every Claude window launches its own ``serve``
process. Loading the 1.5B model in each of those means N model copies (~700 MB
each) for N open windows. Instead, ``serve`` is now a thin shim that forwards
tool calls over a Unix socket to *this* daemon, which loads the model exactly
once and is shared by every window.

Lifecycle
---------
- Started on demand by the first shim (see ``client.ensure_daemon``); a file
  lock guarantees only one daemon spawns even under a simultaneous launch race.
- Prewarms the model on startup so the first real query is fast (latency/RAM
  balance: pay the load once, globally, instead of per window).
- Idle-exits after ``idle_timeout`` seconds with no connections, so the ~700 MB
  is reclaimed when you stop working. The next shim respawns it transparently.

Transport: a ThreadingMixIn UnixStreamServer speaking the newline-JSON
:mod:`comsol_clippy.protocol`. The model lives in the parent ``Engine`` whose
own lock already serializes the one-time load; queries are read-only.
"""
from __future__ import annotations

import hashlib
import os
import socket
import socketserver
import sys
import tempfile
import threading
import time
from pathlib import Path

from .config import PROJECT_ROOT, Config, load_config
from .protocol import recv_json, send_json
from .server import Engine

# Default: reclaim RAM after 30 min of no MCP windows talking to us.
DEFAULT_IDLE_TIMEOUT = 30 * 60


def runtime_dir() -> Path:
    """A native-Linux dir for the socket/lock/pid.

    These MUST live on a real Linux filesystem: AF_UNIX bind() fails with
    ``Errno 95 Operation not supported`` on /mnt/* DrvFs (Windows-drive) paths,
    which is where this project's data/ dir lives under WSL. We prefer
    $XDG_RUNTIME_DIR (tmpfs, user-private) and fall back to /tmp. A short hash of
    the project root keeps two checkouts from colliding on the same socket.
    """
    base = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    tag = hashlib.sha1(str(PROJECT_ROOT).encode()).hexdigest()[:10]
    d = Path(base) / f"comsol-clippy-{tag}"
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    return d


def socket_path(cfg: Config) -> Path:
    return runtime_dir() / "daemon.sock"


def lock_path(cfg: Config) -> Path:
    return runtime_dir() / "daemon.lock"


def pid_path(cfg: Config) -> Path:
    return runtime_dir() / "daemon.pid"


def code_fingerprint(cfg: Config) -> float:
    """Newest mtime across config.toml + the package source.

    The reaper compares this against the value captured at startup; if it grows
    (the user re-ran setup, edited config.toml, or pulled new code), the daemon
    self-exits so the next query respawns it running the current code. This is a
    safety net alongside setup's explicit restart.
    """
    pkg = Path(__file__).resolve().parent
    paths = [PROJECT_ROOT / "config.toml", *pkg.glob("*.py")]
    newest = 0.0
    for p in paths:
        try:
            newest = max(newest, p.stat().st_mtime)
        except OSError:
            pass
    return newest


class _Daemon:
    def __init__(self, cfg: Config, idle_timeout: float = DEFAULT_IDLE_TIMEOUT):
        self.cfg = cfg
        self.engine = Engine(cfg)
        self.idle_timeout = idle_timeout
        self._last_activity = time.monotonic()
        self._active = 0
        self._state_lock = threading.Lock()
        self._server: socketserver.UnixStreamServer | None = None
        self._start_fingerprint = code_fingerprint(cfg)

    # --- activity tracking so the idle reaper knows when we're busy ---
    def _enter(self) -> None:
        with self._state_lock:
            self._active += 1
            self._last_activity = time.monotonic()

    def _leave(self) -> None:
        with self._state_lock:
            self._active -= 1
            self._last_activity = time.monotonic()

    def _idle_seconds(self) -> float:
        with self._state_lock:
            if self._active > 0:
                return 0.0
            return time.monotonic() - self._last_activity

    def handle(self, method: str, params: dict) -> dict:
        """Dispatch one request to the shared engine. Returns a response dict."""
        try:
            if method == "ping":
                return {"ok": True, "result": "pong"}
            if method == "search":
                query = params["query"]
                top_k = int(params.get("top_k", 5))
                return {"ok": True, "result": self.engine.search(query, top_k=top_k)}
            if method == "list_sources":
                return {"ok": True, "result": self.engine.list_sources()}
            return {"ok": False, "error": f"unknown method: {method}"}
        except Exception as e:  # never leak a raw traceback over the wire
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    def _shutdown_async(self) -> None:
        if self._server is not None:
            threading.Thread(target=self._server.shutdown, daemon=True).start()

    def _reaper(self) -> None:
        poll = 30.0  # fixed cadence: also works when idle_timeout == 0 (never idle-exit)
        while True:
            time.sleep(poll)
            # 1) Reclaim RAM after a long idle.
            if self.idle_timeout > 0 and self._idle_seconds() >= self.idle_timeout:
                print(
                    f"[daemon] idle {self.idle_timeout}s — shutting down to free RAM.",
                    file=sys.stderr,
                )
                self._shutdown_async()
                return
            # 2) Self-exit if code/config changed, so the next query runs fresh code.
            #    Only when idle, so we never interrupt an in-flight query.
            if (
                code_fingerprint(self.cfg) > self._start_fingerprint
                and self._idle_seconds() > 0.0
            ):
                print(
                    "[daemon] code/config changed — restarting on next query.",
                    file=sys.stderr,
                )
                self._shutdown_async()
                return

    def serve_forever(self) -> None:
        sock_path = socket_path(self.cfg)
        sock_path.parent.mkdir(parents=True, exist_ok=True)
        # Stale socket from a crashed daemon would block bind(); remove it.
        try:
            sock_path.unlink()
        except FileNotFoundError:
            pass

        daemon_self = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self) -> None:
                daemon_self._enter()
                try:
                    while True:
                        try:
                            req = recv_json(self.connection)
                        except ValueError as e:
                            send_json(self.connection, {"ok": False, "error": str(e)})
                            return
                        if req is None:
                            return  # client hung up
                        resp = daemon_self.handle(
                            req.get("method", ""), req.get("params", {}) or {}
                        )
                        send_json(self.connection, resp)
                except (BrokenPipeError, ConnectionResetError):
                    return
                finally:
                    daemon_self._leave()

        class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
            daemon_threads = True
            allow_reuse_address = True

        self._server = Server(str(sock_path), Handler)
        # Lock the socket down to the current user.
        try:
            os.chmod(sock_path, 0o600)
        except OSError:
            pass

        # Record our pid so `stop-daemon` can signal us cleanly.
        pidfile = pid_path(self.cfg)
        try:
            pidfile.write_text(str(os.getpid()))
        except OSError:
            pidfile = None

        # Prewarm once, globally, so the first window's first query is fast.
        self.engine.prewarm_async()
        threading.Thread(target=self._reaper, name="idle-reaper", daemon=True).start()

        # Clean shutdown on `stop-daemon` (SIGTERM) so the socket/pid files go away.
        import signal

        def _on_term(_signum, _frame):
            threading.Thread(target=self._server.shutdown, daemon=True).start()

        try:
            signal.signal(signal.SIGTERM, _on_term)
        except ValueError:
            pass  # not on the main thread (e.g. under tests) — skip

        print(f"[daemon] listening on {sock_path}", file=sys.stderr)
        try:
            self._server.serve_forever()
        finally:
            for p in (sock_path, pidfile):
                if p is None:
                    continue
                try:
                    p.unlink()
                except FileNotFoundError:
                    pass
            print("[daemon] stopped.", file=sys.stderr)


def is_running(cfg: Config) -> bool:
    """Return True if a daemon is accepting connections on the socket."""
    if not hasattr(socket, "AF_UNIX"):
        return False  # native Windows: no daemon, in-process model is used instead
    sock_path = socket_path(cfg)
    if not sock_path.exists():
        return False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(2.0)
            s.connect(str(sock_path))
            send_json(s, {"method": "ping", "params": {}})
            resp = recv_json(s)
            return bool(resp and resp.get("ok"))
    except OSError:
        return False


def run_daemon(cfg: Config | None = None, idle_timeout: float = DEFAULT_IDLE_TIMEOUT) -> None:
    cfg = cfg or load_config()
    _Daemon(cfg, idle_timeout=idle_timeout).serve_forever()
