"""Shared runner regression tests; no project tool implementation is imported."""
import contextlib
import hashlib
import io
import json
import logging
from pathlib import Path
import subprocess
import tempfile
import typing
import unittest
from unittest.mock import patch

import runner


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name).resolve()
        (self.directory / 'logs').mkdir()
        (self.directory / 'TOOL.md').write_text('No output directory capability.\n')
        (self.directory / 'tool.py').write_text(
            'def calculate(count: int, *, label: str = "default", raw_input: str = "calculate") -> dict:\n    pass\n'
        )
        handler = logging.NullHandler()
        runner.LOGGER.addHandler(handler)
        self.addCleanup(runner.LOGGER.removeHandler, handler)
        previous_level = runner.LOGGER.level
        runner.LOGGER.setLevel(logging.INFO)
        self.addCleanup(runner.LOGGER.setLevel, previous_level)

    def test_signature_binding_and_types_without_import(self):
        runner.validate_input(self.directory, 'calculate', {'count': 3})
        for value in ({}, {'count': True}, {'count': '3'}, {'count': 3, 'extra': 1}):
            with self.subTest(value=value), self.assertRaises((TypeError, ValueError)):
                runner.validate_input(self.directory, 'calculate', value)

    def test_shared_contract(self):
        good = {'input': {'raw_input': 'calculate', 'processed_input': {'count': 1}},
                'output': 'tool-example/output/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.txt', 'status': 'ok',
                'error': None, 'output_format': 'json', 'meta_data': {}}
        runner.validate_output(good)
        with self.assertRaisesRegex(ValueError, 'execution run_id'):
            runner.validate_output(good, 'tool-example', 'b' * 64)
        runner.validate_output(dict(good, status='error', output=None,
                                    error={'code': 'failed', 'message': 'Reason'}))
        bad = [{}, {'status': 'ok'}, dict(good, extra=1), dict(good, output=None),
               dict(good, output='/tmp/result.json'), dict(good, output='tool-example/output/../result.json'),
               dict(good, output='tool-example/output/result.md'),
               dict(good, output_format=None), dict(good, output_format=''),
               dict(good, input={'raw_input': 'x', 'processed_input': {}, 'extra': 1}),
               dict(good, input={'raw_input': None, 'processed_input': {}}),
               dict(good, input={'raw_input': 'x', 'processed_input': []}),
               dict(good, meta_data=[]), dict(good, error={}),
               dict(good, status='error', error=None, output=None),
               dict(good, status='error', error={'code': '', 'message': 'Reason'}, output=None),
               dict(good, status='error', error={'code': 'failed', 'message': 'Reason'}),
               dict(good, meta_data={'invalid': float('nan')})]
        for result in bad:
            with self.subTest(result=result), self.assertRaises(ValueError):
                runner.validate_output(result)

    def test_tools_require_original_request(self):
        for tool_name in ('tool-webpage-og-crawler', 'tool-webpage-markdown'):
            directory, entry = runner.resolve_tool(tool_name)
            runner.validate_input(directory, entry, {'url': 'https://example.com/', 'raw_input': 'தமிழ் request'})
            for supplied in ({'url': 'https://example.com/'},
                             {'url': 'https://example.com/', 'raw_input': None}):
                with self.subTest(tool=tool_name, supplied=supplied), self.assertRaises((TypeError, ValueError)):
                    runner.validate_input(directory, entry, supplied)

    def test_composite_parameter_types(self):
        self.assertTrue(runner.matches_type([{'a': 1}], list[dict[str, int]]))
        self.assertFalse(runner.matches_type([{'a': True}], list[dict[str, int]]))
        self.assertTrue(runner.matches_type(None, str | None))
        self.assertFalse(runner.matches_type(True, typing.Literal[1]))

    def test_tool_name_escape_rejected(self):
        for name in ('../outside', '/tmp/tool-example', 'tool-../../escape', 'TOOL-example'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                runner.resolve_tool(name)

    def test_required_validator_contract_without_import(self):
        documents = {
            'TOOL.md': 'Name: tool-example\nDescription: Example capability.\nEntry point: `tool.py:calculate`\nInstructions: [AGENTS.md](AGENTS.md)\n',
            'validator.py': 'def check_result(value: dict, actual: dict, expected: dict) -> list[str]:\n    return []\n',
        }
        with patch.object(runner, 'ROOT', self.directory), \
             patch.object(Path, 'is_file', return_value=True), \
             patch.object(Path, 'read_text', autospec=True, side_effect=lambda path, **kwargs: documents[path.name]):
            self.assertEqual(runner.resolve_tool('tool-example'), (self.directory / 'tool-example', 'calculate'))
            documents['validator.py'] = 'def unrelated():\n    pass\n'
            with self.assertRaisesRegex(ValueError, 'must define check_result'):
                runner.resolve_tool('tool-example')
        with patch.object(runner, 'ROOT', self.directory), \
             patch.object(Path, 'is_file', autospec=True, side_effect=lambda path: path.name != 'validator.py'):
            with self.assertRaisesRegex(ValueError, 'Missing regular tool file: validator.py'):
                runner.resolve_tool('tool-example')

    def test_wrong_environment_rejected(self):
        with patch.object(runner.sys, 'prefix', runner.sys.base_prefix):
            with self.assertRaises(RuntimeError):
                runner.verify_environment()

    def test_output_directory_requires_explicit_capability_and_real_directory(self):
        self.assertIsNone(runner.output_directory(self.directory))
        (self.directory / 'TOOL.md').write_text('Output directory: output\n')
        target = self.directory / 'output'
        self.assertEqual(runner.output_directory(self.directory), target)
        target.symlink_to(self.directory, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'real tool-local'):
            runner.output_directory(self.directory)
        target.unlink()
        target.mkdir()
        (target / 'escape').symlink_to(self.directory)
        with self.assertRaisesRegex(ValueError, 'symlinks'):
            runner.output_directory(self.directory)


    def test_production_output_and_test_isolation(self):
        result = {'input': {'raw_input': 'calculate', 'processed_input': {'count': 2}}, 'output': 'tool-example/output/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.txt', 'status': 'ok', 'error': None, 'output_format': 'json', 'meta_data': {}}
        result['output'] = 'tool-example/output/' + hashlib.sha256(b'{"count":2,"raw_input":"calculate"}').hexdigest() + '.txt'
        completed = subprocess.CompletedProcess([], 0, json.dumps(result), 'worker diagnostics\n')
        with patch.object(runner, 'resolve_tool', return_value=(self.directory, 'calculate')), \
             patch.object(runner.subprocess, 'run', return_value=completed) as execute:
            self.assertEqual(runner.invoke('tool-example', {'count': 2, 'raw_input': 'calculate'}), result)
            command = execute.call_args.args[0]
            self.assertIn('tool-example', command)
            self.assertEqual(execute.call_args.kwargs['timeout'], 20)
            log = self.directory / 'logs' / 'run.log'
            before = log.read_bytes()
            record = json.loads(before)
            self.assertEqual(record['output'], result['output'])
            self.assertEqual(set(record), {'run_id', 'executed_at', 'processed_input', 'raw_input', 'tool_input', 'output', 'output_format', 'status', 'error', 'meta_data'})
            self.assertEqual(record['run_id'], hashlib.sha256(b'{"count":2,"raw_input":"calculate"}').hexdigest())
            runner.invoke('tool-example', {'count': 2, 'raw_input': 'calculate'}, test_run=True, timeout=5, run_id=record['run_id'])
            self.assertEqual(log.read_bytes(), before)
            self.assertEqual(execute.call_args.kwargs['timeout'], 5)

    def test_production_run_id_is_input_hash_and_preserves_repeated_runs(self):
        result = {'input': {'raw_input': 'calculate', 'processed_input': {}}, 'output': 'tool-example/output/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.txt', 'status': 'ok', 'error': None, 'output_format': 'json', 'meta_data': {}}
        def respond(*args, **kwargs):
            payload = json.loads(kwargs['input'])
            result['output'] = f"tool-example/output/{payload['run_id']}.txt"
            return subprocess.CompletedProcess([], 0, json.dumps(result), '')
        with patch.object(runner, 'resolve_tool', return_value=(self.directory, 'calculate')), \
             patch.object(runner.subprocess, 'run', side_effect=respond):
            for value in ({'count': 2, 'label': 'தமிழ்'},
                          {'label': 'தமிழ்', 'count': 2},
                          {'count': 3, 'label': 'தமிழ்'}):
                runner.invoke('tool-example', dict(value, raw_input='calculate'), rerun=True)
        records = [json.loads(line) for line in (self.directory / 'logs' / 'run.log').read_text().splitlines()]
        self.assertEqual(len(records), 3)
        expected = hashlib.sha256('{"count":2,"label":"தமிழ்","raw_input":"calculate"}'.encode('utf-8')).hexdigest()
        self.assertEqual(records[0]['run_id'], expected)
        self.assertEqual(records[1]['run_id'], expected)
        self.assertNotEqual(records[2]['run_id'], expected)

    def test_timeout_and_worker_failure_diagnostics(self):
        for error in (subprocess.TimeoutExpired([], 1, stderr=b'partial diagnostics'),
                      subprocess.CalledProcessError(1, [], stderr='worker failed')):
            stream = io.StringIO()
            handler = logging.StreamHandler(stream)
            runner.LOGGER.addHandler(handler)
            self.addCleanup(runner.LOGGER.removeHandler, handler)
            with patch.object(runner, 'resolve_tool', return_value=(self.directory, 'calculate')), \
                 patch.object(runner.subprocess, 'run', side_effect=error):
                with self.assertRaises(type(error)):
                    runner.invoke('tool-example', {'count': 1, 'raw_input': 'calculate'}, rerun=True)
            record = json.loads((self.directory / 'logs' / 'run.log').read_text().splitlines()[-1])
            self.assertIsNone(record['output'])
            self.assertEqual(record['status'], 'error')
            self.assertEqual(record['run_id'], hashlib.sha256(b'{"count":1,"raw_input":"calculate"}').hexdigest())
            self.assertIn('Worker diagnostics', stream.getvalue())

    def test_duplicate_success_requires_confirmation_before_execution(self):
        value = {'count': 2}
        history = self.directory / 'logs' / 'run.log'
        # Historical successful records without run_id also count.
        history.write_text(json.dumps({'input': value, 'status': 'ok'}) + '\n')
        before = history.read_bytes()
        with patch.object(runner, 'resolve_tool', return_value=(self.directory, 'calculate')), \
             patch.object(runner.subprocess, 'run') as execute:
            with self.assertRaises(runner.DuplicateInputError):
                runner.invoke('tool-example', value)
            execute.assert_not_called()
        self.assertEqual(history.read_bytes(), before)

    def test_duplicate_matching_uses_full_canonical_input_and_ignores_failures(self):
        value = {'count': 2, 'label': 'தமிழ்'}
        digest = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                          ensure_ascii=False).encode()).hexdigest()
        history = self.directory / 'logs' / 'run.log'
        history.write_text(json.dumps({'input': value, 'status': 'error'}) + '\n')
        runner.require_new_input(self.directory, digest)
        history.write_text(json.dumps({'input': dict(reversed(list(value.items()))), 'status': 'ok'}) + '\n')
        with self.assertRaises(runner.DuplicateInputError):
            runner.require_new_input(self.directory, digest)
        runner.require_new_input(self.directory, '0' * 64)

    def test_cli_duplicate_confirmation(self):
        for answer, interactive, calls, exit_code in (
                ('yes', True, 2, None), ('no', True, 1, 0),
                ('', True, 1, 0), ('yes', False, 1, 2)):
            with self.subTest(answer=answer, interactive=interactive), \
                 patch.object(runner.sys, 'argv', ['runner.py', '--tool', 'tool-example', '--input', '{"count":2}']), \
                 patch.object(runner, 'resolve_tool', return_value=(self.directory, 'calculate')), \
                 patch.object(runner.logging, 'basicConfig'), \
                 patch.object(runner.logging, 'FileHandler', return_value=logging.NullHandler()), \
                 patch.object(runner.sys.stdin, 'isatty', return_value=interactive), \
                 patch('builtins.input', return_value=answer), \
                 patch.object(runner, 'invoke', side_effect=[runner.DuplicateInputError('Duplicate'), {}]) as invoke, \
                 contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                if exit_code is None:
                    runner.main()
                    self.assertTrue(invoke.call_args.kwargs['rerun'])
                else:
                    with self.assertRaises(SystemExit) as stopped:
                        runner.main()
                    self.assertEqual(stopped.exception.code, exit_code)
                self.assertEqual(invoke.call_count, calls)

    def test_cli_returns_failure_for_failed_test_assertions(self):
        for passed, expected in ((True, None), (False, 1)):
            with self.subTest(passed=passed), \
                 patch.object(runner.sys, 'argv', ['runner.py', '--tool', 'tool-example', '--cases', 'cases.json']), \
                 patch.object(runner, 'resolve_tool', return_value=(self.directory, 'calculate')), \
                 patch.object(runner.logging, 'basicConfig'), \
                 patch.object(runner.logging, 'FileHandler', return_value=logging.NullHandler()), \
                 patch.object(runner, 'run_tests', return_value=passed):
                if expected is None:
                    runner.main()
                else:
                    with self.assertRaises(SystemExit) as stopped:
                        runner.main()
                    self.assertEqual(stopped.exception.code, expected)

    def test_nested_type_validation_logs_one_operation(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        runner.LOGGER.addHandler(handler)
        try:
            self.assertTrue(runner.matches_type([{'items': list(range(100))}], list[dict[str, list[int]]]))
        finally:
            runner.LOGGER.removeHandler(handler)
        self.assertEqual(stream.getvalue().count('Function matches_type started'), 1)
        self.assertFalse(runner.matches_type([{'items': [True]}], list[dict[str, list[int]]]))

    def test_summary_keeps_complete_reports_and_reports_failed_cases(self):
        packet = {'output': {'input': {'raw_input': 'calculate', 'processed_input': {}},
                  'output': 'tool-example/output/' + 'a' * 64 + '.txt', 'status': 'ok',
                  'error': None, 'output_format': 'json', 'meta_data': {}},
                  'failed_checks': ['Deliberate failure']}
        cases = self.directory / 'cases.json'
        cases.write_text(json.dumps([{'case_id': 'failure', 'input': {'count': 1},
                                      'expected': {'status': 'ok'}}]))
        stream = io.StringIO()
        with patch.object(runner, 'resolve_tool', return_value=(self.directory, 'calculate')), \
             patch.object(runner, 'invoke', return_value=packet), contextlib.redirect_stdout(stream):
            self.assertFalse(runner.run_tests('tool-example', cases,
                self.directory / 'logs' / 'test-report.log', summary=True))
        summary = json.loads(stream.getvalue())
        self.assertEqual(summary['failed_case_ids'], ['failure'])
        self.assertEqual(summary['status'], 'error')
        self.assertEqual(summary['total_cases'], 1)
        full = json.loads((self.directory / 'logs' / 'test-report.log').read_text())
        self.assertEqual(full['failed_checks'], ['Deliberate failure'])
        self.assertEqual(full['actual'], packet['output'])
        self.assertNotIn('actual', summary)

    def test_no_tool_specific_assertions_in_harness(self):
        packet = {'output': {'input': {'raw_input': 'calculate', 'processed_input': {}}, 'output': 'tool-example/output/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.txt', 'status': 'ok', 'error': None, 'output_format': 'json', 'meta_data': {}}, 'failed_checks': []}
        cases = self.directory / 'cases.json'
        cases.write_text(json.dumps([{'case_id': 'generic', 'input': {'count': 1}, 'expected': {'status': 'ok'}}]))
        with patch.object(runner, 'resolve_tool', return_value=(self.directory, 'calculate')), \
             patch.object(runner, 'invoke', return_value=packet), contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(runner.run_tests('tool-example', cases, self.directory / 'logs' / 'test-report.log'))
        self.assertTrue(json.loads((self.directory / 'logs' / 'test-report.log').read_text())['passed'])
        self.assertFalse((self.directory / 'logs' / 'run.log').exists())


if __name__ == '__main__':
    runner.verify_environment()
    unittest.main()
