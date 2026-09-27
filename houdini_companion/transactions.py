"""Guarded file replacement with durable recovery evidence; not a crash-atomic transaction."""

import base64
import hashlib
import os
import tempfile
from pathlib import Path

from .core import atomic_json
from .errors import CompanionError


def sha(data):
    return hashlib.sha256(data).hexdigest()


def record(path, content):
    path = Path(path).resolve()
    original = path.read_bytes()
    return {
        "path": str(path),
        "before": base64.b64encode(original).decode(),
        "after": base64.b64encode(content).decode(),
        "before_sha256": sha(original),
        "after_sha256": sha(content),
    }


def check_files(records, side):
    for item in records:
        p = Path(item["path"])
        if not p.is_file() or sha(p.read_bytes()) != item[side + "_sha256"]:
            raise CompanionError("STALE_SOURCE", "Source changed; refusing overwrite", path=str(p))


def replace_bytes(path, data):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix=".companion-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, path.stat().st_mode)
        os.replace(temporary, path)
    finally:
        if Path(temporary).exists():
            Path(temporary).unlink()


def transact(records, journal, mutate, revert, metadata=None):
    check_files(records, "before")
    receipt = {
        "state": "prepared",
        "files": records,
        "metadata": metadata or {},
        "guarantee": "guarded rollback on handled failures; not process-crash atomic",
    }
    atomic_json(journal, receipt)
    written = []
    try:
        for item in records:
            check_files([item], "before")
            replace_bytes(item["path"], base64.b64decode(item["after"]))
            written.append(item)
        receipt["state"] = "files_written"
        atomic_json(journal, receipt)
        result = mutate()
        check_files(records, "after")
        receipt["state"] = "applied"
        atomic_json(journal, receipt)
        return result
    except Exception as exc:
        errors = []
        for item in reversed(written):
            try:
                check_files([item], "after")
                replace_bytes(item["path"], base64.b64decode(item["before"]))
            except Exception as rollback_error:
                errors.append(str(rollback_error))
        try:
            revert()
        except Exception as rollback_error:
            errors.append(str(rollback_error))
        receipt.update(
            state="rollback_failed" if errors else "rolled_back",
            error=str(exc),
            rollback_errors=errors,
        )
        atomic_json(journal, receipt)
        if errors:
            raise CompanionError(
                "ROLLBACK_FAILED", "Inspect recovery journal", journal=str(journal), errors=errors
            ) from exc
        raise
