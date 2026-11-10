"""Save an encoder article and its page-scoped entity indexes."""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import uuid
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo


class _Failure(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _domain(url: str) -> str:
    try:
        if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url) or "\\" in url:
            raise ValueError()
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username is not None or parsed.password is not None:
            raise ValueError()
        host = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
        if len(host) > 253 or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in host.split(".")):
            raise ValueError()
        if parsed.port == 0 or parsed.netloc.endswith(":"):
            raise ValueError()
        return host
    except (ValueError, UnicodeError):
        raise _Failure("invalid_url", "url must be an absolute HTTP(S) URL with a valid hostname and no credentials.") from None


_CATEGORIES = {'Person', 'Community', 'Subject', 'Topic', 'Concept', 'Shop',
               'Organization', 'Service', 'Product'}


def _date(value, zone):
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise _Failure('invalid_date', 'Non-null source dates must be nonempty ISO 8601 strings.')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=zone)
    except ValueError as exc:
        raise _Failure('invalid_date', 'Source dates must be valid ISO 8601 values.') from exc


def _heading(name):
    name = name.replace('\\', '\\\\').replace('\r', '\\r').replace('\n', '\\n')
    return re.sub(r'([#*_\[\]<>])', r'\\\1', name)


def _entry(item, total, indexed, validated):
    utterance = item['entity_utternace'].replace('\r\n', '\n').replace('\r', '\n')
    utterance = utterance.replace('\n', '\n    ')
    return (f"## Sequence: **{item['seq_number']}/{total}**\n"
            f"- Utterance: {utterance}\n"
            f"- Entity Category: {item['entity_category']}\n"
            f"- Indexed At: {indexed}\n"
            f"- Last Validated At: {validated}\n")


def _render(name, items, total, indexed, validated):
    return ('# ' + _heading(name) + '\n\n'
            + '\n'.join(_entry(item, total, indexed, validated) for item in items)).rstrip('\n') + '\n'


def _source_file(path):
    root = Path(os.environ['PROJECT_TRANSACTION_INPUT_ROOT'])
    source = Path(path)
    if not source.is_absolute():
        source = root / source
    try:
        if not path.strip() or '..' in source.parts or source.resolve() != source:
            raise ValueError('Not a direct file path')
        info = source.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError('Not a regular unaliased file')
        return source
    except (OSError, ValueError, RuntimeError) as exc:
        raise _Failure('invalid_input_source',
                       'source file must be an existing regular file without traversal, symlinks, or hard links: ' + path) from exc


def _read_input(source):
    try:
        fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'r', encoding='utf-8', newline='') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise OSError('Input must be a regular unaliased file')
            return stream.read()
    except (OSError, UnicodeError, ValueError) as exc:
        raise _Failure('input_read_error', 'Could not read UTF-8 input file: ' + str(source)) from exc


def _article_metadata(article):
    if not article.startswith("## Title\n"):
        raise _Failure("invalid_article", "Expected article writer Markdown.")
    before, separator, footer = article.rpartition("\n## Meta Data\n")
    if not separator or "\n## Description\n" not in before or "\n## Body\n" not in before:
        raise _Failure("invalid_article", "Article writer sections are missing.")
    metadata = {}
    for line in footer.splitlines():
        match = re.fullmatch(r"- \*\*(requested_url|url|page_id|dateModified):\*\* (.*)", line)
        if match:
            key, value = match.groups()
            if key in metadata:
                raise _Failure("invalid_article", "Duplicate article metadata field: " + key)
            metadata[key] = value
    return metadata


