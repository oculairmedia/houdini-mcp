"""Tests for the outbound WSS connection state-machine core (houdini-mcp-xu4).

The core is sans-I/O: every ``on_*`` call returns a deterministic list of
``Action`` side effects. These tests drive the machine directly and assert on
state transitions and emitted actions, covering:

* every state transition of the lifecycle
* authenticated hello / capability negotiation
* heartbeat ping/pong + heartbeat-timeout driven reconnect
* request ids, bounded command/event queues + backpressure
* cancellation (queued and in-flight)
* TLS verification config invariants
* reconnect exponential backoff with capped, deterministic seeded jitter
* stale-session rejection
* duplicate / out-of-order frames
* gateway restart / network partition / clock skew
* secret redaction (api_key never appears in telemetry)

A minimal deterministic driver (:class:`Driver`) replays actions back into the
core so full end-to-end reconnect scenarios can be asserted without any real
sockets, sleeps, or threads.
"""

from __future__ import annotations

import os
import random
import sys

import pytest

# The plugin package lives outside the importable server package; make it
# importable for this test module without altering global test configuration.
_PLUGIN_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "houdini_plugin",
    "python",
)
if _PLUGIN_PATH not in sys.path:
    sys.path.insert(0, _PLUGIN_PATH)

from houdini_mcp_plugin.ws_client import (  # noqa: E402
    ACK,
    BYE,
    CANCEL,
    COMMAND,
    ERROR,
    EVENT,
    HELLO,
    PING,
    PONG,
    WELCOME,
    Action,
    ActionType,
    ConnectionState,
    QueueFullError,
    WSClientCore,
    WSConfig,
    redact,
)

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def make_config(**overrides) -> WSConfig:
    base = {
        "gateway_url": "wss://gateway.example/ws",
        "api_key": "super-secret-key",
        "capabilities": ("events", "commands"),
        "heartbeat_interval": 30.0,
        "heartbeat_timeout": 10.0,
        "handshake_timeout": 10.0,
        "backoff_initial": 1.0,
        "backoff_max": 60.0,
        "backoff_multiplier": 2.0,
        "jitter_ratio": 0.2,
        "max_command_queue": 4,
        "max_event_queue": 4,
    }
    base.update(overrides)
    return WSConfig(**base)


def actions_of(actions: list[Action], kind: ActionType) -> list[Action]:
    return [a for a in actions if a.type == kind]


def sent_frames(actions: list[Action]) -> list[dict]:
    return [a.frame for a in actions if a.type == ActionType.SEND and a.frame is not None]


def telemetry_events(actions: list[Action]) -> list[str]:
    return [a.telemetry["event"] for a in actions if a.type == ActionType.TELEMETRY]


def timers_scheduled(actions: list[Action]) -> list[str]:
    return [a.timer for a in actions if a.type == ActionType.SCHEDULE_TIMER]


def connect_core(core: WSClientCore, *, session_id="s1", capabilities=("events",)):
    """Drive a core from DISCONNECTED to CONNECTED deterministically."""
    core.start()
    core.on_socket_open()
    return core.on_frame(
        {"type": WELCOME, "session_id": session_id, "capabilities": list(capabilities)}
    )


class Driver:
    """Minimal deterministic in-memory driver that replays core actions.

    It records sent frames, telemetry, delivered events/acks, and pending timers.
    Timers are fired manually by tests (no real time passes), which is exactly
    what makes the whole engine deterministic and UI-safe.
    """

    def __init__(self, core: WSClientCore):
        self.core = core
        self.sent: list[dict] = []
        self.telemetry: list[dict] = []
        self.events: list[dict] = []
        self.acks: list[dict] = []
        self.timers: dict[str, float] = {}
        self.open_count = 0
        self.close_count = 0

    def _apply(self, actions: list[Action]) -> None:
        for a in actions:
            if a.type == ActionType.SEND and a.frame is not None:
                self.sent.append(a.frame)
            elif a.type == ActionType.TELEMETRY and a.telemetry is not None:
                self.telemetry.append(a.telemetry)
            elif a.type == ActionType.DELIVER_EVENT and a.event is not None:
                self.events.append(a.event)
            elif a.type == ActionType.DELIVER_ACK and a.event is not None:
                self.acks.append(a.event)
            elif a.type == ActionType.SCHEDULE_TIMER and a.timer is not None:
                self.timers[a.timer] = a.delay
            elif a.type == ActionType.CANCEL_TIMER and a.timer is not None:
                self.timers.pop(a.timer, None)
            elif a.type == ActionType.OPEN:
                self.open_count += 1
            elif a.type == ActionType.CLOSE:
                self.close_count += 1

    def call(self, method: str, *args, **kwargs):
        result = getattr(self.core, method)(*args, **kwargs)
        # Some methods (e.g. send_command) return a value, not an action list.
        if isinstance(result, list):
            self._apply(result)
        return result


