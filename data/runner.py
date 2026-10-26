"""Isolated data commit/push runner for Python 3.11+ and macOS."""
from __future__ import annotations

# Isolate before importing non-frozen modules: data payloads must not shadow
# standard-library modules through the script directory or PYTHONPATH.
import sys
import os
if __name__ == '__main__' and not sys.flags.isolated:
    os.execv(sys.executable, [sys.executable, '-I', '-B', __file__, *sys.argv[1:]])

import argparse
import ctypes
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import importlib.util
import json
import math
from pathlib import Path
import re
import signal
import stat
import subprocess

ROOT = Path(__file__).resolve().parent
ENV = ROOT / ".venv"
FIELDS = {'action', 'page_id', 'files', 'message', 'branch', 'expected_head', 'remote_url', 'author_name', 'author_email', 'create_branch', 'base_commit'}
BRANCHES = {'data-dev', 'data-test', 'data-prod'}
CONFIG_PATH = ROOT / 'tx-commit-and-push' / 'git-config.json'

def strict_json(source):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON field: ' + key)
            result[key] = value
        return result
    def reject_constant(value):
        raise ValueError('Nonfinite JSON number: ' + value)
    return json.loads(source, object_pairs_hook=unique, parse_constant=reject_constant)


def load_git_config():
    """Load the sole source of configurable Git settings; never use fallbacks."""
    if CONFIG_PATH.resolve() != CONFIG_PATH:
        raise ValueError('git-config.json must be a regular unaliased file.')
    fd = os.open(CONFIG_PATH, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'r', encoding='utf-8') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError('git-config.json must be a regular unaliased file.')
        value = strict_json(stream.read())
    fields = {'author_name', 'author_email', 'branch', 'remote_url', 'create_branch'}
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError('git-config.json must contain exactly author_name, author_email, branch, remote_url, create_branch.')
    if not isinstance(value['branch'], str) or value['branch'] not in BRANCHES or type(value['create_branch']) is not bool:
        raise ValueError('Invalid branch or create_branch in git-config.json.')
    for key in ('author_name', 'author_email'):
        item = value[key]
        if item is not None and (not isinstance(item, str) or not item.strip() or any(c in item for c in '\x00\r\n<>')):
            raise ValueError('Invalid ' + key + ' in git-config.json.')
    remote = value['remote_url']
    if not isinstance(remote, str) or re.fullmatch(r'git@github\.com:[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+\.git', remote) is None or remote.rsplit('/', 1)[-1] in ('.git', '..git'):
        raise ValueError('Set an explicit GitHub SSH remote_url in git-config.json.')
    return value


def input_id(value):
    encoded = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


def verify_environment():
    if sys.prefix == sys.base_prefix or Path(sys.prefix).resolve() != ENV.resolve():
        raise RuntimeError('Use data/.venv/bin/python; the separate data environment is required.')
    # No implicit approval through a transitive dependency or an ambient environment.
    approved = {}
    for line in (ROOT / 'requirements.txt').read_text().splitlines():
        if not line or line.startswith(('#', '--')):
            continue
        match = re.fullmatch(r'([A-Za-z0-9_.-]+)(?:\[[A-Za-z0-9_,.-]+\])?==([^ ]+) --hash=sha256:[0-9a-f]{64}', line)
        if match is None:
            raise RuntimeError('Invalid pinned dependency allowlist.')
        approved[re.sub(r'[-_.]+', '-', match[1]).lower()] = match[2]
    for distribution in importlib.metadata.distributions(path=[str(ENV / 'lib' / f'python{sys.version_info.major}.{sys.version_info.minor}' / 'site-packages')]):
        name = re.sub(r'[-_.]+', '-', distribution.metadata['Name']).lower()
        if approved.get(name) != distribution.version:
            raise RuntimeError('Unapproved or mismatched package in data environment: ' + name)


