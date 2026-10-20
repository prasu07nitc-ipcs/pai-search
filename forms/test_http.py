import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from runner import make_server


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        folder = Path(cls.temp.name) / 'form-test'
        folder.mkdir()
        for name in ('form.html', 'form.js', 'form.css'):
            (folder / name).write_text('test')
        cls.server = make_server(cls.temp.name, 0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.server.server_port}'
        with urllib.request.urlopen(cls.base + '/runtime/config.json') as response:
            cls.token = json.load(response)['token']

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.temp.cleanup()

    def request(self, path, body=None, headers=None):
        combined = {'X-Forms-Token': self.token, 'Origin': self.base, 'Content-Type': 'application/json'}
        combined.update(headers or {})
        request = urllib.request.Request(self.base + path, headers=combined,
            data=None if body is None else json.dumps(body).encode())
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as response:
            return response.code, response.read()

    def test_full_session_and_snapshot(self):
        status, body = self.request('/api/sessions', {'form': 'form-test', 'initial_data': {'name': ''}})
        self.assertEqual(status, 201)
        execution_id = json.loads(body)['meta_data']['execution_id']
        path = '/api/sessions/form-test/' + execution_id
        status, body = self.request(path + '/actions', {'action_id': 'a1', 'expected_revision': 0,
            'action_name': 'save_draft', 'data': {'name': 'Jane'}})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['meta_data']['revision'], 1)
        status, body = self.request(path + '/snapshot?revision=0')
        self.assertEqual(json.loads(body)['data'], {'name': ''})
        self.assertEqual(self.request(path + '/actions', {'action_id': 'a2', 'expected_revision': 0,
            'action_name': 'save_draft', 'data': {}})[0], 409)
        self.assertEqual(self.request('/form-test/output/' + execution_id + '.txt')[0], 404)
        self.assertEqual(self.request('/form-test/logs/run.log')[0], 404)
        saved = json.loads((Path(self.temp.name) / 'form-test' / 'output' / f'{execution_id}.txt').read_text())
        self.assertEqual(saved['meta_data']['current_data'], {'name': 'Jane'})

    def test_current_view_preserves_full_saved_history_and_default_api(self):
        status, body = self.request('/api/sessions?view=current',
                                    {'form': 'form-test', 'initial_data': {'name': ''}})
        self.assertEqual(status, 201)
        current = json.loads(body)
        path = '/api/sessions/form-test/' + current['meta_data']['execution_id']
        for revision in range(3):
            status, body = self.request(path + '/actions?view=current',
                {'action_id': f'current-{revision}', 'expected_revision': revision,
                 'action_name': 'save_draft', 'data': {'name': 'Jane', 'note': 'x' * 1000}})
            self.assertEqual(status, 200)
        current = json.loads(body)
        full = json.loads(self.request(path)[1])
        self.assertNotIn('action_log', current['meta_data'])
        self.assertEqual(current['meta_data']['current_data'], full['meta_data']['current_data'])
        self.assertEqual(current['meta_data']['revision'], 3)
        self.assertEqual(len(full['meta_data']['action_log']), 3)
        saved = Path(self.temp.name) / full['output']
        self.assertEqual(json.loads(saved.read_text()), full)
        self.assertLess(len(body), len(json.dumps(full).encode()))
        self.assertEqual(self.request(path + '?view=unknown')[0], 400)

    def test_origin_host_and_token(self):
        payload = {'form': 'form-test', 'initial_data': {}}
        for headers in ({'Origin': 'https://example.com'}, {'Host': 'evil.example'}, {'X-Forms-Token': 'bad'}):
            with self.subTest(headers=headers):
                self.assertEqual(self.request('/api/sessions', payload, headers)[0], 403)

    def test_static_routes_and_unknown_forms(self):
        self.assertEqual(self.request('/new/form-test')[0], 200)
        self.assertEqual(self.request('/assets/form-test/form.js')[0], 200)
        self.assertEqual(self.request('/runtime/runtime.js')[0], 200)
        self.assertEqual(self.request('/assets/form-test/../../../store.py')[0], 404)
        self.assertEqual(self.request('/api/sessions', {'form': 'form-absent'})[0], 400)


if __name__ == '__main__':
    unittest.main()
