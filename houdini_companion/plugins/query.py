from __future__ import annotations

from ..observation import (
    fingerprint,
    inspect_node,
    require_node,
)
from . import BasePlugin, make_plugin


class Handlers(BasePlugin):
    def op_inspect(self, job, path=None, geometry=False):
        if path:
            return inspect_node(self.hou, path, geometry)
        selected = self.hou.selectedNodes()
        return {
            "selection": [inspect_node(self.hou, n.path(), geometry) for n in selected[:16]],
            "selected_count": len(selected),
            "hip_path": self.hou.hipFile.path(),
            "frame": self.hou.frame(),
        }

    def op_validate_observation(self, job, path, expected):
        actual = fingerprint(self.hou, require_node(self.hou, path))
        return {"stale": actual["token"] != expected, "observation": actual}


def plugin():
    return make_plugin("query", Handlers, ("inspect", "validate_observation"), requires=())
