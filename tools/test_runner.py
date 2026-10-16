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
        (self.directory / 'TOOL.md').write_text('No output directory capability.\n')
        (self.directory / 'tool.py').write_text(
            'def calculate(count: int, *, label: str = "default") -> dict:\n    pass\n'
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
                'output': 'tool-example/outputs/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.txt', 'status': 'ok',
                'error': None, 'output_format': 'json', 'meta_data': {}}
        runner.validate_output(good)
        with self.assertRaisesRegex(ValueError, 'execution run_id'):
            runner.validate_output(good, 'tool-example', 'b' * 64)
        runner.validate_output(dict(good, status='error', output=None,
                                    error={'code': 'failed', 'message': 'Reason'}))
        bad = [{}, {'status': 'ok'}, dict(good, extra=1), dict(good, output=None),
               dict(good, output='/tmp/result.json'), dict(good, output='tool-example/outputs/../result.json'),
               dict(good, output='tool-example/outputs/result.md'),
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
        (self.directory / 'TOOL.md').write_text('Output directory: outputs\n')
        target = self.directory / 'outputs'
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
        result = {'input': {'raw_input': 'calculate', 'processed_input': {'count': 2}}, 'output': 'tool-example/outputs/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.txt', 'status': 'ok', 'error': None, 'output_format': 'json', 'meta_data': {}}
        result['output'] = 'tool-example/outputs/' + hashlib.sha256(b'{"count":2}').hexdigest() + '.txt'
        completed = subprocess.CompletedProcess([], 0, json.dumps(result), 'worker diagnostics\n')
        with patch.object(runner, 'resolve_tool', return_value=(self.directory, 'calculate')), \
             patch.object(runner.subprocess, 'run', return_value=completed) as execute:
            self.assertEqual(runner.invoke('tool-example', {'count': 2}), result)
            command = execute.call_args.args[0]
            self.assertIn('tool-example', command)
            self.assertEqual(execute.call_args.kwargs['timeout'], 20)
            log = self.directory / 'run.log'
            before = log.read_bytes()
            record = json.loads(before)
            self.assertEqual(record['output'], result)
            self.assertEqual(set(record), {'run_id', 'executed_at', 'input', 'output', 'status', 'error'})
            self.assertEqual(record['run_id'], hashlib.sha256(b'{"count":2}').hexdigest())
            runner.invoke('tool-example', {'count': 2}, test_run=True, timeout=5, run_id=record['run_id'])
            self.assertEqual(log.read_bytes(), before)
            self.assertEqual(execute.call_args.kwargs['timeout'], 5)

    def test_production_run_id_is_input_hash_and_preserves_repeated_runs(self):
        result = {'input': {'raw_input': 'calculate', 'processed_input': {}}, 'output': 'tool-example/outputs/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.txt', 'status': 'ok', 'error': None, 'output_format': 'json', 'meta_data': {}}
        def respond(*args, **kwargs):
            payload = json.loads(kwargs['input'])
            result['output'] = f"tool-example/outputs/{payload['run_id']}.txt"
            return subprocess.CompletedProcess([], 0, json.dumps(result), '')
        with patch.object(runner, 'resolve_tool', return_value=(self.directory, 'calculate')), \
             patch.object(runner.subprocess, 'run', side_effect=respond):
            for value in ({'count': 2, 'label': 'தமிழ்'},
                          {'label': 'தமிழ்', 'count': 2},
                          {'count': 3, 'label': 'தமிழ்'}):
                runner.invoke('tool-example', value)
        records = [json.loads(line) for line in (self.directory / 'run.log').read_text().splitlines()]
        self.assertEqual(len(records), 3)
        expected = hashlib.sha256('{"count":2,"label":"தமிழ்"}'.encode('utf-8')).hexdigest()
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
                    runner.invoke('tool-example', {'count': 1})
            record = json.loads((self.directory / 'run.log').read_text().splitlines()[-1])
            self.assertIsNone(record['output'])
            self.assertEqual(record['status'], 'error')
            self.assertEqual(record['run_id'], hashlib.sha256(b'{"count":1}').hexdigest())
            self.assertIn('Worker diagnostics', stream.getvalue())

    def test_no_tool_specific_assertions_in_harness(self):
        packet = {'output': {'input': {'raw_input': 'calculate', 'processed_input': {}}, 'output': 'tool-example/outputs/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.txt', 'status': 'ok', 'error': None, 'output_format': 'json', 'meta_data': {}}, 'failed_checks': []}
        cases = self.directory / 'cases.json'
        cases.write_text(json.dumps([{'case_id': 'generic', 'input': {'count': 1}, 'expected': {'status': 'ok'}}]))
        with patch.object(runner, 'resolve_tool', return_value=(self.directory, 'calculate')), \
             patch.object(runner, 'invoke', return_value=packet), contextlib.redirect_stdout(io.StringIO()):
            runner.run_tests('tool-example', cases, self.directory / 'test-report.log')
        self.assertTrue(json.loads((self.directory / 'test-report.log').read_text())['passed'])
        self.assertFalse((self.directory / 'run.log').exists())


if __name__ == '__main__':
    runner.verify_environment()
    unittest.main()
