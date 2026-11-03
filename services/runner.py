"""Shared durable queue for service receiver and worker agents (standard library)."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parent


def stamp(ns):
    return None if ns is None else datetime.fromtimestamp(ns / 1e9, timezone.utc).isoformat().replace('+00:00', 'Z')


@contextmanager
def database(service, create=False, readonly=False):
    if sys.prefix == sys.base_prefix or Path(sys.prefix).resolve() != (ROOT / '.venv').resolve():
        raise ValueError('runtime_unavailable: use services/.venv/bin/python')
    if not re.fullmatch(r'service-[a-z0-9]+(?:-[a-z0-9]+)*', service):
        raise ValueError('service_not_found: invalid service name')
    directory = ROOT / service
    if directory.is_symlink() or not (directory / 'SERVICE.md').is_file():
        raise ValueError('service_not_found: missing service contract')
    runtime = directory / 'runtime'
    if runtime.is_symlink():
        raise ValueError('storage_error: aliased runtime')
    path = runtime / 'queue.sqlite3'
    if path.is_symlink():
        raise ValueError('storage_error: aliased database')
    if not create and not path.exists():
        raise ValueError('service_unavailable: no initialized queue')
    if create:
        runtime.mkdir(exist_ok=True)
    db = sqlite3.connect(path.as_uri() + '?mode=ro' if readonly else path, uri=readonly, timeout=5)
    db.row_factory = sqlite3.Row
    try:
        if readonly:
            db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN')
            yield db
            return
        db.execute('PRAGMA synchronous=FULL')
        db.execute('BEGIN IMMEDIATE')
        if not create:
            yield db
            db.commit()
            return
        db.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        db.execute("INSERT OR IGNORE INTO settings VALUES ('admission', 'closed')")
        db.execute('''CREATE TABLE IF NOT EXISTS jobs (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT UNIQUE NOT NULL,
            text TEXT NOT NULL, intent TEXT NOT NULL, status TEXT NOT NULL,
            submitted_ns INTEGER NOT NULL, started_ns INTEGER, finished_ns INTEGER,
            worker_id TEXT, result TEXT, error TEXT)''')
        # Preserve existing queue/history while replacing legacy prevalidation metadata.
        columns = {row[1] for row in db.execute('PRAGMA table_info(jobs)')}
        if 'intent' not in columns and 'validation' in columns:
            db.execute('ALTER TABLE jobs RENAME COLUMN validation TO intent')
            db.execute("UPDATE jobs SET intent='legacy_unclassified'")
        db.execute('CREATE INDEX IF NOT EXISTS jobs_status_sequence ON jobs(status, sequence)')
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def mean_duration(db):
    rows = db.execute("SELECT finished_ns-started_ns FROM jobs WHERE status='completed' AND started_ns IS NOT NULL AND finished_ns>=started_ns ORDER BY sequence DESC LIMIT 20").fetchall()
    return sum(row[0] for row in rows) / len(rows) if rows else None


def estimate(db, sequence, now):
    mean = mean_duration(db)
    if mean is None:
        return None
    count, started = db.execute("SELECT count(*), min(started_ns) FROM jobs WHERE status IN ('queued','processing') AND sequence<=?", (sequence,)).fetchone()
    elapsed = max(0, now - started) if started is not None else 0
    if started is not None and elapsed >= mean:
        return None
    wait = count * mean - elapsed
    return stamp(now + int(wait))


def run(args):
    if args.command in ('job', 'finish'):
        try:
            if str(uuid.UUID(args.job_id)) != args.job_id:
                raise ValueError()
        except (ValueError, AttributeError):
            raise ValueError('invalid_job_id: canonical UUID required') from None
    if args.command in ('claim', 'finish') and not args.worker_id.strip():
        raise ValueError('invalid_arguments: nonempty worker ID required')
    with database(args.service, create=args.command == 'admission',
                  readonly=args.command in ('job', 'report', 'queue-status')) as db:
        now = time.time_ns()
        if args.command == 'admission':
            db.execute("UPDATE settings SET value=? WHERE key='admission'", (args.value,))
            return {'admission': args.value}
        if args.command == 'submit':
            if not args.text.strip():
                raise ValueError('invalid_input: empty input')
            if not re.fullmatch(r'[a-z][a-z0-9_]*', args.intent):
                raise ValueError('invalid_input: root-approved intent identifier required')
            if db.execute("SELECT value FROM settings WHERE key='admission'").fetchone()[0] != 'open':
                raise ValueError('service_unavailable: admission closed')
            job_id = str(uuid.uuid4())
            count = db.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','processing')").fetchone()[0]
            cursor = db.execute("INSERT INTO jobs (job_id,text,intent,status,submitted_ns) VALUES (?,?,?,'queued',?)", (job_id,args.text,args.intent,now))
            return {'status':'accepted', 'job_id':job_id, 'submitted_at':stamp(now),
                    'worker_status':'activation_required', 'pending_jobs':count,
                    'estimated_execution_time':estimate(db,cursor.lastrowid,now)}
        if args.command == 'claim':
            if db.execute("SELECT 1 FROM jobs WHERE status='processing'").fetchone():
                return {'status':'busy'}
            row = db.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY sequence LIMIT 1").fetchone()
            if not row:
                return {'status':'empty'}
            db.execute("UPDATE jobs SET status='processing',started_ns=?,worker_id=? WHERE job_id=?", (now,args.worker_id,row['job_id']))
            return {'status':'processing','job_id':row['job_id'],'input':row['text'],
                    'intent':row['intent'], 'started_at':stamp(now)}
        if args.command == 'finish':
            row = db.execute('SELECT * FROM jobs WHERE job_id=?', (args.job_id,)).fetchone()
            if not row:
                raise ValueError('job_not_found: unknown job ID')
            if row['status'] != 'processing' or row['worker_id'] != args.worker_id:
                raise ValueError('invalid_arguments: job is not owned by this worker')
            result = json.loads(args.result) if args.result is not None else None
            error = json.loads(args.error) if args.error is not None else None
            if args.status == 'failed' and (not isinstance(error,dict) or set(error) != {'code','message'} or not all(isinstance(v,str) and v for v in error.values())):
                raise ValueError('invalid_arguments: failure requires code and message')
            if args.status == 'completed' and (error is not None or result is None):
                raise ValueError('invalid_arguments: completion requires a result and no error')
            db.execute('UPDATE jobs SET status=?,finished_ns=?,result=?,error=? WHERE job_id=?',
                       (args.status,now,json.dumps(result,allow_nan=False),json.dumps(error,allow_nan=False),args.job_id))
            return {'job_id':args.job_id,'status':args.status,'completed_at':stamp(now)}
        if args.command == 'report':
            rows = db.execute("SELECT * FROM jobs WHERE status IN ('completed','failed') ORDER BY sequence").fetchall()
            return {'service': args.service, 'jobs': [
                {'job_id': row['job_id'], 'status': row['status'],
                 'submitted_at': stamp(row['submitted_ns']),
                 'started_at': stamp(row['started_ns']),
                 'completed_at': stamp(row['finished_ns']),
                 'execution_seconds': (row['finished_ns'] - row['started_ns']) / 1e9
                     if row['started_ns'] is not None and row['finished_ns'] is not None else None,
                 'result': json.loads(row['result']) if row['result'] else None,
                 'error': json.loads(row['error']) if row['error'] else None}
                for row in rows]}
        if args.command == 'job':
            row = db.execute('SELECT * FROM jobs WHERE job_id=?',(args.job_id,)).fetchone()
            if not row:
                raise ValueError('job_not_found: unknown job ID')
            ahead = db.execute("SELECT count(*) FROM jobs WHERE sequence<? AND status IN ('queued','processing')",(row['sequence'],)).fetchone()[0] if row['status']=='queued' else 0
            return {'job_id':row['job_id'],'status':row['status'],'submitted_at':stamp(row['submitted_ns']),
                    'started_at':stamp(row['started_ns']),'completed_at':stamp(row['finished_ns']),
                    'execution_seconds':max(0, (row['finished_ns'] or now)-row['started_ns'])/1e9 if row['started_ns'] is not None else None,
                    'pending_jobs':ahead,'estimated_execution_time':estimate(db,row['sequence'],now) if row['status'] in ('queued','processing') else None,
                    'result':json.loads(row['result']) if row['result'] else None,
                    'error':json.loads(row['error']) if row['error'] else None}
        counts = {state:0 for state in ('queued','processing','completed','failed')}
        counts.update({r[0]:r[1] for r in db.execute('SELECT status,count(*) FROM jobs GROUP BY status')})
        oldest = db.execute("SELECT min(submitted_ns),max(sequence) FROM jobs WHERE status IN ('queued','processing')").fetchone()
        return {'admission':db.execute("SELECT value FROM settings WHERE key='admission'").fetchone()[0],
                'worker_active':bool(counts['processing']),'jobs':counts,
                'oldest_queued_at':stamp(db.execute("SELECT min(submitted_ns) FROM jobs WHERE status='queued'").fetchone()[0]),
                'estimated_execution_time':estimate(db,oldest[1],now) if oldest[1] else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--service', required=True)
    commands = parser.add_subparsers(dest='command', required=True)
    submit = commands.add_parser('submit')
    submit.add_argument('--text',required=True)
    submit.add_argument('--intent',required=True)
    commands.add_parser('admission').add_argument('value',choices=['open','closed'])
    commands.add_parser('queue-status')
    commands.add_parser('report')
    commands.add_parser('job').add_argument('--job-id',required=True)
    commands.add_parser('claim').add_argument('--worker-id',required=True)
    finish = commands.add_parser('finish')
    finish.add_argument('--worker-id',required=True)
    finish.add_argument('--job-id',required=True)
    finish.add_argument('--status',choices=['completed','failed'],required=True)
    finish.add_argument('--result')
    finish.add_argument('--error')
    args = parser.parse_args()
    try:
        print(json.dumps(run(args),ensure_ascii=False,allow_nan=False))
    except (ValueError, OSError, sqlite3.Error) as exc:
        message = str(exc)
        if isinstance(exc, (OSError, sqlite3.Error)):
            message = 'storage_error: service storage unavailable; inspect permissions, schema and locks'
        elif ': ' not in message:
            message = 'invalid_arguments: invalid JSON or argument value'
        print(json.dumps({'status':'error','error':{'code':message.split(':')[0], 'message':message}}))
        sys.exit(1)


if __name__ == '__main__':
    main()
