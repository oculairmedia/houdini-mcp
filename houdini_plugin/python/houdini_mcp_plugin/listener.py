"""Remote hrpyc listener activation for the Houdini MCP plugin.

This module implements the "remote mode" listener that lets an external MCP
server (for example the Docker-based gateway) connect to a running Houdini
session over RPyC. It is the testable core behind the shelf tools and the
backwards-compatible functions in :mod:`houdini_mcp_plugin.remote`.

Design goals (bead houdini-mcp-00p):

- **Explicit, configurable bind address/port** instead of hard-coded values.
- **Idempotent** start / stop / reload.
- **Reachability self-test** that reports the *actual* bound endpoints, the
  Houdini / plugin / protocol versions, a loopback-only warning and firewall
  guidance.
- **Security by default**: never silently expose an unauthenticated listener on
  ``0.0.0.0`` (or any non-loopback address). Wildcard/remote binds require an
  explicit trusted-network opt-in or an authentication token.

The module is fully unit-testable: the ``hrpyc`` module and the ``hou`` module
are injected, so tests use light-weight fakes and never need a real Houdini.
"""

from __future__ import annotations

import logging
import os
import socket
import threading
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("houdini_mcp_plugin.listener")

__all__ = [
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "ListenerConfig",
    "SecurityPolicy",
    "SecurityError",
    "RemoteListener",
    "resolve_security_policy",
    "is_loopback_host",
]

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 18811

# Hosts that only accept connections from the local machine.
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}
# Hosts that bind every interface (wildcard).
_WILDCARD_HOSTS = {"0.0.0.0", "::"}


def _env_flag(name: str) -> bool:
    """Interpret an environment variable as a boolean flag."""
    val = os.getenv(name)
    if val is None:
        return False
    return val.strip().lower() in {"1", "true", "yes", "on"}


def is_loopback_host(host: str) -> bool:
    """Return True if *host* only accepts local connections."""
    return host in _LOOPBACK_HOSTS


def is_wildcard_host(host: str) -> bool:
    """Return True if *host* binds all interfaces."""
    return host in _WILDCARD_HOSTS


class SecurityError(RuntimeError):
    """Raised when a requested bind would violate the security policy."""


@dataclass
class ListenerConfig:
    """Configuration for the remote hrpyc listener.

    Attributes:
        host: Bind address. ``127.0.0.1`` (default) is loopback-only and safe.
            ``0.0.0.0`` or a specific LAN IP exposes the listener to the network
            and therefore requires ``trusted_network=True`` or a ``token``.
        port: TCP port to bind. ``0`` lets the OS choose a free port.
        trusted_network: Explicit opt-in acknowledging the network is trusted.
        token: Shared secret used to authenticate remote clients. When set, a
            non-loopback bind is permitted (the operator has chosen auth).
        reuse_addr: Whether to set ``SO_REUSEADDR`` on the server socket.
    """

    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    trusted_network: bool = False
    token: str | None = None
    reuse_addr: bool = True

    @classmethod
    def from_env(cls) -> ListenerConfig:
        """Build a config from environment variables.

        Recognised variables:
            HOUDINI_RPC_BIND_HOST       (default 127.0.0.1)
            HOUDINI_RPC_BIND_PORT       (default 18811)
            HOUDINI_RPC_TRUSTED_NETWORK (default off)
            HOUDINI_RPC_TOKEN           (default unset)
        """
        host = os.getenv("HOUDINI_RPC_BIND_HOST", DEFAULT_HOST)
        port_str = os.getenv("HOUDINI_RPC_BIND_PORT")
        try:
            port = int(port_str) if port_str else DEFAULT_PORT
        except ValueError:
            port = DEFAULT_PORT
        token = os.getenv("HOUDINI_RPC_TOKEN") or None
        trusted = _env_flag("HOUDINI_RPC_TRUSTED_NETWORK")
        return cls(host=host, port=port, trusted_network=trusted, token=token)


