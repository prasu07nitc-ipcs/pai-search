"""The sole project entry point for local commits and explicit GitHub pushes."""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import uuid

GIT = os.environ.get('PROJECT_DATA_GIT_BINARY', '/usr/bin/git')
ALLOWED_BRANCHES = frozenset(('data-dev', 'data-test', 'data-prod'))
PROTECTED = frozenset(('commit', 'tx-commit-and-push', 'runner.py', 'requirements.txt', 'AGENTS.md', 'README.md'))

FIELDS = ('action', 'page_id', 'files', 'message', 'branch', 'expected_head', 'remote_url',
          'author_name', 'author_email', 'create_branch', 'base_commit')


class Failure(Exception):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def _environment(author_name, author_email):
    # Do not inherit Git overrides, proxy commands, credentials, agents, or Python paths.
    env = {'PATH': '/usr/bin:/bin', 'HOME': '/var/empty', 'LC_ALL': 'C',
           'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null',
           'GIT_TERMINAL_PROMPT': '0', 'GIT_ASKPASS': '/usr/bin/false',
           'GIT_LITERAL_PATHSPECS': '1', 'GIT_OPTIONAL_LOCKS': '0',
           'GIT_NO_REPLACE_OBJECTS': '1'}
    if author_name is not None:
        env.update(GIT_AUTHOR_NAME=author_name, GIT_COMMITTER_NAME=author_name,
                   GIT_AUTHOR_EMAIL=author_email, GIT_COMMITTER_EMAIL=author_email)
    return env


