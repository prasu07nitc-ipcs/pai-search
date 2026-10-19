"""Persistence regression tests; all session data stays in temporary folders."""
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from store import Conflict, Store, atomic_json


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        form = self.root / 'form-test'
        form.mkdir()
        for name in ('form.html', 'form.js', 'form.css'):
            (form / name).write_text('')
        self.store = Store(self.root)
        self.session = self.store.create('form-test', 'Test', {'name': ''})
        self.id = self.session['meta_data']['execution_id']

    def action(self, revision, data, name='save_draft', action_id='a1'):
        return self.store.action('form-test', self.id, {'expected_revision': revision,
            'data': data, 'action_name': name, 'action_id': action_id})

    def test_history_output_and_restart(self):
        self.action(0, {'name': 'Jane', 'rows': [None, False, 0, '']})
        final = self.action(1, {'name': 'Janet'}, action_id='a2')
        restarted = Store(self.root)
        self.assertEqual(restarted.read('form-test', self.id), final)
        self.assertEqual(restarted.snapshot('form-test', self.id, 0)['data'], {'name': ''})
        self.assertEqual(restarted.snapshot('form-test', self.id, 1)['data']['rows'], [None, False, 0, ''])
        self.assertEqual(restarted.snapshot('form-test', self.id, 2)['data'], {'name': 'Janet'})
        self.assertEqual(json.loads((self.root / final['output']).read_text()), final)
        self.assertFalse((self.root / 'form-test' / 'metadata').exists())
        self.assertEqual(set(final), {'input', 'output', 'output_format', 'status', 'error', 'meta_data'})

    def test_idempotent_retry_and_stale_update(self):
        value = self.action(0, {'name': 'Jane'})
        self.assertEqual(self.action(0, {'name': 'Jane'}), value)
        with self.assertRaises(Conflict):
            self.action(0, {'name': 'Other'}, action_id='a2')
        with self.assertRaises(Conflict):
            self.action(0, {'name': 'Other'})

    def test_concurrent_actions_accept_exactly_one_revision(self):
        def update(index):
            try:
                self.action(0, {'name': str(index)}, action_id=f'a{index}')
                return True
            except Conflict:
                return False
        with ThreadPoolExecutor(max_workers=4) as executor:
            self.assertEqual(sum(executor.map(update, range(4))), 1)

    def test_submission_freezes_session_and_is_retryable(self):
        value = self.action(0, {'name': 'Jane'}, 'submit')
        self.assertEqual(value['meta_data']['execution_state'], 'submitted')
        self.assertEqual(self.action(0, {'name': 'Jane'}, 'submit'), value)
        with self.assertRaises(Conflict):
            self.action(1, {'name': 'Other'}, action_id='a2')

    def test_rejected_submit_remains_editable_and_retry_checks_outcome(self):
        request = {'expected_revision': 0, 'data': {'name': ''},
                   'action_name': 'submit', 'action_id': 'rejected', 'outcome': 'rejected'}
        value = self.store.action('form-test', self.id, request)
        self.assertEqual(value['meta_data']['execution_state'], 'in_progress')
        self.assertEqual(value['meta_data']['action_log'][0]['outcome'], 'rejected')
        self.assertEqual(self.store.action('form-test', self.id, request), value)
        with self.assertRaises(Conflict):
            self.store.action('form-test', self.id, {**request, 'outcome': 'accepted'})
        self.action(1, {'name': 'Jane'}, action_id='draft')
        final = self.action(2, {'name': 'Jane'}, 'submit', action_id='submitted')
        self.assertEqual(final['meta_data']['execution_state'], 'submitted')

    def test_failed_write_preserves_previous_revision(self):
        import store
        original = store.atomic_json
        def fail_write(path, value):
            if path.suffix == '.txt':
                raise OSError('disk interrupted')
            return original(path, value)
        with patch('store.atomic_json', side_effect=fail_write):
            with self.assertRaises(OSError):
                self.action(0, {'name': 'Updated'})
        self.assertEqual(self.store.read('form-test', self.id), self.session)
        restored = self.action(0, {'name': 'Updated'})
        self.assertEqual(restored['meta_data']['revision'], 1)
        self.assertEqual(json.loads((self.root / restored['output']).read_text()), restored)

    def test_migration_preserves_history_and_is_repeatable(self):
        value = self.action(0, {'name': 'Ram', 'phone_number': '92939'})
        legacy = self.root / 'form-test' / 'metadata'
        legacy.mkdir()
        source = legacy / f'{self.id}.json'
        source.write_text(json.dumps(value))
        output = self.root / value['output']
        output.write_text(json.dumps(value['meta_data']['current_data']))
        self.assertEqual(self.store.migrate(), 1)
        self.assertFalse(legacy.exists())
        self.assertEqual(self.store.read('form-test', self.id), value)
        self.assertEqual(self.store.snapshot('form-test', self.id, 0)['data'], {'name': ''})
        self.assertEqual(self.store.migrate(), 0)
        # Resume after a crash following output replacement, before legacy removal.
        legacy.mkdir()
        source.write_text(json.dumps(value))
        self.assertEqual(self.store.migrate(), 1)

    def test_migration_keeps_source_if_write_fails_or_output_conflicts(self):
        legacy = self.root / 'form-test' / 'metadata'
        legacy.mkdir()
        source = legacy / f'{self.id}.json'
        source.write_text(json.dumps(self.session))
        with patch('store.atomic_json', side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):
                self.store.migrate()
        self.assertTrue(source.exists())
        changed = self.action(0, {'name': 'Newer'})
        with self.assertRaises(Conflict):
            self.store.migrate()
        self.assertTrue(source.exists())
        self.assertEqual(self.store.read('form-test', self.id), changed)

    def test_sessions_are_independent(self):
        other = self.store.create('form-test', '', {'name': 'Other'})
        self.action(0, {'name': 'Jane'})
        self.assertEqual(self.store.read('form-test', other['meta_data']['execution_id']), other)

    def test_traversal_symlinks_and_nonfinite_rejected(self):
        with self.assertRaises(ValueError):
            self.store.form('../tools')
        with self.assertRaises(ValueError):
            self.store.read('form-test', '../bad')
        output = self.root / self.session['output']
        output.unlink()
        output.symlink_to(self.root / 'outside')
        with self.assertRaises(ValueError):
            self.store.read('form-test', self.id)
        with self.assertRaises(ValueError):
            atomic_json(self.root / 'bad.json', {'value': float('nan')})


if __name__ == '__main__':
    unittest.main()