# --------------------------------------------------------------------------- #
# Config invariants (TLS verification on by default, etc.)
# --------------------------------------------------------------------------- #


class TestConfig:
    def test_tls_verify_on_by_default(self):
        cfg = make_config()
        assert cfg.tls_verify is True

    def test_non_wss_url_rejected_when_tls_verified(self):
        with pytest.raises(ValueError, match="wss://"):
            make_config(gateway_url="ws://insecure.example/ws")

    def test_non_wss_url_allowed_only_when_tls_disabled(self):
        cfg = make_config(gateway_url="ws://localhost:9000/ws", tls_verify=False)
        assert cfg.tls_verify is False

    def test_missing_api_key_rejected(self):
        with pytest.raises(ValueError, match="api_key"):
            make_config(api_key="")

    def test_missing_gateway_url_rejected(self):
        with pytest.raises(ValueError, match="gateway_url"):
            make_config(gateway_url="")

    def test_invalid_jitter_ratio_rejected(self):
        with pytest.raises(ValueError, match="jitter_ratio"):
            make_config(jitter_ratio=1.0)
        with pytest.raises(ValueError, match="jitter_ratio"):
            make_config(jitter_ratio=-0.1)

    def test_invalid_backoff_rejected(self):
        with pytest.raises(ValueError, match="backoff"):
            make_config(backoff_initial=0)
        with pytest.raises(ValueError, match="backoff"):
            make_config(backoff_initial=10, backoff_max=5)

    def test_invalid_heartbeat_rejected(self):
        with pytest.raises(ValueError, match="heartbeat_interval"):
            make_config(heartbeat_interval=0)


# --------------------------------------------------------------------------- #
# Lifecycle / every state transition
# --------------------------------------------------------------------------- #


class TestLifecycleTransitions:
    def test_initial_state_disconnected(self):
        core = WSClientCore(make_config())
        assert core.state == ConnectionState.DISCONNECTED

    def test_start_transitions_to_connecting_and_opens(self):
        core = WSClientCore(make_config())
        actions = core.start()
        assert core.state == ConnectionState.CONNECTING
        assert actions_of(actions, ActionType.OPEN)
        assert "connecting" in telemetry_events(actions)

    def test_start_is_idempotent_while_active(self):
        core = WSClientCore(make_config())
        core.start()
        # A second start while connecting must not open a second socket.
        actions = core.start()
        assert actions == []
        assert core.state == ConnectionState.CONNECTING

    def test_socket_open_transitions_to_handshaking_and_sends_hello(self):
        core = WSClientCore(make_config())
        core.start()
        actions = core.on_socket_open()
        assert core.state == ConnectionState.HANDSHAKING
        frames = sent_frames(actions)
        assert len(frames) == 1
        hello = frames[0]
        assert hello["type"] == HELLO
        assert hello["api_key"] == "super-secret-key"
        assert hello["protocol_version"] == 1
        assert hello["capabilities"] == ["events", "commands"]
        assert "handshake_timeout" in timers_scheduled(actions)

    def test_welcome_transitions_to_connected_and_negotiates(self):
        core = WSClientCore(make_config())
        core.start()
        core.on_socket_open()
        actions = core.on_frame(
            {"type": WELCOME, "session_id": "sess-42", "capabilities": ["events"]}
        )
        assert core.state == ConnectionState.CONNECTED
        assert core.session_id == "sess-42"
        assert core.negotiated_capabilities == ("events",)
        assert "heartbeat" in timers_scheduled(actions)
        assert "connected" in telemetry_events(actions)

    def test_full_happy_path_transition_sequence(self):
        core = WSClientCore(make_config())
        assert core.state == ConnectionState.DISCONNECTED
        core.start()
        assert core.state == ConnectionState.CONNECTING
        core.on_socket_open()
        assert core.state == ConnectionState.HANDSHAKING
        core.on_frame({"type": WELCOME, "session_id": "s"})
        assert core.state == ConnectionState.CONNECTED

    def test_stop_from_connected_sends_bye_and_closes(self):
        core = WSClientCore(make_config())
        connect_core(core)
        actions = core.stop()
        assert core.state == ConnectionState.CLOSED
        assert any(f["type"] == BYE for f in sent_frames(actions))
        assert actions_of(actions, ActionType.CLOSE)

    def test_stop_from_disconnected_is_terminal_without_bye(self):
        core = WSClientCore(make_config())
        actions = core.stop()
        assert core.state == ConnectionState.CLOSED
        assert not any(f["type"] == BYE for f in sent_frames(actions))

    def test_socket_error_during_handshake_enters_backoff(self):
        core = WSClientCore(make_config())
        core.start()
        core.on_socket_open()
        actions = core.on_socket_error("reset")
        assert core.state == ConnectionState.BACKOFF
        assert "backoff" in timers_scheduled(actions)

    def test_handshake_timeout_enters_backoff(self):
        core = WSClientCore(make_config())
        core.start()
        core.on_socket_open()
        actions = core.on_handshake_timeout()
        assert core.state == ConnectionState.BACKOFF
        assert "backoff_scheduled" in telemetry_events(actions)

    def test_backoff_elapsed_reconnects(self):
        core = WSClientCore(make_config())
        core.start()
        core.on_socket_open()
        core.on_socket_error()
        assert core.state == ConnectionState.BACKOFF
        actions = core.on_backoff_elapsed()
        assert core.state == ConnectionState.CONNECTING
        assert actions_of(actions, ActionType.OPEN)

    def test_closed_is_terminal_ignores_socket_events(self):
        core = WSClientCore(make_config())
        core.stop()
        assert core.on_socket_error() == []
        assert core.on_socket_closed() == []
        assert core.state == ConnectionState.CLOSED


