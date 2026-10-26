"""Local Markdown grant lifecycle. Legacy SQLite history is never consulted or removed."""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import uuid

PROJECT = Path(__file__).resolve().parent.parent
NAME = 'authorization-git-commit-and-push'


class AuthorizationError(ValueError):
    def __init__(self, message, code='authorization_error'):
        super().__init__(message)
        self.code = code


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def now():
    return datetime.now(timezone.utc).timestamp()


def timestamp(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def seconds(value):
    if not isinstance(value, str):
        raise AuthorizationError('Grant timestamp required.')
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError('Timezone required.')
    return parsed.timestamp()


def session_id():
    # CODEX_THREAD_ID identifies a chat; a process/turn ID does not.
    value = os.environ.get('CODEX_THREAD_ID')
    if not value or re.fullmatch(r'[A-Za-z0-9_-]{1,200}', value) is None:
        raise AuthorizationError('Platform chat ID CODEX_THREAD_ID is unavailable; do not invent one.')
    return value


def regular(path):
    path = Path(path)
    if path.resolve() != path:
        raise AuthorizationError('Aliased path: ' + str(path))
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise AuthorizationError('Regular unaliased file required.')
    return path


def read_text(path):
    regular(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, encoding='utf-8') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise AuthorizationError('Unsafe file.')
        return stream.read()


# Flat, fixed Markdown schema. JSON scalar/list encoding prevents ambiguous values.
FIELDS = (
    'Schema version', 'Authorisation', 'Grant ID', 'Status', 'Project', 'Session ID',
    'Requested at', 'Approval deadline', 'Granted at', 'Expires at', 'Revoked at',
    'Approved by', 'Approval reference', 'Decision reference', 'Request token',
    'Definition fingerprint', 'Duration seconds', 'Consumer', 'Operation',
    'Branch', 'Remote URL', 'Author name', 'Author email', 'Create branch',
    'Base commit', 'Page scope', 'Allowed roots', 'Message prefix', 'Reuse',
)


def render(record):
    if set(record) != set(FIELDS):
        raise AuthorizationError('Incomplete grant record.')
    return '# Authorisation grant\n\n' + '\n'.join(
        '- **' + key + '**: ' + canonical(record[key]) for key in FIELDS) + '\n'


def parse(text):
    lines = text.splitlines()
    if lines[:2] != ['# Authorisation grant', ''] or len(lines) != len(FIELDS) + 2:
        raise AuthorizationError('Invalid Markdown grant structure.')
    record = {}
    for key, line in zip(FIELDS, lines[2:]):
        prefix = '- **' + key + '**: '
        if not line.startswith(prefix):
            raise AuthorizationError('Missing, duplicate or reordered grant field: ' + key)
        record[key] = json.loads(line[len(prefix):])
    if render(record) != text:
        raise AuthorizationError('Noncanonical grant Markdown.')
    validate_record(record)
    return record


def validate_record(record):
    if type(record['Schema version']) is not int or record['Schema version'] != 1 or record['Authorisation'] != NAME:
        raise AuthorizationError('Unsupported grant protocol.')
    if record['Status'] not in ('pending','active','declined','revoked'):
        raise AuthorizationError('Invalid grant status.')
    for key, pattern in (('Grant ID',r'[0-9a-f]{32}'),('Request token',r'[0-9a-f]{32}'),
                         ('Session ID',r'[A-Za-z0-9_-]{1,200}'),('Definition fingerprint',r'[0-9a-f]{64}')):
        if not isinstance(record[key],str) or re.fullmatch(pattern,record[key]) is None:
            raise AuthorizationError('Invalid grant identity: '+key)
    if not isinstance(record['Project'],str) or not Path(record['Project']).is_absolute():
        raise AuthorizationError('Invalid project identity.')
    if type(record['Duration seconds']) is not int or record['Duration seconds'] <= 0:
        raise AuthorizationError('Invalid grant duration.')
    requested, deadline = seconds(record['Requested at']), seconds(record['Approval deadline'])
    if deadline <= requested:
        raise AuthorizationError('Invalid approval deadline.')
    for key in ('Granted at','Expires at','Revoked at'):
        if record[key] is not None:
            seconds(record[key])
    if record['Status'] == 'active':
        if record['Revoked at'] is not None or any(not isinstance(record[k],str) or not record[k].strip() for k in ('Approved by','Approval reference')):
            raise AuthorizationError('Missing human approval record.')
        issued, expires = seconds(record['Granted at']), seconds(record['Expires at'])
        if issued < requested or abs(expires-issued-record['Duration seconds']) > 0.00001:
            raise AuthorizationError('Inconsistent granted validity.')



def adapter(project, name):
    if name != NAME:
        raise AuthorizationError('Unknown authorisation component.')
    path = regular(project / 'authorizations' / name / 'authorization.py')
    spec = importlib.util.spec_from_file_location('authorization_definition', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Store:
    def __init__(self, project=PROJECT):
        self.project = Path(project).resolve()

    def path(self, name):
        if name != NAME:
            raise AuthorizationError('Unknown authorisation component.')
        return self.project / 'authorizations' / name / '.runtime/grant.md'

    @contextmanager
    def locked(self, name):
        folder = self.path(name).parent
        if folder.resolve() != folder:
            raise AuthorizationError('Aliased runtime directory.')
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        lock = folder / 'lock'
        fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise AuthorizationError('Unsafe lock.')
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def read(self, name):
        path = self.path(name)
        try:
            return parse(read_text(path))
        except FileNotFoundError:
            return None

    def publish(self, name, record):
        path = self.path(name)
        if path.exists() or path.is_symlink():
            regular(path)
        text = render(record)
        # Retain issuance and decisions before replacement. Audit is not transactional
        # with publication; failures stop the caller and require inspection, not retry.
        audit = path.parent / 'history.jsonl'
        fd = os.open(audit, os.O_CREAT | os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise AuthorizationError('Unsafe audit file.')
            data = (canonical(record) + '\n').encode()
            if os.write(fd, data) != len(data):
                raise OSError('Incomplete audit append.')
            os.fsync(fd)
        finally:
            os.close(fd)
        fd, temporary = tempfile.mkstemp(prefix='.grant-', dir=path.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def execute(self, name, session, decision=None):
        with self.locked(name):
            current = self.read(name)
            if current and current['Project'] != str(self.project):
                raise AuthorizationError('Grant belongs to another project.')
            instant = now()
            if decision is not None:
                return self.decide(name, session, current, decision, instant)
            if current:
                active = current['Status'] == 'active' and instant < seconds(current['Expires at'])
                pending = current['Status'] == 'pending' and instant < seconds(current['Approval deadline'])
                if active or pending:
                    if current['Session ID'] != session:
                        raise AuthorizationError('Authorisation belongs to another chat until expiry or revocation.', 'authorization_session_conflict')
                    return current, active
            definition = adapter(self.project, name).definition(self.project)
            record = dict.fromkeys(FIELDS)
            record.update(definition)
            record.update({'Schema version':1, 'Authorisation':name, 'Grant ID':uuid.uuid4().hex,
                           'Status':'pending', 'Project':str(self.project), 'Session ID':session,
                           'Requested at':timestamp(instant), 'Approval deadline':timestamp(instant + 900),
                           'Request token':uuid.uuid4().hex})
            record['Definition fingerprint'] = hashlib.sha256(canonical(definition).encode()).hexdigest()
            self.publish(name, record)
            return record, False

    def decide(self, name, session, record, decision, instant):
        required = {'request_id','token','decision','approved_by','source'}
        if not isinstance(decision, dict) or set(decision) != required:
            raise AuthorizationError('Decision requires request_id, token, decision, approved_by and source.')
        if not record or record['Status'] != 'pending' or record['Session ID'] != session or record['Grant ID'] != decision['request_id'] or record['Request token'] != decision['token'] or instant >= seconds(record['Approval deadline']):
            raise AuthorizationError('Exact unexpired request for this session required.')
        if decision['decision'] not in ('approve','decline') or any(not isinstance(decision[k], str) or not decision[k].strip() for k in ('approved_by','source')):
            raise AuthorizationError('Explicit human decision and source reference required.')
        record['Decision reference'] = decision['source']
        if decision['decision'] == 'decline':
            record['Status'] = 'declined'
        else:
            record.update({'Status':'active', 'Granted at':timestamp(instant),
                           'Expires at':timestamp(instant + record['Duration seconds']),
                           'Approved by':decision['approved_by'], 'Approval reference':decision['source']})
        self.publish(name, record)
        return record, False

    def revoke(self, name, grant_id, source):
        if not isinstance(source, str) or not source.strip():
            raise AuthorizationError('Explicit human revocation reference required.')
        with self.locked(name):
            record = self.read(name)
            if not record or record['Grant ID'] != grant_id:
                raise AuthorizationError('Expected current grant ID required for revocation.')
            record.update({'Status':'revoked', 'Revoked at':timestamp(now()), 'Decision reference':source})
            self.publish(name, record)
            return record
