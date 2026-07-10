"""Safety-rail tests for execute_code (bead houdini-mcp-9e2).

Covers, per acceptance criteria:
1. Dangerous / heavy-geometry gating with actionable hints (+ network patterns).
2. Timeout/output/diff caps tested at boundaries; timed-out work cannot leave
   untracked mutations (undo/rollback or fail-closed).
3. Explicit, audited policy profiles: read-only / normal / privileged.
4. Bypass flags require configuration + request opt-in and are logged/audited.
5. Fuzz/property tests over evasion variants.
6. Red-path harness proving blocked code never reaches the interpreter.
"""

from unittest.mock import patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st


@pytest.fixture
def allow_bypass_config(monkeypatch):
    """Enable the server-side bypass configuration gate."""
    monkeypatch.setenv("HOUDINI_MCP_ALLOW_BYPASS", "true")
    import houdini_mcp.tools.code as code_mod

    monkeypatch.setattr(code_mod, "_bypass_config_enabled", lambda: True)
    yield


@pytest.fixture
def deny_bypass_config(monkeypatch):
    """Force the server-side bypass configuration gate OFF."""
    monkeypatch.delenv("HOUDINI_MCP_ALLOW_BYPASS", raising=False)
    import houdini_mcp.tools.code as code_mod

    monkeypatch.setattr(code_mod, "_bypass_config_enabled", lambda: False)
    yield


# ---------------------------------------------------------------------------
# AC1: expanded dangerous-pattern coverage (network / evasion)
# ---------------------------------------------------------------------------


class TestNetworkPatternDetection:
    """Network egress patterns must be treated as dangerous."""

    @pytest.mark.parametrize(
        "code",
        [
            "import socket; socket.socket()",
            "import urllib.request; urllib.request.urlopen('http://x')",
            "import requests; requests.get('http://x')",
            "from http.client import HTTPConnection",
            "eval('1+1')",
            "exec('x=1')",
            "__import__('os').system('ls')",
        ],
    )
    def test_network_and_eval_flagged(self, code):
        from houdini_mcp.tools import _detect_dangerous_code

        assert _detect_dangerous_code(code), f"expected detection for: {code!r}"


class TestCommentAndStringEvasion:
    """Detection should not be fooled by trivial whitespace obfuscation."""

    @pytest.mark.parametrize(
        "code",
        [
            "hou . exit ()",
            "hou.exit ( )",
            "os.remove ('/tmp/x')",
            "subprocess . run(['ls'])",
        ],
    )
    def test_whitespace_variants_detected(self, code):
        from houdini_mcp.tools import _detect_dangerous_code

        assert _detect_dangerous_code(code), f"expected detection for: {code!r}"


# ---------------------------------------------------------------------------
# AC5: property / fuzz tests over evasion variants
# ---------------------------------------------------------------------------


class TestEvasionProperties:
    @settings(max_examples=75, deadline=None)
    @given(
        pre=st.text(alphabet=" \t", max_size=4),
        mid=st.text(alphabet=" \t", max_size=4),
    )
    def test_hou_exit_survives_inner_whitespace(self, pre, mid):
        from houdini_mcp.tools import _detect_dangerous_code

        code = f"hou{pre}.{mid}exit()"
        assert _detect_dangerous_code(code)

    @settings(max_examples=75, deadline=None)
    @given(indent=st.text(alphabet=" \t", max_size=8))
    def test_subprocess_detected_regardless_of_indent(self, indent):
        from houdini_mcp.tools import _detect_dangerous_code

        code = f"{indent}subprocess.run(['x'])"
        assert _detect_dangerous_code(code)

    @settings(max_examples=75, deadline=None)
    @given(name=st.text(alphabet="abcdefghijklmnopqrstuvwxyz_", min_size=1, max_size=12))
    def test_safe_identifiers_not_flagged(self, name):
        from houdini_mcp.tools import _detect_dangerous_code

        # A bare variable assignment must never be considered dangerous.
        assert _detect_dangerous_code(f"{name} = 1") == []


# ---------------------------------------------------------------------------
# AC3: policy profiles (read-only / normal / privileged)
# ---------------------------------------------------------------------------