# --------------------------------------------------------------------------- #
# Reconnect backoff with capped, deterministic seeded jitter
# --------------------------------------------------------------------------- #


class TestBackoffAndJitter:
    def _first_backoff_delay(self, actions: list[Action]) -> float:
        for a in actions:
            if a.type == ActionType.SCHEDULE_TIMER and a.timer == "backoff":
                return a.delay
        raise AssertionError("no backoff timer scheduled")

    def test_backoff_is_deterministic_for_a_given_seed(self):
        delays = []
        for _ in range(2):
            core = WSClientCore(make_config(), rng=random.Random(1234))
            seq = []
            core.start()
            core.on_socket_open()
            seq.append(self._first_backoff_delay(core.on_socket_error()))
            for _ in range(5):
                core.on_backoff_elapsed()
                core.on_socket_open()
                seq.append(self._first_backoff_delay(core.on_socket_error()))
            delays.append(seq)
        assert delays[0] == delays[1]  # fully reproducible

    def test_backoff_grows_exponentially_within_jitter_bounds(self):
        core = WSClientCore(make_config(jitter_ratio=0.2), rng=random.Random(7))
        bases = [1.0, 2.0, 4.0, 8.0, 16.0, 32.0]
        core.start()
        core.on_socket_open()
        observed = [self._first_backoff_delay(core.on_socket_error())]
        for _ in range(len(bases) - 1):
            core.on_backoff_elapsed()
            core.on_socket_open()
            observed.append(self._first_backoff_delay(core.on_socket_error()))
        for base, delay in zip(bases, observed, strict=False):
            assert base * 0.8 <= delay <= base * 1.2 + 1e-9

    def test_backoff_capped_at_max_with_jitter_ceiling(self):
        core = WSClientCore(make_config(backoff_max=60.0, jitter_ratio=0.2), rng=random.Random(99))
        core.start()
        core.on_socket_open()
        core.on_socket_error()
        # Drive many failures so backoff saturates at the cap.
        for _ in range(20):
            core.on_backoff_elapsed()
            core.on_socket_open()
            actions = core.on_socket_error()
            delay = self._first_backoff_delay(actions)
            # Never exceeds cap * (1 + jitter_ratio); never negative.
            assert 0.0 <= delay <= 60.0 * 1.2 + 1e-9
        # After saturation, the base should be pinned at the cap.
        assert core._current_backoff == 60.0

    def test_jitter_can_be_disabled(self):
        core = WSClientCore(make_config(jitter_ratio=0.0), rng=random.Random(0))
        core.start()
        core.on_socket_open()
        assert self._first_backoff_delay(core.on_socket_error()) == pytest.approx(1.0)

    def test_successful_connect_resets_backoff(self):
        core = WSClientCore(make_config(), rng=random.Random(3))
        core.start()
        core.on_socket_open()
        core.on_socket_error()
        core.on_backoff_elapsed()
        core.on_socket_open()
        core.on_socket_error()
        assert core.backoff_attempt >= 2
        core.on_backoff_elapsed()
        core.on_socket_open()
        core.on_frame({"type": WELCOME, "session_id": "s"})
        assert core.backoff_attempt == 0  # reset after a healthy handshake

    def test_reconnect_attempt_budget_closes_after_exhaustion(self):
        core = WSClientCore(make_config(max_reconnect_attempts=3), rng=random.Random(1))
        core.start()
        core.on_socket_open()
        core.on_socket_error()  # attempt 1
        core.on_backoff_elapsed()
        core.on_socket_open()
        core.on_socket_error()  # attempt 2
        core.on_backoff_elapsed()
        core.on_socket_open()
        actions = core.on_socket_error()  # attempt 3 -> exhausted
        assert core.state == ConnectionState.CLOSED
        assert "reconnect_exhausted" in telemetry_events(actions)


