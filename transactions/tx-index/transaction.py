"""Replace page-scoped entity indexes from validated encoder contexts."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import uuid
from urllib.parse import urlsplit


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


def _source_file(path, component):
    root = Path(os.environ['PROJECT_TRANSACTION_INPUT_ROOT'])
    source = Path(path)
    if not source.is_absolute():
        source = root / source
    expected = root / component / 'output'
    try:
        # Require a direct output file; do not follow aliases into or out of it.
        if (not path.strip() or '..' in source.parts
                or source.parent != expected
                or source.resolve() != source
                or source.suffix != '.txt'
                or re.fullmatch(r'[0-9a-f]{64}', source.stem) is None):
            raise ValueError('Not a component output path')
        info = source.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError('Not a regular unaliased file')
        return source
    except (OSError, ValueError, RuntimeError) as exc:
        raise _Failure('invalid_input_source', 'Input must be a regular ' + component
                       + '/output/<run_id>.txt file: ' + path) from exc


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



from datetime import datetime
from zoneinfo import ZoneInfo

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
    return (f"Sequence: {item['seq_number']}/{total}\n"
            f"Utterance: {utterance}\n"
            f"Indexed At: {indexed}\n"
            f"Last Validated At: {validated}\n")


def _render(groups, page_id, total, indexed, validated):
    return '\n\n'.join(
        '# ' + _heading(name) + '\n\n## Source Page ID: ' + page_id + '\n\n'
        + '\n'.join(_entry(item, total, indexed, validated) for item in items)
        for name, items in groups.items()).rstrip('\n') + '\n'


def _update(root, folder, domain, groups, page_id, total, indexed, validated):
    descriptor = None
    temporary = None
    try:
        descriptor = os.open(root.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        for part in root.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        for part in (folder, domain):
            for entry in os.listdir(descriptor):
                if entry != part:
                    try:
                        if os.stat(entry, dir_fd=descriptor, follow_symlinks=False) == os.stat(part, dir_fd=descriptor, follow_symlinks=False):
                            raise OSError("Entity or domain folder aliases an existing name: " + repr(part))
                    except FileNotFoundError:
                        pass
            try:
                os.mkdir(part, dir_fd=descriptor)
            except FileExistsError:
                pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        filename = page_id + '.md'
        try:
            fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
        except FileNotFoundError:
            pass
        else:
            with os.fdopen(fd, encoding='utf-8', newline='') as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise OSError('Unsafe index target')
                stream.read(0)
        text = _render(groups, page_id, total, indexed, validated) + '\n' + os.environ['PROJECT_TRANSACTION_SIGNATURE_MARKDOWN']
        temporary = '.index-' + uuid.uuid4().hex + '.tmp'
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=descriptor)
        with os.fdopen(fd, 'w', encoding='utf-8', newline='') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, filename, src_dir_fd=descriptor, dst_dir_fd=descriptor)
        temporary = None
        os.fsync(descriptor)
    finally:
        if temporary is not None and descriptor is not None:
            try:
                os.unlink(temporary, dir_fd=descriptor)
            except OSError:
                pass
        if descriptor is not None:
            os.close(descriptor)


def index(page_file: str, context_file: str, raw_input: str) -> dict:
    result = {'input': {'raw_input': raw_input, 'processed_input': {
        'page_file': page_file, 'context_file': context_file}},
        'output': None, 'output_format': 'markdown', 'status': 'error',
        'error': None, 'meta_data': {}}
    written = []
    try:
        page_source = _source_file(page_file, 'tools/tool-webpage-og-crawler')
        context_source = _source_file(context_file, 'skills/skill-context-encoder')
        try:
            page_text = _read_input(page_source)
            context_text = _read_input(context_source)
            expected_hashes = os.environ.get('PROJECT_TRANSACTION_INDEX_HASHES')
            if expected_hashes and json.loads(expected_hashes) != [
                    hashlib.sha256(text.encode('utf-8')).hexdigest() for text in (page_text, context_text)]:
                raise _Failure('input_read_error', 'Index sources changed after batch preparation.')
            page = json.loads(page_text)
            contexts = json.loads(context_text)
        except (ValueError, RecursionError) as exc:
            raise _Failure('invalid_json', 'Both inputs must contain valid JSON.') from exc
        if not isinstance(page, dict):
            raise _Failure('invalid_input', 'Crawler output must be a JSON object.')
        page_id, url = page.get('page_id'), page.get('url')
        if not isinstance(page_id, str) or not re.fullmatch('[0-9a-f]{64}', page_id):
            raise _Failure('invalid_page_id', 'page_id must be 64 lowercase hexadecimal characters.')
        if not isinstance(url, str):
            raise _Failure('invalid_url', 'Crawler url must be a nonempty HTTP(S) URL.')
        domain = _domain(url).replace('.', '_')
        if hashlib.sha256(url.encode()).hexdigest() != page_id:
            raise _Failure('page_id_mismatch', 'page_id does not match the exact URL hash.')
        if not isinstance(contexts, list) or not contexts:
            raise _Failure('invalid_context', 'Context input must be a nonempty array.')
        groups = {}
        keys = {'entity_name', 'named_entity', 'entity_category', 'entity_utternace', 'seq_number'}
        for seq, item in enumerate(contexts, 1):
            if (not isinstance(item, dict) or set(item) != keys
                    or not isinstance(item['entity_name'], str) or not item['entity_name'].strip()
                    or type(item['named_entity']) is not bool
                    or not isinstance(item['entity_category'], str) or item['entity_category'] not in _CATEGORIES
                    or not isinstance(item['entity_utternace'], str) or not item['entity_utternace'].strip()
                    or type(item['seq_number']) is not int or item['seq_number'] != seq):
                raise _Failure('invalid_context', 'Encoder entries must match its schema and consecutive sequence numbers.')
            folder = item['entity_name']
            if folder in ('.', '..') or '/' in folder or '\x00' in folder:
                raise _Failure('output_write_error', 'Entity name must be a single safe folder component: ' + repr(folder))
            groups.setdefault(folder, {}).setdefault(folder, []).append(item)
        zone = ZoneInfo(os.environ['PROJECT_TRANSACTION_TIMEZONE'])
        now = datetime.fromisoformat(os.environ['PROJECT_TRANSACTION_INDEXED_AT']) if os.environ.get('PROJECT_TRANSACTION_INDEXED_AT') else datetime.now(zone)
        dates = [now]
        for field in ('dateModified', 'datePublished'):
            parsed = _date(page.get(field), zone)
            if parsed is not None:
                dates.append(parsed)
        indexed, validated = now.isoformat(), max(dates).isoformat()
        root = Path(os.environ['PROJECT_TRANSACTION_DATA_DIRECTORY'])
        if not root.is_absolute() or root.name != 'index' or root.resolve() != root:
            raise _Failure('output_write_error', 'Runner must provide the canonical index directory.')
        for folder, entities in groups.items():
            _update(root, folder, domain, entities, page_id, len(contexts), indexed, validated)
            written.append(f'data/index/{folder}/{domain}/{page_id}.md')
        result.update(output=written, status='ok', meta_data={
            'page_id': page_id, 'indexed_at': indexed, 'last_validated_at': validated,
            'total_utterances': len(contexts), 'skipped_utterances': 0})
    except _Failure as exc:
        result['error'] = {'code': exc.code, 'message': str(exc)}
        if written:
            result['meta_data'] = {'affected_paths': written}
    except (OSError, UnicodeError) as exc:
        result['error'] = {'code': 'output_write_error', 'message': str(exc)}
        result['meta_data'] = {'affected_paths': written}
    return result
