"""Client side of the daemon protocol: connect, auto-spawn, forward.

Used by the thin stdio shim (``serve``). Keeps to the stdlib so importing this
never drags in torch/chromadb — that weight lives only in the daemon.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from .config import Config
from .daemon import is_running, lock_path, runtime_dir, socket_path
from .protocol import recv_json, send_json

SPAWN_TIMEOUT = 90.0  # cold model load can take a while on CPU


class DaemonError(RuntimeError):
    pass


def _spawn_daemon(cfg: Config) -> None:
    """Launch a detached daemon process. Safe to call; bind() races resolve cleanly."""
    # Re-exec this same interpreter + entry point in `daemon` mode, fully detached
    # so it outlives the spawning shim (and thus outlives the Claude window).
    cmd = [sys.executable, "-m", "comsol_clippy.cli", "daemon"]
    # Send the daemon's stderr to a log file so a failed startup (e.g. a bad bind
    # or a model-load error) is diagnosable instead of vanishing into DEVNULL.
    log = runtime_dir() / "daemon.log"
    kwargs: dict = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": open(log, "ab", buffering=0),
        "cwd": str(Path(__file__).resolve().parent.parent),
    }
    if os.name == "posix":
        kwargs["start_new_session"] = True  # detach from our process group
    subprocess.Popen(cmd, **kwargs)


def ensure_daemon(cfg: Config) -> None:
    """Make sure a daemon is reachable, spawning one under a file lock if not.

    The lock guarantees that if several Claude windows launch at once, only one
    spawns the daemon; the rest fall through and connect to it.
    """
    if is_running(cfg):
        return

    lock = lock_path(cfg)
    lock.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        _acquire_lock(fd)
        # Re-check under the lock: another window may have spawned it already.
        if not is_running(cfg):
            _spawn_daemon(cfg)
            _wait_until_running(cfg)
    finally:
        _release_lock(fd)
        os.close(fd)


def _acquire_lock(fd: int) -> None:
    import fcntl

    fcntl.flock(fd, fcntl.LOCK_EX)


def _release_lock(fd: int) -> None:
    import fcntl

    fcntl.flock(fd, fcntl.LOCK_UN)


def _wait_until_running(cfg: Config) -> None:
    deadline = time.monotonic() + SPAWN_TIMEOUT
    while time.monotonic() < deadline:
        if is_running(cfg):
            return
        time.sleep(0.25)
    raise DaemonError(
        f"daemon did not become ready within {SPAWN_TIMEOUT:.0f}s "
        f"(socket: {socket_path(cfg)})"
    )


def call(cfg: Config, method: str, params: dict | None = None) -> object:
    """Send one request to the daemon and return its ``result``. Auto-spawns."""
    ensure_daemon(cfg)
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(SPAWN_TIMEOUT)
            s.connect(str(socket_path(cfg)))
            send_json(s, {"method": method, "params": params or {}})
            resp = recv_json(s)
    except OSError as e:
        raise DaemonError(f"could not reach daemon: {e}") from e
    if resp is None:
        raise DaemonError("daemon closed the connection without responding")
    if not resp.get("ok"):
        raise DaemonError(resp.get("error", "unknown daemon error"))
    return resp.get("result")