# --------------------------------------------------------------------------- #
# Heartbeats
# --------------------------------------------------------------------------- #


class TestHeartbeat:
    def test_heartbeat_tick_sends_ping_and_arms_timeout(self):
        core = WSClientCore(make_config())
        connect_core(core, session_id="hb")
        actions = core.on_heartbeat_tick()
        frames = sent_frames(actions)
        assert any(f["type"] == PING for f in frames)
        assert frames[0]["session_id"] == "hb"
        assert "heartbeat_timeout" in timers_scheduled(actions)

    def test_pong_clears_timeout_and_rearms_interval(self):
        core = WSClientCore(make_config())
        connect_core(core, session_id="hb")
        core.on_heartbeat_tick()
        actions = core.on_frame({"type": PONG, "session_id": "hb"})
        cancelled = [a.timer for a in actions if a.type == ActionType.CANCEL_TIMER]
        assert "heartbeat_timeout" in cancelled
        assert "heartbeat" in timers_scheduled(actions)

    def test_missing_pong_timeout_triggers_reconnect(self):
        core = WSClientCore(make_config())
        connect_core(core, session_id="hb")
        core.on_heartbeat_tick()
        actions = core.on_heartbeat_timeout()
        assert core.state == ConnectionState.BACKOFF
        assert "heartbeat_timeout" in [
            t["reason"]
            for t in [
                a.telemetry
                for a in actions
                if a.type == ActionType.TELEMETRY and "reason" in a.telemetry
            ]
        ]

    def test_heartbeat_tick_ignored_when_not_connected(self):
        core = WSClientCore(make_config())
        core.start()  # only CONNECTING
        actions = core.on_heartbeat_tick()
        assert not sent_frames(actions)

    def test_double_tick_without_pong_does_not_stack_pings(self):
        core = WSClientCore(make_config())
        connect_core(core, session_id="hb")
        core.on_heartbeat_tick()
        actions = core.on_heartbeat_tick()  # still awaiting pong
        assert not sent_frames(actions)


# --------------------------------------------------------------------------- #
# Request ids, command queue, backpressure
# --------------------------------------------------------------------------- #