def validate_input(value):
    optional = {'branch', 'create_branch'}
    if not isinstance(value, dict) or not FIELDS - optional <= set(value) or not set(value) <= FIELDS:
        raise ValueError('Supply action, page_id, files, message, expected_head, remote_url, author_name, author_email, base_commit, and optionally branch and create_branch; no extra fields.')
    settings = load_git_config()
    value = {'branch': settings['branch'], 'create_branch': False, **value}
    required = {'branch': settings['branch'],
                'remote_url': None if value['action'] == 'commit' else settings['remote_url'],
                'author_name': None if value['action'] == 'push' else settings['author_name'],
                'author_email': None if value['action'] == 'push' else settings['author_email']}
    if any(value[key] != item for key, item in required.items()):
        raise ValueError('Git settings must match git-config.json; edit that file instead of supplying overrides.')
    if value['action'] != 'push' and any(settings[key] is None for key in ('author_name', 'author_email')):
        raise ValueError('Fill author_name and author_email in git-config.json before committing.')
    if value['create_branch'] and not settings['create_branch']:
        raise ValueError('Branch creation is disabled in git-config.json.')
    if not isinstance(value['page_id'], str) or re.fullmatch(r'[0-9a-f]{64}', value['page_id']) is None:
        raise ValueError('page_id must contain exactly 64 lowercase hexadecimal characters.')
    if not isinstance(value['branch'], str) or not isinstance(value['action'], str) or value['branch'] not in BRANCHES or value['action'] not in ('commit', 'push', 'commit-and-push'):
        raise ValueError('Select an explicit action and data-dev, data-test, or data-prod branch.')
    if not isinstance(value['files'], list) or any(not isinstance(p, str) for p in value['files']):
        raise ValueError('files must be an array of literal data-relative file paths.')
    if any(value['page_id'] not in path.split('/')[1:-1] for path in value['files']):
        raise ValueError('Every file must be beneath data/<folders>/<page_id>/ with an exact page_id directory match.')
    for key in ('message', 'expected_head', 'remote_url', 'author_name', 'author_email', 'base_commit'):
        if value[key] is not None and not isinstance(value[key], str):
            raise ValueError(key + ' must be a string or null.')
    if type(value['create_branch']) is not bool:
        raise ValueError('create_branch must be a boolean.')
    json.dumps(value, allow_nan=False)
    return value


def validate_directory(root):
    if root.is_symlink() or root.resolve() != root or not root.is_dir():
        raise ValueError('Storage must be a canonical real directory.')


def validate_tree(root):
    validate_directory(root)
    for base, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            info = (Path(base) / name).lstat()
            if stat.S_ISLNK(info.st_mode) or (not stat.S_ISDIR(info.st_mode) and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1)):
                raise ValueError('Storage aliases and nonregular files are forbidden.')


class SSHSetupError(ValueError):
    """SSH prerequisites must be configured before commit or push effects."""


