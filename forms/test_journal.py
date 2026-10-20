"""Exercise logging only against disposable form/session directories."""
import json
import unittest
from unittest.mock import patch

from test_store import StoreTests
from store import Conflict, Store


class JournalTests(unittest.TestCase):
    setUp = StoreTests.setUp
    action = StoreTests.action

    def records(self):
        return [json.loads(line) for line in (self.root / 'form-test' / 'logs' / 'run.log').read_text().splitlines()]

    def test_flattened_contract_initialization_actions_and_retries(self):
        value = self.action(0, {'name': 'Jane'})
        self.action(0, {'name': 'Jane'})
        self.store.read('form-test', self.id)
        records = self.records()
        self.assertEqual(len(records), 2)
        for record in records:
            self.assertEqual(set(record), {'run_id', 'executed_at', 'input', 'output',
                'output_format', 'status', 'error', 'meta_data'})
            self.assertIsInstance(record['output'], str)
            self.assertEqual(record['run_id'], self.id)
        self.assertEqual(records[0]['meta_data']['revision'], 0)
        self.assertEqual(records[1], {'run_id': self.id,
            'executed_at': value['meta_data']['action_log'][0]['action_time'], **value})

    def test_backfill_missing_log_and_partial_tail(self):
        value = self.action(0, {'name': 'Jane'})
        self.action(1, {'name': 'Janet'}, action_id='a2')
        path = self.root / 'form-test' / 'logs' / 'run.log'
        path.write_text(path.read_text().splitlines()[0] + '\n' + '{"interrupted":')
        restarted = Store(self.root)
        restarted.recover_logs()
        records = self.records()
        self.assertEqual([r['meta_data']['revision'] for r in records], [0, 1, 2])
        self.assertEqual(records[1]['meta_data'], value['meta_data'])
        restarted.recover_logs()
        self.assertEqual(self.records(), records)

    def test_append_failure_after_commit_recovers_on_retry(self):
        import store
        original = store.append_records
        def fail_new_record(path, records):
            records = list(records)
            if any(r['meta_data']['revision'] == 1 for r in records):
                raise OSError('log unavailable')
            return original(path, records)
        with patch('store.append_records', side_effect=fail_new_record):
            with self.assertRaises(OSError):
                self.action(0, {'name': 'Jane'})
        result = self.action(0, {'name': 'Jane'})
        self.assertEqual(result['meta_data']['revision'], 1)
        self.assertEqual(len(self.records()), 2)

    def test_storage_failure_logged_without_changing_output(self):
        with patch('store.atomic_json', side_effect=OSError('write failed')):
            with self.assertRaises(OSError):
                self.action(0, {'name': 'Jane'})
        failure = self.records()[-1]
        self.assertEqual(failure['status'], 'error')
        self.assertEqual(failure['error']['code'], 'STORAGE_ERROR')
        self.assertEqual(failure['meta_data']['current_data'], {'name': ''})
        self.assertEqual(failure['meta_data']['failed_action']['data'], {'name': 'Jane'})
        self.assertEqual(self.store.read('form-test', self.id), self.session)

    def test_pre_execution_rejection_is_not_logged(self):
        with self.assertRaises(Conflict):
            self.action(99, {'name': 'Stale'})
        self.assertEqual(len(self.records()), 1)

    def test_corrupt_complete_line_and_symlink_fail_closed(self):
        path = self.root / 'form-test' / 'logs' / 'run.log'
        path.write_text('not-json\n')
        with self.assertRaises(ValueError):
            self.store.read('form-test', self.id)
        self.assertEqual(path.read_text(), 'not-json\n')
        path.unlink()
        path.symlink_to(self.root / 'outside')
        with self.assertRaises(ValueError):
            self.store.read('form-test', self.id)


del StoreTests
