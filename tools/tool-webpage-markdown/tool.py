"""Extract reader-style Markdown from a public webpage with Trafilatura."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import uuid
from typing import Literal

from webpage_http import WebpageError, download_html, validate_url


def _extract_markdown(
    url: str,
    page_id: str,
    mode: str,
    include_images: bool,
    include_links: bool,
    include_tables: bool,
) -> dict:
    """Extract a public URL as Markdown, optionally comparing three modes.

    URL: absolute HTTP(S), <=8192 characters, without credentials or whitespace.
    Defaults retain tables and formatting, exclude images, links, and comments,
    enable backup extraction and disable deduplication. Requires Trafilatura 2.x.
    Network budget: 15 seconds; response limit: 2 MiB; runner timeout: 60 seconds.
    Saves UTF-8 Markdown directly in tool-local output/<page_id>.md. Compare joins
    nonempty variants with labeled headings; single modes preserve extracted text.
    Supported Markdown structure is retained; exact CSS/font layout is not.
    Expected failures return structured errors; unexpected exceptions propagate.
    """
    result = {"status": "error", "error": None, "final_url": None}
    try:
        validate_url(url)
        if mode not in ("balanced", "precision", "recall", "compare"):
            raise WebpageError("invalid_options", "Unsupported extraction mode.")
        if any(type(flag) is not bool for flag in (include_images, include_links, include_tables)):
            raise WebpageError("invalid_options", "Inclusion options must be booleans.")
        if include_images is not False or include_links is not False:
            raise WebpageError("invalid_options", "Images and links must be disabled.")
        try:
            from importlib.metadata import version
            from trafilatura import extract
            if int(version("trafilatura").split(".")[0]) != 2:
                raise WebpageError("incompatible_dependency", "Requires Trafilatura >=2.0,<3.0.")
        except ImportError:
            raise WebpageError("missing_dependency", "Trafilatura or a required dependency is absent from the project environment.") from None
        downloaded = download_html(url)
        result["final_url"] = downloaded["final_url"]
        if downloaded["status"] == "error":
            result["error"] = downloaded["error"]
            return result
        modes = ("balanced", "precision", "recall") if mode == "compare" else (mode,)
        variants = {}
        for selected in modes:
            markdown = extract(
                downloaded["html"], url=downloaded["final_url"],
                output_format="markdown", include_formatting=True,
                include_comments=False, include_images=False,
                include_links=False, include_tables=include_tables,
                fast=False, favor_precision=selected == "precision",
                favor_recall=selected == "recall", deduplicate=False,
                with_metadata=False, only_with_metadata=False,
            )
            variants[selected] = markdown.strip() if markdown else None
        if not any(variants.values()):
            raise WebpageError("extraction_empty", "No main content could be extracted from the HTML.")
        if mode == "compare":
            content = "\n\n".join(f"# {selected}\n\n{variants[selected]}"
                                    for selected in modes if variants[selected])
        else:
            content = variants[mode]
        result.update(status="ok", result_file=_write_output(content, page_id))
    except WebpageError as exc:
        result["error"] = {"code": exc.code, "message": str(exc)}
    return result


def _write_output(content: str, page_id: str) -> str:
    """Atomically replace <page_id>.md using a pinned tool-local directory."""
    # Resolve output relative to this module, never the caller working directory.
    tool_root = Path(__file__).resolve().parent
    if re.fullmatch(r"[0-9a-f]{64}", page_id) is None:
        raise WebpageError("output_write_error", "Output page_id is missing or invalid.")
    filename = f"{page_id}.md"
    descriptor = None
    temporary = None
    try:
        # Pin the directory without following symlinks. Exclusive temporary
        # creation plus flush/fsync/replace preserves an old result on failure.
        # Same-ID concurrent writes are last-replacement-wins; abrupt termination
        # can leave a temporary file for later cleanup.
        descriptor = os.open(tool_root / "output", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        name = f".output-{uuid.uuid4().hex}.tmp"
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=descriptor)
        temporary = name
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, filename, src_dir_fd=descriptor, dst_dir_fd=descriptor)
        temporary = None
        return f"{tool_root.name}/output/{filename}"
    except OSError as exc:
        raise WebpageError("output_write_error", "Could not save <page_id>.md in the tool output directory.") from exc
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary, dir_fd=descriptor)
            except OSError:
                pass
        if descriptor is not None:
            os.close(descriptor)


def extract_markdown(
    url: str,
    page_id: str,
    mode: Literal["balanced", "precision", "recall", "compare"] = "balanced",
    include_images: Literal[False] = False,
    include_links: Literal[False] = False,
    include_tables: bool = True,
) -> dict:
    """Extract Markdown and save it directly to output/<page_id>.md.

    page_id must be the lowercase SHA-256 digest of the exact UTF-8 input URL.
    The caller supplies it independently; no other tool is required.
    URL/options constraints match _extract_markdown; defaults are recorded in
    input.processed_input. Expected failures return output=null; successful paths
    are relative to tools/. Success atomically replaces the previous <page_id>.md.
    """
    processed = {"url": url, "mode": mode, "include_images": include_images,
                 "include_links": include_links, "include_tables": include_tables}
    if not re.fullmatch(r"[0-9a-f]{64}", page_id) or page_id != hashlib.sha256(url.encode("utf-8")).hexdigest():
        return {"input": {"page_id": page_id, "processed_input": processed},
                "output": None, "output_format": "markdown", "status": "error",
                "error": {"code": "invalid_page_id", "message": "page_id must equal the lowercase SHA-256 digest of the supplied URL."},
                "meta_data": {"requested_url": url, "final_url": None, "mode": mode}}
    payload = _extract_markdown(url, page_id, mode, include_images, include_links, include_tables)
    return {"input": {"page_id": page_id, "processed_input": processed},
            "output": payload.get("result_file"), "output_format": "markdown", "status": payload["status"],
            "error": payload["error"],
            "meta_data": {"requested_url": url, "final_url": payload["final_url"], "mode": mode}}
