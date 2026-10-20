"""Append-only, flattened JSONL execution records with retry-safe recovery."""
import fcntl
import json
import os


META_FIELDS = ('form', 'revision', 'execution_state', 'created_at')


def compact_record(record):
    return {**record, 'meta_data': {key: record['meta_data'][key] for key in META_FIELDS}}


def record_key(record):
    meta = record["meta_data"]
    return (record["run_id"], meta["revision"], record["status"])


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
            record = compact_record(record)
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
    """Emit only the final, durably submitted execution."""
    meta = value['meta_data']
    if meta['execution_state'] != 'submitted' or meta['revision'] < start_revision:
        return
    entry = meta['action_log'][-1]
    yield {'run_id': meta['execution_id'], 'executed_at': entry['action_time'], **value}