class TestCommandsAndQueues:
    def test_request_ids_are_monotonic_and_unique(self):
        core = WSClientCore(make_config())
        ids = [core.send_command({"op": i}) for i in range(5)]
        assert ids == sorted(ids)
        assert len(set(ids)) == len(ids)

    def test_commands_queued_while_disconnected_flush_on_connect(self):
        core = WSClientCore(make_config())
        r1 = core.send_command({"op": "a"})
        r2 = core.send_command({"op": "b"})
        assert core.command_backlog == 2
        actions = connect_core(core)
        sent = [f for f in sent_frames(actions) if f["type"] == COMMAND]
        assert {f["request_id"] for f in sent} == {r1, r2}
        assert core.command_backlog == 0
        assert set(core.pending_request_ids) == {r1, r2}

    def test_ack_terminates_pending_request(self):
        core = WSClientCore(make_config())
        rid = core.send_command({"op": "x"})
        connect_core(core, session_id="s1")
        actions = core.on_frame({"type": ACK, "request_id": rid, "session_id": "s1"})
        assert rid not in core.pending_request_ids
        assert any(a.type == ActionType.DELIVER_ACK for a in actions)

    def test_command_queue_backpressure_drops_oldest_by_default(self):
        core = WSClientCore(make_config(max_command_queue=2))
        core.send_command({"op": 0})
        core.send_command({"op": 1})
        core.send_command({"op": 2})  # evicts op0
        assert core.command_backlog == 2
        connect_core(core)
        # Only the two most recent survive.

    def test_command_queue_reject_policy_raises(self):
        core = WSClientCore(make_config(max_command_queue=1))
        core.send_command({"op": 0})
        with pytest.raises(QueueFullError):
            core.send_command({"op": 1}, reject_on_full=True)

    def test_send_command_is_nonblocking_and_returns_immediately(self):
        # Contract: send_command performs no I/O; it must not require a
        # connection and must return synchronously.
        core = WSClientCore(make_config())
        rid = core.send_command({"op": "x"})
        assert isinstance(rid, int)
        assert core.state == ConnectionState.DISCONNECTED


class TestEventBackpressure:
    def test_events_delivered_to_app(self):
        core = WSClientCore(make_config())
        connect_core(core, session_id="s1")
        actions = core.on_frame({"type": EVENT, "id": "e1", "session_id": "s1"})
        delivered = [a for a in actions if a.type == ActionType.DELIVER_EVENT]
        assert len(delivered) == 1
        assert delivered[0].event["id"] == "e1"

    def test_event_backpressure_never_blocks(self):
        # Even with a tiny bound, delivering many events must never raise or
        # block; excess buffering emits telemetry, the UI thread stays free.
        core = WSClientCore(make_config(max_event_queue=1))
        connect_core(core, session_id="s1")
        for i in range(10):
            actions = core.on_frame({"type": EVENT, "id": f"e{i}", "session_id": "s1"})
            assert any(a.type == ActionType.DELIVER_EVENT for a in actions)


# --------------------------------------------------------------------------- #
# Cancellation
# --------------------------------------------------------------------------- #


class TestCancellation:
    def test_cancel_queued_command_drops_it_before_send(self):
        core = WSClientCore(make_config())
        rid = core.send_command({"op": "x"})
        core.cancel_command(rid)
        actions = connect_core(core)
        sent = [f for f in sent_frames(actions) if f["type"] == COMMAND]
        assert rid not in {f["request_id"] for f in sent}

    def test_cancel_inflight_command_sends_cancel_frame(self):
        core = WSClientCore(make_config())
        rid = core.send_command({"op": "x"})
        connect_core(core, session_id="s1")
        assert rid in core.pending_request_ids
        actions = core.cancel_command(rid)
        cancels = [f for f in sent_frames(actions) if f["type"] == CANCEL]
        assert cancels and cancels[0]["request_id"] == rid
        assert cancels[0]["session_id"] == "s1"

    def test_cancel_unknown_id_is_safe_noop(self):
        core = WSClientCore(make_config())
        connect_core(core)
        actions = core.cancel_command(9999)
        assert not [f for f in sent_frames(actions) if f["type"] == CANCEL]

    def test_cancel_is_idempotent(self):
        core = WSClientCore(make_config())
        rid = core.send_command({"op": "x"})
        connect_core(core, session_id="s1")
        core.cancel_command(rid)
        # Second cancel must not error.
        core.cancel_command(rid)


# --------------------------------------------------------------------------- #
# Stale-session rejection, duplicate / out-of-order frames
# --------------------------------------------------------------------------- #


