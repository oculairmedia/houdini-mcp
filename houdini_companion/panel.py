"""Small optional Houdini panel; the runtime owns all state independently."""

from __future__ import annotations

import json
import uuid


def create_interface():
    try:
        from PySide2 import QtCore, QtGui, QtWidgets
    except ImportError:
        from PySide6 import QtCore, QtGui, QtWidgets

    import hou

    from . import runtime

    class CompanionPanel(QtWidgets.QWidget):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("Houdini Companion")
            self.last_sequence = -1
            layout = QtWidgets.QVBoxLayout(self)
            self.status = QtWidgets.QLabel()
            layout.addWidget(self.status)
            buttons = QtWidgets.QHBoxLayout()
            layout.addLayout(buttons)
            for title, callback in [
                ("Start", self.start),
                ("Inspect selected", self.inspect_selected),
                ("Cancel queued / request stop", self.cancel),
                ("Undo selected", self.undo),
            ]:
                button = QtWidgets.QPushButton(title)
                button.clicked.connect(callback)
                buttons.addWidget(button)
            self.jobs = QtWidgets.QListWidget()
            self.jobs.setMaximumHeight(180)
            self.jobs.currentItemChanged.connect(self.show_job)
            layout.addWidget(self.jobs)
            self.image = QtWidgets.QLabel()
            self.image.setAlignment(QtCore.Qt.AlignCenter)
            self.image.setMinimumHeight(220)
            self.image.setMaximumHeight(320)
            layout.addWidget(self.image)
            self.report = QtWidgets.QPlainTextEdit()
            self.report.setReadOnly(True)
            layout.addWidget(self.report, 1)
            self.timer = QtCore.QTimer(self)
            self.timer.timeout.connect(self.refresh)
            self.timer.start(500)
            self.refresh()

        def start(self):
            try:
                runtime.start()
            except Exception as exc:
                self.report.setPlainText(str(exc))
            self.refresh()

        def submit(self, operation, params):
            rt = runtime.instance()
            if rt is None:
                self.report.setPlainText("Start the companion first")
                return
            try:
                rt.ledger.submit(
                    {
                        "version": 1,
                        "session_id": rt.ledger.session_id,
                        "scene_id": rt.ledger.scene_id,
                        "request_id": uuid.uuid4().hex,
                        "operation": operation,
                        "params": params,
                    }
                )
            except Exception as exc:
                self.report.setPlainText(str(exc))

        def inspect_selected(self):
            nodes = hou.selectedNodes()
            if nodes and isinstance(nodes[0], hou.SopNode):
                self.submit("snapshot", {"path": nodes[0].path()})
            else:
                self.submit("inspect", {})

        def cancel(self):
            rt, item = runtime.instance(), self.jobs.currentItem()
            if rt and item:
                rt.ledger.cancel(item.data(QtCore.Qt.UserRole))

        def undo(self):
            item = self.jobs.currentItem()
            if item:
                self.submit("undo", {"job_id": item.data(QtCore.Qt.UserRole)})

        def refresh(self):
            rt = runtime.instance()
            if rt is None:
                self.status.setText("Companion stopped")
                return
            status = rt.ledger.status()
            self.status.setText(
                f"Houdini {rt.capabilities['houdini']} • {status['queued']} queued • "
                + ("Executing " + status["active_job"][:8] if status["active_job"] else "Ready")
            )
            sequence = (rt.ledger.session_id, rt.ledger.sequence)
            if self.last_sequence == sequence:
                return
            self.last_sequence = sequence
            current = self.jobs.currentItem()
            selected = current.data(QtCore.Qt.UserRole) if current else None
            self.jobs.clear()
            for jid, job in reversed(list(rt.ledger.jobs.items())[-30:]):
                item = QtWidgets.QListWidgetItem(
                    f"{jid[:8]}  {job['operation']}  {job['state']} / {job['phase']}"
                )
                item.setData(QtCore.Qt.UserRole, jid)
                self.jobs.addItem(item)
                if jid == selected:
                    self.jobs.setCurrentItem(item)
            if not self.jobs.currentItem() and self.jobs.count():
                self.jobs.setCurrentRow(0)

        def show_job(self, item, previous=None):
            rt = runtime.instance()
            self.image.clear()
            if not rt or not item:
                return
            jid = item.data(QtCore.Qt.UserRole)
            job = rt.ledger.get(jid)
            self.report.setPlainText(json.dumps(job, indent=2))
            result = job.get("result", {})
            images = result.get("feedback", result).get("images", [])
            if images:
                path = rt.ledger.root / jid / images[-1]["name"]
                pixmap = QtGui.QPixmap(str(path))
                self.image.setPixmap(
                    pixmap.scaled(
                        400, 300, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation
                    )
                )

    return CompanionPanel()
