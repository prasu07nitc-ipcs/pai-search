"""Append-only, flattened JSONL execution records with retry-safe recovery."""
import copy
import fcntl
import json
import os


def record_key(record):
    meta = record["meta_data"]
    return (record["run_id"], meta["revision"], record["status"],
            meta.get("failed_action", {}).get("action_id"))


def append_records(path, records):
    if path.parent.is_symlink():
        raise ValueError("Logs directory must not be a symlink")
    path.parent.mkdir(exist_ok=True)
    if path.is_symlink():
        raise ValueError("run.log must not be a symlink")
    with path.open("a+b") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        stream.seek(0)
        contents = stream.read()
        # An interrupted final append is not a committed record. Keep all full lines.
        complete = contents.rfind(b"\n") + 1
        existing = [json.loads(line) for line in contents[:complete].splitlines()]
        keys = {record_key(record) for record in existing}
        if complete != len(contents):
            stream.truncate(complete)
        stream.seek(0, os.SEEK_END)
        for record in records:
            key = record_key(record)
            if key not in keys:
                payload = json.dumps(record, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
                stream.write((payload + "\n").encode("utf-8"))
                keys.add(key)
        stream.flush()
        os.fsync(stream.fileno())
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def session_records(value, start_revision=0):
    """Reconstruct committed envelopes, including revision zero, from saved snapshots."""
    meta = value["meta_data"]
    for revision in range(start_revision, meta["revision"] + 1):
        envelope = copy.deepcopy({key: item for key, item in value.items() if key != "meta_data"})
        state = copy.deepcopy({**meta, "revision": revision, "action_log": meta["action_log"][:revision]})
        envelope["meta_data"] = state
        entry = state["action_log"][-1] if revision else None
        state["current_data"] = copy.deepcopy(entry["data_after"] if entry else state["initial_data"])
        state["execution_state"] = entry["execution_state"] if entry else "in_progress"
        envelope["status"], envelope["error"] = "ok", None
        yield {"run_id": meta["execution_id"],
               "executed_at": entry["action_time"] if entry else meta["created_at"], **envelope}