class TestPolicyProfiles:
    def test_read_only_blocks_node_creation_pattern(self, mock_connection):
        from houdini_mcp.tools import execute_code

        result = execute_code(
            "hou.node('/obj').createNode('geo')",
            policy="read-only",
            host="localhost",
            port=18811,
        )
        assert result["status"] == "error"
        assert result["policy"] == "read-only"
        assert "read-only" in result["message"].lower()
        assert "mutation_patterns" in result

    def test_read_only_allows_pure_inspection(self, mock_connection):
        from houdini_mcp.tools import execute_code

        result = execute_code(
            "print(hou.applicationVersionString())",
            policy="read-only",
            host="localhost",
            port=18811,
        )
        assert result["status"] == "success"
        assert result["policy"] == "read-only"

    def test_read_only_ignores_bypass_flags(self, mock_connection, allow_bypass_config):
        """read-only is the strictest profile: bypass flags cannot escalate it."""
        from houdini_mcp.tools import execute_code

        result = execute_code(
            "hou.hipFile.clear()",
            policy="read-only",
            allow_dangerous=True,
            host="localhost",
            port=18811,
        )
        assert result["status"] == "error"
        assert result["policy"] == "read-only"

    def test_normal_is_default_profile(self, mock_connection):
        from houdini_mcp.tools import execute_code

        result = execute_code("print('hi')", host="localhost", port=18811)
        assert result["status"] == "success"
        assert result["policy"] == "normal"

    def test_privileged_requires_config_gate(self, mock_connection, deny_bypass_config):
        """privileged profile without config gate must fail closed."""
        from houdini_mcp.tools import execute_code

        result = execute_code(
            "print('x')",
            policy="privileged",
            host="localhost",
            port=18811,
        )
        assert result["status"] == "error"
        assert "config" in result["message"].lower()

    def test_privileged_allowed_with_config(self, mock_connection, allow_bypass_config):
        from houdini_mcp.tools import execute_code

        result = execute_code(
            "print('privileged run')",
            policy="privileged",
            host="localhost",
            port=18811,
        )
        assert result["status"] == "success"
        assert result["policy"] == "privileged"

    def test_unknown_policy_rejected(self, mock_connection):
        from houdini_mcp.tools import execute_code

        result = execute_code("print('x')", policy="superuser", host="localhost", port=18811)
        assert result["status"] == "error"
        assert "policy" in result["message"].lower()


# ---------------------------------------------------------------------------
# AC4: bypass flags require configuration + request opt-in and are audited
# ---------------------------------------------------------------------------


class TestBypassRequiresConfigAndRequest:
    def test_request_flag_without_config_is_denied(self, mock_connection, deny_bypass_config):
        from houdini_mcp.tools import execute_code

        result = execute_code(
            "hou.exit()",
            allow_dangerous=True,
            host="localhost",
            port=18811,
        )
        assert result["status"] == "error"
        # Denied because config gate is off, even though request asked to bypass.
        assert "config" in result["message"].lower()
        assert result.get("bypass_requested") is True
        assert result.get("bypass_config_enabled") is False

    def test_config_without_request_flag_still_blocks(self, mock_connection, allow_bypass_config):
        from houdini_mcp.tools import execute_code

        result = execute_code("hou.exit()", host="localhost", port=18811)
        assert result["status"] == "error"
        assert "Dangerous operations detected" in result["message"]

    def test_both_config_and_request_allows(self, mock_connection, allow_bypass_config):
        from houdini_mcp.tools import execute_code

        result = execute_code(
            "print('would call hou.exit()')",
            allow_dangerous=True,
            host="localhost",
            port=18811,
        )
        assert result["status"] == "success"

    def test_heavy_geometry_bypass_requires_config(self, mock_connection, deny_bypass_config):
        from houdini_mcp.tools import execute_code

        result = execute_code(
            "geo = hou.node('/obj/geo1/out').geometry()",
            allow_heavy_geometry=True,
            host="localhost",
            port=18811,
        )
        assert result["status"] == "error"
        assert "config" in result["message"].lower()


