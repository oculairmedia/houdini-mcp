"""Bounded, targeted scene awareness. Callbacks only invalidate prior evidence."""

import time
from pathlib import Path


def observations(value):
    if isinstance(value, dict):
        if "token" in value and "dependency_paths" in value:
            yield value
        for child in value.values():
            yield from observations(child)
    elif isinstance(value, list):
        for child in value:
            yield from observations(child)


class Watchers:
    def __init__(self, hou, ledger):
        self.hou, self.ledger = hou, ledger
        self.nodes = {}
        self.files = {}
        self.last_poll = 0
        self.frame = hou.frame()
        self.take = hou.takes.currentTake().name()
        self.callback = self.node_event
        self.event_types = tuple(
            getattr(hou.nodeEventType, name)
            for name in (
                "ParmTupleChanged",
                "InputRewired",
                "NameChanged",
                "BeingDeleted",
                "FlagChanged",
                "ChildCreated",
                "ChildDeleted",
            )
        )

    def track(self, result):
        for obs in observations(result):
            for path in obs["dependency_paths"]:
                node = self.hou.node(path)
                if node is None or node.sessionId() in self.nodes:
                    continue
                if len(self.nodes) >= 512:
                    self.ledger.event(
                        "awareness.limit",
                        message="Watcher limit reached; explicit validation still required",
                    )
                    return
                node.addEventCallback(self.event_types, self.callback)
                self.nodes[node.sessionId()] = node
            for source in obs.get("sources", []):
                if len(self.files) < 128:
                    self.files[source["path"]] = self.stat(source["path"])

    @staticmethod
    def stat(path):
        try:
            value = Path(path).stat()
            return value.st_mtime_ns, value.st_size
        except OSError:
            return None

    def invalidate(self, path=None, source=None, all_results=False):
        with self.ledger.lock:
            for job in self.ledger.jobs.values():
                result = job.get("result")
                if not isinstance(result, dict) or result.get("stale"):
                    continue
                for obs in observations(result):
                    if (
                        all_results
                        or path in obs["dependency_paths"]
                        or any(entry["path"] == source for entry in obs.get("sources", []))
                    ):
                        result["stale"] = True
                        result["stale_reason"] = (
                            "Observed dependency changed; inspect or validate again"
                        )
                        self.ledger.event(
                            "observation.stale", job_id=job["job_id"], path=path, source=source
                        )
                        break

    def node_event(self, node, event_type, **kwargs):
        self.invalidate(path=node.path())
        if event_type == self.hou.nodeEventType.BeingDeleted:
            self.nodes.pop(node.sessionId(), None)

    def poll(self):
        if time.monotonic() - self.last_poll < 0.5:
            return
        self.last_poll = time.monotonic()
        frame, take = self.hou.frame(), self.hou.takes.currentTake().name()
        if (frame, take) != (self.frame, self.take):
            self.frame, self.take = frame, take
            self.invalidate(all_results=True)
            self.ledger.event("scene.context_changed", frame=frame, take=take)
        for path, previous in list(self.files.items()):
            current = self.stat(path)
            if current != previous:
                self.files[path] = current
                self.invalidate(source=path)

    def clear(self):
        for node in self.nodes.values():
            try:
                node.removeEventCallback(self.event_types, self.callback)
            except self.hou.Error:
                pass
        self.nodes.clear()
        self.files.clear()
