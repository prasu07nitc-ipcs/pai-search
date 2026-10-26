"""File lifecycle and consumer enforcement tests. Temporary files; no live grants/Git."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


f = load('grant_framework', ROOT / 'authorizations/framework.py')
c = load('grant_consumer', ROOT / 'data/tx-commit-and-push/authorization.py')
d = load('data_runner', ROOT / 'data/runner.py')


class Grants(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        component = self.root / 'authorizations' / f.NAME
        component.mkdir(parents=True)
        (component / 'authorization.py').write_text((ROOT / 'authorizations' / f.NAME / 'authorization.py').read_text())
        task = self.root / 'tasks/task-example'
        task.mkdir(parents=True)
        (task / 'TASK.md').write_text('# task-example')
        self.store = f.Store(self.root)
        self.environment = patch.dict(os.environ, {'CODEX_THREAD_ID':'chat-one'})
        self.environment.start()
        self.framework_module = patch.dict(sys.modules, {'framework':f})
        self.framework_module.start()
        self.runner = load('grant_runner', ROOT / 'authorizations/runner.py')
        self.page = 'a' * 64
        self.live = {'branch':'data-test','remote_url':'git@github.com:prasu07nitc-ipcs/pai-search.git',
                     'author_name':'pai-search-agent','author_email':'psa@sayujai.com',
                     'create_branch':False,'expected_head':'b'*40}

    def tearDown(self):
        self.framework_module.stop()
        self.environment.stop()
        self.temp.cleanup()

    def request(self):
        return self.store.execute(f.NAME, f.session_id())[0]

    def decision(self, record, choice='approve'):
        return {'request_id':record['Grant ID'],'token':record['Request token'],'decision':choice,
                'approved_by':'human user','source':'chat/message:yes'}

    def approve(self):
        record = self.request()
        return self.store.execute(f.NAME, f.session_id(), self.decision(record))[0]

    def operation(self):
        return {'action':'commit-and-push','page_id':self.page,
                'files':[f'articles/example/{self.page}/article.md'],
                'message':'data: index webpage '+self.page,**self.live,'base_commit':None}

    def verify(self, record):
        return c.verify(self.root,str(self.store.path(f.NAME)),record['Grant ID'],self.operation(),self.live)

    def test_complete_markdown_request_approval_and_cached_reuse(self):
        result = self.runner.execute(self.store,'task-example',f.NAME)
        self.assertEqual(set(result),{'input','output','output_format','status','error','meta_data'})
        self.assertEqual(result['error']['code'],'approval_required')
        self.assertEqual(result['output_format'],'markdown')
        record = self.store.read(f.NAME)
        self.assertEqual(record['Status'],'pending')
        self.assertIsNone(record['Granted at'])
        accepted = self.runner.execute(self.store,'task-example',f.NAME,self.decision(record))
        self.assertEqual(accepted['status'],'ok')
        text = self.store.path(f.NAME).read_text()
        self.assertTrue(text.startswith('# Authorisation grant\n'))
        with patch.object(f,'adapter',side_effect=AssertionError('Cache must not resolve new terms')):
            reused = self.runner.execute(self.store,'task-example',f.NAME)
        self.assertTrue(reused['meta_data']['cache_hit'])
        self.assertEqual(reused['output'],accepted['output'])
        self.assertEqual(self.store.path(f.NAME).read_text(),text)

    def test_no_runtime_permission_overrides(self):
        with self.assertRaises(TypeError):
            self.store.execute(f.NAME,'chat-one',ttl=3600)
        result = subprocess.run([sys.executable,'-B',str(ROOT/'authorizations/runner.py'),'execute',
                                 '--task','task-webpage-index','--authorization',f.NAME,'--input','{}'],capture_output=True,text=True)
        self.assertEqual(result.returncode,2)
        self.assertIn('unrecognized arguments',result.stderr)

    def test_missing_platform_chat_identity_fails_before_write(self):
        with patch.dict(os.environ,{},clear=True),self.assertRaises(ValueError):
            self.runner.execute(self.store,'task-example',f.NAME)
        self.assertFalse(self.store.path(f.NAME).exists())

    def test_unknown_task_cannot_execute(self):
        for task in ('tx-bookmark','task-missing','../task-example'):
            with self.subTest(task=task),self.assertRaises((ValueError,OSError)):
                self.runner.execute(self.store,task,f.NAME)
        self.assertFalse(self.store.path(f.NAME).exists())

    def test_other_session_blocked_for_pending_and_active_grants(self):
        pending = self.request()
        with self.assertRaises(f.AuthorizationError) as error:
            self.store.execute(f.NAME,'chat-two')
        self.assertEqual(error.exception.code,'authorization_session_conflict')
        self.approve()
        with self.assertRaises(f.AuthorizationError):
            self.store.execute(f.NAME,'chat-two')
        self.assertEqual(self.store.read(f.NAME)['Grant ID'],pending['Grant ID'])

    def test_reservation_expiry_allows_other_session(self):
        record = self.request()
        with patch.object(f,'now',return_value=f.seconds(record['Approval deadline'])):
            next_record,_ = self.store.execute(f.NAME,'chat-two')
        self.assertEqual(next_record['Session ID'],'chat-two')
        with self.assertRaises(ValueError):
            self.store.execute(f.NAME,'chat-one',self.decision(record))

    def test_wrong_token_and_wrong_session_cannot_approve(self):
        record = self.request()
        decision = self.decision(record)
        decision['token'] = 'wrong'
        with self.assertRaises(ValueError): self.store.execute(f.NAME,'chat-one',decision)
        with self.assertRaises(ValueError): self.store.execute(f.NAME,'chat-two',self.decision(record))
        self.assertEqual(self.store.read(f.NAME)['Status'],'pending')

    def test_expired_request_cannot_be_approved(self):
        record = self.request()
        with patch.object(f,'now',return_value=f.seconds(record['Approval deadline'])),self.assertRaises(ValueError):
            self.store.execute(f.NAME,'chat-one',self.decision(record))

    def test_decline_releases_reservation(self):
        record = self.request()
        result = self.runner.execute(self.store,'task-example',f.NAME,self.decision(record,'decline'))
        self.assertEqual(result['error']['code'],'authorization_declined')
        next_record,_ = self.store.execute(f.NAME,'chat-two')
        self.assertEqual(next_record['Session ID'],'chat-two')

    def test_grant_expiry_allows_new_session_without_implicit_approval(self):
        record = self.approve()
        with patch.object(f,'now',return_value=f.seconds(record['Expires at'])):
            replacement,cached = self.store.execute(f.NAME,'chat-two')
        self.assertFalse(cached)
        self.assertEqual(replacement['Status'],'pending')
        self.assertNotEqual(replacement['Grant ID'],record['Grant ID'])

    def test_revocation_updates_same_file_and_blocks_consumer(self):
        record = self.approve()
        self.verify(record)
        self.store.revoke(f.NAME,record['Grant ID'],'chat/message:revoke')
        self.assertEqual(self.store.read(f.NAME)['Status'],'revoked')
        with self.assertRaises(ValueError): self.verify(record)
        replacement,_ = self.store.execute(f.NAME,'chat-two')
        self.assertEqual(replacement['Status'],'pending')

    def test_stale_revocation_cannot_revoke_replacement(self):
        record = self.approve()
        self.store.revoke(f.NAME,record['Grant ID'],'human revocation')
        self.store.execute(f.NAME,'chat-two')
        with self.assertRaises(ValueError): self.store.revoke(f.NAME,record['Grant ID'],'stale revocation')

    def test_definition_change_does_not_invalidate_or_extend_approved_terms(self):
        record = self.approve()
        definition = self.root/'authorizations'/f.NAME/'authorization.py'
        definition.write_text("def definition(project):\n return {'Duration seconds': 10}\n")
        reused,cached = self.store.execute(f.NAME,'chat-one')
        self.assertTrue(cached)
        self.assertEqual(reused,record)
        self.verify(record)

    def test_consumer_reads_file_without_authorisation_calls_or_writes(self):
        record = self.approve()
        before = self.store.path(f.NAME).read_bytes()
        with patch.object(f.Store,'execute',side_effect=AssertionError()),patch.object(f.Store,'read',side_effect=AssertionError()):
            self.verify(record)
            self.verify(record)
        self.assertEqual(self.store.path(f.NAME).read_bytes(),before)

    def test_consumer_rejects_wrong_session_id_and_stale_grant_id(self):
        record = self.approve()
        with patch.dict(os.environ,{'CODEX_THREAD_ID':'chat-two'}),self.assertRaises(ValueError): self.verify(record)
        changed = dict(record);changed['Grant ID']='c'*32
        with self.assertRaises(ValueError): self.verify(changed)

    def test_consumer_rejects_expired_and_future_grant(self):
        record = self.approve()
        path = self.store.path(f.NAME)
        for granted in (0, f.now()+100):
            changed = dict(record)
            changed.update({'Granted at':f.timestamp(granted),'Expires at':f.timestamp(granted+86400)})
            path.write_text(f.render(changed))
            with self.assertRaises(ValueError): self.verify(record)

    def test_consumer_rejects_operation_scope_mismatches(self):
        record = self.approve()
        for field,value in {'action':'push','branch':'data-prod','remote_url':'git@github.com:other/repo.git',
                            'message':'arbitrary','files':[f'other/example/{self.page}/file'],
                            'create_branch':True,'base_commit':'d'*40,'expected_head':'e'*40}.items():
            operation = self.operation();operation[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):
                c.verify(self.root,str(self.store.path(f.NAME)),record['Grant ID'],operation,self.live)

    def test_existing_branch_advancement_permitted(self):
        record = self.approve()
        self.live['expected_head']='c'*40
        self.verify(record)

    def test_missing_or_malformed_file_fails_closed(self):
        record = self.approve()
        path = self.store.path(f.NAME)
        path.write_text('# granted\n')
        with self.assertRaises(ValueError): self.verify(record)
        with self.assertRaises(ValueError): self.store.execute(f.NAME,'chat-one')
        path.unlink()
        with self.assertRaises(OSError): self.verify(record)

    def test_copy_and_symlink_grants_are_rejected(self):
        record = self.approve()
        path = self.store.path(f.NAME)
        copy = self.root/'copy.md';copy.write_text(path.read_text())
        with self.assertRaises(ValueError): c.verify(self.root,str(copy),record['Grant ID'],self.operation(),self.live)
        path.unlink();path.symlink_to(copy)
        with self.assertRaises(ValueError): self.verify(record)
        with self.assertRaises(ValueError): self.store.execute(f.NAME,'chat-one')

    def test_legacy_store_untouched_and_never_used(self):
        legacy=self.root/'authorizations/.runtime';legacy.mkdir()
        path=legacy/'grants.sqlite3';path.write_bytes(b'legacy-history')
        self.assertEqual(self.request()['Status'],'pending')
        self.assertEqual(path.read_bytes(),b'legacy-history')

    def test_malformed_identity_and_status_are_not_overwritten(self):
        record = self.approve()
        path = self.store.path(f.NAME)
        for key,value in (('Schema version',2),('Status','invented'),('Session ID',None),('Project','relative')):
            changed=dict(record);changed[key]=value
            text=f.render(changed);path.write_text(text)
            with self.subTest(field=key),self.assertRaises(ValueError):
                self.store.execute(f.NAME,'chat-one')
            self.assertEqual(path.read_text(),text)

    def test_audit_failure_does_not_activate_pending_grant(self):
        record = self.request()
        path = self.store.path(f.NAME)
        before = path.read_text()
        with patch.object(f.os,'write',side_effect=OSError('audit unavailable')),self.assertRaises(OSError):
            self.store.execute(f.NAME,'chat-one',self.decision(record))
        self.assertEqual(path.read_text(),before)
        self.assertEqual(path.stat().st_mode & 0o777,0o600)

    def test_cli_failures_keep_six_field_contract(self):
        import contextlib
        import io
        output=io.StringIO()
        arguments=['runner.py','execute','--task','task-example','--authorization',f.NAME]
        with patch.object(self.runner,'Store',return_value=self.store),patch.object(sys,'argv',arguments),patch.dict(os.environ,{},clear=True),contextlib.redirect_stdout(output):
            self.assertEqual(self.runner.main(),2)
        result=json.loads(output.getvalue())
        self.assertEqual(set(result),{'input','output','output_format','status','error','meta_data'})
        self.assertIsNone(result['output'])
        self.assertFalse(self.store.path(f.NAME).exists())

    def test_concurrent_sessions_have_only_one_pending_owner(self):
        code = '''import importlib.util,sys
from pathlib import Path
spec=importlib.util.spec_from_file_location('f',sys.argv[1]);f=importlib.util.module_from_spec(spec);spec.loader.exec_module(f)
try:
 record,cached=f.Store(Path(sys.argv[2])).execute(f.NAME,sys.argv[3]);print('reserved')
except f.AuthorizationError as exc:print(exc.code)
'''
        children=[subprocess.Popen([sys.executable,'-B','-c',code,f.__file__,str(self.root),'chat-'+str(n)],stdout=subprocess.PIPE,stderr=subprocess.PIPE) for n in range(4)]
        results=[child.communicate(timeout=20) for child in children]
        self.assertTrue(all(child.returncode==0 for child in children),results)
        self.assertEqual(sum(out.strip()==b'reserved' for out,err in results),1)
        self.assertEqual(sum(out.strip()==b'authorization_session_conflict' for out,err in results),3)

    def invoke(self, record, worker):
        folder = self.root/'data/tx-commit-and-push';folder.mkdir(parents=True,exist_ok=True)
        (self.root/'.git').mkdir(exist_ok=True)
        with patch.object(d,'ROOT',self.root/'data'),patch.object(d,'verify_environment'),patch.object(d,'validate_input',side_effect=lambda x:x),patch.object(d,'prepare_ssh',return_value={}),patch.object(d,'authorization_adapter',return_value=c),patch.object(d,'inspect_settings',return_value=self.live),patch.object(d,'run_worker_process',worker),patch.object(d,'validate_output'),patch.object(d,'validate_saved_output'):
            return d.invoke(self.operation(),grant_id=record['Grant ID'],execution_id='task:1',grant_file=str(self.store.path(f.NAME)))

    def test_data_runner_validates_before_dispatch_without_settlement(self):
        record = self.approve()
        def worker(*args,**kwargs):
            self.verify(record)
            operation=json.loads(kwargs['input'])['input']
            return subprocess.CompletedProcess(args[0],0,json.dumps({'input':operation,'output':['fake-receipt'],'output_format':'json','status':'ok','error':None,'meta_data':{'committed':True,'pushed':True}}),'')
        before=self.store.path(f.NAME).read_bytes()
        result=self.invoke(record,worker)
        self.assertEqual(result['status'],'ok')
        self.assertEqual(self.store.path(f.NAME).read_bytes(),before)

    def test_data_runner_rejects_revoked_before_worker(self):
        record=self.approve()
        self.store.revoke(f.NAME,record['Grant ID'],'human revoked')
        def worker(*args,**kwargs): self.fail('Worker must not start')
        result=self.invoke(record,worker)
        self.assertEqual(result['error']['code'],'authorization_required')
        self.assertFalse(result['meta_data']['committed'])


if __name__ == '__main__':
    unittest.main()
