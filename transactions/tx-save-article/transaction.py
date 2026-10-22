"""Validate article source identity and atomically store supplied Markdown."""
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


def _title_url(article):
    # Require the first nonblank line to be an inline linked H1. Consume nested
    # parentheses so common URL paths are not truncated at the first closing ).
    line = article.lstrip('\r\n').splitlines()[0]
    match = re.match(r'^# \[((?:\\.|[^\]\\])+)\]\(', line)
    if not match or not match[1].strip():
        raise _Failure('invalid_article', 'The first nonblank line must be # [Title](absolute_http_url).')
    rest = line[match.end():]
    if rest.startswith('<'):
        end = rest.find('>')
        if end < 0 or rest[end + 1:].strip() != ')':
            raise _Failure('invalid_article', 'Malformed title link destination.')
        url = rest[1:end]
    else:
        depth = 1
        escaped = False
        for index, char in enumerate(rest):
            if escaped:
                escaped = False
                continue
            if char == '\\':
                escaped = True
            elif char == '(':
                depth += 1
            elif char == ')':
                depth -= 1
                if depth == 0:
                    break
        else:
            raise _Failure('invalid_article', 'Unclosed title link destination.')
        if rest[index + 1:].strip():
            raise _Failure('invalid_article', 'Unexpected text after the title link.')
        url = re.sub(r'\\([!"#$%&\'()*+,\-./:;<=>?@\[\]\\^_`{|}~])', r'\1', rest[:index])
    try:
        parsed = urlsplit(url)
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url)
                or '\\' in url or parsed.port == 0 or parsed.netloc.endswith(':')):
            raise ValueError()
    except ValueError:
        raise _Failure('invalid_url', 'Title link must contain an absolute HTTP(S) URL without credentials or whitespace.') from None
    if not '\n' in article or not article.split('\n', 1)[1].strip():
        raise _Failure('invalid_article', 'Article must contain Markdown text beyond the title.')
    return url


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


def _render(article, page_id):
    # The writer can already supply a trailing identifier. Accept it only when
    # it agrees, retaining one canonical final label.
    lines = article.rstrip('\r\n').splitlines()
    if lines and re.match(r'^Source Page I[dD]:', lines[-1]):
        if lines[-1].split(':', 1)[1].strip() != page_id:
            raise _Failure('page_id_mismatch', 'Existing Source Page ID does not match page_id.')
        article = article[:article.rfind(lines[-1])].rstrip('\r\n')
    return article.rstrip('\r\n') + '\n\nSource Page ID: ' + page_id + '\n\n' + os.environ['PROJECT_TRANSACTION_SIGNATURE_MARKDOWN']


def _write(domain, page_id, content):
    configured = os.environ.get('PROJECT_TRANSACTION_DATA_DIRECTORY', '')
    path = Path(configured)
    if (not configured or not path.is_absolute() or path.name != 'articles'
            or '..' in path.parts or str(path) != configured):
        raise _Failure('output_write_error', 'Runner must supply the prepared absolute articles directory.')
    descriptor = None
    temporary = None
    folder = domain.replace(".", "_")
    try:
        descriptor = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        for component in path.parts[1:]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        try:
            os.mkdir(folder, dir_fd=descriptor)
        except FileExistsError:
            pass
        child = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
        os.close(descriptor)
        descriptor = child
        filename = page_id + '.md'
        try:
            info = os.stat(filename, dir_fd=descriptor, follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise OSError('Unsafe article target')
        except FileNotFoundError:
            pass
        temporary = '.article-' + uuid.uuid4().hex + '.tmp'
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=descriptor)
        with os.fdopen(fd, 'w', encoding='utf-8', newline='') as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, filename, src_dir_fd=descriptor, dst_dir_fd=descriptor)
        temporary = None
        return 'data/articles/' + folder + '/' + filename
    except OSError as exc:
        raise _Failure('output_write_error', 'Could not atomically save article in the prepared directory.') from exc
    finally:
        if temporary is not None and descriptor is not None:
            try:
                os.unlink(temporary, dir_fd=descriptor)
            except OSError:
                pass
        if descriptor is not None:
            os.close(descriptor)


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


def save_article(page_id_file: str, article_file: str, raw_input: str) -> dict:
    result = {'input': {'raw_input': raw_input, 'processed_input': {'page_id_file': page_id_file, 'article_file': article_file}},
              'output': None, 'output_format': 'markdown', 'status': 'error', 'error': None, 'meta_data': {}}
    try:
        # Validate BOTH producers before reading either payload or checking identity.
        page_source = _source_file(page_id_file, 'tools/tool-webpage-og-crawler')
        article_source = _source_file(article_file, 'skills/skill-article-writer')
        try:
            metadata = json.loads(_read_input(page_source))
        except (ValueError, RecursionError) as exc:
            raise _Failure('invalid_json', 'Page ID file must contain a JSON object.') from exc
        if not isinstance(metadata, dict):
            raise _Failure('invalid_json', 'Page ID file must contain a JSON object.')
        page_id = metadata.get('page_id')
        article = _read_input(article_source)
        if not isinstance(page_id, str) or re.fullmatch(r'[0-9a-f]{64}', page_id) is None:
            raise _Failure('invalid_page_id', 'page_id must contain exactly 64 lowercase hexadecimal characters.')
        if not article.strip():
            raise _Failure('invalid_article', 'article must contain nonempty Markdown.')
        url = _title_url(article)
        if hashlib.sha256(url.encode('utf-8')).hexdigest() != page_id:
            raise _Failure('page_id_mismatch', 'SHA-256 of the title URL does not match page_id; no article was written.')
        domain = _domain(url)
        content = _render(article, page_id)
        result.update(output=[_write(domain, page_id, content)], status='ok', meta_data={'page_id': page_id, 'url': url})
    except _Failure as exc:
        result['error'] = {'code': exc.code, 'message': str(exc)}
    return result
