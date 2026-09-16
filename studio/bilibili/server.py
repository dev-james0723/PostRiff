"""Studio bridge to the user-selected GPL recorder upload engine.

Private session material and provider errors never enter Studio content storage.
"""
import asyncio
import contextlib
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import re
import secrets
import sys
import subprocess
import shutil
import threading
import time
from types import SimpleNamespace

import qrcode
import qrcode.image.svg
import requests

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'vendor'))
from cryptography.fernet import Fernet
from fastapi import FastAPI, Request, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, Response, RedirectResponse
from bilibili_api import Verify, user, video
from upload_task import UploadTask

UID = '3546856139262666'
PORT = int(os.environ.get('JAMES_BILI_PORT', '4387'))
DATA = Path(os.environ.get('JAMES_BILI_DATA', str(Path.home() / 'Library/Application Support/JamesAuStudio-Bilibili')))
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
OWNER = secrets.token_urlsafe(32)
LOCK = threading.Lock()
IDENTITY = None
ACTIVE = False
QR_SESSION = None
QR_KEY = None
QR_SVG = None
QR_URL = None

def private_dir(path):
    if any(p.is_symlink() for p in [path, *path.parents]):
        raise ValueError('unsafe_storage')
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    path.chmod(0o700)

def save(path, data):
    private_dir(path.parent)
    if path.is_symlink():
        raise ValueError('unsafe_storage')
    tmp = path.with_name(path.name + '.' + secrets.token_hex(8))
    with open(tmp, 'xb') as f:
        os.chmod(tmp, 0o600)
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)

def cipher():
    private_dir(DATA)
    path = DATA / 'vault.key'
    if not path.exists():
        save(path, Fernet.generate_key())
    if path.is_symlink() or path.stat().st_mode & 0o077:
        raise ValueError('unsafe_storage')
    return Fernet(path.read_bytes())

def credential():
    path = DATA / 'session.enc'
    if path.is_symlink() or path.stat().st_mode & 0o077:
        raise ValueError('unsafe_storage')
    c = json.loads(cipher().decrypt(path.read_bytes()))
    return Verify(sessdata=c['sessdata'], csrf=c['bili_jct'])

def verified(v):
    result = user.get_self_info(v)
    if str(result.get('mid')) != UID or result.get('isLogin') is not True:
        raise ValueError('account_mismatch')
    public = user.get_relation_info(int(UID), v)
    if str(public.get('mid')) != UID:
        raise ValueError('identity_unverified')
    return {'uid': UID, 'name': result['uname'], 'verifiedAt': int(time.time())}

