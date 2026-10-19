"""Durable form sessions: one output file stores data and its complete history."""
import copy
import json
import os
import re
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from journal import append_records, session_records


class Conflict(Exception):
    pass


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink() or path.is_symlink():
        raise ValueError("Storage paths must not be symlinks")
    payload = json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".pending-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.lock = threading.RLock()

    def sync_log(self, value):
        path = self.form(value["meta_data"]["form"]) / "run.log"
        append_records(path, session_records(value))

    def recover_logs(self):
        """Backfill existing sessions and repair missing acknowledged log records."""
        with self.lock:
            for folder in sorted(self.root.glob("form-*")):
                if not folder.is_dir():
                    continue
                self.form(folder.name)
                records = []
                directory = folder / "output"
                if directory.is_symlink():
                    raise ValueError("Output directory must not be a symlink")
                for file in sorted(directory.glob("*.txt")):
                    path = self.path(folder.name, file.stem)
                    records.extend(session_records(json.loads(path.read_text(encoding="utf-8"))))
                if records:
                    records.sort(key=lambda record: (record["executed_at"], record["run_id"], record["meta_data"]["revision"]))
                    append_records(folder / "run.log", records)

    def form(self, name):
        if not isinstance(name, str) or not re.fullmatch(r"form-[a-z0-9]+(?:-[a-z0-9]+)*", name) or len(name) >= 64:
            raise ValueError("Invalid form name")
        folder = self.root / name
        if folder.is_symlink() or not folder.is_dir():
            raise ValueError("Unknown form")
        for filename in ("form.html", "form.js", "form.css"):
            file = folder / filename
            if file.is_symlink() or not file.is_file():
                raise ValueError("Form requires regular HTML, JavaScript and CSS files")
        return folder

    def path(self, name, execution_id):
        folder = self.form(name)
        if not isinstance(execution_id, str) or not re.fullmatch(r"[0-9a-f]{32}", execution_id):
            raise ValueError("Invalid execution ID")
        output = folder / "output" / f"{execution_id}.txt"
        if output.parent.is_symlink() or output.is_symlink():
            raise ValueError("Storage paths must not be symlinks")
        return output

    def migrate(self):
        """Move legacy envelopes into output files; remove sources only after verification.

        Run with the server stopped. Interrupted migrations can be rerun safely.
        Unknown files and conflicting new-format outputs are retained, never discarded.
        """
        count = 0
        with self.lock:
            for folder in sorted(self.root.glob("form-*")):
                legacy = folder / "metadata"
                if not legacy.exists():
                    continue
                self.form(folder.name)
                if legacy.is_symlink() or not legacy.is_dir():
                    raise ValueError("Legacy metadata must be a regular directory")
                for source in sorted(legacy.iterdir()):
                    if source.is_symlink() or not source.is_file() or source.suffix != ".json":
                        raise ValueError("Unexpected legacy metadata entry; migration stopped")
                    output = self.path(folder.name, source.stem)
                    value = json.loads(source.read_text(encoding="utf-8"))
                    required = {"input", "output", "output_format", "status", "error", "meta_data"}
                    if not isinstance(value, dict) or set(value) != required:
                        raise ValueError("Invalid legacy session envelope")
                    meta = value["meta_data"]
                    if meta["execution_id"] != source.stem or meta["form"] != folder.name or value["output"] != output.relative_to(self.root).as_posix():
                        raise ValueError("Legacy session identity mismatch")
                    if not isinstance(meta["current_data"], dict) or not isinstance(meta["action_log"], list):
                        raise ValueError("Invalid legacy session data or history")
                    if output.exists():
                        existing = json.loads(output.read_text(encoding="utf-8"))
                        if existing != value and existing != meta["current_data"]:
                            raise Conflict("Existing output differs from legacy session; migration stopped")
                    atomic_json(output, value)
                    if json.loads(output.read_text(encoding="utf-8")) != value:
                        raise OSError("Migration verification failed")
                    source.unlink()
                    count += 1
                legacy.rmdir()
        return count

    def create(self, name, raw_input, initial_data):
        if not isinstance(raw_input, str) or not isinstance(initial_data, dict):
            raise ValueError("raw_input must be a string and initial_data an object")
        with self.lock:
            execution_id = uuid.uuid4().hex
            output = self.path(name, execution_id)
            value = {
                "input": {"raw_input": raw_input, "processed_input": {"initial_data": copy.deepcopy(initial_data)}},
                "output": output.relative_to(self.root).as_posix(),
                "output_format": "json", "status": "ok", "error": None,
                "meta_data": {"execution_id": execution_id, "form": name, "revision": 0,
                              "execution_state": "in_progress", "created_at": timestamp(),
                              "initial_data": copy.deepcopy(initial_data), "current_data": copy.deepcopy(initial_data),
                              "action_log": []}}
            atomic_json(output, value)
            self.sync_log(value)
            return value

    def read(self, name, execution_id):
        with self.lock:
            output = self.path(name, execution_id)
            value = json.loads(output.read_text(encoding="utf-8"))
            self.sync_log(value)
            return value

    def action(self, name, execution_id, request):
        with self.lock:
            value = self.read(name, execution_id)
            state = value["meta_data"]
            action_id = request.get("action_id")
            if not isinstance(action_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", action_id):
                raise ValueError("A unique action_id is required")
            for entry in state["action_log"]:
                if entry["action_id"] == action_id:
                    if entry["action_name"] != request.get("action_name") or entry["data_after"] != request.get("data") or entry["sequence"] != request.get("expected_revision", -2) + 1 or entry.get("outcome", "accepted") != request.get("outcome", "accepted"):
                        raise Conflict("Action ID already used for a different request")
                    return value
            if type(request.get("expected_revision")) is not int or request["expected_revision"] != state["revision"]:
                raise Conflict("Stale revision; reload the saved session before continuing")
            if state["execution_state"] == "submitted":
                raise Conflict("This session has already been submitted")
            action = request.get("action_name")
            if not isinstance(action, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", action):
                raise ValueError("Invalid action name")
            data = request.get("data")
            if not isinstance(data, dict):
                raise ValueError("Form data must be a JSON object")
            outcome = request.get("outcome", "accepted")
            if outcome not in ("accepted", "rejected") or (outcome == "rejected" and action != "submit"):
                raise ValueError("Invalid action outcome")
            previous = copy.deepcopy(value)
            state["revision"] += 1
            if action == "submit" and outcome == "accepted":
                state["execution_state"] = "submitted"
            state["current_data"] = copy.deepcopy(data)
            state["action_log"].append({"sequence": state["revision"], "action_id": action_id,
                "action_name": action, "outcome": outcome, "action_time": timestamp(), "execution_state": state["execution_state"],
                "data_after": copy.deepcopy(data)})
            output = self.path(name, execution_id)
            try:
                atomic_json(output, value)
            except OSError:
                # Atomic replacement may have committed before a later fsync failed.
                committed = json.loads(output.read_text(encoding="utf-8"))
                if committed == value:
                    self.sync_log(value)
                    raise
                failure = copy.deepcopy(previous)
                failure["status"] = "error"
                failure["error"] = {"code": "STORAGE_ERROR", "message": "Unable to persist form action"}
                failure["meta_data"]["failed_action"] = copy.deepcopy(request)
                append_records(self.form(name) / "run.log", [{"run_id": execution_id,
                    "executed_at": timestamp(), **failure}])
                raise
            self.sync_log(value)
            return value

    def snapshot(self, name, execution_id, revision):
        value = self.read(name, execution_id)["meta_data"]
        if revision == 0:
            return {"revision": 0, "data": value["initial_data"], "execution_state": "in_progress"}
        if revision < 0 or revision > value["revision"]:
            raise ValueError("Unknown revision")
        entry = value["action_log"][revision - 1]
        return {"revision": revision, "data": entry["data_after"], "execution_state": entry["execution_state"]}
