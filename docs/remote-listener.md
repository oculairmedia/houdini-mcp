# Remote hrpyc Listener Activation

The Houdini MCP plugin can start a remotely reachable **hrpyc** listener so an
external MCP server (for example the Docker-based gateway) can connect to a
running Houdini session over RPyC.

This replaces the friction of manually running `import hrpyc;
hrpyc.start_server()` in the Python shell and then discovering the listener is
unreachable because of bind/firewall ambiguity.

> The **manual/direct** workflow still works exactly as before. The activation
> path described here is an additional, safer entry point — it does not change
> or remove the manual mode.

## Quick start (from the shelf)

The **Houdini MCP** shelf provides:

| Tool               | Action                                                            |
| ------------------ | ---------------------------------------------------------------- |
| **Start Remote**   | Start the hrpyc listener (bind/security from environment)        |
| **Stop Remote**    | Stop the listener (idempotent)                                   |
| **Remote Status**  | Show bind host, actual bound port, exposure, auth                |
| **Remote Self-Test** | Reachability + versions + loopback warning + firewall guidance |

## Configuration (environment variables)

| Variable                      | Default     | Meaning                                             |
| ----------------------------- | ----------- | --------------------------------------------------- |
| `HOUDINI_RPC_BIND_HOST`       | `127.0.0.1` | Bind address. Loopback is local-only and safe.      |
| `HOUDINI_RPC_BIND_PORT`       | `18811`     | TCP port (`0` = OS-assigned).                       |
| `HOUDINI_RPC_TRUSTED_NETWORK` | `0`         | Set `1` to allow a non-loopback bind (opt-in).      |
| `HOUDINI_RPC_TOKEN`           | *(unset)*   | Shared secret; enables authenticated remote bind.   |

## Security model — no silent exposure

`hrpyc`/RPyC `SlaveService` grants **arbitrary remote code execution** inside
Houdini. To prevent accidentally exposing that to the network, the listener
enforces this policy:

- **Loopback binds** (`127.0.0.1`, `::1`, `localhost`) are always allowed and
  are reachable only from the same machine.
- **Any non-loopback bind** (`0.0.0.0` or a specific LAN IP) is **refused**
  unless the operator explicitly opts in via **either**:
  - `HOUDINI_RPC_TRUSTED_NETWORK=1` (you attest the network is trusted), or
  - `HOUDINI_RPC_TOKEN=<secret>` (clients must present the token first).

If neither is set, `Start Remote` returns a security error and **no listener is
created** — there is no code path that silently binds `0.0.0.0` without auth.

### Limitations (read this)

- The token authenticator is a lightweight shared-secret handshake performed
  before the RPyC protocol. It is **not** TLS and provides **no encryption** —
  use it only on trusted networks or behind an encrypted tunnel
  (WireGuard, SSH, Cloudflare Tunnel, etc.).
- If the installed `rpyc` build does not expose the authenticator primitives,
  the token cannot be enforced at the socket layer; the bind still requires the
  trusted-network opt-in, but you should prefer a tunnel in that case.
- `SlaveService` is inherently powerful; treat any reachable listener as a
  full remote shell into Houdini.

## Loopback-only warning & firewall guidance

If the listener is bound to loopback, `Remote Status` / `Remote Self-Test`
warn that **remote clients cannot reach it** and explain how to re-bind. The
self-test also emits per-OS firewall commands for the bound port.

## Live verification (opt-in, read-only)

`scripts/verify_remote_listener.py` connects to an already-running listener and
reads the Houdini version. It is **read-only** and never starts/stops/restarts
Houdini. It only runs when explicitly enabled:

```bash
RUN_LIVE_REMOTE_CHECK=1 \
HOUDINI_HOST=127.0.0.1 HOUDINI_PORT=18811 \
python scripts/verify_remote_listener.py
```

Exit codes: `0` reachable/responsive, `1` failed, `2` disabled/misconfigured.