class TestAuditFields:
    """Every execution must return structured audit metadata."""

    def test_audit_present_on_success(self, mock_connection):
        from houdini_mcp.tools import execute_code

        result = execute_code("print('hi')", host="localhost", port=18811)
        audit = result["audit"]
        assert audit["policy"] == "normal"
        assert audit["allow_dangerous_requested"] is False
        assert audit["allow_heavy_geometry_requested"] is False
        assert audit["bypass_config_enabled"] in (True, False)
        assert audit["dangerous_patterns"] == []
        assert audit["heavy_geometry_patterns"] == []
        assert audit["timed_out"] is False
        assert "code_sha256" in audit
        assert "code_length" in audit

    def test_audit_records_executed_bypass(self, mock_connection, allow_bypass_config):
        from houdini_mcp.tools import execute_code

        result = execute_code(
            "print('mentions hou.exit()')",
            allow_dangerous=True,
            host="localhost",
            port=18811,
        )
        audit = result["audit"]
        assert audit["allow_dangerous_requested"] is True
        assert audit["bypass_config_enabled"] is True
        assert audit["dangerous_patterns"]

    def test_blocked_execution_is_logged(self, mock_connection, caplog):
        import logging

        from houdini_mcp.tools import execute_code

        with caplog.at_level(logging.WARNING):
            execute_code("hou.exit()", host="localhost", port=18811)
        assert any(
            "execute_code" in r.message.lower() and "block" in r.message.lower()
            for r in caplog.records
        )


# ---------------------------------------------------------------------------
# AC2: timeout must not leave untracked mutations (undo / fail-closed)
# ---------------------------------------------------------------------------


class TestTimeoutRollback:
    def test_timeout_triggers_rollback_when_undo_available(self, mock_connection):
        """A timed-out run wrapped in an undo group must attempt a rollback."""
        from houdini_mcp.tools import execute_code

        code = "import time\nwhile True:\n    time.sleep(0.05)\n"
        result = execute_code(
            code,
            timeout=1,
            allow_dangerous=True,  # 'import time' + while loop is otherwise fine
            host="localhost",
            port=18811,
        )
        assert result["status"] == "error"
        assert result.get("timeout") == 1
        # Rollback must have been attempted on the Houdini side.
        assert mock_connection.undos.performed_undos >= 1
        assert result["audit"]["timed_out"] is True
        assert result["audit"]["rollback_attempted"] is True

    def test_timeout_reports_rollback_status(self, mock_connection):
        from houdini_mcp.tools import execute_code

        code = "import time\nwhile True:\n    time.sleep(0.05)\n"
        result = execute_code(
            code,
            timeout=1,
            allow_dangerous=True,
            host="localhost",
            port=18811,
        )
        assert "rollback" in result
        assert result["rollback"]["attempted"] is True

    def test_rollback_does_not_overclaim_guarantee(self, mock_connection):
        """The daemon exec thread cannot be force-killed on timeout, so even a
        'succeeded' rollback must not be reported as a hard guarantee that the
        scene is consistent - the original code may still be running and
        mutating the scene concurrently. The response must surface this risk
        explicitly rather than implying rollback == safety.
        """
        from houdini_mcp.tools import execute_code

        code = "import time\nwhile True:\n    time.sleep(0.05)\n"
        result = execute_code(
            code,
            timeout=1,
            allow_dangerous=True,
            host="localhost",
            port=18811,
        )
        assert result["rollback"]["attempted"] is True
        assert result["rollback"]["succeeded"] is True
        # Even on a "succeeded" rollback, the thread-still-running risk must be
        # reported explicitly in the structured rollback block...
        assert result["rollback"]["thread_still_running"] is True
        # ...and the human-readable warning must not claim a hard guarantee -
        # it should communicate that the scene may still be mutated further.
        warning = result.get("warning", "").lower()
        assert "not" in warning and "guarantee" in warning
        assert "still" in warning and ("running" in warning or "thread" in warning)

    def test_undo_group_opened_around_execution(self, mock_connection):
        """Successful runs must be wrapped in a named undo group for later rollback."""
        from houdini_mcp.tools import execute_code

        result = execute_code("print('wrapped')", host="localhost", port=18811)
        assert result["status"] == "success"
        assert mock_connection.undos.closed_groups, "expected a named undo group"

    def test_fail_closed_when_no_undo_primitive(self, monkeypatch, mock_connection):
        """If Houdini exposes no usable undo primitive, timeout must fail closed."""
        from houdini_mcp.tools import execute_code

        # Remove undo capability to simulate an environment without rollback.
        monkeypatch.delattr(mock_connection, "undos", raising=False)

        code = "import time\nwhile True:\n    time.sleep(0.05)\n"
        result = execute_code(
            code,
            timeout=1,
            allow_dangerous=True,
            host="localhost",
            port=18811,
        )
        assert result["status"] == "error"
        assert result["audit"]["timed_out"] is True
        assert result["audit"]["rollback_attempted"] is False
        # Must clearly surface that mutations may be untracked.
        assert (
            "untracked" in result.get("warning", "").lower()
            or result.get("rollback", {}).get("attempted") is False
        )


