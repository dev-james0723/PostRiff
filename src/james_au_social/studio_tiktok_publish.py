"""Persistent owner-approved TikTok queue. No automatic retry after dispatch."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone

from .studio import StudioError


def fail(message):
    raise StudioError('tiktok_publish_rejected', message, 422)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def plain_path(path):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        fail('Symbolic links are not accepted for publishing files.')
    return path


class TikTokPublishing:
    def __init__(self, data_dir, project_root, transport=None, now=time.time):
        self.root = plain_path(Path(data_dir) / 'tiktok-publishing')
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)
        self.project_root = Path(project_root)
        self.db_path = plain_path(self.root / 'queue.sqlite3')
        self.now = now
        self.transport = transport or self.execute
        self.stop_event = threading.Event()
        self.thread = None
        self.lock_file = None
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, state TEXT NOT NULL, manifest TEXT NOT NULL, hash TEXT NOT NULL, due REAL NOT NULL, result TEXT, created REAL NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS control (id INTEGER PRIMARY KEY, paused INTEGER NOT NULL)')
            db.execute('INSERT OR IGNORE INTO control VALUES (1,0)')
        self.db_path.chmod(0o600)

    def db(self):
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def unpack(self, row):
        return {'id': row['id'], 'state': row['state'], 'manifest': json.loads(row['manifest']), 'hash': row['hash'], 'result': json.loads(row['result']) if row['result'] else None}

    def get(self, identifier):
        with self.db() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=?', (identifier,)).fetchone()
        if row is None:
            fail('TikTok review not found.')
        return self.unpack(row)

    def status(self):
        with self.db() as db:
            jobs = [self.unpack(r) for r in db.execute('SELECT * FROM jobs ORDER BY created DESC LIMIT 100')]
            paused = bool(db.execute('SELECT paused FROM control WHERE id=1').fetchone()[0])
        return {'account': '@jamesaucreates', 'route': 'unofficial_session_uploader', 'workerRunning': bool(self.thread and self.thread.is_alive()), 'paused': paused, 'jobs': jobs}

    def prepare(self, value):
        if set(value) != {'path', 'caption', 'visibility', 'dueUtc', 'timezone', 'comments', 'duet', 'stitch', 'rightsConfirmed', 'derivatives'}:
            fail('Use only the displayed review fields.')
        if value['rightsConfirmed'] is not True or value['derivatives'] != 'none':
            fail('Confirm rights and the no-derivatives choice for this video.')
        if value['visibility'] not in ('private', 'public'):
            fail('Choose Only me or Everyone explicitly.')
        if any(type(value[k]) is not bool for k in ('comments','duet','stitch')):
            fail('Invalid interaction settings.')
        if not isinstance(value['caption'], str) or not 1 <= len(value['caption']) <= 2200:
            fail('Enter a caption of 1–2200 characters.')
        from zoneinfo import ZoneInfo
        try:
            zone = ZoneInfo(value['timezone'])
            due = datetime.fromisoformat(value['dueUtc'].replace('Z', '+00:00')) if value['dueUtc'] else None
            if due and due.utcoffset() is None: raise ValueError()
            if due and not self.now()+15 <= due.timestamp() <= self.now()+30*86400: raise ValueError()
        except (ValueError, TypeError, KeyError):
            fail('Choose a future time within 30 days and a valid timezone.')
        if not isinstance(value['path'], str) or not Path(value['path']).is_absolute():
            fail('Enter an absolute local MP4 path.')
        source = plain_path(value['path'])
        if not source.is_file() or source.suffix.lower() != '.mp4' or not 0 < source.stat().st_size <= 500*1024*1024:
            fail('Select a local MP4 under 500 MB.')
        identifier = uuid.uuid4().hex
        media = self.root / (identifier + '.mp4')
        try:
            with source.open('rb') as incoming, media.open('xb') as outgoing:
                os.fchmod(outgoing.fileno(), 0o600)
                total = 0
                while chunk := incoming.read(1024*1024):
                    total += len(chunk)
                    if total > 500*1024*1024: fail('Video exceeds 500 MB.')
                    outgoing.write(chunk)
            probe = subprocess.run([shutil.which('ffprobe') or '/opt/homebrew/bin/ffprobe','-v','error','-show_entries','format=duration:stream=codec_type,codec_name,width,height','-of','json',str(media)], capture_output=True, timeout=30, check=True)
            info = json.loads(probe.stdout)
            video = next(s for s in info['streams'] if s['codec_type']=='video')
            duration = float(info['format']['duration'])
            if video['codec_name'] != 'h264' or not 0 < duration <= 600:
                fail('This route currently accepts H.264 MP4 videos up to 10 minutes.')
            frozen = {**value, 'path': str(media), 'sourceName': source.name, 'account':'@jamesaucreates', 'sha256':digest(media), 'duration':duration, 'width':video['width'], 'height':video['height'], 'dueUtc':due.astimezone(timezone.utc).isoformat() if due else None, 'dueLocal':due.astimezone(zone).isoformat() if due else 'Immediately after approval', 'route':'unofficial_session_uploader'}
            encoded = json.dumps(frozen, sort_keys=True)
            with self.db() as db:
                db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?)',(identifier,'review',encoded,hashlib.sha256(encoded.encode()).hexdigest(),due.timestamp() if due else 0,None,self.now()))
        except BaseException:
            media.unlink(missing_ok=True)
            raise
        return self.get(identifier)

    def approve(self, identifier, supplied_hash):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM jobs WHERE id=?',(identifier,)).fetchone()
            if not row or row['hash'] != supplied_hash: fail('The review changed. Reload it before approval.')
            if row['state'] != 'review': return self.unpack(row)
            if row['due'] and row['due'] <= self.now(): fail('This time has passed. Prepare a new review.')
            manifest = json.loads(row['manifest'])
            if digest(plain_path(manifest['path'])) != manifest['sha256']: fail('The reviewed media changed.')
            db.execute('UPDATE jobs SET state=?,due=? WHERE id=?',('queued',row['due'] or self.now(),identifier))
        return self.get(identifier)

    def cancel(self, identifier):
        with self.db() as db:
            changed = db.execute("UPDATE jobs SET state='cancelled' WHERE id=? AND state IN ('review','queued','needs_review')",(identifier,)).rowcount
            if not changed: fail('Only unsent jobs can be cancelled.')
        return self.get(identifier)

    def pause(self, paused):
        if type(paused) is not bool: fail('Invalid pause value.')
        with self.db() as db: db.execute('UPDATE control SET paused=? WHERE id=1',(int(paused),))
        return self.status()

    def tick(self):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT paused FROM control WHERE id=1').fetchone()[0]: return
            db.execute("UPDATE jobs SET state='needs_review' WHERE state='queued' AND due<?",(self.now()-300,))
            row = db.execute("SELECT * FROM jobs WHERE state='queued' AND due<=? ORDER BY due LIMIT 1",(self.now(),)).fetchone()
            if not row: return
            db.execute("UPDATE jobs SET state='sending' WHERE id=?",(row['id'],))
        job = self.unpack(row)
        try:
            if digest(plain_path(job['manifest']['path'])) != job['manifest']['sha256']:
                result = {'state':'needs_review','reason':'Reviewed video changed.'}
            else: result = self.transport(job)
        except Exception:
            result = {'state':'unresolved','reason':'Attempt interrupted. Check TikTok before any new submission.'}
        if result.get('state') not in ('submitted','unresolved','needs_review'):
            result = {'state':'unresolved','reason':'Unexpected uploader result.'}
        with self.db() as db:
            db.execute('UPDATE jobs SET state=?,result=? WHERE id=?',(result['state'],json.dumps(result),job['id']))

    def execute(self, job):
        runtime = self.project_root / 'studio/tiktok-runtime'
        process = subprocess.Popen([str(runtime/'.venv/bin/python'),str(runtime/'runner.py')],cwd=runtime/'source',stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,env={**os.environ,'PYTHON_DOTENV_DISABLED':'1'})
        try:
            output, _ = process.communicate(json.dumps(job),timeout=300)
            if process.returncode != 0: return {'state':'unresolved','reason':'Uploader stopped. Inspect TikTok before another attempt.'}
            return json.loads(output)
        except subprocess.TimeoutExpired:
            process.kill(); process.communicate()
            return {'state':'unresolved','reason':'Uploader timed out. No automatic retry.'}

    def start(self):
        self.lock_file = (self.root/'worker.lock').open('a')
        try: fcntl.flock(self.lock_file,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock_file.close(); self.lock_file=None; return
        with self.db() as db:
            db.execute("UPDATE jobs SET state='unresolved',result=? WHERE state='sending'",(json.dumps({'reason':'Studio restarted during an attempt. Check TikTok.'}),))
        self.thread=threading.Thread(target=self.loop,daemon=True,name='tiktok-publishing')
        self.thread.start()

    def loop(self):
        while not self.stop_event.is_set():
            try: self.tick()
            except Exception: pass
            self.stop_event.wait(3)

    def shutdown(self):
        self.stop_event.set()
        if self.thread: self.thread.join(timeout=305)
        if self.lock_file: self.lock_file.close()


def register_tiktok_publishing(app, store, body_parser):
    from fastapi import Request
    from fastapi.responses import FileResponse
    from starlette.concurrency import run_in_threadpool
    service = TikTokPublishing(store.data_dir, store.project_root)
    @app.get('/api/tiktok-publishing')
    def status(): return service.status()
    @app.post('/api/tiktok-publishing/reviews')
    async def review(request: Request): return await run_in_threadpool(service.prepare, await body_parser(request))
    @app.post('/api/tiktok-publishing/{identifier}/approve')
    async def approve(identifier: str, request: Request):
        data=await body_parser(request)
        if set(data)!={'hash'}: fail('Invalid approval fields.')
        return await run_in_threadpool(service.approve,identifier,data['hash'])
    @app.post('/api/tiktok-publishing/{identifier}/cancel')
    async def cancel(identifier: str, request: Request):
        if await body_parser(request): fail('Invalid cancellation fields.')
        return service.cancel(identifier)
    @app.post('/api/tiktok-publishing/control')
    async def pause(request: Request):
        data=await body_parser(request)
        if set(data)!={'paused'}: fail('Invalid control fields.')
        return service.pause(data['paused'])
    @app.get('/api/tiktok-publishing/{identifier}/video')
    def preview(identifier: str):
        job=service.get(identifier)
        return FileResponse(job['manifest']['path'],media_type='video/mp4')
    return service
