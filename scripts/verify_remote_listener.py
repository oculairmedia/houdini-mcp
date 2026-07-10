#!/usr/bin/env python3
"""Opt-in live verification of a Houdini hrpyc remote listener.

This script connects to an *already running* Houdini hrpyc listener (started
via the "Start Remote" shelf tool or the manual ``import hrpyc;
hrpyc.start_server(...)`` workflow) and verifies end-to-end reachability from
the machine running this script (for example, the Docker gateway).

IMPORTANT:
- This script is **opt-in** and read-only. It NEVER starts, stops, restarts,
  or otherwise mutates a Houdini session. It only *connects and reads*.
- It must be explicitly enabled with ``RUN_LIVE_REMOTE_CHECK=1`` so it cannot
  run accidentally in CI.

Usage:
    RUN_LIVE_REMOTE_CHECK=1 \
    HOUDINI_HOST=127.0.0.1 HOUDINI_PORT=18811 \
    python scripts/verify_remote_listener.py

Environment:
    RUN_LIVE_REMOTE_CHECK   must equal "1" to run (safety gate)
    HOUDINI_HOST            listener host (default 127.0.0.1)
    HOUDINI_PORT            listener port (default 18811)
    HOUDINI_RPC_TOKEN       optional shared secret (sent before handshake)

Exit codes:
    0  listener reachable and responsive
    1  verification failed
    2  not enabled / misconfigured (safety gate or bad env)
"""

from __future__ import annotations

import os
import socket
import sys


def _enabled() -> bool:
    return os.getenv("RUN_LIVE_REMOTE_CHECK") == "1"


def _target() -> tuple[str, int]:
    host = os.getenv("HOUDINI_HOST", "127.0.0.1")
    port = int(os.getenv("HOUDINI_PORT", "18811"))
    return host, port


def _tcp_probe(host: str, port: int, timeout: float = 3.0) -> bool:
    connect_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    try:
        with socket.create_connection((connect_host, port), timeout=timeout):
            return True
    except OSError as exc:
        print(f"[verify] TCP probe to {connect_host}:{port} failed: {exc}")
        return False


def _rpyc_check(host: str, port: int) -> bool:
    """Connect via rpyc.classic and read the Houdini version (read-only)."""
    try:
        import rpyc  # noqa: PLC0415
    except ImportError:
        print("[verify] rpyc not installed in this environment; skipping RPC check.")
        return False

    token = os.getenv("HOUDINI_RPC_TOKEN")
    try:
        if token:
            # Send the shared secret first, matching the listener authenticator.
            sock = socket.create_connection((host, port), timeout=5.0)
            sock.sendall(token.encode("utf-8"))
            conn = rpyc.classic.connect_stream(rpyc.SocketStream(sock))
        else:
            conn = rpyc.classic.connect(host, port)

        hou = conn.modules.hou
        version = hou.applicationVersionString()
        hip = hou.hipFile.path()
        print(f"[verify] Connected. Houdini version: {version}")
        print(f"[verify] Current hip file: {hip}")
        conn.close()
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[verify] RPC check failed: {exc}")
        return False


def main() -> int:
    if not _enabled():
        print(
            "[verify] Live remote check is disabled. "
            "Set RUN_LIVE_REMOTE_CHECK=1 to run it explicitly."
        )
        return 2

    host, port = _target()
    print(f"[verify] Target listener: {host}:{port}")

    if not _tcp_probe(host, port):
        print("[verify] FAIL: listener is not reachable at the TCP level.")
        print(
            "[verify] Guidance: confirm the listener is bound to a routable "
            "address (not loopback-only) and that the firewall allows the port."
        )
        return 1

    print("[verify] TCP reachable.")

    if not _rpyc_check(host, port):
        print("[verify] FAIL: RPC handshake/version read did not succeed.")
        return 1

    print("[verify] OK: listener reachable and responsive (read-only check).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
