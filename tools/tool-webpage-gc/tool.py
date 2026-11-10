"""Remove the saved tool outputs for a batch of pages."""
import json
import os
import stat
from tempfile import NamedTemporaryFile

from runner import ROOT, cleanup_targets

TOOL = "tool-webpage-gc"


def collect_outputs(page_ids: list[str]) -> dict:
    """Delete peer outputs for validated page IDs supplied through the runner."""
    page_id = page_ids[0]
    metadata = {"page_id": page_id, "deleted": []}
    result = {
        "input": {"page_id": page_id, "processed_input": {"page_ids": page_ids}},
        "output": None,
        "output_format": "json",
        "status": "error",
        "error": None,
        "meta_data": metadata,
    }

    report = ROOT / TOOL / "output" / f"{page_id}.json"
    temporary = None
    try:
        targets = (target for identifier in dict.fromkeys(page_ids) for target in cleanup_targets(identifier))
        for target in targets:
            try:
                directory = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            except FileNotFoundError:
                continue
            try:
                try:
                    info = os.stat(target.name, dir_fd=directory, follow_symlinks=False)
                    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                        continue
                    relative = target.relative_to(ROOT).as_posix()
                    os.unlink(target.name, dir_fd=directory)
                    metadata["deleted"].append(relative)
                except FileNotFoundError:
                    continue
            finally:
                os.close(directory)

        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=report.parent, delete=False) as stream:
            temporary = stream.name
            json.dump({**metadata, "page_ids": page_ids}, stream)
        os.replace(temporary, report)
    except OSError as error:
        result["error"] = {"code": "cleanup_error", "message": str(error)}
        return result
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    return {**result, "output": report.relative_to(ROOT).as_posix(), "status": "ok"}
