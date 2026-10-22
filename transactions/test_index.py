"""Index integration checks in disposable projects only."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import unittest

import runner
import test_runner


class IndexIntegration(unittest.TestCase):
    def setUp(self):
        test_runner.IsolatedIntegration.setUp(self)
        shutil.copytree(runner.ROOT / 'tx-index', self.transactions / 'tx-index',
                        ignore=shutil.ignore_patterns('logs', '__pycache__'))
        self.url = 'https://www.example.com/story'
        self.page_id = hashlib.sha256(self.url.encode()).hexdigest()
        self.source = self.project / 'tools/tool-webpage-og-crawler/output' / ('a'*64 + '.txt')
        self.context = self.project / 'skills/skill-context-encoder/output' / ('b'*64 + '.txt')
        for path in (self.source, self.context):
            path.parent.mkdir(parents=True)
        self.source.write_text(json.dumps({'url':self.url,'page_id':self.page_id,
                                          'dateModified':'2099-01-01T00:00:00Z'}))
        self.context.write_text(json.dumps([self.item('Delhi Police',1),self.item('Delhi Police',2),
                                           self.item('Other Entity',3),self.item('!!!',4)]))

    @staticmethod
    def item(name,seq):
        return {'entity_name':name,'named_entity':True,'entity_category':'Organization',
                'entity_utternace':'I provide a service.','seq_number':seq}

    def execute(self, raw='Index page', extra=()):
        value={'page_file':str(self.source),'context_file':str(self.context),'raw_input':raw}
        return subprocess.run([str(runner.PYTHON),'-B',str(self.transactions/'runner.py'),
                               '--transaction','tx-index','--input',json.dumps(value),*extra],
                              capture_output=True,text=True,cwd=self.project,timeout=30)

    def test_layout_replacement_and_confirmation(self):
        first=self.execute()
        self.assertEqual(first.returncode,0,first.stderr)
        result=json.loads(first.stdout)
        self.assertEqual(result['status'],'ok',result)
        self.assertEqual(len(result['output']),3)
        self.assertEqual(result['meta_data']['skipped_utterances'],0)
        target=self.project/f'data/index/Delhi Police/www_example_com/{self.page_id}.md'
        text=target.read_text()
        self.assertIn('# Delhi Police\n',text)
        self.assertIn('Sequence: 1/4',text)
        self.assertIn('Last Validated At: 2099-01-01T00:00:00+00:00',text)
        duplicate=self.execute()
        self.assertNotEqual(duplicate.returncode,0)
        again=self.execute(extra=('--rerun',))
        self.assertEqual(again.returncode,0,again.stderr)
        text=target.read_text()
        self.assertEqual(text.count('# Delhi Police\n'),1)
        self.assertEqual(text.count('## Source Page ID: '+self.page_id),1)
        self.assertEqual(text.count('Sequence: 1/4'),1)
        self.assertEqual(text.count('Indexed At:'),2)
        self.assertFalse((self.project/'data/index/_pages').exists())

    def test_validation_failure_can_be_corrected(self):
        self.context.write_text('[]')
        self.assertEqual(json.loads(self.execute().stdout)['status'], 'error')
        self.context.write_text(json.dumps([self.item('Fixed',1)]))
        self.assertEqual(json.loads(self.execute().stdout)['status'], 'ok')

    def test_invalid_names_fail_without_writes(self):
        for name in ('..', 'a/b', 'a\x00b', 'x' * 300):
            self.context.write_text(json.dumps([self.item(name,1)]))
            result = json.loads(self.execute(raw=name).stdout)
            self.assertEqual(result['error']['code'], 'output_write_error')
            self.assertEqual(list((self.project/'data/index').rglob('*.md')), [])

    def test_case_alias_fails(self):
        self.context.write_text(json.dumps([self.item('Delhi Police',1), self.item('delhi police',2)]))
        result = self.execute()
        payload = json.loads(result.stdout)
        # Case-sensitive filesystems can preserve both names independently.
        if payload['status'] == 'ok':
            self.assertEqual(len(payload['output']), 2)
        else:
            self.assertEqual(payload['error']['code'], 'output_write_error')

    def test_distinct_pages_coexist(self):
        self.assertEqual(self.execute().returncode, 0)
        second_url = 'https://www.example.com/another'
        second_id = hashlib.sha256(second_url.encode()).hexdigest()
        self.source.write_text(json.dumps({'url': second_url, 'page_id': second_id}))
        self.assertEqual(self.execute(raw='Another page').returncode, 0)
        folder = self.project/'data/index/Delhi Police/www_example_com'
        self.assertEqual({p.stem for p in folder.glob('*.md')}, {self.page_id, second_id})

    def test_partial_failure_recovers_without_duplicates(self):
        module=self.transactions/'tx-index/transaction.py'
        with module.open('a') as stream:
            stream.write("\n_original_update = _update\n_count = 0\n"
                         "def _update(*args):\n"
                         "    global _count\n"
                         "    _count += 1\n"
                         "    if _count == 2:\n"
                         "        raise OSError('Injected second write failure')\n"
                         "    return _original_update(*args)\n")
        failed=self.execute()
        result=json.loads(failed.stdout)
        self.assertEqual(result['error']['code'],'output_write_error')
        self.assertIsNone(result['output'])
        paths=result['meta_data']['affected_paths']
        self.assertEqual(len(paths),1)
        self.assertTrue((self.project/paths[0]).is_file())
        original = (self.project/paths[0]).read_text()
        module.write_text(module.read_text().split('\n_original_update = _update')[0])
        recovered = self.execute()
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertEqual((self.project/paths[0]).read_text(), original)

    def test_interrupted_attempt_recovers_timestamp(self):
        logs = self.transactions / 'tx-index/logs'
        logs.mkdir()
        hashes = [hashlib.sha256(p.read_bytes()).hexdigest() for p in (self.source, self.context)]
        identity = hashlib.sha256(json.dumps(['replacement-v1', hashes]).encode()).hexdigest()
        stamp = '2026-10-21T10:00:00+05:30'
        (logs/'index-attempts.jsonl').write_text(json.dumps({
            'identity': identity, 'state': 'started', 'indexed_at': stamp})+'\n')
        result = self.execute()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['meta_data']['indexed_at'], stamp)

    def test_kernel_source_reads_are_read_only_and_scoped(self):
        blocked = self.project / 'skills/skill-article-writer/output/blocked.txt'
        blocked.parent.mkdir(parents=True)
        blocked.write_text('private')
        module = self.transactions / 'tx-index/transaction.py'
        with module.open('a') as stream:
            stream.write("""
