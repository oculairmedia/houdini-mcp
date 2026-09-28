"""Declared temporary state with a restoration receipt, including failure paths."""

from .errors import CompanionError

CAMERA_PARMS = (
    "tx",
    "ty",
    "tz",
    "rx",
    "ry",
    "rz",
    "sx",
    "sy",
    "sz",
    "focal",
    "projection",
    "orthowidth",
    "aperture",
    "near",
    "far",
    "resx",
    "resy",
    "aspect",
    "winx",
    "winy",
    "winsizex",
    "winsizey",
)


def time_state(hou):
    return {
        "frame": hou.frame(),
        "fps": hou.fps(),
        "frame_range": list(hou.playbar.frameRange()),
        "playback_range": list(hou.playbar.playbackRange()),
        "playing": hou.playbar.isPlaying(),
    }


def camera_state(node):
    return {
        p: {"value": node.parm(p).eval(), "keys": [k.asCode() for k in node.parm(p).keyframes()]}
        for p in CAMERA_PARMS
        if node.parm(p) is not None
    }


class StateGuard:
    """Only restores declared channels/time; arbitrary Python is not sandboxed.

    Each bounded operation owns this guard for one UI dispatch. It must not span
    an event-loop yield: artist changes between jobs belong to the artist.
    """

    def __init__(self, hou, cameras=()):
        self.hou = hou
        self.cameras = list(cameras)
        self.receipt = {"restored": False, "failures": []}

    def __enter__(self):
        self.before = time_state(self.hou)
        self.saved = [
            (
                n,
                camera_state(n),
                {
                    p: (n.parm(p).eval(), tuple(n.parm(p).keyframes()))
                    for p in CAMERA_PARMS
                    if n.parm(p) is not None
                },
            )
            for n in self.cameras
        ]
        self.receipt["before"] = {
            "time": self.before,
            "cameras": {n.path(): s for n, s, _ in self.saved},
        }
        if self.before["playing"]:
            self.hou.playbar.stop()
        return self

    def __exit__(self, kind, error, traceback):
        failures = self.receipt["failures"]

        def attempt(name, operation):
            try:
                operation()
            except Exception as exc:
                failures.append({"field": name, "message": str(exc)})

        h, before = self.hou, self.before
        for name, getter, setter in (
            ("fps", h.fps, h.setFps),
            (
                "frame_range",
                lambda: list(h.playbar.frameRange()),
                lambda v: h.playbar.setFrameRange(*v),
            ),
            (
                "playback_range",
                lambda: list(h.playbar.playbackRange()),
                lambda v: h.playbar.setPlaybackRange(*v),
            ),
            ("frame", h.frame, h.setFrame),
        ):
            attempt(
                name,
                lambda name=name, getter=getter, setter=setter: (
                    setter(before[name]) if getter() != before[name] else None
                ),
            )
        for node, state, saved in self.saved:
            for name, (value, keys) in saved.items():

                def restore(node=node, name=name, value=value, keys=keys, state=state):
                    p = node.parm(name)
                    current = {"value": p.eval(), "keys": [k.asCode() for k in p.keyframes()]}
                    if current != state[name]:
                        p.deleteAllKeyframes()
                        if keys:
                            p.setKeyframes(keys)
                        else:
                            p.set(value)

                attempt(f"camera:{name}", restore)
        attempt(
            "playing",
            lambda: (
                (h.playbar.play() if before["playing"] else h.playbar.stop())
                if h.playbar.isPlaying() != before["playing"]
                else None
            ),
        )
        self.receipt["restored"] = not failures
        attempt(
            "readback",
            lambda: self.receipt.update(
                after={
                    "time": time_state(h),
                    "cameras": {n.path(): camera_state(n) for n in self.cameras},
                }
            ),
        )
        self.receipt["restored"] = not failures
        if not failures and self.receipt.get("after") != self.receipt["before"]:
            failures.append(
                {"field": "readback", "message": "Restored state differs from captured state"}
            )
            self.receipt["restored"] = False
        if failures:
            raise CompanionError(
                "STATE_RESTORE_FAILED",
                "Temporary state was only partially restored",
                receipt=self.receipt,
                original_error=str(error) if error else None,
            ) from error
        return False
