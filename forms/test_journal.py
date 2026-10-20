"""Submission-only journal checks against temporary storage."""
import json
import unittest
from unittest.mock import patch
from test_store import StoreTests
from store import Conflict, Store
from journal import META_FIELDS

class JournalTests(unittest.TestCase):
    setUp = StoreTests.setUp
    action = StoreTests.action

    def records(self):
        path = self.root / 'form-test/logs/run.log'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def test_only_submission_logged_and_retry_deduplicated(self):
        self.assertEqual(self.records(), [])
        self.action(0, {'name': 'Jane'})
        self.action(1, {'name': 'Jane'}, 'reader', 'reader1')
        self.assertEqual(self.records(), [])
        value = self.action(2, {'name': 'Jane'}, 'submit', 'submit1')
        self.action(2, {'name': 'Jane'}, 'submit', 'submit1')
        self.store.read('form-test', self.id)
        records = self.records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['meta_data'], {k: value['meta_data'][k] for k in META_FIELDS})
        self.assertEqual(records[0]['meta_data']['revision'], 3)
        self.assertEqual(records[0]['run_id'], self.id)
        self.assertEqual(len(value['meta_data']['action_log']), 3)

    def test_recovery_only_backfills_final_submission(self):
        self.action(0, {'name': 'Jane'})
        Store(self.root).recover_logs()
        self.assertEqual(self.records(), [])
        self.action(1, {'name': 'Jane'}, 'submit', 'submit1')
        path = self.root / 'form-test/logs/run.log'
        path.write_text('{"interrupted":')
        restarted = Store(self.root)
        restarted.recover_logs()
        self.assertEqual([r['meta_data']['revision'] for r in self.records()], [2])
        restarted.recover_logs()
        self.assertEqual(len(self.records()), 1)

    def test_append_failure_after_submit_recovers_on_retry(self):
        with patch('store.append_records', side_effect=OSError('log unavailable')):
            with self.assertRaises(OSError):
                self.action(0, {'name': 'Jane'}, 'submit')
        result = self.action(0, {'name': 'Jane'}, 'submit')
        self.assertEqual(result['meta_data']['execution_state'], 'submitted')
        self.assertEqual(len(self.records()), 1)

    def test_failed_and_rejected_submissions_do_not_log(self):
        with patch('store.atomic_json', side_effect=OSError('write failed')):
            with self.assertRaises(OSError):
                self.action(0, {'name': 'Jane'}, 'submit')
        self.assertEqual(self.records(), [])
        self.assertEqual(self.store.read('form-test', self.id), self.session)
        self.store.action('form-test', self.id, {'expected_revision': 0, 'action_id': 'reject',
            'action_name': 'submit', 'outcome': 'rejected', 'data': {'name': ''}})
        Store(self.root).recover_logs()
        self.assertEqual(self.records(), [])

    def test_completed_reads_use_checkpoint_and_recover_deleted_log(self):
        self.action(0, {'name': 'Jane'}, 'submit')
        with patch('store.append_records') as append:
            self.store.read('form-test', self.id)
            append.assert_not_called()
        (self.root / 'form-test/logs/run.log').unlink()
        self.store.read('form-test', self.id)
        self.assertEqual(len(self.records()), 1)

    def test_corrupt_log_fails_closed(self):
        self.action(0, {'name': 'Jane'}, 'submit')
        path = self.root / 'form-test/logs/run.log'
        path.write_text('not-json\n')
        with self.assertRaises(ValueError):
            self.store.read('form-test', self.id)
        self.assertEqual(path.read_text(), 'not-json\n')

del StoreTests
