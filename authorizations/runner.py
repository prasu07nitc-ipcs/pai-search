"""Execute fixed authorisations as a task; return canonical Markdown file references."""
import argparse
import json
from pathlib import Path
import re
import sys
from framework import AuthorizationError, NAME, Store, canonical, regular, session_id


def task_definition(project, task):
    if not isinstance(task, str) or re.fullmatch(r'task-[a-z0-9]+(?:-[a-z0-9]+)*', task) is None or len(task) >= 64:
        raise AuthorizationError('A canonical task name is required.')
    return regular(project / 'tasks' / task / 'TASK.md')


def envelope(task, name, output=None, error=None, metadata=None):
    return {'input':{'task':task,'authorization':name}, 'output':output,
            'output_format':'markdown', 'status':'error' if error else 'ok',
            'error':error, 'meta_data':metadata or {}}


def execute(store, task, name, decision=None):
    task_definition(store.project, task)
    record, cached = store.execute(name, session_id(), decision)
    error = None
    if record['Status'] != 'active':
        code = 'approval_required' if record['Status'] == 'pending' else 'authorization_declined'
        error = {'code':code, 'message':'Present the complete Markdown request and obtain an explicit human decision.' if code == 'approval_required' else 'Human declined authorisation.'}
    return envelope(task, name, [str(store.path(name).relative_to(store.project))], error,
                    {'cache_hit':cached,'grant_id':record['Grant ID'],'session_id':record['Session ID']})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for command in ('execute', 'revoke'):
        p = commands.add_parser(command)
        p.add_argument('--task', required=True)
        p.add_argument('--authorization', required=True, choices=[NAME])
        if command == 'execute':
            p.add_argument('--decision', help='Already-obtained human decision; exact pending request ID/token and references')
        else:
            p.add_argument('--grant-id', required=True)
            p.add_argument('--source', required=True, help='Explicit human revocation chat/message reference')
    args = parser.parse_args()
    store = Store()
    try:
        task_definition(store.project, args.task)
        session_id()  # Missing platform identity fails before any persistent writes.
        if args.command == 'execute':
            result = execute(store,args.task,args.authorization,json.loads(args.decision) if args.decision else None)
        else:
            record = store.revoke(args.authorization,args.grant_id,args.source)
            result = envelope(args.task,args.authorization,[str(store.path(args.authorization).relative_to(store.project))],
                              metadata={'grant_id':record['Grant ID'],'revoked':True})
    except (ValueError,OSError,RuntimeError) as exc:
        result = envelope(args.task,args.authorization,error={'code':getattr(exc,'code','authorization_error'),'message':str(exc)})
    print(canonical(result))
    return 0 if result['status'] == 'ok' else 2


if __name__ == '__main__':
    sys.exit(main())