_original_update = _update
def _update(*args):
    project = Path(os.environ['PROJECT_TRANSACTION_INPUT_ROOT'])
    source = project / 'tools/tool-webpage-og-crawler/output' / ('a'*64 + '.txt')
    blocked = project / 'skills/skill-article-writer/output/blocked.txt'
    source.read_text()
    try:
        blocked.read_text()
    except PermissionError:
        pass
    else:
        raise RuntimeError('Unauthorized producer read')
    try:
        source.write_text('overwrite')
    except PermissionError:
        pass
    else:
        raise RuntimeError('Source write was allowed')
    return _original_update(*args)
""")
        result = self.execute()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'ok')
        self.assertEqual(json.loads(self.source.read_text())['page_id'], self.page_id)

    def test_concurrent_updates_serialize(self):
        command=[str(runner.PYTHON),'-B',str(self.transactions/'runner.py'),
                 '--transaction','tx-index']
        processes=[]
        for n in range(2):
            value={'page_file':str(self.source),'context_file':str(self.context),'raw_input':'Concurrent '+str(n)}
            processes.append(subprocess.Popen(command+['--input',json.dumps(value)],
                             stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,cwd=self.project))
        for process in processes:
            stdout,stderr=process.communicate(timeout=30)
            self.assertEqual(process.returncode,0,stderr)
            self.assertEqual(json.loads(stdout)['status'],'ok')
        text=(self.project/f'data/index/Delhi Police/www_example_com/{self.page_id}.md').read_text()
        self.assertEqual(text.count('Sequence: 1/4'),1)


if __name__=='__main__':
    unittest.main()