def digest(path):
    with open(path, 'rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()

def job_path(jobid):
    if not re.fullmatch('[a-f0-9]{32}', jobid):
        raise ValueError('invalid_job')
    return DATA / 'jobs' / (jobid + '.json')

def read_job(jobid):
    return json.loads(job_path(jobid).read_text())

def write_job(job):
    save(job_path(job['id']), json.dumps(job, ensure_ascii=False).encode())

@app.middleware('http')
async def owner_boundary(request, call_next):
    host = request.headers.get('host')
    if host != f'127.0.0.1:{PORT}':
        return JSONResponse({'error': 'invalid_host'}, 403)
    origin = request.headers.get('origin')
    if origin and origin != f'http://{host}':
        return JSONResponse({'error': 'invalid_origin'}, 403)
    root = request.method == 'GET' and request.url.path == '/'
    health = request.method == 'GET' and request.url.path == '/health'
    if request.method == 'POST' and not request.url.path.startswith('/asset/'):
        if int(request.headers.get('content-length', '0')) > 65536:
            return JSONResponse({'error': 'request_too_large'}, 413)
    if not root and not health and not hmac.compare_digest(request.cookies.get('bili_owner', ''), OWNER):
        return JSONResponse({'error': 'open_workspace_first'}, 401)
    if request.method != 'GET' and (origin != f'http://{host}' or request.headers.get('x-studio-request') != '1'):
        return JSONResponse({'error': 'owner_request_required'}, 403)
    if request.headers.get('sec-fetch-site') == 'cross-site' and not root:
        return JSONResponse({'error': 'cross_site'}, 403)
    try:
        response = await call_next(request)
    except Exception:
        response = JSONResponse({'error': 'operation_failed_check_account_or_input'}, 400)
    response.headers.update({'Cache-Control': 'no-store', 'X-Frame-Options': 'DENY', 'Referrer-Policy': 'no-referrer', 'Content-Security-Policy': "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; form-action 'self'"})
    if root:
        response.set_cookie('bili_owner', OWNER, httponly=True, samesite='strict')
    return response

@app.get('/health')
def health():
    return {'app': 'james-studio-bilibili', 'version': 1}

@app.get('/')
def home():
    return HTMLResponse((ROOT / 'index.html').read_text())

@app.get('/status')
def status():
    fresh = IDENTITY and time.time() - IDENTITY['verifiedAt'] < 300
    jobs = []
    for p in sorted((DATA / 'jobs').glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True)[:20]:
        j = json.loads(p.read_text())
        jobs.append({k: j.get(k) for k in ('id', 'state', 'bvid', 'error')})
    return {'connection': IDENTITY if fresh else None, 'savedSession': (DATA / 'session.enc').exists(), 'active': ACTIVE, 'jobs': jobs, 'route': 'unofficial_session_provider', 'oauth': False}

@app.post('/connect')
async def connect(request: Request):
    global IDENTITY
    data = await request.json()
    if set(data) != {'sessdata', 'bili_jct'} or any(not isinstance(v, str) or not 1 <= len(v) <= 4096 for v in data.values()):
        raise ValueError('invalid_credentials')
    if ACTIVE:
        raise ValueError('upload_active')
    v = Verify(sessdata=data['sessdata'], csrf=data['bili_jct'])
    identity = await asyncio.to_thread(verified, v)
    save(DATA / 'session.enc', cipher().encrypt(json.dumps(data).encode()))
    IDENTITY = identity
    return {'connection': identity}

@app.post('/qr/start')
async def qr_start():
    global QR_SESSION, QR_KEY, QR_SVG, QR_URL
    if ACTIVE:
        raise ValueError('upload_active')
    session = requests.Session()
    session.headers.update({'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.bilibili.com/'})
    response = await asyncio.to_thread(session.get, 'https://passport.bilibili.com/x/passport-login/web/qrcode/generate', timeout=15)
    payload = response.json()
    if payload.get('code') != 0:
        raise ValueError('qr_generation_failed')
    data = payload['data']
    image = qrcode.make(data['url'], image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2)
    buffer = io.BytesIO()
    image.save(buffer)
    QR_SESSION, QR_KEY, QR_SVG, QR_URL = session, data['qrcode_key'], buffer.getvalue(), data['url']
    return {'state': 'qr_ready'}

@app.get('/qr/image')
def qr_image():
    if not QR_SVG:
        raise ValueError('qr_not_started')
    return Response(QR_SVG, media_type='image/svg+xml', headers={'Cache-Control': 'no-store'})

@app.get('/qr/open')
def qr_open():
    if not QR_URL:
        raise ValueError('qr_not_started')
    return RedirectResponse(QR_URL, status_code=302, headers={'Cache-Control': 'no-store'})

@app.post('/qr/poll')
async def qr_poll():
    global IDENTITY, QR_SESSION, QR_KEY, QR_SVG, QR_URL
    if not QR_SESSION or not QR_KEY:
        raise ValueError('qr_not_started')
    response = await asyncio.to_thread(QR_SESSION.get, 'https://passport.bilibili.com/x/passport-login/web/qrcode/poll', params={'qrcode_key': QR_KEY}, timeout=15)
    payload = response.json()
    if payload.get('code') != 0:
        raise ValueError('qr_poll_failed')
    code = payload['data'].get('code')
    if code in (86101, 86090):
        return {'state': 'waiting_scan' if code == 86101 else 'waiting_confirmation'}
    if code == 86038:
        QR_SESSION = QR_KEY = QR_SVG = QR_URL = None
        return {'state': 'expired'}
    if code != 0:
        raise ValueError('qr_login_failed')
    sessdata = QR_SESSION.cookies.get('SESSDATA')
    csrf = QR_SESSION.cookies.get('bili_jct')
    if not sessdata or not csrf:
        raise ValueError('qr_session_incomplete')
    identity = await asyncio.to_thread(verified, Verify(sessdata=sessdata, csrf=csrf))
    save(DATA / 'session.enc', cipher().encrypt(json.dumps({'sessdata': sessdata, 'bili_jct': csrf}).encode()))
    IDENTITY = identity
    QR_SESSION = QR_KEY = QR_SVG = QR_URL = None
    return {'state': 'connected', 'connection': identity}

@app.post('/verify')
async def verify():
    global IDENTITY
    IDENTITY = None
    IDENTITY = await asyncio.to_thread(verified, credential())
    return {'connection': IDENTITY}

@app.post('/asset/{kind}')
async def asset(kind: str, file: UploadFile = File(...)):
    if kind not in ('video', 'cover'):
        raise ValueError('invalid_kind')
    ext = Path(file.filename or '').suffix.lower()
    if ext not in ({'.mp4', '.mov', '.mkv', '.flv'} if kind == 'video' else {'.jpg', '.jpeg', '.png'}):
        raise ValueError('invalid_type')
    assetid = secrets.token_hex(16) + ext
    private_dir(DATA / 'media')
    path = DATA / 'media' / assetid
    size = 0
    with open(path, 'xb') as f:
        os.chmod(path, 0o600)
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > (20 * 1024**3 if kind == 'video' else 5 * 1024**2):
                raise ValueError('file_too_large')
            f.write(chunk)
    if size == 0:
        raise ValueError('empty_file')
    return {'id': assetid, 'sha256': await asyncio.to_thread(digest, path), 'size': size, 'kind': kind}

def media_path(assetid):
    if not isinstance(assetid, str) or not re.fullmatch(r'[a-f0-9]{32}\.(mp4|mov|mkv|flv|jpg|jpeg|png)', assetid):
        raise ValueError('invalid_asset')
    p = DATA / 'media' / assetid
    if p.is_symlink() or not p.is_file():
        raise ValueError('invalid_asset')
    return p

def probe(path):
    binary = shutil.which('ffprobe')
    if not binary:
        raise ValueError('ffprobe_required')
    result = subprocess.run([binary, '-v', 'error', '-show_entries', 'stream=codec_type', '-of', 'json', str(path)], capture_output=True, timeout=30)
    if result.returncode or not any(s.get('codec_type') == 'video' for s in json.loads(result.stdout).get('streams', [])):
        raise ValueError('invalid_media')

@app.post('/preview')
async def preview(request: Request):
    data = await request.json()
    if set(data) != {'video', 'cover', 'title', 'description', 'tags', 'category', 'copyright', 'source'}:
        raise ValueError('invalid_metadata')
    for field, limit in [('title', 80), ('description', 2000), ('tags', 200), ('source', 200)]:
        if not isinstance(data[field], str) or len(data[field]) > limit:
            raise ValueError('invalid_metadata')
    if not data['title'].strip() or not data['tags'].strip() or type(data['category']) is not int or data['category'] <= 0 or data['copyright'] not in (1, 2):
        raise ValueError('invalid_metadata')
    if data['copyright'] == 2 and not data['source'].strip():
        raise ValueError('source_required')
    for kind in ('video', 'cover'):
        p = media_path(data[kind])
        if p.suffix not in ({'.mp4','.mov','.mkv','.flv'} if kind == 'video' else {'.jpg','.jpeg','.png'}):
            raise ValueError('wrong_media_kind')
        await asyncio.to_thread(probe, p)
        data[kind] = {'id': data[kind], 'sha256': await asyncio.to_thread(digest, p), 'size': p.stat().st_size}
    data.update({'uid': UID, 'visibility': 'public_after_Bilibili_review', 'derivatives': 'none', 'route': 'Misaka-Mikoto-Tech/bililive-auto-upload', 'timing': 'immediate_on_confirmation'})
    job = {'id': secrets.token_hex(16), 'state': 'preview', 'manifest': data, 'hash': fingerprint(data)}
    write_job(job)
    return job

def execute(job):
    global ACTIVE
    try:
        v = credential()
        verified(v)
        m = job['manifest']
        for kind in ('video', 'cover'):
            if digest(media_path(m[kind]['id'])) != m[kind]['sha256']:
                raise ValueError('media_changed')
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            task = UploadTask(job['id'], str(media_path(m['video']['id'])), str(media_path(m['cover']['id'])), None, None, None, m['title'], m['source'], m['description'], m['tags'], m['category'], False, SimpleNamespace(verify=v))
            task.copyright = m['copyright']
            def before_submit():
                job['state'] = 'submission_started'
                write_job(job)
            task.before_submit = before_submit
            with open(os.devnull, 'w') as quiet, contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
                bvid = task.upload({})
            if not re.fullmatch('BV[A-Za-z0-9]{10}', bvid):
                raise ValueError('unresolved_provider_result')
            job.update({'bvid': bvid, 'state': 'submitted_unverified'})
            write_job(job)
            try:
                result = video.get_video_info(bvid=bvid, verify=v)
                if str(result.get('owner', {}).get('mid')) == UID and result.get('title') == m['title']:
                    job['state'] = 'published_verified'
            except Exception:
                pass
        finally:
            loop.close()
    except Exception:
        job['error'] = 'Provider operation failed. Inspect Creator Centre before any new upload.'
        if job['state'] == 'submission_started':
            job['state'] = 'submission_unknown'
        elif job['state'] != 'submitted_unverified':
            job['state'] = 'failed_before_submission'
    finally:
        write_job(job)
        ACTIVE = False

def launch(job):
    threading.Thread(target=execute, args=(job,), daemon=True).start()

@app.post('/submit/{jobid}')
async def submit(jobid: str, request: Request):
    global ACTIVE
    data = await request.json()
    with LOCK:
        job = read_job(jobid)
        if data != {'hash': job['hash'], 'approvePublicUpload': True} or job['hash'] != fingerprint(job['manifest']):
            raise ValueError('exact_approval_required')
        if job['state'] != 'preview':
            return {'id': job['id'], 'state': job['state']}
        if ACTIVE:
            raise ValueError('upload_active')
        # Duplicate manifests cannot create a second submission, even across restarts.
        for p in (DATA / 'jobs').glob('*.json'):
            other = json.loads(p.read_text())
            if other['id'] != jobid and other['hash'] == job['hash'] and other['state'] != 'preview':
                raise ValueError('duplicate_manifest')
        job.update({'state': 'upload_started', 'approvedAt': int(time.time())})
        write_job(job)
        ACTIVE = True
        launch(job)
        return {'id': job['id'], 'state': 'upload_started'}

if __name__ == '__main__':
    os.umask(0o077)
    private_dir(DATA)
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=PORT, access_log=False, log_level='critical')