def _git(root, env, *args, input=None, allowed=(0,)):
    command = [GIT, '-C', str(root), '-c', 'core.hooksPath=/dev/null',
               '-c', 'core.fsmonitor=false', '-c', 'commit.gpgSign=false',
               '-c', 'tag.gpgSign=false', '-c', 'credential.helper=',
               '-c', 'core.askPass=/usr/bin/false', '-c', 'gc.auto=0',
               '-c', 'maintenance.auto=false', '-c', 'protocol.allow=never',
               '-c', 'protocol.ssh.allow=always', *args]
    process = subprocess.run(command, env=env, input=input, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace')
    if process.returncode not in allowed:
        # Git diagnostics can contain credentials, repository content and URLs.
        raise Failure('git_failed', f'Git {args[0]} failed (exit {process.returncode}); inspect repository state before retrying.')
    return process.stdout


def _validate(value):
    page_id = value['page_id']
    if not isinstance(page_id, str) or re.fullmatch(r'[0-9a-f]{64}', page_id) is None:
        raise Failure('invalid_page_id', 'page_id must contain exactly 64 lowercase hexadecimal characters.')
    action = value['action']
    if action not in ('commit', 'push', 'commit-and-push'):
        raise Failure('invalid_input', 'action must be commit, push, or commit-and-push.')
    branch = value['branch']
    if not isinstance(branch, str) or branch not in ALLOWED_BRANCHES:
        raise Failure('invalid_branch', 'Only data-dev, data-test, and data-prod are permitted.')
    sha = lambda value: isinstance(value, str) and re.fullmatch(r'[0-9a-f]{40}', value) is not None
    if type(value['create_branch']) is not bool:
        raise Failure('invalid_input', 'create_branch must be an explicit boolean.')
    if value['create_branch']:
        if action == 'push' or value['expected_head'] is not None or not sha(value['base_commit']):
            raise Failure('invalid_input', 'Creation requires a commit action, expected_head=null, and an explicit full base_commit.')
    elif not sha(value['expected_head']) or value['base_commit'] is not None:
        raise Failure('invalid_input', 'Existing targets require their full expected_head and base_commit=null.')
    files = value['files']
    if not isinstance(files, list) or any(not isinstance(p, str) for p in files) or len(set(files)) != len(files):
        raise Failure('invalid_input', 'files must be an array of unique literal repository-relative file paths.')
    for path in files:
        if (not path or path.split('/')[0] in PROTECTED or any(p.startswith('.') or p.lower() in ('logs', 'receipts', 'credentials', '__pycache__') or p.lower().endswith(('.pem', '.key')) for p in path.split('/')) or path.startswith('/') or '\\' in path or any(ord(c) < 32 or ord(c) == 127 for c in path)
                or any(p in ('', '.', '..') or p.lower() == '.git' for p in path.split('/'))):
            raise Failure('invalid_input', 'files must be canonical literal file paths outside .git.')
        if page_id not in path.split('/')[1:-1]:
            raise Failure('page_scope_mismatch', 'Every file must be beneath data/<folders>/<page_id>/ with an exact page_id directory match.')
    if action == 'push':
        if files or any(value[key] is not None for key in ('message', 'author_name', 'author_email')):
            raise Failure('invalid_input', 'push requires files=[] and null message/author_name/author_email.')
    else:
        if not files:
            raise Failure('invalid_input', 'Commit requires an explicit nonempty file list.')
        for key in ('message', 'author_name', 'author_email'):
            text = value[key]
            if not isinstance(text, str) or not text.strip() or '\x00' in text:
                raise Failure('invalid_input', f'{key} must be a nonempty string without NUL.')
        if any(c in value['author_name'] + value['author_email'] for c in '\r\n<>'):
            raise Failure('invalid_input', 'Author identity cannot contain newlines or angle brackets.')
    remote = value['remote_url']
    if action == 'commit':
        if remote is not None:
            raise Failure('invalid_input', 'Local commit requires remote_url=null.')
    elif (not isinstance(remote, str) or not re.fullmatch(
            r'git@github\.com:[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+\.git', remote)
            or remote.rsplit('/', 1)[-1] in ('.git', '..git')):
        raise Failure('invalid_input', 'Push requires git@github.com:<owner>/<repository>.git using SSH.')


def _repository(root, env, files):
    data_root = root / 'data'
    if data_root.resolve() != data_root or not data_root.is_dir() or (data_root / '.git').exists():
        raise Failure('unsafe_repository', 'Use the parent repository with a canonical data/ directory and no nested data/.git.')
    if any(not path.startswith('data/') for path in files):
        raise Failure('invalid_path', 'Every Git path must be confined to data/.')
    if not root.is_absolute() or root.resolve() != root or not (root / '.git').is_dir() or (root / '.git').is_symlink():
        raise Failure('unsafe_repository', 'A canonical primary checkout with a real .git directory is required; linked worktrees are unsupported.')
    # The runner checks metadata aliases once before sandboxing/import.
    if _git(root, env, 'rev-parse', '--show-toplevel').strip() != str(root):
        raise Failure('unsafe_repository', 'Runner root must be the Git worktree root.')
    # Local configuration can launch filters/helpers or redirect writes. Fail closed
    # rather than trusting config overrides to neutralize every such mechanism.
    config = _git(root, env, 'config', '--local', '--no-includes', '--list', '-z')
    safe = {'core.repositoryformatversion', 'core.filemode', 'core.bare',
            'core.logallrefupdates', 'core.ignorecase', 'core.precomposeunicode',
            'user.name', 'user.email', 'remote.origin.url', 'remote.origin.fetch'}
    origin = None
    for record in filter(None, config.split('\x00')):
        key, _, argument = record.partition('\n')
        if key == 'remote.origin.url':
            if origin is not None:
                raise Failure('unsafe_configuration', 'Multiple origin URLs are unsupported.')
            origin = argument
        # VS Code's comparison-base hint is inert metadata, never a commit base.
        if key not in safe and not re.fullmatch(r'branch\.[A-Za-z0-9._/-]+\.(remote|merge|vscode-merge-base)', key):
            raise Failure('unsafe_configuration', 'Unsupported local Git configuration: ' + key)
    for marker in ('MERGE_HEAD', 'CHERRY_PICK_HEAD', 'REVERT_HEAD', 'rebase-merge',
                   'rebase-apply', 'BISECT_LOG', 'index.lock', 'shallow', 'info/grafts',
                   'objects/info/alternates', 'objects/info/http-alternates'):
        if (root / '.git' / marker).exists():
            raise Failure('unsafe_repository', 'Repository has an active operation, lock, or unsupported alternate/shallow history.')
    for path in files:
        target = root / path
        if target.resolve() != target:
            raise Failure('invalid_path', 'Selected file or ancestor is a symlink: ' + path)
        if target.exists():
            info = target.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise Failure('invalid_path', 'Only regular unaliased files or tracked deletions may be selected: ' + path)
    return origin


def _check_origin(root, env, requested, origin=None):
    origin = origin if origin is not None else _git(root, env, 'config', '--get', 'remote.origin.url', allowed=(0, 1)).strip()
    if origin.startswith('https://github.com/'):
        origin = 'git@github.com:' + origin[len('https://github.com/'):]
    elif origin.startswith('ssh://git@github.com/'):
        origin = 'git@github.com:' + origin[len('ssh://git@github.com/'):]
    origin = origin.rstrip('/')
    if not origin.endswith('.git'):
        origin += '.git'
    if (not re.fullmatch(r'git@github\.com:[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+\.git', origin)
            or origin.casefold() != requested.casefold()):
        raise Failure('invalid_remote', 'Push URL must match the parent repository origin on GitHub.')


def _ssh_environment(data_root, env):
    expected = data_root / 'tx-commit-and-push/logs/ssh-transport'
    wrapper = os.environ.get('PROJECT_DATA_SSH_WRAPPER', '')
    agent = os.environ.get('PROJECT_DATA_SSH_AGENT_SOCKET', '')
    known = os.environ.get('PROJECT_DATA_SSH_KNOWN_HOSTS', '')
    if wrapper != str(expected) or not agent or not known or not expected.is_file():
        raise Failure('ssh_not_configured', 'Automatic SSH pushes require a prepared transport, an SSH agent with an authorized key, and trusted GitHub known_hosts.')
    return {**env, 'GIT_SSH': wrapper, 'GIT_SSH_VARIANT': 'ssh', 'SSH_AUTH_SOCK': agent,
            'PROJECT_DATA_SSH_KNOWN_HOSTS': known, 'SSH_ASKPASS_REQUIRE': 'never'}


def _check_target(root, env, branch, expected_head):
    ref = 'refs/heads/' + branch
    records = _git(root, env, 'for-each-ref',
                   '--format=%(refname)%00%(objectname)%00%(objecttype)%00%(symref)', ref)
    target = next((row.split('\x00') for row in records.splitlines()
                   if row.startswith(ref + '\x00')), None)
    if target and (target[3] or target[2] != 'commit'):
        raise Failure('unsafe_target', 'Target must be a direct branch reference to a commit.')
    if (target[1] if target else None) != expected_head:
        raise Failure('stale_repository', 'Target differs from expected_head; review it before retrying.')


def _check_not_checked_out(root, env, branch):
    # Include all registered worktrees, not just the calling checkout.
    checked = _git(root, env, 'worktree', 'list', '--porcelain').splitlines()
    if 'branch refs/heads/' + branch in checked:
        raise Failure('checked_out_target', 'Refusing to advance a checked-out target: checkout and index must stay unchanged. Select another allowed target.')


def _checkout_state(root):
    """Detect concurrent changes without modifying the checkout or normal index."""
    paths = (root / '.git/HEAD', root / '.git/index')
    files = tuple(path.read_bytes() if path.exists() else None for path in paths)
    current = _git(root, _environment(None, None), 'rev-parse', '--verify', '--quiet', 'HEAD', allowed=(0, 1)).strip()
    return files + (current,)


def _local_commit(root, env, files, message, branch, expected_head, base_commit, details):
    """Commit through a private index and atomically advance only an off-checkout ref."""
    git_dir = root / '.git'
    temporary = git_dir / ('data-commit-index-' + uuid.uuid4().hex)
    locks = []
    try:
        # Standard Git locks block cooperating checkout/index writers during the CAS.
        # Neither normal HEAD nor the normal index is replaced or refreshed.
        for name in ('index.lock', 'HEAD.lock'):
            path = git_dir / name
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            except FileExistsError:
                raise Failure('repository_busy', 'Git checkout/index is locked; no commit attempted.') from None
            locks.append((path, fd))
        snapshot = _checkout_state(root)
        _check_not_checked_out(root, env, branch)
        _check_target(root, env, branch, expected_head)
        base = expected_head or base_commit
        if expected_head is None and _git(root, env, 'cat-file', '-t', base).strip() != 'commit':
            raise Failure('invalid_base', 'Explicit base_commit must identify an existing commit.')
        private = {**env, 'GIT_INDEX_FILE': str(temporary)}
        _git(root, private, 'read-tree', base)
        for path in files:
            if not (root / path).exists():
                # A deletion must be tracked on the target/base, not the checkout.
                _git(root, private, 'ls-files', '--error-unmatch', '--', path)
        # Explicit validated outputs may be ignored by repository-wide rules.
        _git(root, private, 'add', '--force', '--all', '--', *files)
        staged = [p for p in _git(root, private, 'diff', '--cached', '--name-only',
                                 '--no-renames', '-z', base).split('\x00') if p]
        details['staged_paths'] = staged
        if not staged:
            raise Failure('no_changes', 'The selected files have no changes relative to the target/base commit.')
        if set(staged) - set(files):
            raise Failure('unexpected_changes', 'Private index contains unselected changes; no commit attempted.')
        tree = _git(root, private, 'write-tree').strip()
        head = _git(root, private, 'commit-tree', tree, '-p', base, '-F', '-', input=message).strip()
        if not re.fullmatch(r'[0-9a-f]{40}', head):
            raise Failure('invalid_git_result', 'Git did not return a valid commit SHA.')
        _check_not_checked_out(root, env, branch)
        _check_target(root, env, branch, expected_head)
        if _checkout_state(root) != snapshot:
            raise Failure('concurrent_checkout_change', 'Checkout or staging index changed; no target update attempted.')
        details.update(commit_attempted=True, candidate_commit_sha=head, base_commit=base)
        _git(root, env, 'update-ref', '--no-deref', '-m', 'data-commit', 'refs/heads/' + branch,
             head, expected_head or '0' * 40)
        details.update(commit_sha=head, committed=True, branch_created=expected_head is None,
                       checkout_preserved=True, index_updated=False)
        if _checkout_state(root) != snapshot:
            details['checkout_preserved'] = False
            raise Failure('concurrent_checkout_change', 'Target committed, but another process changed checkout/index; inspect metadata before continuing.')
        return head
    finally:
        for path, fd in reversed(locks):
            os.close(fd)
            path.unlink(missing_ok=True)
        temporary.unlink(missing_ok=True)
        Path(str(temporary) + '.lock').unlink(missing_ok=True)


def _receipt(destination, value, details):
    run_id = os.environ['PROJECT_DATA_RUN_ID']
    if not re.fullmatch(r'[0-9a-f]{64}', run_id):
        raise Failure('receipt_failed', 'Runner run ID is invalid.')
    target = destination / (run_id + '.json')
    temporary = destination / ('.receipt-' + uuid.uuid4().hex)
    try:
        if target.is_symlink() or (target.exists() and (not target.is_file() or target.stat().st_nlink != 1)):
            raise OSError('Unsafe receipt target')
        with temporary.open('x', encoding='utf-8') as stream:
            json.dump({'input': value, **details}, stream, ensure_ascii=False, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        fd = os.open(destination, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        raise Failure('receipt_failed', 'Git effects may have completed but receipt persistence failed; inspect meta_data before retrying.') from None
    finally:
        temporary.unlink(missing_ok=True)
    return 'tx-commit-and-push/receipts/' + target.name


def commit(action: str, page_id: str, files: list, message: str | None, branch: str,
           expected_head: str | None, remote_url: str | None, author_name: str | None,
           author_email: str | None, create_branch: bool, base_commit: str | None) -> dict:
    """Commit explicit files and/or push an explicit SHA to one GitHub branch."""
    value = dict(zip(FIELDS, (action, page_id, files, message, branch, expected_head,
                              remote_url, author_name, author_email, create_branch, base_commit)))
    result = {'input': value, 'output': None,
              'output_format': 'json', 'status': 'error', 'error': None, 'meta_data': {}}
    details = result['meta_data']
    lock = None
    try:
        _validate(value)
        data_root = Path(os.environ['PROJECT_DATA_INPUT_ROOT'])
        if data_root.name != 'data' or data_root.resolve() != data_root:
            raise Failure('unsafe_repository', 'Runner must supply the canonical data/ subproject.')
        root = data_root.parent
        git_files = ['data/' + path for path in files]
        destination = Path(os.environ['PROJECT_DATA_DATA_DIRECTORY'])
        if destination.resolve() != data_root / 'tx-commit-and-push' / 'receipts' or destination.is_symlink() or not destination.is_dir():
            raise Failure('invalid_destination', 'Runner must prepare data/tx-commit-and-push/receipts.')
        env = _environment(author_name, author_email)
        origin = _repository(root, env, git_files)
        if action != 'commit':
            _check_origin(root, env, remote_url, origin or '')
            push_env = _ssh_environment(data_root, env)
        lock = os.open(root / '.git' / 'data-commit.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        if os.fstat(lock).st_nlink != 1:
            raise Failure('unsafe_repository', 'Transaction lock must not be hard-linked.')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Failure('repository_busy', 'Another data-commit owns this repository.') from None
        _check_target(root, env, branch, expected_head)
        details.update(branch=branch, previous_head=expected_head, commit_sha=None,
                       committed=False, pushed=False, push_attempted=False,
                       staged_paths=[], remote_url=remote_url)
        if action != 'push':
            head = _local_commit(root, env, git_files, message, branch, expected_head, base_commit, details)
        else:
            head = expected_head
            details['commit_sha'] = head
        if action != 'commit':
            _check_target(root, env, branch, head)
            details['push_attempted'] = True
            details['remote_state_uncertain'] = True
            # Explicit SHA and ref: no force, wildcard, tags, default remote or branch inference.
            _git(root, push_env, 'push', '--porcelain',
                 '--no-verify', '--recurse-submodules=no', '--', remote_url, head + ':refs/heads/' + branch)
            details.update(pushed=True, remote_state_uncertain=False)
        result['output'] = [_receipt(destination, value, details)]
        result.update(status='ok')
    except Failure as exc:
        result['error'] = {'code': exc.code, 'message': str(exc)}
    except (OSError, ValueError, KeyError) as exc:
        result['error'] = {'code': 'transaction_failed', 'message': 'Transaction failed; inspect meta_data and repository state before retrying.'}
    finally:
        if lock is not None:
            os.close(lock)
    return result
