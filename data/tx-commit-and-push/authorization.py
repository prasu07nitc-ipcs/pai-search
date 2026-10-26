"""Consumer-owned, read-only Markdown grant validation. No authorisation calls."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import stat

NAME = 'authorization-git-commit-and-push'
FIELDS = (
    'Schema version', 'Authorisation', 'Grant ID', 'Status', 'Project', 'Session ID',
    'Requested at', 'Approval deadline', 'Granted at', 'Expires at', 'Revoked at',
    'Approved by', 'Approval reference', 'Decision reference', 'Request token',
    'Definition fingerprint', 'Duration seconds', 'Consumer', 'Operation',
    'Branch', 'Remote URL', 'Author name', 'Author email', 'Create branch',
    'Base commit', 'Page scope', 'Allowed roots', 'Message prefix', 'Reuse',
)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def read_grant(root, supplied):
    expected = root / 'authorizations' / NAME / '.runtime/grant.md'
    path = Path(supplied)
    if not path.is_absolute():
        path = root / path
    if path != expected or path.resolve() != expected:
        raise ValueError('Only the canonical authorisation grant file is accepted.')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, encoding='utf-8') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError('Grant must be a regular unaliased file.')
        text = stream.read()
    lines = text.splitlines()
    if lines[:2] != ['# Authorisation grant', ''] or len(lines) != len(FIELDS) + 2:
        raise ValueError('Invalid Markdown grant structure.')
    record = {}
    for key, line in zip(FIELDS, lines[2:]):
        prefix = '- **' + key + '**: '
        if not line.startswith(prefix):
            raise ValueError('Invalid grant field: ' + key)
        record[key] = json.loads(line[len(prefix):])
    rendered = '# Authorisation grant\n\n' + '\n'.join('- **'+k+'**: '+canonical(record[k]) for k in FIELDS) + '\n'
    if rendered != text:
        raise ValueError('Noncanonical grant file.')
    return record


def instant(value):
    if not isinstance(value, str):
        raise ValueError('Grant timestamp required.')
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError('Timezone required.')
    return parsed.timestamp()


def verify(root, grant_file, grant_id, operation, live):
    """Read the canonical file immediately before dispatch. Never mutate permission."""
    session = os.environ.get('CODEX_THREAD_ID')
    if not session or re.fullmatch(r'[A-Za-z0-9_-]{1,200}', session) is None:
        raise ValueError('Platform chat identity unavailable.')
    record = read_grant(root, grant_file)
    fixed = {'Schema version':1, 'Authorisation':NAME, 'Grant ID':grant_id,
             'Status':'active', 'Project':str(root), 'Session ID':session,
             'Consumer':'data/tx-commit-and-push', 'Operation':'commit-and-push',
             'Reuse':'same-session-until-expiry', 'Page scope':'all',
             'Create branch':False, 'Base commit':None, 'Revoked at':None}
    if any(record[k] != value for k, value in fixed.items()) or type(record['Schema version']) is not int or record['Create branch'] is not False:
        raise ValueError('Grant identity, session, status or supported permission mismatch.')
    if not isinstance(grant_id, str) or re.fullmatch('[0-9a-f]{32}', grant_id) is None:
        raise ValueError('Expected grant ID required.')
    duration = record['Duration seconds']
    if type(duration) is not int or duration <= 0:
        raise ValueError('Invalid granted duration.')
    issued, expires = instant(record['Granted at']), instant(record['Expires at'])
    current = datetime.now(timezone.utc).timestamp()
    if not issued <= current < expires or abs(expires - issued - duration) > 0.00001:
        raise ValueError('Grant expired, not yet valid or inconsistent.')
    if any(not isinstance(record[k],str) or not record[k].strip() for k in ('Approved by','Approval reference')):
        raise ValueError('Explicit approval record missing.')
    # Validate approved terms, not today's authorisation definition or fingerprint.
    required = {'action','page_id','files','message','branch','remote_url','author_name','author_email',
                'expected_head','create_branch','base_commit'}
    if not isinstance(operation,dict) or set(operation) != required:
        raise ValueError('Invalid complete Git dispatch input.')
    for label, key in (('Branch','branch'),('Remote URL','remote_url'),('Author name','author_name'),('Author email','author_email')):
        if record[label] != live[key] or operation[key] != record[label]:
            raise ValueError('Current Git configuration exceeds granted scope: '+key)
    if live['expected_head'] is None or operation['expected_head'] != live['expected_head'] or live['create_branch'] is not False or operation['create_branch'] is not False or operation['base_commit'] is not None:
        raise ValueError('Grant covers only the existing configured target without branch creation.')
    page = operation['page_id']
    if not isinstance(page,str) or re.fullmatch('[0-9a-f]{64}',page) is None:
        raise ValueError('Invalid page identity.')
    if record['Message prefix'] != 'data: index webpage ' or operation['action'] != 'commit-and-push' or operation['message'] != record['Message prefix'] + page:
        raise ValueError('Only canonical webpage-index commit-and-push is permitted.')
    roots = record['Allowed roots']
    if not isinstance(roots,list) or not roots or any(not isinstance(x,str) or x not in ('bookmark','index','articles') for x in roots) or len(set(roots)) != len(roots):
        raise ValueError('Unsupported granted output roots.')
    paths = operation['files']
    if not isinstance(paths,list) or not paths or any(not isinstance(p,str) for p in paths) or len(set(paths)) != len(paths):
        raise ValueError('Unique nonempty file paths required.')
    for path in paths:
        parts = path.split('/')
        if len(parts) < 4 or parts[0] not in roots or parts[-2] != page or any(p in ('','.','..') or p.startswith('.') for p in parts) or '\\' in path or any(ord(c)<32 or ord(c)==127 for c in path):
            raise ValueError('File lies outside the granted output scope.')
    return {'grant_id':grant_id,'session_id':session,'grant_file':str(root / 'authorizations' / NAME / '.runtime/grant.md')}