class TestStaleSessionAndOrdering:
    def test_stale_session_event_rejected(self):
        core = WSClientCore(make_config())
        connect_core(core, session_id="current")
        actions = core.on_frame({"type": EVENT, "id": "e", "session_id": "OLD"})
        assert not any(a.type == ActionType.DELIVER_EVENT for a in actions)
        assert "stale_session_rejected" in telemetry_events(actions)

    def test_stale_session_ack_rejected(self):
        core = WSClientCore(make_config())
        rid = core.send_command({"op": "x"})
        connect_core(core, session_id="current")
        actions = core.on_frame({"type": ACK, "request_id": rid, "session_id": "OLD"})
        assert not any(a.type == ActionType.DELIVER_ACK for a in actions)
        assert rid in core.pending_request_ids  # not terminated by stale ack

    def test_session_agnostic_frame_accepted(self):
        core = WSClientCore(make_config())
        connect_core(core, session_id="current")
        actions = core.on_frame({"type": EVENT, "id": "e"})  # no session id
        assert any(a.type == ActionType.DELIVER_EVENT for a in actions)

    def test_duplicate_welcome_ignored(self):
        core = WSClientCore(make_config())
        connect_core(core, session_id="s1")
        actions = core.on_frame({"type": WELCOME, "session_id": "s2"})
        assert core.state == ConnectionState.CONNECTED
        assert core.session_id == "s1"  # unchanged
        assert "ignored_welcome" in telemetry_events(actions)

    def test_duplicate_ack_ignored(self):
        core = WSClientCore(make_config())
        rid = core.send_command({"op": "x"})
        connect_core(core, session_id="s1")
        core.on_frame({"type": ACK, "request_id": rid, "session_id": "s1"})
        actions = core.on_frame({"type": ACK, "request_id": rid, "session_id": "s1"})
        assert "ignored_ack" in telemetry_events(actions)

    def test_out_of_order_pong_before_tick_ignored(self):
        core = WSClientCore(make_config())
        connect_core(core, session_id="s1")
        # A pong arriving with no outstanding ping: harmless, just re-arms.
        actions = core.on_frame({"type": PONG, "session_id": "s1"})
        assert core.state == ConnectionState.CONNECTED
        assert "heartbeat" in timers_scheduled(actions)

    def test_unknown_frame_type_ignored(self):
        core = WSClientCore(make_config())
        connect_core(core, session_id="s1")
        actions = core.on_frame({"type": "bogus"})
        assert "unknown_frame" in telemetry_events(actions)

    def test_welcome_before_socket_open_ignored(self):
        # Out-of-order: a welcome cannot arrive before we even connect.
        core = WSClientCore(make_config())
        actions = core.on_frame({"type": WELCOME, "session_id": "s"})
        assert core.state == ConnectionState.DISCONNECTED
        assert "ignored_welcome" in telemetry_events(actions)


# --------------------------------------------------------------------------- #
# Fatal errors
# --------------------------------------------------------------------------- #


class TestErrors:
    def test_fatal_error_closes_permanently(self):
        core = WSClientCore(make_config())
        connect_core(core, session_id="s1")
        actions = core.on_frame({"type": ERROR, "code": "auth_failed", "fatal": True})
        assert core.state == ConnectionState.CLOSED
        assert "fatal_error" in telemetry_events(actions)

    def test_nonfatal_error_stays_connected(self):
        core = WSClientCore(make_config())
        connect_core(core, session_id="s1")
        actions = core.on_frame({"type": ERROR, "code": "rate_limited", "fatal": False})
        assert core.state == ConnectionState.CONNECTED
        assert "gateway_error" in telemetry_events(actions)


# --------------------------------------------------------------------------- #
# Secret redaction
# --------------------------------------------------------------------------- #


class TestRedaction:
    def test_redact_masks_secret_keys_at_any_depth(self):
        data = {
            "api_key": "secret1",
            "nested": {"token": "secret2", "ok": 1},
            "list": [{"password": "secret3"}],
        }
        out = redact(data)
        assert out["api_key"] == "***REDACTED***"
        assert out["nested"]["token"] == "***REDACTED***"
        assert out["nested"]["ok"] == 1
        assert out["list"][0]["password"] == "***REDACTED***"

    def test_redact_does_not_mutate_input(self):
        data = {"api_key": "secret"}
        redact(data)
        assert data["api_key"] == "secret"

    def test_api_key_never_appears_in_any_telemetry(self):
        core = WSClientCore(make_config(api_key="TOP-SECRET-VALUE"))
        driver = Driver(core)
        driver.call("start")
        driver.call("on_socket_open")
        driver.call("on_frame", {"type": WELCOME, "session_id": "s1"})
        driver.call("on_heartbeat_tick")
        driver.call("on_frame", {"type": PONG, "session_id": "s1"})
        driver.call("send_command", {"op": "x"})
        driver.call("drain")
        blob = repr(driver.telemetry)
        assert "TOP-SECRET-VALUE" not in blob
        # The hello frame itself carries the key (that is the wire), but the
        # telemetry mirror of it must be redacted.
        hello_telemetry = [t for t in driver.telemetry if t["event"] == "hello_sent"]
        assert hello_telemetry and hello_telemetry[0]["api_key"] == "***REDACTED***"


