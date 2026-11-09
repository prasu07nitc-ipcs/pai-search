"""Delete explicitly selected files from skill output directories."""
import json
import os
import stat
from contextlib import ExitStack
from tempfile import NamedTemporaryFile

from runner import ROOT, skill_cleanup_targets


def collect_outputs(file_paths: list[str]) -> dict:
    """Remove the selected skill outputs and save a cleanup receipt."""
    targets = skill_cleanup_targets(file_paths)
    receipt_id = os.environ["PROJECT_TOOL_RUN_ID"]
    metadata = {"page_id": receipt_id, "deleted": []}
    result = {
        "input": {"raw_input": file_paths[0], "processed_input": {"file_paths": file_paths}},
        "output": None,
        "output_format": "json",
        "status": "error",
        "error": None,
        "meta_data": metadata,
    }
    report = ROOT / "tool-skill-gc" / "output" / f"{receipt_id}.json"
    temporary = None
    try:
        for target in targets:
            relative = target.relative_to(ROOT.parent)
            with ExitStack() as stack:
                directory = None
                try:
                    for part in (ROOT.parent, *relative.parts[:-1]):
                        directory = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                        stack.callback(os.close, directory)
                    info = os.stat(target.name, dir_fd=directory, follow_symlinks=False)
                    if stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                        os.unlink(target.name, dir_fd=directory)
                        metadata["deleted"].append(relative.as_posix())
                except (FileNotFoundError, NotADirectoryError):
                    continue
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=report.parent, delete=False) as stream:
            temporary = stream.name
            json.dump({**metadata, "file_paths": file_paths}, stream)
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