@dataclass
class SecurityPolicy:
    """Result of evaluating a :class:`ListenerConfig` against the policy."""

    allowed: bool
    loopback_only: bool
    authenticated: bool
    reason: str = ""

    @property
    def exposure(self) -> str:
        return "loopback" if self.loopback_only else "network"

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "loopback_only": self.loopback_only,
            "authenticated": self.authenticated,
            "exposure": self.exposure,
            "reason": self.reason,
        }


def resolve_security_policy(config: ListenerConfig) -> SecurityPolicy:
    """Evaluate a bind request against the "no silent exposure" policy.

    Rules:
    - Loopback binds (``127.0.0.1``/``::1``/``localhost``) are always allowed.
    - Any non-loopback bind (wildcard or a specific LAN IP) is refused unless
      the operator has explicitly opted in via ``trusted_network=True`` or has
      configured an authentication ``token``.
    """
    loopback = is_loopback_host(config.host)
    authenticated = bool(config.token)

    if loopback:
        return SecurityPolicy(
            allowed=True,
            loopback_only=True,
            authenticated=authenticated,
            reason="loopback bind is local-only",
        )

    if config.trusted_network or authenticated:
        reason = (
            "authenticated remote bind (token configured)"
            if authenticated
            else "trusted-network opt-in acknowledged"
        )
        return SecurityPolicy(
            allowed=True,
            loopback_only=False,
            authenticated=authenticated,
            reason=reason,
        )

    return SecurityPolicy(
        allowed=False,
        loopback_only=False,
        authenticated=False,
        reason=(
            f"refusing to bind non-loopback host {config.host!r} without an explicit "
            "trusted-network opt-in (HOUDINI_RPC_TRUSTED_NETWORK=1) or an "
            "authentication token (HOUDINI_RPC_TOKEN). This prevents silent, "
            "unauthenticated exposure of a remote-code-execution endpoint."
        ),
    )


