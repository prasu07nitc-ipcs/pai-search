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
    def test_canonical_identity(self):
        value = {"raw_input": "दिल्ली", "page_file": "source.txt"}
        expected = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                             ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()
        self.assertEqual(runner.canonical_hash(value), expected)
        self.assertEqual(runner.canonical_hash(dict(reversed(list(value.items())))), expected)
        self.assertNotEqual(runner.canonical_hash({**value, "raw_input": "other"}), expected)
        with self.assertRaises(ValueError):
            runner.canonical_hash({"number": float("nan")})

    def test_name_and_destination(self):
        directory, entry = runner.resolve_transaction('tx-bookmark')
        self.assertEqual(entry, 'bookmark')
        runner.validate_input(directory, entry, {'page_file': 'example.txt', 'raw_input': 'bookmark'})
        for name in ('tool-bookmark', 'tx-../bookmark', '../tx-bookmark', 'tx-Bookmark'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                runner.resolve_transaction(name)
        for value in ({'page_file': 'x'}, {'page_file': 'x', 'raw_input': None}, {'page_file': [], 'raw_input': 'x'}):
            with self.subTest(value=value), self.assertRaises((ValueError, TypeError)):
                runner.validate_input(directory, entry, value)

    def test_output_boundary(self):
        good = {'input': {'raw_input': 'x', 'processed_input': {}}, 'output': ['data/bookmark/domain/page.md'],
                'output_format': 'markdown', 'status': 'ok', 'error': None, 'meta_data': {}}
        runner.validate_output(good, 'tx-bookmark')
        for output in ('data/index/a.md', '/data/bookmark/a.md', 'data/bookmark/../a.md',
                       'data/bookmark//a.md', 'data/bookmark/./a.md', 'data/bookmark/a\\b.md'):
            with self.subTest(output=output), self.assertRaises(ValueError):
                runner.validate_output(dict(good, output=[output]), 'tx-bookmark')
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
        payload = page if page is not None else self.page
        filename = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest() + '.txt'
        source = self.project / 'tools/tool-webpage-og-crawler/output' / filename
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(json.dumps(payload))
        value = {'page_file': str(source), 'raw_input': raw}
        return subprocess.run([str(runner.PYTHON), '-B', str(self.transactions / 'runner.py'),
                               '--transaction', 'tx-bookmark', '--input', json.dumps(value), *extra],
                              capture_output=True, text=True, cwd=self.project, timeout=timeout)

    def test_persistence_logs_and_confirmation(self):
        self.assertFalse((self.project / 'data').exists())
        first = self.execute(); self.assertEqual(first.returncode, 0, first.stderr)
        result = json.loads(first.stdout)
        self.assertEqual(result['status'], 'ok', first.stdout + first.stderr)
        target = self.project / result['output'][0]
        self.assertTrue(target.is_file())
        log = self.transactions / 'tx-bookmark/logs/run.log'
        records = [json.loads(line) for line in log.read_text().splitlines()]
        self.assertEqual(records[0]['output'], result['output'])
        self.assertEqual(records[0]['transaction_input'], records[0]['processed_input'])
        self.assertIn('page_file', records[0]['transaction_input'])
        again = self.execute(); self.assertEqual(again.returncode, 2, again.stderr)
        self.assertEqual(len(log.read_text().splitlines()), 1)
        confirmed = self.execute(extra=('--rerun',)); self.assertEqual(confirmed.returncode, 0, confirmed.stderr)
        changed = dict(self.page, title='Updated')
        update = self.execute(changed); self.assertEqual(update.returncode, 0, update.stderr)
        self.assertIn('# Updated', target.read_text())
        other = self.execute(dict(self.page, page_id='b' * 64, url='https://example.com/b'))
        self.assertEqual(other.returncode, 0, other.stderr)
        self.assertTrue(target.is_file())
        self.assertTrue((self.project / json.loads(other.stdout)['output'][0]).is_file())
        invalid = self.execute(dict(self.page, title=''))
        self.assertEqual(json.loads(invalid.stdout)['status'], 'error')
        self.assertIn('# Updated', target.read_text())

    def test_cases_never_create_production_data(self):
        completed = subprocess.run([str(runner.PYTHON), '-B', str(self.transactions / 'runner.py'),
                                   '--transaction', 'tx-bookmark', '--cases',
                                   str(self.transactions / 'tx-bookmark/test-cases.json'), '--summary'],
                                  capture_output=True, text=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        report = self.transactions / 'tx-bookmark/logs/test-report.log'
        records = [json.loads(line) for line in report.read_text().splitlines()]
        cases_path = self.transactions / 'tx-bookmark/test-cases.json'
        cases = json.loads(cases_path.read_bytes())
        for record, case in zip(records, cases, strict=True):
            self.assertEqual(record['cases_sha256'], hashlib.sha256(cases_path.read_bytes()).hexdigest())
            self.assertEqual(record['validator_sha256'], hashlib.sha256(
                (self.transactions / 'tx-bookmark/validator.py').read_bytes()).hexdigest())
            self.assertEqual(record['fixture_files_hash'], runner.canonical_hash(case.get('fixture_files', {})))
            self.assertTrue(record['python_version'])
            self.assertEqual(record['platform'], 'darwin')
        self.assertFalse((self.project / 'data').exists())
        self.assertFalse((self.transactions / 'tx-bookmark/logs/run.log').exists())
        self.assertTrue((self.project / '.tmp').is_dir())
        self.assertEqual(list((self.project / '.tmp').iterdir()), [])
        self.assertFalse((self.transactions / 'tx-bookmark/fixtures').exists())

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

def bookmark(page_file: str, raw_input: str) -> dict:
    destination = Path(os.environ['PROJECT_TRANSACTION_DATA_DIRECTORY'])
    source = Path(page_file)
    source.read_text()
    project = Path(__file__).resolve().parents[2]
    for blocked in (project / 'skills/skill-article-writer/output/blocked.txt',
                    project / 'tools/tool-webpage-markdown/output/blocked.txt'):
        try:
            blocked.read_text()
        except PermissionError:
            pass
        else:
            raise RuntimeError('Read escape: ' + str(blocked))
    targets = [destination.parent / 'index' / 'blocked', destination.parent / 'blocked',
               Path(__file__).parent / 'blocked', Path(os.sys.prefix) / 'blocked', source]
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
    return {'input': {'raw_input': raw_input, 'processed_input': {'page_file': page_file}},
            'output': ['data/bookmark/proof.md'], 'output_format': 'markdown',
            'status': 'ok', 'error': None, 'meta_data': {}}
''')
        sibling = self.project / 'data/index'; sibling.mkdir(parents=True)
        for relative in ('skills/skill-article-writer/output/blocked.txt',
                         'tools/tool-webpage-markdown/output/blocked.txt'):
            blocked = self.project / relative
            blocked.parent.mkdir(parents=True, exist_ok=True)
            blocked.write_text('unreadable')
        result = self.execute(); self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((sibling / 'blocked').exists())

    def test_timeout_record(self):
        module = self.transactions / 'tx-bookmark/transaction.py'
        module.write_text('import time\ndef bookmark(page_file: str, raw_input: str) -> dict:\n    time.sleep(3)\n    return {}\n')
        completed = self.execute(extra=('--timeout', '0.3'))
        self.assertNotEqual(completed.returncode, 0)
        record = json.loads((self.transactions / 'tx-bookmark/logs/run.log').read_text())
        self.assertEqual(record['error']['code'], 'runner_timeout')
        self.assertIsNone(record['output'])


class ArticleIntegration(unittest.TestCase):
    def setUp(self):
        IsolatedIntegration.setUp(self)
        shutil.copytree(runner.ROOT / 'tx-publish-article', self.transactions / 'tx-publish-article',
                        ignore=shutil.ignore_patterns('logs', '__pycache__'))
        self.url = 'https://example.com/story'
        self.page_id = hashlib.sha256(self.url.encode()).hexdigest()

    def execute_article(self, text='Article text.', url=None):
        article = f'# [Title]({url or self.url})\n\n{text}\n\n*Published: 22 October 2026*'
        metadata = self.project / 'tools/tool-webpage-og-crawler/output' / ('a' * 64 + '.txt')
        markdown = self.project / 'skills/skill-article-writer/output' / ('b' * 64 + '.txt')
        metadata.parent.mkdir(parents=True, exist_ok=True)
        markdown.parent.mkdir(parents=True, exist_ok=True)
        metadata.write_text(json.dumps({'page_id': self.page_id}))
        markdown.write_text(article)
        value = {'page_id_file': str(metadata), 'article_file': str(markdown), 'raw_input': 'Publish ' + text}
        completed = subprocess.run([str(runner.PYTHON), '-B', str(self.transactions / 'runner.py'),
                                   '--transaction', 'tx-publish-article', '--input', json.dumps(value)],
                                  capture_output=True, text=True, cwd=self.project, timeout=20)
        return completed, article

    def test_replace_mismatch_and_logging(self):
        first, article = self.execute_article()
        self.assertEqual(first.returncode, 0, first.stderr)
        result = json.loads(first.stdout)
        self.assertEqual(result['output'], [f'data/articles/example_com/{self.page_id}.md'])
        target = self.project / result['output'][0]
        self.assertEqual(target.read_text(), article + '\n\nSource Page ID: ' + self.page_id + '\n\n' + runner.signature_markdown(runner.source_code_signature(self.transactions / 'tx-publish-article')))
        replaced, updated = self.execute_article('Replacement text.')
        self.assertEqual(replaced.returncode, 0, replaced.stderr)
        expected = updated + '\n\nSource Page ID: ' + self.page_id + '\n\n' + runner.signature_markdown(runner.source_code_signature(self.transactions / 'tx-publish-article'))
        self.assertEqual(target.read_text(), expected)
        mismatch, _ = self.execute_article('Mismatch', url='https://example.com/other')
        rejected = json.loads(mismatch.stdout)
        self.assertEqual(rejected['error']['code'], 'page_id_mismatch')
        self.assertEqual(target.read_text(), expected)
        records = [json.loads(line) for line in (self.transactions / 'tx-publish-article/logs/run.log').read_text().splitlines()]
        self.assertEqual(records[0]['output'], result['output'])
        self.assertIsNone(records[-1]['output'])
        self.assertFalse((self.project / 'data/publish-article').exists())

    def test_alias_target_rejected(self):
        owned = self.project / 'data/articles/example_com'
        owned.mkdir(parents=True)
        outside = self.project / 'outside'; outside.write_text('keep')
        (owned / (self.page_id + '.md')).symlink_to(outside)
        failed, _ = self.execute_article()
        self.assertNotEqual(failed.returncode, 0)
        self.assertEqual(outside.read_text(), 'keep')

    def test_source_validation_precedes_payload_validation(self):
        first, _ = self.execute_article()
        self.assertEqual(first.returncode, 0, first.stderr)
        metadata = self.project / 'tools/tool-webpage-og-crawler/output' / ('a' * 64 + '.txt')
        article = self.project / 'skills/skill-article-writer/output' / ('b' * 64 + '.txt')
        metadata.write_text('{malformed')
        outside = self.project / 'outside.txt'
        outside.write_text('unrelated')
        cases = [
            (metadata, outside),
            (article, metadata),
        ]
        alias = article.parent / ('c' * 64 + '.txt')
        alias.symlink_to(article)
        cases.append((metadata, alias))
        for index, (page, body) in enumerate(cases):
            value = {'page_id_file': str(page), 'article_file': str(body),
                     'raw_input': 'Reject source ' + str(index)}
            completed = subprocess.run(
                [str(runner.PYTHON), '-B', str(self.transactions / 'runner.py'),
                 '--transaction', 'tx-publish-article', '--input', json.dumps(value)],
                capture_output=True, text=True, cwd=self.project, timeout=20)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            rejected = json.loads(completed.stdout)
            self.assertEqual(rejected['status'], 'error')
            self.assertEqual(rejected['error']['code'], 'invalid_input_source')
        self.assertEqual(outside.read_text(), 'unrelated')

    def test_mapping_is_exclusive(self):
        self.assertEqual(runner.owned_data_name('tx-publish-article'), 'articles')
        self.assertEqual(runner.owned_data_name('tx-bookmark'), 'bookmark')
        with self.assertRaises(ValueError):
            runner.prepare_data('tx-articles', self.project / 'data')
        good = {'input': {'raw_input': 'x', 'processed_input': {}},
                'output': [f'data/articles/example_com/{self.page_id}.md'], 'output_format': 'markdown',
                'status': 'ok', 'error': None, 'meta_data': {}}
        runner.validate_output(good, 'tx-publish-article')
        for path in ('data/bookmark/a.md', 'data/publish-article/a.md', 'data/articles/../a.md'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                runner.validate_output(dict(good, output=[path]), 'tx-publish-article')


if __name__ == '__main__':
    unittest.main()
