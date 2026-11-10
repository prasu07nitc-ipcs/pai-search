"""Assemble a Markdown article from two matching webpage artifacts."""
import json
from pathlib import Path
import re
from tempfile import NamedTemporaryFile

TOOL = Path(__file__).resolve().parent
ROOT = TOOL.parent


def write_article(raw_input: str, markdown_file: str) -> dict:
    """Write the article and return the shared tool result."""
    result = {
        "input": {"raw_input": raw_input, "processed_input": {"markdown_file": markdown_file}},
        "output": None,
        "output_format": "markdown",
        "status": "error",
        "error": None,
        "meta_data": {},
    }

    def fail(code, message):
        return {**result, "error": {"code": code, "message": message}}

    match = re.fullmatch(r"tool-webpage-metadata/output/([0-9a-f]{64})\.json", raw_input)
    if match is None or markdown_file != f"tool-webpage-markdown/output/{match[1]}.md":
        return fail("invalid_source_path", "Use matching webpage metadata and Markdown output paths.")
    page_id = match[1]
    metadata_path, body_path = ROOT / raw_input, ROOT / markdown_file
    try:
        for source in (metadata_path, body_path):
            if source.resolve() != source or not source.is_file() or source.stat().st_nlink != 1:
                return fail("invalid_source_path", "Both inputs must be regular, unaliased files.")
        metadata_text = metadata_path.read_text(encoding="utf-8")
        with body_path.open(encoding="utf-8", newline="") as stream:
            body = stream.read()
    except (OSError, UnicodeError, RuntimeError):
        return fail("source_read_error", "Could not read both input files as UTF-8.")
    try:
        metadata = json.loads(metadata_text)
    except (ValueError, RecursionError):
        return fail("invalid_metadata", "Metadata must be a valid JSON object.")
    if (not isinstance(metadata, dict) or metadata.get("page_id") != page_id
            or any(value is not None and not isinstance(value, str) for value in metadata.values())):
        return fail("invalid_metadata", "Metadata must contain the matching page ID and only string or null values.")
    if not body.strip():
        return fail("empty_body", "The Markdown body is empty.")

    title = metadata.get("title") or "Not provided"
    description = metadata.get("description") or "Not provided"
    def footer_value(value):
        return "\n    ".join(value.splitlines()) if value else "Not provided"

    remaining = "\n".join(
        f"- **{key}:** {footer_value(value)}"
        for key, value in metadata.items() if key not in {"title", "description"}
    )
    article = (
        f"## Title\n\n{title}\n\n## Description\n\n{description}\n\n"
        f"## Body\n\n{body}\n\n## Meta Data\n\n{remaining}\n"
    )
    target = TOOL / "output" / f"{page_id}.md"
    temporary_path = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent, delete=False) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(article)
        temporary_path.replace(target)
    except (OSError, UnicodeError):
        return fail("output_write_error", "Could not write the article.")
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    return {**result, "output": target.relative_to(ROOT).as_posix(), "status": "ok",
            "meta_data": {"page_id": page_id}}