def _detect_local_ip() -> str:
    """Best-effort discovery of the machine's outward-facing IPv4 address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return str(s.getsockname()[0])
        finally:
            s.close()
    except OSError:
        return "localhost"


def _probe_reachable(host: str, port: int, timeout: float = 2.0) -> bool:
    """Return True when a TCP listener actually accepts a connection."""
    # A wildcard/unspecified bind cannot be *connected* to directly; probe
    # loopback in that case since the listener also accepts local traffic.
    connect_host = "127.0.0.1" if is_wildcard_host(host) else host
    if connect_host == "localhost":
        connect_host = "127.0.0.1"
    deadline = time.monotonic() + timeout
    last_err: OSError | None = None
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((connect_host, port), timeout=0.3):
                return True
        except OSError as exc:
            last_err = exc
            time.sleep(0.05)
    if last_err is not None:
        logger.debug("reachability probe failed for %s:%s: %s", connect_host, port, last_err)
    return False


def firewall_guidance(host: str, port: int) -> list[str]:
    """Return human-readable firewall / connectivity guidance."""
    guidance = [
        f"Ensure inbound TCP port {port} is allowed through the OS firewall.",
        f"Linux (ufw):    sudo ufw allow {port}/tcp",
        f"Linux (nft):    add rule inet filter input tcp dport {port} accept",
        f"Windows:        New-NetFirewallRule -DisplayName 'Houdini hrpyc' "
        f"-Direction Inbound -LocalPort {port} -Protocol TCP -Action Allow",
    ]
    if is_loopback_host(host):
        guidance.insert(
            0,
            "Listener is bound to loopback only; remote clients (e.g. a Docker "
            "gateway on another host/network namespace) cannot reach it. Re-bind "
            "to a routable address with an explicit trusted-network opt-in or token.",
        )
    return guidance


class RemoteListener:
    """Manages a single hrpyc ``ThreadedServer`` with a safe, testable API.

    ``hrpyc`` and ``hou`` are injected so the class can be exercised with fakes.
    In Houdini they default to the real modules (resolved lazily on use).
    """

    def __init__(self, hrpyc: Any = None, hou: Any = None) -> None:
        self._hrpyc = hrpyc
        self._hou = hou
        self._server: Any | None = None
        self._config: ListenerConfig | None = None
        self._policy: SecurityPolicy | None = None
        self._bound_port: int | None = None
        self._lock = threading.RLock()

    # -- dependency resolution ------------------------------------------------

    def _resolve_hrpyc(self) -> Any:
        if self._hrpyc is not None:
            return self._hrpyc
        import hrpyc  # noqa: PLC0415 - lazy import; only present inside Houdini

        return hrpyc

    def _resolve_hou(self) -> Any:
        if self._hou is not None:
            return self._hou
        try:
            import hou  # noqa: PLC0415 - only present inside Houdini

            return hou
        except ImportError:
            return None

    # -- lifecycle ------------------------------------------------------------

    def is_running(self) -> bool:
        return self._server is not None

    def start(
        self, config: ListenerConfig | None = None, *, raise_on_policy: bool = False
    ) -> dict[str, Any]:
        """Start the listener. Idempotent: a second call reports already_running.

        Args:
            config: bind configuration (defaults to :meth:`ListenerConfig.from_env`).
            raise_on_policy: when True, a policy violation raises
                :class:`SecurityError` instead of returning an error dict.
        """
        with self._lock:
            if self._server is not None:
                assert self._config is not None
                return {
                    "status": "already_running",
                    "running": True,
                    "host": self._config.host,
                    "port": self._config.port,
                    "bound_port": self._bound_port,
                    "message": (
                        f"hrpyc listener already running on "
                        f"{self._config.host}:{self._bound_port}"
                    ),
                }

            cfg = config if config is not None else ListenerConfig.from_env()
            policy = resolve_security_policy(cfg)

            if not policy.allowed:
                logger.warning("Refusing to start listener: %s", policy.reason)
                if raise_on_policy:
                    raise SecurityError(policy.reason)
                return {
                    "status": "error",
                    "error_type": "security",
                    "running": False,
                    "host": cfg.host,
                    "port": cfg.port,
                    "message": policy.reason,
                    "security": policy.as_dict(),
                }

            try:
                hrpyc = self._resolve_hrpyc()
            except ImportError as exc:
                return {
                    "status": "error",
                    "error_type": "dependency",
                    "running": False,
                    "message": (
                        "hrpyc module not available. Houdini's Python environment "
                        f"must provide hrpyc. ({exc})"
                    ),
                }
            if hrpyc is None:
                return {
                    "status": "error",
                    "error_type": "dependency",
                    "running": False,
                    "message": "hrpyc module not available (None injected).",
                }

            try:
                server = self._build_server(hrpyc, cfg, policy)
            except OSError as exc:
                logger.error("Failed to bind hrpyc listener on %s:%s: %s", cfg.host, cfg.port, exc)
                return {
                    "status": "error",
                    "error_type": "bind",
                    "running": False,
                    "host": cfg.host,
                    "port": cfg.port,
                    "message": (
                        f"Failed to bind hrpyc listener on {cfg.host}:{cfg.port} "
                        f"(address in use or not permitted): {exc}"
                    ),
                }
            except Exception as exc:  # noqa: BLE001 - report any startup failure cleanly
                logger.error("Failed to start hrpyc listener: %s", exc)
                return {
                    "status": "error",
                    "error_type": "start",
                    "running": False,
                    "message": f"Failed to start hrpyc listener: {exc}",
                }

            bound_port = getattr(server, "bound_port", None) or cfg.port

            thread = threading.Thread(
                target=server.start, name="houdini-hrpyc", daemon=True
            )
            thread.start()

            if not _probe_reachable(cfg.host, bound_port):
                # Clean up the half-started server so state stays consistent.
                self._close_server(server)
                return {
                    "status": "error",
                    "error_type": "unreachable",
                    "running": False,
                    "host": cfg.host,
                    "port": bound_port,
                    "message": (
                        f"hrpyc listener did not become reachable on "
                        f"{cfg.host}:{bound_port}."
                    ),
                }

            self._server = server
            self._config = cfg
            self._policy = policy
            self._bound_port = bound_port

            logger.info(
                "Started hrpyc listener on %s:%s (exposure=%s, auth=%s)",
                cfg.host,
                bound_port,
                policy.exposure,
                policy.authenticated,
            )

            result = self.status()
            result["status"] = "success"
            result["message"] = (
                f"hrpyc listener started on {cfg.host}:{bound_port}. "
                f"Connect with HOUDINI_HOST={cfg.host} HOUDINI_PORT={bound_port}"
            )
            return result

    def _build_server(self, hrpyc: Any, cfg: ListenerConfig, policy: SecurityPolicy) -> Any:
        """Construct the underlying ThreadedServer, wiring auth if configured."""
        kwargs: dict[str, Any] = {
            "hostname": cfg.host,
            "port": cfg.port,
            "reuse_addr": cfg.reuse_addr,
            "auto_register": False,
        }
        # If a token is configured and hrpyc supports an authenticator, use it.
        if cfg.token:
            authenticator = _make_token_authenticator(cfg.token)
            if authenticator is not None:
                kwargs["authenticator"] = authenticator

        service = getattr(hrpyc, "SlaveService", None)
        if service is not None:
            server = hrpyc.ThreadedServer(service, **kwargs)
        else:  # pragma: no cover - defensive; real hrpyc always has SlaveService
            server = hrpyc.ThreadedServer(**kwargs)

        # Quiet the noisy per-connection logger if present.
        server_logger = getattr(server, "logger", None)
        if server_logger is not None and hasattr(server_logger, "quiet"):
            server_logger.quiet = True
        return server

    @staticmethod
    def _server_alive(server: Any) -> bool:
        """Best-effort liveness check of the underlying ThreadedServer object.

        Real ``rpyc``/``hrpyc`` servers expose ``active`` (bool) and/or
        ``closed`` attributes; our fakes expose ``_closed``. A server that has
        been closed out from under us is considered dead (stale).
        """
        closed = getattr(server, "_closed", None)
        if closed is True:
            return False
        closed_attr = getattr(server, "closed", None)
        if closed_attr is True:
            return False
        active = getattr(server, "active", None)
        return active is not False

    @staticmethod
    def _close_server(server: Any) -> None:
        close = getattr(server, "close", None)
        if close is not None:
            try:
                close()
            except Exception as exc:  # noqa: BLE001
                logger.debug("Error closing hrpyc server: %s", exc)

    def stop(self) -> dict[str, Any]:
        """Stop the listener. Idempotent and tolerant of an already-dead server."""
        with self._lock:
            if self._server is None:
                return {
                    "status": "not_running",
                    "running": False,
                    "message": "hrpyc listener is not running.",
                }

            self._close_server(self._server)
            host = self._config.host if self._config else DEFAULT_HOST
            port = self._bound_port
            self._server = None
            self._config = None
            self._policy = None
            self._bound_port = None
            logger.info("Stopped hrpyc listener (%s:%s)", host, port)
            return {
                "status": "success",
                "running": False,
                "message": "hrpyc listener stopped.",
            }

    def reload(
        self, config: ListenerConfig | None = None, *, raise_on_policy: bool = False
    ) -> dict[str, Any]:
        """Stop (if running) and start again with *config*. Idempotent restart."""
        with self._lock:
            if self._server is not None:
                self.stop()
            return self.start(config, raise_on_policy=raise_on_policy)

    # -- introspection --------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Return current listener status (no reachability probe)."""
        if self._server is None or self._config is None:
            return {
                "running": False,
                "message": "hrpyc listener is not running.",
            }
        policy = self._policy or resolve_security_policy(self._config)
        return {
            "running": True,
            "host": self._config.host,
            "port": self._config.port,
            "bound_port": self._bound_port,
            "local_ip": _detect_local_ip(),
            "loopback_only": policy.loopback_only,
            "authenticated": policy.authenticated,
            "security": policy.as_dict(),
            "connection_string": (
                f"HOUDINI_HOST={self._config.host} HOUDINI_PORT={self._bound_port}"
            ),
            "message": "hrpyc listener is running.",
        }

    def self_test(self) -> dict[str, Any]:
        """Run a reachability + capability self-test.

        Reports:
        - reachability of the bound endpoint,
        - whether the listener is stale (referenced but not reachable),
        - Houdini / plugin / protocol versions,
        - loopback-only warning + firewall guidance,
        - the actual bound endpoints.
        """
        from . import __version__ as plugin_version

        if self._server is None or self._config is None:
            return {
                "running": False,
                "reachable": False,
                "stale": False,
                "warnings": ["hrpyc listener is not running."],
                "guidance": ["Start the listener before running a self-test."],
            }

        cfg = self._config
        policy = self._policy or resolve_security_policy(cfg)
        bound_port = self._bound_port or cfg.port
        server_alive = self._server_alive(self._server)
        # If the server object reports dead, don't let a lingering accept()
        # window fool the probe: treat as unreachable/stale immediately.
        if not server_alive:
            reachable = False
        else:
            reachable = _probe_reachable(cfg.host, bound_port, timeout=1.0)
        # Stale = we still hold a server reference, but it is no longer serving.
        stale = (not server_alive) or (not reachable)

        warnings: list[str] = []
        if policy.loopback_only:
            warnings.append(
                "Listener is bound to loopback (127.0.0.1) only. Remote clients "
                "cannot connect; only processes on this machine can reach it."
            )
        if not policy.loopback_only and not policy.authenticated:
            warnings.append(
                "Listener is exposed to the network without an authentication "
                "token. Ensure the network is trusted (trusted-network opt-in)."
            )
        if stale:
            warnings.append(
                f"Listener object exists but {cfg.host}:{bound_port} is not "
                "answering. The underlying server may have died (stale listener)."
            )

        hou = self._resolve_hou()
        houdini_version: str | None = None
        houdini_version_tuple: list[int] | None = None
        if hou is not None:
            try:
                houdini_version = hou.applicationVersionString()
                houdini_version_tuple = list(hou.applicationVersion())
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"Could not read Houdini version: {exc}")

        local_ip = _detect_local_ip()
        bound_endpoints = [f"{cfg.host}:{bound_port}"]
        if not policy.loopback_only and not is_wildcard_host(cfg.host):
            bound_endpoints.append(f"{local_ip}:{bound_port}")
        elif is_wildcard_host(cfg.host):
            bound_endpoints.append(f"{local_ip}:{bound_port} (via 0.0.0.0)")

        return {
            "running": True,
            "reachable": reachable,
            "stale": stale,
            "host": cfg.host,
            "port": cfg.port,
            "bound_port": bound_port,
            "bound_endpoints": bound_endpoints,
            "local_ip": local_ip,
            "loopback_only": policy.loopback_only,
            "authenticated": policy.authenticated,
            "security": policy.as_dict(),
            "houdini_version": houdini_version,
            "houdini_version_tuple": houdini_version_tuple,
            "plugin_version": plugin_version,
            "protocol": "rpyc/hrpyc SlaveService (classic)",
            "connection_string": (
                f"HOUDINI_HOST={cfg.host} HOUDINI_PORT={bound_port}"
            ),
            "warnings": warnings,
            "guidance": firewall_guidance(cfg.host, bound_port),
        }


def _make_token_authenticator(token: str) -> Any:
    """Build an rpyc authenticator that enforces a shared-secret handshake.

    Returns ``None`` if rpyc's authentication primitives are unavailable, in
    which case the caller falls back to trusted-network semantics (the bind is
    still gated by :func:`resolve_security_policy`).
    """
    try:
        from rpyc.utils.authenticators import AuthenticationError  # noqa: PLC0415
    except Exception:  # noqa: BLE001 - rpyc layout varies across versions
        return None

    expected = token.encode("utf-8")
    length = len(expected)

    def authenticate(sock: Any) -> tuple[Any, Any]:
        # Read exactly len(token) bytes; compare in constant-ish time.
        import hmac  # noqa: PLC0415

        received = b""
        while len(received) < length:
            chunk = sock.recv(length - len(received))
            if not chunk:
                break
            received += chunk
        if not hmac.compare_digest(received, expected):
            raise AuthenticationError("invalid hrpyc token")
        return sock, None

    return authenticate