def prepare_ssh():
    configured = os.environ.get('SSH_AUTH_SOCK', '')
    agent = Path(configured).resolve() if configured else None
    known = Path.home() / '.ssh/known_hosts'
    if (agent is None or not agent.is_socket() or agent.stat().st_uid != os.getuid()
            or not known.is_file() or known.resolve() != known or known.stat().st_nlink != 1):
        raise SSHSetupError('Automatic pushes require an accessible SSH agent and trusted ~/.ssh/known_hosts; configure SSH first.')
    interpreter = str(ENV / 'bin/python')
    if any(character.isspace() for character in interpreter):
        raise SSHSetupError('SSH transport launcher requires a runtime path without whitespace.')
    wrapper = ROOT / 'tx-commit-and-push/logs/ssh-transport'
    source = '#!' + interpreter + ' -I\n' + (ROOT / 'tx-commit-and-push/ssh.py').read_text()
    temporary = ROOT / ('tx-commit-and-push/logs/.ssh-transport-' + os.urandom(8).hex() + '.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o700)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(source)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, wrapper)
    finally:
        temporary.unlink(missing_ok=True)
    return {'PROJECT_DATA_SSH_WRAPPER': str(wrapper), 'PROJECT_DATA_SSH_AGENT_SOCKET': str(agent),
            'PROJECT_DATA_SSH_KNOWN_HOSTS': str(known)}


def commit_sandbox_rules(value):
    if ROOT.name != 'data':
        raise ValueError('The runner must live in the data/ subproject.')
    if (ROOT / '.git').exists():
        raise ValueError('Nested data/.git is unsupported; Git operations must use the parent repository.')
    validate_tree(ROOT.parent / '.git')
    discovered = subprocess.run(['/usr/bin/git', '--exec-path'], check=True, capture_output=True,
                                text=True, timeout=5, env={'PATH': '/usr/bin:/bin', 'HOME': '/var/empty',
                                'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null'})
    helpers = Path(discovered.stdout.strip())
    if helpers.resolve() != helpers or not (str(helpers).startswith('/Library/Developer/') or str(helpers).startswith('/Applications/Xcode.app/')):
        raise ValueError("Apple's installed Git toolchain is required.")
    binary = (helpers / 'git').resolve()
    if not binary.is_file():
        raise ValueError('Installed Git binary unavailable.')
    os.environ['PROJECT_DATA_GIT_BINARY'] = str(binary)
    binaries = {binary}
    if value['action'] != 'commit':
        wrapper = ROOT / 'tx-commit-and-push/logs/ssh-transport'
        if os.environ.get('PROJECT_DATA_SSH_WRAPPER') != str(wrapper) or not wrapper.is_file():
            raise SSHSetupError('The parent must prepare the fixed SSH transport before push.')
        binaries.update((Path('/usr/bin/ssh'), Path(sys.executable).resolve(), wrapper))
        # Framework Python's launcher execs its app binary on macOS.
        framework_python = Path(sys.base_prefix) / 'Resources/Python.app/Contents/MacOS/Python'
        if framework_python.is_file():
            binaries.add(framework_python.resolve())
    readable = [ROOT, ROOT.parent / '.git', ENV.resolve(), Path(sys.base_prefix).resolve(), helpers.parent.parent,
                Path('/System'), Path('/usr/lib'), Path('/usr/share'), Path('/private/etc'),
                Path('/private/var/run'), Path('/dev'), Path('/Library/Apple'),
                Path('/Library/Preferences/SystemConfiguration')]
    rules = ['(version 1)', '(allow default)', '(deny file-read*)', '(allow file-read-metadata)',
             '(deny file-write*)', '(deny file-link)', '(deny process-exec)', '(deny network*)']
    for path in readable:
        rules.append('(allow file-read* (subpath ' + json.dumps(str(path)) + '))')
    # Git's getcwd opens ancestor directories; grant the directories themselves,
    # never the parent repository's files or sibling subtrees.
    for path in ROOT.parents:
        rules.append('(allow file-read* (literal ' + json.dumps(str(path)) + '))')
    for name in ('.gitignore', '.gitattributes'):
        rules.append('(allow file-read* (literal ' + json.dumps(str(ROOT.parent / name)) + '))')
    for path in (ROOT.parent / '.git', ROOT / 'tx-commit-and-push/receipts'):
        rules += ['(allow file-write* (subpath ' + json.dumps(str(path)) + '))',
                  '(deny file-write-unlink (literal ' + json.dumps(str(path)) + '))']
    # These files must remain unchanged even if component code regresses.
    for name in ('HEAD', 'index', 'logs/HEAD'):
        rules.append('(deny file-write* (literal ' + json.dumps(str(ROOT.parent / '.git' / name)) + '))')
    current = (ROOT.parent / '.git/HEAD').read_text().strip()
    if current.startswith('ref: refs/heads/'):
        ref = current[len('ref: '):]
        if any(part in ('', '.', '..') for part in ref.split('/')):
            raise ValueError('Unsafe checked-out branch reference.')
        for relative in (ref, ref + '.lock', 'logs/' + ref):
            rules.append('(deny file-write* (literal ' + json.dumps(str(ROOT.parent / '.git' / relative)) + '))')
    rules.append('(allow file-write* (literal "/dev/null"))')
    for binary in sorted(binaries):
        rules += ['(allow file-read* (literal ' + json.dumps(str(binary)) + '))',
                  '(allow process-exec (literal ' + json.dumps(str(binary)) + '))']
    if value['action'] != 'commit':
        known = Path(os.environ['PROJECT_DATA_SSH_KNOWN_HOSTS'])
        agent = Path(os.environ['PROJECT_DATA_SSH_AGENT_SOCKET'])
        if not known.is_file() or not agent.is_socket():
            raise SSHSetupError('SSH agent and trusted host file are required.')
        rules.append('(allow file-read* (literal ' + json.dumps(str(known)) + '))')
        for ancestor in known.parents:
            rules.append('(allow file-read* (literal ' + json.dumps(str(ancestor)) + '))')
        rules.append('(allow file-read* (literal ' + json.dumps(str(agent)) + '))')
        rules.append('(allow network-outbound)')

    return rules


def install_sandbox(value):
    if sys.platform != 'darwin':
        raise RuntimeError('macOS sandbox_init is required; refusing unsandboxed execution.')
    rules = commit_sandbox_rules(value)
    library = ctypes.CDLL('/usr/lib/libsandbox.dylib', use_errno=True)
    library.sandbox_init.argtypes = [ctypes.c_char_p, ctypes.c_uint64, ctypes.POINTER(ctypes.c_char_p)]
    library.sandbox_init.restype = ctypes.c_int
    error = ctypes.c_char_p()
    if library.sandbox_init(''.join(rules).encode(), 0, ctypes.byref(error)):
        raise RuntimeError('Cannot apply data sandbox: ' + (error.value or b'unknown').decode())
    for path in (ROOT / 'runner.py', ROOT / 'requirements.txt', ROOT / 'tx-commit-and-push/.write-probe', ROOT.parent / '.parent-write-probe'):
        try:
            fd = os.open(path, os.O_WRONLY)
        except (PermissionError, FileNotFoundError):
            # Existing runner/requirements prove denial; missing probes do not create files.
            pass
        else:
            os.close(fd)
            raise RuntimeError('Sandbox write restriction verification failed.')
    try:
        subprocess.run(['/bin/sh', '-c', 'exit 0'], check=True, capture_output=True)
    except PermissionError:
        pass
    else:
        raise RuntimeError('Sandbox executable restriction verification failed.')


def validate_output(result, value, run_id):
    if not isinstance(result, dict) or set(result) != {'input', 'output', 'output_format', 'status', 'error', 'meta_data'}:
        raise ValueError('Invalid result envelope.')
    if result['input'] != value or result['output_format'] != 'json' or not isinstance(result['meta_data'], dict):
        raise ValueError('Invalid result input/format/metadata.')
    if result['status'] == 'ok':
        if result['error'] is not None or result['output'] != ['tx-commit-and-push/receipts/' + run_id + '.json']:
            raise ValueError('Successful result must identify the exact owned receipt.')
    elif result['status'] != 'error' or result['output'] is not None or not isinstance(result['error'], dict) or set(result['error']) != {'code', 'message'} or any(not isinstance(v, str) or not v for v in result['error'].values()):
        raise ValueError('Invalid failure envelope.')
    json.dumps(result, allow_nan=False)


def validate_saved_output(result, root, run_id):
    if result['status'] != 'ok':
        return
    folder = root / 'tx-commit-and-push/receipts'
    if folder.resolve() != folder:
        raise ValueError('Receipt directory must not contain aliases.')
    fd = os.open(folder / (run_id + '.json'), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError('Receipt must be a regular unaliased file.')
        with os.fdopen(os.dup(fd), 'r', encoding='utf-8') as stream:
            receipt = strict_json(stream.read())
        if receipt != {'input': result['input'], **result['meta_data']}:
            raise ValueError('Receipt contents do not match the returned input and effects.')
    finally:
        os.close(fd)


def run_worker_process(command, **options):
    payload, timeout = options.pop('input'), options.pop('timeout')
    options.pop('capture_output')
    options.pop('check')
    with subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          start_new_session=True, **options) as child:
        try:
            stdout, stderr = child.communicate(payload, timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, stderr = child.communicate()
            raise subprocess.TimeoutExpired(command, timeout, output=stdout, stderr=stderr) from None
        finally:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if child.returncode:
            raise subprocess.CalledProcessError(child.returncode, command, output=stdout, stderr=stderr)
        return subprocess.CompletedProcess(command, child.returncode, stdout, stderr)


def worker(value, run_id):
    verify_environment()
    value = validate_input(value)
    expected = input_id(value)
    if run_id != expected:
        raise ValueError('Invalid run ID.')
    install_sandbox(value)
    os.environ.update(PROJECT_DATA_INPUT_ROOT=str(ROOT), PROJECT_DATA_DATA_DIRECTORY=str(ROOT / 'tx-commit-and-push/receipts'), PROJECT_DATA_RUN_ID=run_id)
    spec = importlib.util.spec_from_file_location('data_commit', ROOT / 'tx-commit-and-push/commit.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.commit(**value)
    validate_output(result, value, run_id)
    validate_saved_output(result, ROOT, run_id)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(',', ':')))


def append_record(path, record):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError('Log must be regular and unaliased.')
        encoded = (json.dumps(record, ensure_ascii=False, allow_nan=False, separators=(',', ':')) + '\n').encode()
        if os.write(fd, encoded) != len(encoded):
            raise OSError('Incomplete log append.')
        os.fsync(fd)
    finally:
        os.close(fd)


def invoke(value, timeout=20, rerun=False):
    verify_environment()
    value = validate_input(value)
    if not math.isfinite(timeout) or not 0 < timeout <= 300:
        raise ValueError('Timeout must be >0 and <=300 seconds.')
    if ROOT.name != 'data' or (ROOT / '.git').exists():
        raise ValueError('Use data/ inside the parent repository without a nested .git.')
    validate_directory(ROOT.parent / '.git')
    for folder in (ROOT / 'tx-commit-and-push', ROOT / 'tx-commit-and-push/logs', ROOT / 'tx-commit-and-push/receipts'):
        if folder.resolve() != folder or folder.is_symlink():
            raise ValueError('Runtime storage must not contain aliases.')
        folder.mkdir(exist_ok=True)
    logs = ROOT / 'tx-commit-and-push/logs'
    validate_directory(logs)
    validate_directory(ROOT / 'tx-commit-and-push/receipts')
    run_id = input_id(value)
    history = logs / 'run.log'
    if not rerun:
        try:
            fd = os.open(history, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            fd = None
        if fd is not None:
            with os.fdopen(fd, 'r', encoding='utf-8') as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise ValueError('History must be a regular unaliased file.')
                for line in stream:
                    previous = strict_json(line)
                    if previous['run_id'] == run_id and previous['status'] == 'ok':
                        raise ValueError('Successful input already executed; explicit --rerun required after reconciliation.')
    record = {'run_id': run_id, 'executed_at': datetime.now(timezone.utc).isoformat(), 'transaction_input': value}
    accepted_result = None
    try:
        ssh_settings = prepare_ssh() if value['action'] != 'commit' else {}
        completed = run_worker_process([str(ENV / 'bin/python'), '-I', '-B', str(Path(__file__).resolve()), '--worker'],
                                      input=json.dumps({'input': value, 'run_id': run_id}), text=True,
                                      encoding='utf-8', capture_output=True, check=True, cwd=str(ROOT), timeout=timeout,
                                      env={**os.environ, **ssh_settings})
        result = strict_json(completed.stdout)
        validate_output(result, value, run_id)
        accepted_result = result
        validate_saved_output(result, ROOT, run_id)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        result = {'input': value, 'output': None, 'output_format': 'json',
                  'status': 'error', 'error': {'code': 'ssh_not_configured' if isinstance(exc, SSHSetupError) else ('runner_timeout' if isinstance(exc, subprocess.TimeoutExpired) else 'runner_error'),
                  'message': str(exc) if isinstance(exc, SSHSetupError) else 'Data worker failed; reconcile repository/index/remote state before retrying.'},
                  'meta_data': {'repository_state_uncertain': not isinstance(exc, SSHSetupError), 'remote_state_uncertain': value['action'] != 'commit' and not isinstance(exc, SSHSetupError)}}
        if isinstance(exc, SSHSetupError):
            result['meta_data'].update(committed=False, pushed=False, push_attempted=False)
        if accepted_result is not None:
            result['meta_data'].update(accepted_result['meta_data'])
            if accepted_result['output']:
                result['meta_data']['saved_receipts'] = accepted_result['output']
        diagnostics = getattr(exc, 'stderr', '') or ''
        if isinstance(diagnostics, bytes):
            diagnostics = diagnostics.decode('utf-8', errors='replace')
        try:
            append_record(logs / 'runner.log', {'error': result['error'], 'diagnostics': diagnostics})
        except (OSError, ValueError):
            result['meta_data']['audit_incomplete'] = True
    record.update({key: result[key] for key in ('output', 'output_format', 'status', 'error', 'meta_data')})
    try:
        append_record(history, record)
    except (OSError, ValueError):
        details = {**result['meta_data'], 'audit_incomplete': True}
        if result['output']:
            details['saved_receipts'] = result['output']
        if result['error']:
            details['operation_error'] = result['error']
        result = {**result, 'status': 'error', 'output': None, 'meta_data': details,
                  'error': {'code': 'audit_write_failed',
                            'message': 'Audit append failed; inspect known Git effects in meta_data before any retry.'}}
    return result


def inspect_settings():
    """Read local settings and refs without invoking Git or changing metadata."""
    settings = load_git_config()
    branch = settings['branch']
    metadata = ROOT.parent / '.git'
    if (ROOT / '.git').exists():
        raise ValueError('Nested data repository is unsupported.')
    validate_directory(metadata)

    def read_metadata(path):
        if path.resolve() != path:
            raise ValueError('Git reference aliases are forbidden.')
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            return None
        with os.fdopen(fd, 'r', encoding='utf-8') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError('Git references must be regular unaliased files.')
            return stream.read()

    packed = {}
    packed_path = metadata / 'packed-refs'
    packed_text = read_metadata(packed_path)
    if packed_text is not None:
        for line in packed_text.splitlines():
            if not line or line.startswith(('#', '^')):
                continue
            sha, ref = line.split(' ', 1)
            if ref in packed or re.fullmatch(r'[0-9a-f]{40}', sha) is None:
                raise ValueError('Invalid packed refs.')
            packed[ref] = sha

    def resolve(ref):
        if not ref.startswith('refs/') or any(
                part in ('', '.', '..') for part in ref.split('/')):
            raise ValueError('Invalid symbolic reference.')
        path = metadata / ref
        text = read_metadata(path)
        value = text.strip() if text is not None else packed.get(ref)
        if value is not None and value.startswith('ref: '):
            raise ValueError('Target must be a direct branch reference.')
        if value is not None and re.fullmatch(r'[0-9a-f]{40}', value) is None:
            raise ValueError('Invalid reference SHA.')
        return value

    head = resolve('refs/heads/' + branch)
    return {**settings, 'expected_head': head, 'base_commit': None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input')
    parser.add_argument('--inspect-settings', action='store_true')
    parser.add_argument('--timeout', type=float, default=20)
    parser.add_argument('--rerun', action='store_true')
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        if args.inspect_settings or args.input is not None or args.rerun:
            parser.error('Worker mode cannot be combined with other operations.')
        payload = strict_json(sys.stdin.read())
        worker(payload['input'], payload['run_id'])
        return
    original = None
    try:
        if args.inspect_settings:
            if args.input is not None or args.rerun:
                raise ValueError('Settings inspection cannot be combined with execution.')
            verify_environment()
            result = inspect_settings()
        elif args.input is not None:
            original = strict_json(args.input)
            result = invoke(original, args.timeout, args.rerun)
        else:
            raise ValueError('Supply --input JSON or --inspect-settings.')
    except (OSError, ValueError, RuntimeError) as exc:
        result = {'input': original, 'output': None, 'output_format': 'json',
                  'status': 'error', 'error': {'code': 'preflight_failed', 'message': str(exc)},
                  'meta_data': {'committed': False, 'pushed': False, 'push_attempted': False}}
    print(json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(',', ':')))



if __name__ == '__main__':
    main()
