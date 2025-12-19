"""Integration tests against a live Houdini hrpyc server.

These tests are skipped by default. To run them, set:

- RUN_INTEGRATION_TESTS=1
- HOUDINI_HOST=<host>
- HOUDINI_PORT=<port>

They create temporary nodes and clean up after themselves.
"""

from __future__ import annotations

import os
import uuid

import pytest

from houdini_mcp import tools


def _integration_enabled() -> bool:
    return os.getenv("RUN_INTEGRATION_TESTS") == "1"


def _houdini_target() -> tuple[str, int]:
    host = os.getenv("HOUDINI_HOST")
    port_str = os.getenv("HOUDINI_PORT")

    if not host or not port_str:
        raise RuntimeError("HOUDINI_HOST and HOUDINI_PORT must both be set")

    return host, int(port_str)


pytestmark = pytest.mark.skipif(
    not _integration_enabled(),
    reason="set RUN_INTEGRATION_TESTS=1 to enable integration tests",
)


@pytest.mark.integration
def test_check_connection_round_trip() -> None:
    host, port = _houdini_target()

    info = tools.get_scene_info(host, port)
    assert info["status"] == "success"
    assert "houdini_version" in info


@pytest.mark.integration
def test_create_and_delete_node() -> None:
    host, port = _houdini_target()

    node_name = f"mcp_it_{uuid.uuid4().hex[:8]}"
    created_path = None

    try:
        created = tools.create_node("geo", "/obj", node_name, host, port)
        assert created["status"] == "success"
        created_path = created["node_path"]

        node_info = tools.get_node_info(created_path, include_params=False, host=host, port=port)
        assert node_info["status"] == "success"
        assert node_info["path"] == created_path

    finally:
        if created_path:
            tools.delete_node(created_path, host, port)


@pytest.mark.integration
def test_parameter_schema_recurses_into_folders() -> None:
    host, port = _houdini_target()

    geo_name = f"mcp_it_schema_{uuid.uuid4().hex[:8]}"
    geo_path = None

    try:
        geo = tools.create_node("geo", "/obj", geo_name, host, port)
        assert geo["status"] == "success"
        geo_path = geo["node_path"]

        attribnoise = tools.create_node("attribnoise", geo_path, "attribnoise1", host, port)
        assert attribnoise["status"] == "success"
        attribnoise_path = attribnoise["node_path"]

        schema = tools.get_parameter_schema(attribnoise_path, max_parms=200, host=host, port=port)
        assert schema["status"] == "success"
        assert schema["count"] > 0

        names = {p["name"] for p in schema["parameters"]}
        # `attribnoise` is folder-heavy; `remapramp` is nested and should appear.
        assert "remapramp" in names

    finally:
        if geo_path:
            tools.delete_node(geo_path, host, port)


@pytest.mark.integration
def test_get_node_info_serializes_ramp_parameter() -> None:
    host, port = _houdini_target()

    geo_name = f"mcp_it_ramp_{uuid.uuid4().hex[:8]}"
    geo_path = None

    try:
        geo = tools.create_node("geo", "/obj", geo_name, host, port)
        assert geo["status"] == "success"
        geo_path = geo["node_path"]

        attribnoise = tools.create_node("attribnoise", geo_path, "attribnoise1", host, port)
        assert attribnoise["status"] == "success"
        attribnoise_path = attribnoise["node_path"]

        info = tools.get_node_info(attribnoise_path, include_params=True, host=host, port=port)
        assert info["status"] == "success"

        remapramp = info["parameters"].get("remapramp")
        assert isinstance(remapramp, dict)
        assert remapramp.get("type") == "hou.Ramp"
        assert "keys" in remapramp
        assert "values" in remapramp

    finally:
        if geo_path:
            tools.delete_node(geo_path, host, port)
