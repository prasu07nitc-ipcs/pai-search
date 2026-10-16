"""Integration checks through the project runner; never import a tool directly."""
import contextlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import runner


class OutputSandboxTests(unittest.TestCase):
    def test_markdown_content_and_replacement(self):
        directory = runner.ROOT / 'tool-webpage-markdown'
        cases = json.loads((directory / 'test-cases.json').read_text())
        cases.append({'case_id': 'balanced-repeat',
                      'input': {'url': 'https://example.com/', 'raw_input': 'Extract Markdown'},
                      'expected': {'status': 'ok', 'markdown_contains': ['documentation examples']}})
        log = directory / 'run.log'
        before = log.read_bytes() if log.exists() else None
        for case in cases:
            previous = {p.name: p.read_bytes() for p in (directory / 'outputs').glob('*.txt')}
            with tempfile.TemporaryDirectory() as temporary:
                case_path = Path(temporary) / 'cases.json'
                case_path.write_text(json.dumps([case]))
                completed = subprocess.run(
                    [str(runner.PYTHON), '-B', str(runner.ROOT / 'runner.py'),
                     '--tool', directory.name, '--timeout', '60', '--cases', str(case_path)],
                    cwd=runner.ROOT, capture_output=True, text=True, timeout=90, check=True)
            record = json.loads(completed.stdout)
            self.assertTrue(record['passed'], record)
            actual = record['actual']
            self.assertEqual(actual['output_format'], 'markdown')
            if actual['status'] != 'ok':
                self.assertIsNone(actual['output'])
                self.assertEqual({p.name: p.read_bytes() for p in (directory / 'outputs').glob('*.txt')}, previous)
                continue
            self.assertEqual(actual['output'], directory.name + '/outputs/' + record['run_id'] + '.txt')
            target = runner.ROOT / actual['output']
            for name, content in previous.items():
                self.assertEqual((directory / 'outputs' / name).read_bytes(), content)
            self.assertFalse(target.is_symlink())
            content = target.read_text(encoding='utf-8')
            self.assertIn('documentation examples', content)
            if case['input'].get('mode') == 'compare':
                for mode in ('balanced', 'precision', 'recall'):
                    self.assertIn('# ' + mode + '\n\n', content)
            else:
                self.assertNotIn('# balanced\n\n', content)
                self.assertNotIn('# precision\n\n', content)
        self.assertEqual(log.read_bytes() if log.exists() else None, before)

    def test_worker_write_and_read_boundaries(self):
        with contextlib.ExitStack() as stack:
            while True:
                temporary = stack.enter_context(tempfile.TemporaryDirectory(prefix='tool-probe-', dir=runner.ROOT))
                directory = Path(temporary)
                if '_' not in directory.name:
                    break
            (directory / 'TOOL.md').write_text(
                f'Name: {directory.name}\nDescription: Temporary sandbox regression fixture.\n'
                'Entry point: `tool.py:probe() -> dict`\n'
                'Instructions: [AGENTS.md](AGENTS.md)\nOutput directory: outputs\n')
            (directory / 'AGENTS.md').write_text('Temporary regression fixture; no network.\n')
            (directory / 'tool.py').write_text('''
import os
from pathlib import Path

def probe() -> dict:
    root = Path(__file__).resolve().parent
    checks = {}
    output = root / 'outputs' / 'probe.md'
    output.write_text('# Heading\\n\\n**Bold**\\n', encoding='utf-8')
    checks['output_write'] = output.read_text() == '# Heading\\n\\n**Bold**\\n'
    for label, target in [('tool_root', root / 'forbidden'),
                          ('outside', root.parent / 'forbidden'),
                          ('temporary', Path('/private/tmp/forbidden-probe'))]:
        try:
            with target.open('x'):
                pass
        except PermissionError:
            checks[label] = True
        else:
            checks[label] = False
            target.unlink()
    try:
        (root.parent / 'AGENTS.md').read_text()
    except PermissionError:
        checks['unrelated_read'] = True
    else:
        checks['unrelated_read'] = False
    link = root / 'outputs' / 'escape'
    try:
        link.symlink_to(root.parent, target_is_directory=True)
        try:
            (link / 'escape-probe').write_text('forbidden')
        except PermissionError:
            checks['symlink_escape'] = True
        else:
            checks['symlink_escape'] = False
    except PermissionError:
        checks['symlink_escape'] = True
    finally:
        if link.is_symlink():
            link.unlink()
    try:
        os.link(root / 'tool.py', root / 'outputs' / 'hardlink')
    except PermissionError:
        checks['hardlink'] = True
    else:
        checks['hardlink'] = False
    (root / 'outputs' / (os.environ['PROJECT_TOOL_RUN_ID'] + '.txt')).write_text('{}')
    return {'input': {'raw_input': 'sandbox probe', 'processed_input': {}},
            'output': root.name + '/outputs/' + os.environ['PROJECT_TOOL_RUN_ID'] + '.txt', 'status': 'ok', 'error': None,
            'output_format': 'json', 'meta_data': {'checks': checks}}
''')
            (directory / 'validator.py').write_text('''
def check_result(value: dict, actual: dict, expected: dict) -> list[str]:
    return [key for key, passed in actual['meta_data']['checks'].items() if passed is not True]
''')
            cases = directory / 'cases.json'
            cases.write_text(json.dumps([{'case_id': 'boundaries', 'input': {}, 'expected': {'status': 'ok'}}]))
            completed = subprocess.run(
                [str(runner.PYTHON), '-B', str(runner.ROOT / 'runner.py'),
                 '--tool', directory.name, '--cases', str(cases)],
                cwd=runner.ROOT, capture_output=True, text=True, timeout=30, check=True)
            record = json.loads(completed.stdout)
            self.assertTrue(record['passed'], record)
            self.assertFalse((directory / 'run.log').exists())


if __name__ == '__main__':
    runner.verify_environment()
    unittest.main()
