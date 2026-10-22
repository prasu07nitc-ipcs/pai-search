"""Transaction runner checks using disposable projects; production data is untouched."""
import contextlib
import hashlib
import io
import json
import logging
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import runner

runner.LOGGER.addHandler(logging.NullHandler())


class Contracts(unittest.TestCase):
    def test_name_and_destination(self):
        directory, entry = runner.resolve_transaction('tx-bookmark')
        self.assertEqual(entry, 'bookmark')
        runner.validate_input(directory, entry, {'page': {}, 'raw_input': 'bookmark'})
        for name in ('tool-bookmark', 'tx-../bookmark', '../tx-bookmark', 'tx-Bookmark'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                runner.resolve_transaction(name)
        for value in ({'page': {}}, {'page': {}, 'raw_input': None}, {'page': [], 'raw_input': 'x'}):
            with self.subTest(value=value), self.assertRaises((ValueError, TypeError)):
                runner.validate_input(directory, entry, value)

    def test_output_boundary(self):
        good = {'input': {'raw_input': 'x', 'processed_input': {}}, 'output': 'data/bookmark/domain/page.md',
                'output_format': 'markdown', 'status': 'ok', 'error': None, 'meta_data': {}}
        runner.validate_output(good, 'tx-bookmark')
        for output in ('data/index/a.md', '/data/bookmark/a.md', 'data/bookmark/../a.md',
                       'data/bookmark//a.md', 'data/bookmark/./a.md', 'data/bookmark/a\\b.md'):
            with self.subTest(output=output), self.assertRaises(ValueError):
                runner.validate_output(dict(good, output=output), 'tx-bookmark')
        with self.assertRaises(ValueError):
            runner.validate_output(dict(good, extra=True), 'tx-bookmark')

    def test_aliases(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            real = base / 'real'; real.mkdir()
            linked = base / 'linked'; linked.symlink_to(real, target_is_directory=True)
            with self.assertRaises(ValueError):
                runner.prepare_data('tx-bookmark', linked)
            data = runner.prepare_data('tx-bookmark', base / 'data')
            original = data / 'a'; original.write_text('a')
            (data / 'link').hardlink_to(original)
            with self.assertRaises(ValueError):
                runner.validate_tree(data)

    def test_environment(self):
        runner.verify_environment()
        with patch.object(runner, 'ENV', Path('/unrelated/environment')):
            with self.assertRaises(RuntimeError):
                runner.verify_environment()


class SourceSignature(unittest.TestCase):
    def test_remote_urls(self):
        self.assertEqual(runner.repository_http_url('git@github.com:owner/repo.git'), 'https://github.com/owner/repo')
        self.assertEqual(runner.repository_http_url('https://user:secret@example.com/a.git?token=x#f'), 'https://example.com/a')
        self.assertEqual(runner.repository_http_url('/local/repo'), 'Unavailable')

    def test_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            directory = root / 'transactions/tx-example'
            directory.mkdir(parents=True)
            def git(*args):
                return subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True, text=True).stdout.strip()
            git('init')
            (directory / '.gitignore').write_text('ignored*\n')
            (directory / 'source.py').write_text('original')
            git('add', '.')
            git('-c', 'user.name=Test', '-c', 'user.email=test@example.com', 'commit', '-m', 'initial')
            git('remote', 'add', 'origin', 'git@github.com:owner/repo.git')
            clean = runner.source_code_signature(directory)
            self.assertEqual(clean['local_changes'], [])
            self.assertEqual(clean['commit'], git('rev-parse', 'HEAD'))
            self.assertEqual(clean['branch'], git('branch', '--show-current'))
            (directory / 'source.py').write_text('staged')
            git('add', '.')
            (directory / 'source.py').write_text('unstaged')
            (directory / 'new.py').write_text('new')
            (directory / 'ignored.py').write_text('ignore')
            (root / 'outside').write_text('outside')
            changes = runner.source_code_signature(directory)['local_changes']
            self.assertEqual(changes, [{'status': 'MM', 'path': 'transactions/tx-example/source.py'}, {'status': '??', 'path': 'transactions/tx-example/new.py'}])
            git('checkout', '--detach')
            self.assertEqual(runner.source_code_signature(directory)['branch'], 'Detached HEAD')
            (directory / '.gitignore').write_text('ignored*\nsource.py\n')
            paths = [c['path'] for c in runner.source_code_signature(directory)['local_changes']]
            self.assertNotIn('transactions/tx-example/source.py', paths)


class IsolatedIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='transaction-integration-')
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name).resolve()
        self.transactions = self.project / 'transactions'; self.transactions.mkdir()
        shutil.copy(runner.__file__, self.transactions / 'runner.py')
        shutil.copy(runner.ROOT / 'AGENTS.md', self.transactions / 'AGENTS.md')
        (self.transactions / '.venv').symlink_to(runner.ENV.resolve(), target_is_directory=True)
        shutil.copytree(runner.ROOT / 'tx-bookmark', self.transactions / 'tx-bookmark',
                        ignore=shutil.ignore_patterns('logs', '__pycache__'))
        self.page = {'title': 'First', 'description': 'Description', 'url': 'https://example.com/a', 'page_id': 'a' * 64}

    def execute(self, page=None, extra=(), raw='bookmark', timeout=20):
        value = {'page': page if page is not None else self.page, 'raw_input': raw}
        return subprocess.run([str(runner.PYTHON), '-B', str(self.transactions / 'runner.py'),
                               '--transaction', 'tx-bookmark', '--input', json.dumps(value), *extra],
                              capture_output=True, text=True, cwd=self.project, timeout=timeout)

    def test_persistence_logs_and_confirmation(self):
        self.assertFalse((self.project / 'data').exists())
        first = self.execute(); self.assertEqual(first.returncode, 0, first.stderr)
        result = json.loads(first.stdout)
        self.assertEqual(result['status'], 'ok', first.stdout + first.stderr)
        target = self.project / result['output']
        self.assertTrue(target.is_file())
        log = self.transactions / 'tx-bookmark/logs/run.log'
        records = [json.loads(line) for line in log.read_text().splitlines()]
        self.assertEqual(records[0]['output'], result['output'])
        self.assertEqual(records[0]['transaction_input'], {'page': self.page})
        again = self.execute(); self.assertEqual(again.returncode, 2, again.stderr)
        self.assertEqual(len(log.read_text().splitlines()), 1)
        confirmed = self.execute(extra=('--rerun',)); self.assertEqual(confirmed.returncode, 0, confirmed.stderr)
        changed = dict(self.page, title='Updated')
        update = self.execute(changed); self.assertEqual(update.returncode, 0, update.stderr)
        self.assertIn('# Updated', target.read_text())
        other = self.execute(dict(self.page, page_id='b' * 64, url='https://example.com/b'))
        self.assertEqual(other.returncode, 0, other.stderr)
        self.assertTrue(target.is_file())
        self.assertTrue((self.project / json.loads(other.stdout)['output']).is_file())
        invalid = self.execute(dict(self.page, title=''))
        self.assertEqual(json.loads(invalid.stdout)['status'], 'error')
        self.assertIn('# Updated', target.read_text())

    def test_cases_never_create_production_data(self):
        completed = subprocess.run([str(runner.PYTHON), '-B', str(self.transactions / 'runner.py'),
                                   '--transaction', 'tx-bookmark', '--cases',
                                   str(self.transactions / 'tx-bookmark/test-cases.json'), '--summary'],
                                  capture_output=True, text=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        self.assertFalse((self.project / 'data').exists())
        self.assertFalse((self.transactions / 'tx-bookmark/logs/run.log').exists())

    def test_parent_rejects_symlink_and_preserves_target(self):
        outside = self.project / 'untouched'; outside.write_text('keep')
        owned = self.project / 'data/bookmark/example_com'; owned.mkdir(parents=True)
        (owned / ('a' * 64 + '.md')).symlink_to(outside)
        failed = self.execute()
        self.assertNotEqual(failed.returncode, 0)
        self.assertEqual(outside.read_text(), 'keep')

    def test_kernel_denies_sibling_local_environment_writes_and_fork(self):
        module = self.transactions / 'tx-bookmark/transaction.py'
        module.write_text('''import os
from pathlib import Path

def bookmark(page: dict, raw_input: str) -> dict:
    destination = Path(os.environ['PROJECT_TRANSACTION_DATA_DIRECTORY'])
    targets = [destination.parent / 'index' / 'blocked', destination.parent / 'blocked',
               Path(__file__).parent / 'blocked', Path(os.sys.prefix) / 'blocked']
    for target in targets:
        try:
            target.write_text('escape')
        except PermissionError:
            pass
        else:
            raise RuntimeError('Write escape: ' + str(target))
    try:
        os.fork()
    except PermissionError:
        pass
    else:
        raise RuntimeError('Fork escape')
    (destination / 'proof.md').write_text('isolated')
    return {'input': {'raw_input': raw_input, 'processed_input': {'page': page}},
            'output': 'data/bookmark/proof.md', 'output_format': 'markdown',
            'status': 'ok', 'error': None, 'meta_data': {}}
''')
        sibling = self.project / 'data/index'; sibling.mkdir(parents=True)
        result = self.execute(); self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((sibling / 'blocked').exists())

    def test_timeout_record(self):
        module = self.transactions / 'tx-bookmark/transaction.py'
        module.write_text('import time\ndef bookmark(page: dict, raw_input: str) -> dict:\n    time.sleep(3)\n    return {}\n')
        completed = self.execute(extra=('--timeout', '0.3'))
        self.assertNotEqual(completed.returncode, 0)
        record = json.loads((self.transactions / 'tx-bookmark/logs/run.log').read_text())
        self.assertEqual(record['error']['code'], 'runner_timeout')
        self.assertIsNone(record['output'])


if __name__ == '__main__':
    unittest.main()