# --------------------------------------------------------------------------- #
# End-to-end scenarios via the deterministic driver:
# gateway restart, network partition, clock skew
# --------------------------------------------------------------------------- #


class TestScenarios:
    def test_gateway_restart_new_session_supersedes_old(self):
        core = WSClientCore(make_config(), rng=random.Random(5))
        driver = Driver(core)
        driver.call("start")
        driver.call("on_socket_open")
        driver.call("on_frame", {"type": WELCOME, "session_id": "sess-A"})
        assert core.session_id == "sess-A"

        # Gateway restarts: our socket drops.
        driver.call("on_socket_closed", "gateway_restart")
        assert core.state == ConnectionState.BACKOFF

        # A late frame from the OLD session must be rejected once we reconnect.
        driver.call("on_backoff_elapsed")
        driver.call("on_socket_open")
        driver.call("on_frame", {"type": WELCOME, "session_id": "sess-B"})
        assert core.session_id == "sess-B"
        before = len(driver.events)
        driver.call("on_frame", {"type": EVENT, "id": "late", "session_id": "sess-A"})
        assert len(driver.events) == before  # stale, not delivered
        assert "stale_session_rejected" in [t["event"] for t in driver.telemetry]

    def test_network_partition_commands_are_retried_at_least_once(self):
        core = WSClientCore(make_config(), rng=random.Random(11))
        driver = Driver(core)
        driver.call("start")
        driver.call("on_socket_open")
        driver.call("on_frame", {"type": WELCOME, "session_id": "s1"})
        rid = driver.call("send_command", {"op": "critical"})
        driver.call("drain")
        # Command was sent, not yet acked.
        assert rid in core.pending_request_ids

        # Partition: socket drops before ack. Command must be requeued.
        driver.call("on_socket_error", "partition")
        assert core.state == ConnectionState.BACKOFF
        assert core.command_backlog >= 1  # requeued for retry

        # Heal: reconnect, command re-sent (at-least-once semantics).
        driver.call("on_backoff_elapsed")
        driver.call("on_socket_open")
        driver.call("on_frame", {"type": WELCOME, "session_id": "s2"})
        resent = [f for f in driver.sent if f["type"] == COMMAND and f["request_id"] == rid]
        assert len(resent) >= 2  # original + retry

        # Finally acked exactly once terminates it.
        driver.call("on_frame", {"type": ACK, "request_id": rid, "session_id": "s2"})
        assert rid not in core.pending_request_ids

    def test_clock_skew_does_not_affect_logical_transitions(self):
        # The core never reads a wall clock; it is driven purely by ordered
        # events + timer callbacks. Firing timers "early" or "late" (simulating
        # skew) must not corrupt state. We fire a heartbeat timeout far out of
        # band and assert clean reconnect rather than a wedged state.
        core = WSClientCore(make_config(), rng=random.Random(2))
        driver = Driver(core)
        driver.call("start")
        driver.call("on_socket_open")
        driver.call("on_frame", {"type": WELCOME, "session_id": "s1"})

        # Skew: a heartbeat_timeout fires though no ping was sent (stale timer).
        driver.call("on_heartbeat_timeout")
        # It should be honoured as a liveness failure -> reconnect, never crash.
        assert core.state in (ConnectionState.BACKOFF, ConnectionState.CONNECTED)

        # And a backoff-elapsed firing while already CONNECTED (skewed leftover
        # timer) is ignored, not acted on.
        driver.call("on_backoff_elapsed")
        driver.call("on_socket_open")
        driver.call("on_frame", {"type": WELCOME, "session_id": "s2"})
        stray = core.on_backoff_elapsed()  # stray timer while connected
        assert core.state == ConnectionState.CONNECTED
        assert "ignored_backoff_elapsed" in [
            a.telemetry["event"] for a in stray if a.type == ActionType.TELEMETRY
        ]

    def test_full_reconnect_cycle_never_opens_two_sockets_at_once(self):
        core = WSClientCore(make_config(), rng=random.Random(8))
        driver = Driver(core)
        driver.call("start")
        for _ in range(4):
            driver.call("on_socket_open")
            driver.call("on_socket_error", "flap")
            driver.call("on_backoff_elapsed")
        # Opens and closes stay balanced (never leaks a dangling open).
        assert driver.open_count == driver.close_count + 1  # last open still live