def _contexts(raw):
    try:
        items = json.loads(raw)
    except ValueError as exc:
        raise _Failure("invalid_context", "Expected encoder JSON.") from exc
    if not isinstance(items, list):
        raise _Failure("invalid_context", "Expected an encoder JSON array.")
    groups = {}
    keys = {"entity_name", "entity_category", "entity_utternace", "seq_number"}
    legacy_keys = keys | {"named_entity"}
    for seq, item in enumerate(items, 1):
        if (not isinstance(item, dict) or item.keys() not in (keys, legacy_keys)
                or not isinstance(item["entity_name"], str) or not item["entity_name"].strip()
                or type(item.get("named_entity", False)) is not bool
                or not isinstance(item["entity_category"], str) or item["entity_category"] not in _CATEGORIES
                or not isinstance(item["entity_utternace"], str) or not item["entity_utternace"].strip()
                or type(item["seq_number"]) is not int or item["seq_number"] != seq):
            raise _Failure("invalid_context", "Invalid encoder entry at sequence " + str(seq))
        name = item["entity_name"]
        folder = re.sub(r"[^a-z0-9]", "_", name.lower())
        if len(folder) > 255:
            raise _Failure("invalid_context", "Normalized entity name exceeds 255 characters.")
        group = groups.setdefault(folder, (name, []))
        if group[0] != name:
            raise _Failure("invalid_context", "Distinct entity names normalize to the same folder: " + folder)
        group[1].append(item)
    return len(items), groups


def _stage(root, relative, content, staged):
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in relative.parts[:-1]:
            try:
                os.mkdir(part, dir_fd=directory)
            except FileExistsError:
                pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        try:
            info = os.stat(relative.name, dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise OSError("Unsafe output target: " + relative.as_posix())
        temporary = ".webpage-index-" + uuid.uuid4().hex + ".tmp"
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=directory)
        staged.append((directory, temporary, relative))
    except OSError:
        os.close(directory)
        raise
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def index_webpage(context_file_path: str, article_file_path: str) -> dict:
    result = {
        "input": {"raw_input": None, "processed_input": {
            "context_file_path": context_file_path, "article_file_path": article_file_path}},
        "output": None, "output_format": "markdown", "status": "error",
        "error": None, "meta_data": {},
    }
    staged = []
    written = []
    try:
        project = Path(os.environ["PROJECT_TRANSACTION_INPUT_ROOT"])
        article_source = _source_file(article_file_path)
        context_source = _source_file(context_file_path)
        page_id = article_source.stem
        if (not re.fullmatch(r"[a-f0-9]{64}", page_id)
                or article_source != project / "tools/tool-webpage-article/output" / (page_id + ".md")
                or context_source != project / "skills/skill-webpage-context/output" / (page_id + ".json")):
            raise _Failure("invalid_input_source", "Use matching article writer and context encoder output paths.")
        article = _read_input(article_source)
        metadata = _article_metadata(article)
        url = metadata.get("requested_url", metadata.get("url", ""))
        domain = _domain(url).replace(".", "_")
        if metadata.get("page_id") != page_id or hashlib.sha256(url.encode("utf-8")).hexdigest() != page_id:
            raise _Failure("page_id_mismatch", "Article metadata and both filenames must identify the same URL.")
        zone = ZoneInfo(os.environ["PROJECT_TRANSACTION_TIMEZONE"])
        modified = metadata.get("dateModified")
        validated = "Not provided" if modified in (None, "Not provided") else _date(modified, zone).isoformat()
        total, groups = _contexts(_read_input(context_source))
        indexed = datetime.now(zone).isoformat()
        root = Path(os.environ["PROJECT_TRANSACTION_DATA_DIRECTORY"])
        if root != project / "data":
            raise OSError("Expected the runner's canonical data root.")
        _stage(root, Path("articles", domain, page_id + ".md"), article, staged)
        for folder, (name, items) in groups.items():
            _stage(root, Path("index", domain, folder, page_id + ".md"),
                   _render(name, items, total, indexed, validated), staged)
        for directory, temporary, relative in staged:
            os.replace(temporary, relative.name, src_dir_fd=directory, dst_dir_fd=directory)
            written.append("data/" + relative.as_posix())
            os.fsync(directory)
        result.update(status="ok", output=written, meta_data={
            "page_id": page_id, "indexed_at": indexed, "last_validated_at": validated,
            "total_utterances": total})
    except _Failure as exc:
        result["error"] = {"code": exc.code, "message": str(exc)}
    except (OSError, UnicodeError) as exc:
        result["error"] = {"code": "output_write_error", "message": str(exc)}
    finally:
        for directory, temporary, _ in staged:
            try:
                os.unlink(temporary, dir_fd=directory)
            except OSError:
                pass
            os.close(directory)
    if result["status"] == "error" and written:
        result["meta_data"]["affected_paths"] = written
    return result