# ---------------------------------------------------------------------------
# AC2: cap-boundary tests (stdout / stderr / diff nodes)
# ---------------------------------------------------------------------------


class TestCapBoundaries:
    def test_stdout_exactly_at_limit_not_truncated(self, mock_connection):
        from houdini_mcp.tools import execute_code

        # Emit exactly 50 characters, cap at 50.
        result = execute_code(
            "import sys; sys.stdout.write('x' * 50)",
            max_stdout_size=50,
            host="localhost",
            port=18811,
        )
        assert result["status"] == "success"
        assert len(result["stdout"]) == 50
        assert result.get("stdout_truncated") is not True

    def test_stdout_one_over_limit_truncated(self, mock_connection):
        from houdini_mcp.tools import execute_code

        result = execute_code(
            "import sys; sys.stdout.write('x' * 51)",
            max_stdout_size=50,
            host="localhost",
            port=18811,
        )
        assert result["status"] == "success"
        assert len(result["stdout"]) == 50
        assert result.get("stdout_truncated") is True

    def test_stderr_one_over_limit_truncated(self, mock_connection):
        from houdini_mcp.tools import execute_code

        result = execute_code(
            "import sys; sys.stderr.write('y' * 51)",
            max_stderr_size=50,
            host="localhost",
            port=18811,
        )
        assert result["status"] == "success"
        assert len(result["stderr"]) == 50
        assert result.get("stderr_truncated") is True

    def test_diff_nodes_boundary(self, mock_connection):
        """added_nodes must be capped at exactly max_diff_nodes."""
        from houdini_mcp.tools import code as code_mod

        before = []
        after = [{"path": f"/obj/geo{i}", "type": "geo", "name": f"geo{i}"} for i in range(5)]

        with patch.object(code_mod, "_serialize_scene_state", side_effect=[before, after]):
            result = code_mod.execute_code(
                "print('make nodes')",
                capture_diff=True,
                max_diff_nodes=3,
                host="localhost",
                port=18811,
            )
        assert result["status"] == "success"
        assert len(result["scene_changes"]["added_nodes"]) == 3
        assert result.get("diff_truncated") is True


# ---------------------------------------------------------------------------
# AC6: red-path harness — blocked code never reaches exec()
# ---------------------------------------------------------------------------


class TestBlockedCodeNeverExecutes:
    def test_dangerous_block_short_circuits_before_exec(self, mock_connection):
        from houdini_mcp.tools import code as code_mod

        sentinel = {"ran": False}

        def _tripwire(*_a, **_k):
            sentinel["ran"] = True
            raise AssertionError("exec must not run for blocked code")

        # Patch the builtin exec used inside the module's execution path.
        with patch.object(code_mod, "exec", _tripwire, create=True):
            result = code_mod.execute_code("hou.exit()", host="localhost", port=18811)
        assert result["status"] == "error"
        assert sentinel["ran"] is False

    def test_read_only_mutation_short_circuits_before_exec(self, mock_connection):
        from houdini_mcp.tools import code as code_mod

        sentinel = {"ran": False}

        def _tripwire(*_a, **_k):
            sentinel["ran"] = True
            raise AssertionError("exec must not run under read-only block")

        with patch.object(code_mod, "exec", _tripwire, create=True):
            result = code_mod.execute_code(
                "hou.node('/obj').createNode('geo')",
                policy="read-only",
                host="localhost",
                port=18811,
            )
        assert result["status"] == "error"
        assert sentinel["ran"] is False
