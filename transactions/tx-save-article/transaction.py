"""Validate article source identity and atomically store supplied Markdown."""
import hashlib
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


def _references(article):
    """Collect valid HTTP(S) Markdown link destinations in document order."""
    # Ignore fenced and inline code, preserving offsets for ordering.
    masked = re.sub(r'(?ms)^ {0,3}(`{3,}|~{3,})[^\n]*\n.*?^ {0,3}\1[^\n]*(?:\n|$)',
                    lambda m: ' ' * len(m[0]), article)
    masked = re.sub(r'(`+).*?\1', lambda m: ' ' * len(m[0]), masked, flags=re.S)
    def unescape(text):
        return re.sub(r"\\([!\"#$%&'()*+,\-./:;<=>?@\[\]\\^_`{|}~])", r'\1', text)

    def destination(text):
        if text.startswith('<'):
            end = text.find('>')
            return (text[1:end], end + 1) if end >= 0 else (None, 0)
        depth = 0
        escaped = False
        for index, char in enumerate(text):
            if escaped:
                escaped = False
                continue
            if char == '\\':
                escaped = True
            elif char == '(':
                depth += 1
            elif char == ')':
                if depth == 0:
                    return unescape(text[:index]), index
                depth -= 1
            elif char.isspace() and depth == 0:
                return unescape(text[:index]), index
        return (unescape(text), len(text)) if depth == 0 else (None, 0)

    normalize = lambda label: ' '.join(unescape(label).split()).casefold()
    definitions = {}
    for match in re.finditer(r'(?m)^ {0,3}\[([^]\n]+)\]:[ \t]*(.+)$', masked):
        url, _ = destination(match[2])
        definitions.setdefault(normalize(match[1]), url)
    candidates = []
    # Consume image syntax as well, so its destination cannot become an autolink.
    pattern = r'(?<!\\)(!?)\[((?:\\.|[^]\\\n])+)\](?:\(([^\n]*)|\[([^]\n]*)\])?'
    consumed = []
    for match in re.finditer(pattern, masked):
        if match[3] is not None:
            url, length = destination(match[3])
            tail = match[3][length:]
            valid_tail = re.match(r"^\s*(?:(?:\"[^\"]*\"|'[^']*'|\([^)]*\))\s*)?\)", tail)
            if not valid_tail:
                continue
            end = match.start(3) + length + valid_tail.end()
        else:
            if masked[match.end():match.end()+1] == ':':
                continue
            url = definitions.get(normalize(match[4] or match[2]))
            end = match.end()
        consumed.append((match.start(), end))
        if not match[1] and url:
            candidates.append((match.start(), url))
    for match in re.finditer(r'<(https?://[^<>\s]+)>', masked):
        if not any(start <= match.start() < end for start, end in consumed):
            candidates.append((match.start(), match[1]))
    links = []
    for _, url in sorted(candidates):
        try:
            _domain(url)
        except _Failure:
            continue
        if url not in links:
            links.append(url)
    return links


def _render(article, page_id):
    lines = article.rstrip('\r\n').splitlines()
    if lines and re.match(r'^Source Page I[dD]:', lines[-1]):
        if lines[-1].split(':', 1)[1].strip() != page_id:
            raise _Failure('page_id_mismatch', 'Existing Source Page ID does not match page_id.')
        article = article[:article.rfind(lines[-1])].rstrip('\r\n')
    article = article.rstrip('\r\n') + '\n'
    references = '\n'.join('- <' + url + '>' for url in _references(article))
    signature = os.environ['PROJECT_TRANSACTION_SIGNATURE_MARKDOWN']
    signature = re.sub(r'^## Source Code Signature', '# Source Code Signature', signature, count=1)
    metadata = ('# References\n\n' + references + '\n\n# Source Page ID\n\n'
                + page_id + '\n\n' + signature)
    return {'article.md': article, 'meta.md': metadata}


def _write(domain, page_id, contents, written):
    """Stage both files before replacement; failed runs can rewrite the full pair."""
    configured = os.environ.get('PROJECT_TRANSACTION_DATA_DIRECTORY', '')
    path = Path(configured)
    if (not configured or not path.is_absolute() or path.name != 'articles'
            or '..' in path.parts or str(path) != configured):
        raise _Failure('output_write_error', 'Runner must supply the prepared absolute articles directory.')
    descriptor = None
    staged = {}
    folder = domain.replace('.', '_')
    try:
        descriptor = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        for index, component in enumerate((*path.parts[1:], folder, page_id)):
            if index >= len(path.parts) - 1:
                try:
                    os.mkdir(component, dir_fd=descriptor)
                except FileExistsError:
                    pass
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        for filename, content in contents.items():
            try:
                info = os.stat(filename, dir_fd=descriptor, follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise OSError('Unsafe article target')
            except FileNotFoundError:
                pass
            temporary = '.article-' + uuid.uuid4().hex + '.tmp'
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=descriptor)
            staged[filename] = temporary
            with os.fdopen(fd, 'w', encoding='utf-8', newline='') as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
        for filename, temporary in list(staged.items()):
            os.replace(temporary, filename, src_dir_fd=descriptor, dst_dir_fd=descriptor)
            del staged[filename]
            written.append('data/articles/' + folder + '/' + page_id + '/' + filename)
        os.fsync(descriptor)
        return written
    except (OSError, UnicodeError) as exc:
        raise _Failure('output_write_error', 'Could not save article and metadata; retry the complete pair after a partial replacement.') from exc
    finally:
        if descriptor is not None:
            for temporary in staged.values():
                try:
                    os.unlink(temporary, dir_fd=descriptor)
                except OSError:
                    pass
            os.close(descriptor)


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
                       'article_file must be an existing regular file without traversal, symlinks, or hard links: ' + path) from exc


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


def save_article(page_id: str, article_file: str) -> dict:
    result = {'input': {'raw_input': None, 'processed_input': {'page_id': page_id, 'article_file': article_file}},
              'output': None, 'output_format': 'markdown', 'status': 'error', 'error': None, 'meta_data': {}}
    written = []
    try:
        article_source = _source_file(article_file)
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
        result.update(output=_write(domain, page_id, content, written), status='ok', meta_data={'page_id': page_id, 'url': url})
    except _Failure as exc:
        result['error'] = {'code': exc.code, 'message': str(exc)}
        if written:
            result['meta_data'] = {'affected_paths': written}
    return result