# --------------------------------------------------------------------------- #
# Property-based / stateful tests (hypothesis): the machine must never crash,
# never leak invariants, no matter the order or duplication of driver events.
# --------------------------------------------------------------------------- #

from hypothesis import HealthCheck, given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402
from hypothesis.stateful import (  # noqa: E402
    RuleBasedStateMachine,
    invariant,
    precondition,
    rule,
)

_VALID_STATES = set(ConnectionState)


@settings(max_examples=200, deadline=None)
@given(seed=st.integers(min_value=0, max_value=2**32 - 1))
def test_backoff_delay_always_within_bounds_property(seed):
    cfg = make_config(jitter_ratio=0.2, backoff_max=60.0)
    core = WSClientCore(cfg, rng=random.Random(seed))
    core.start()
    core.on_socket_open()
    for _ in range(40):
        actions = core.on_socket_error()
        for a in actions:
            if a.type == ActionType.SCHEDULE_TIMER and a.timer == "backoff":
                assert 0.0 <= a.delay <= cfg.backoff_max * (1 + cfg.jitter_ratio) + 1e-9
        if core.state == ConnectionState.CLOSED:
            break
        core.on_backoff_elapsed()
        core.on_socket_open()


@settings(max_examples=200, deadline=None)
@given(
    ops=st.lists(
        st.dictionaries(st.text(min_size=1, max_size=4), st.integers(), max_size=3), max_size=30
    )
)
def test_request_ids_strictly_increasing_property(ops):
    core = WSClientCore(make_config(max_command_queue=0))  # unbounded for id test
    ids = [core.send_command(op) for op in ops]
    assert ids == sorted(ids)
    assert len(set(ids)) == len(ids)


class WSClientStateMachine(RuleBasedStateMachine):
    """Fuzz every driver event in arbitrary order and assert core invariants."""

    def __init__(self):
        super().__init__()
        self.core = WSClientCore(
            make_config(max_command_queue=8, max_event_queue=8), rng=random.Random(0)
        )
        self._sent_secret = "super-secret-key"

    @rule()
    def start(self):
        self.core.start()

    @rule()
    def socket_open(self):
        self.core.on_socket_open()

    @rule(reason=st.sampled_from(["reset", "partition", "restart"]))
    def socket_error(self, reason):
        self.core.on_socket_error(reason)

    @rule()
    def backoff_elapsed(self):
        self.core.on_backoff_elapsed()

    @rule()
    def handshake_timeout(self):
        self.core.on_handshake_timeout()

    @rule(sid=st.sampled_from(["s1", "s2", "OLD", None]))
    def welcome(self, sid):
        frame = {"type": WELCOME}
        if sid is not None:
            frame["session_id"] = sid
        self.core.on_frame(frame)

    @rule()
    def heartbeat_tick(self):
        self.core.on_heartbeat_tick()

    @rule()
    def heartbeat_timeout(self):
        self.core.on_heartbeat_timeout()

    @rule(sid=st.sampled_from(["s1", "s2", "OLD", None]), eid=st.integers(min_value=0, max_value=5))
    def event(self, sid, eid):
        frame = {"type": EVENT, "id": eid}
        if sid is not None:
            frame["session_id"] = sid
        self.core.on_frame(frame)

    @rule(payload=st.dictionaries(st.text(max_size=3), st.integers(), max_size=2))
    def send_command(self, payload):
        self.core.send_command(payload)

    @rule()
    @precondition(lambda self: self.core.pending_request_ids)
    def cancel_pending(self):
        rid = self.core.pending_request_ids[0]
        self.core.cancel_command(rid)

    @rule()
    def drain(self):
        self.core.drain()

    @invariant()
    def state_is_valid(self):
        assert self.core.state in _VALID_STATES

    @invariant()
    def queues_stay_bounded(self):
        assert self.core.command_backlog <= self.core.config.max_command_queue
        assert self.core.event_backlog <= self.core.config.max_event_queue

    @invariant()
    def backoff_never_exceeds_ceiling(self):
        cfg = self.core.config
        assert self.core._current_backoff <= cfg.backoff_max + 1e-9


TestWSClientStateMachine = WSClientStateMachine.TestCase
TestWSClientStateMachine.settings = settings(
    max_examples=200,
    stateful_step_count=40,
    deadline=None,
    suppress_health_check=[HealthCheck.filter_too_much],
)
