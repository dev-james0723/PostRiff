"""Text-only Zhihu browser pilot. Selective MIT upstream flow adaptation.
Upstream: liuboacean/zhihu-automation-skill @ 9aca95da75ffd0238174ba9ed2438f4c519ce233.
No cookie export, HTTP endpoints, blind retries, or generic-success inference.
"""
from __future__ import annotations
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time
from urllib.parse import urljoin
from fastapi import Request

VERSION = 'zhihu-browser/1'
DEFAULT_ROOT = Path.home() / 'Library/Application Support/JamesAuStudio/zhihu-browser'

class Stop(ValueError):
    pass

def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))

def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()

def profile(value):
    if not isinstance(value, str): raise Stop('invalid_profile')
    if re.fullmatch(r'[A-Za-z0-9_-]{1,100}', value): value = 'https://www.zhihu.com/people/' + value
    if not re.fullmatch(r'https://www\.zhihu\.com/people/[A-Za-z0-9_-]{1,100}', value): raise Stop('invalid_profile')
    return value

def permalink(value):
    if not isinstance(value, str) or not re.fullmatch(r'https://www\.zhihu\.com/pin/[0-9]+', value): raise Stop('invalid_permalink')
    return value

def manifest(account, text):
    if not isinstance(text, str) or not text.strip() or len(text) > 1000 or any(ord(c)<32 and c not in '\n\t' for c in text):
        raise Stop('invalid_text')  # Conservative pilot bound, not platform limit.
    return dict(version=VERSION, channel='zhihu', nativeFormat='zhihu.idea', profile=profile(account),
                text=text, audience='public', timing='now', media=[], derivatives=[])

def validate(value):
    if not isinstance(value, dict) or value != manifest(value.get('profile'), value.get('text')): raise Stop('invalid_manifest')
    return value

def private_dir(root):
    root = Path(os.path.abspath(root))
    if any(p.is_symlink() for p in [root, *root.parents]): raise Stop('unsafe_private_path')
    root.mkdir(parents=True, exist_ok=True, mode=0o700); root.chmod(0o700)
    return root

class Store:
    def __init__(self, root):
        self.root = private_dir(root)
        p = self.root / 'state.sqlite3'
        if p.is_symlink(): raise Stop('unsafe_private_path')
        fd = os.open(p, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600); os.close(fd)
        p.chmod(0o600)
        self.db = sqlite3.connect(p, isolation_level=None)
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS records (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
    def close(self): self.db.close()
    def get(self, key):
        row=self.db.execute('SELECT value FROM records WHERE key=?',(key,)).fetchone()
        return json.loads(row[0]) if row else None
    def put(self, key, value):
        self.db.execute('INSERT OR REPLACE INTO records VALUES (?,?)',(key,canonical(value)))
        return value
    @contextlib.contextmanager
    def lock(self):
        fd=os.open(self.root/'browser.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        try:
            try: fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError: raise Stop('browser_busy_close_login_window') from None
            yield
        finally: os.close(fd)
    def status(self):
        c=self.get('connection') or {}
        fresh=time.time()-c.get('verifiedAt',0)<900
        return dict(provider='zhihu', route='controlled_browser', routeDriver=VERSION,
                    state='connected_identity' if fresh else 'login_or_verification_required',
                    profile=c.get('profile'), identitySignals=c.get('identitySignals',[]) if fresh else [],
                    publishReady=False, publishing=False, liveTestVerified=bool(c.get('liveTestVerified')))

@contextlib.contextmanager
def browser(root):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        ctx=pw.chromium.launch_persistent_context(str(private_dir(Path(root)/'chrome-profile')),channel='chrome',headless=False,
                accept_downloads=False,chromium_sandbox=True)
        try: yield ctx
        finally: ctx.close()

class ZhihuUI:
    def __init__(self, ctx):
        self.ctx=ctx; self.page=ctx.new_page(); self.page.set_default_timeout(10000)
    def one(self, locator):
        if locator.count()!=1 or not locator.is_visible(): raise Stop('ui_changed')
        return locator
    def public_page(self, page, url):
        page.goto(url,wait_until='domcontentloaded')
        if page.url.rstrip('/') != url: raise Stop('login_or_ui_changed')
        if page.locator('input[type="password"], .SignFlow, .Captcha, iframe[src*="captcha"]').count():
            raise Stop('private_handoff_required')
    def identity(self, account):
        p=self.ctx.new_page()
        try:
            p.set_default_timeout(10000); self.public_page(p,account)
            # Header's own-account link is distinct from the profile's owner-only control.
            avatar=self.one(p.locator('.AppHeader-profileAvatar'))
            avatar.click()
            own=self.one(p.get_by_role('link',name='我的主页',exact=True))
            if urljoin('https://www.zhihu.com',own.get_attribute('href') or '').rstrip('/')!=account:
                raise Stop('identity_mismatch')
            self.one(p.get_by_role('button',name='编辑个人资料',exact=True))
            return ['authenticated_header_profile','own_profile_edit_control']
        finally: p.close()
    def links(self, account):
        self.public_page(self.page,account+'/pins')
        return {urljoin('https://www.zhihu.com',x.get_attribute('href')) for x in self.page.locator('a[href*="/pin/"]').all()
                if re.fullmatch(r'(https://www\.zhihu\.com)?/pin/[0-9]+',x.get_attribute('href') or '')}
    def compose(self,text):
        self.public_page(self.page,'https://www.zhihu.com')
        self.one(self.page.get_by_role('button',name='发想法',exact=True)).click()
        self.one(self.page.locator('[contenteditable="true"]')).fill(text)
        self.assert_text(text)
    def assert_text(self,text):
        if self.one(self.page.locator('[contenteditable="true"]')).inner_text()!=text: raise Stop('rendered_text_mismatch')
    def submit(self):
        self.one(self.page.get_by_role('button',name='发布',exact=True)).click()
    def verify(self,url,value):
        permalink(url); p=self.ctx.new_page()
        try:
            p.set_default_timeout(10000); self.public_page(p,url)
            card=self.one(p.locator('.PinItem'))
            author=self.one(card.locator('.AuthorInfo a[href*="/people/"]'))
            if urljoin('https://www.zhihu.com',author.get_attribute('href') or '').rstrip('/')!=value['profile']:
                raise Stop('wrong_author')
            if self.one(card.locator('.RichContent-inner .RichText')).inner_text()!=value['text']: raise Stop('wrong_content')
            return dict(permalink=url,profile=value['profile'],textHash=digest(value['text']),independentRead=True)
        finally: p.close()
    def find_new(self,before,value):
        for _ in range(3):
            for url in sorted(self.links(value['profile'])-set(before)):
                try: return self.verify(url,value)
                except Stop: continue
            self.page.wait_for_timeout(1500)
        raise Stop('publication_unresolved')

def execute(store, value, approved_hash, ui):
    validate(value); key=digest(value)
    if approved_hash!=key: raise Stop('exact_approval_required')
    with store.lock():
        existing=store.get(key)
        if existing: return existing
        ui.identity(value['profile'])
        before=sorted(ui.links(value['profile']))
        # Claim before composition: even autosaved drafts are approval-bound.
        record=dict(state='attempting',manifest=value,hash=key,previousLinks=before,claimedAt=time.time())
        store.put(key,record)
        try:
            ui.compose(value['text']); ui.identity(value['profile']); ui.assert_text(value['text'])
            store.put(key,{**record,'state':'submitting'})
            ui.submit()
            evidence=ui.find_new(before,value)
            record.update(state='published_verified',evidence=evidence)
            connection=store.get('connection') or {}
            if connection.get('profile')==value['profile']: store.put('connection',{**connection,'liveTestVerified':True})
        except Exception:
            record.update(state='unknown',reason='reconcile_before_retry')
        return store.put(key,record)

def reconcile(store,key,url,ui):
    record=store.get(key)
    if not record or record.get('hash')!=key: raise Stop('attempt_missing')
    with store.lock():
        if url in record['previousLinks']: raise Stop('preexisting_post')
        ui.identity(record['manifest']['profile'])
        evidence=ui.verify(permalink(url),record['manifest'])
        return store.put(key,{**record,'state':'published_verified','evidence':evidence})

def login(root):
    store=Store(root)
    try:
        with store.lock(), browser(root) as ctx:
            page=ctx.new_page(); page.goto('https://www.zhihu.com/signin',wait_until='domcontentloaded')
            print('{"state":"private_handoff","browser":"Google Chrome"}',flush=True)
            # No snapshots, cookies, network logging or DOM observations during login.
            while ctx.pages:
                try: ctx.pages[0].wait_for_timeout(500)
                except Exception: break
    finally: store.close()

def register_routes(app,data_dir,body_parser):
    from fastapi import Request
    from starlette.concurrency import run_in_threadpool
    from .studio import StudioError
    root=Path(data_dir)/'zhihu-browser'
    def work(operation,value):
        store=Store(root)
        try:
            if operation=='status': return store.status()
            if operation=='preview':
                if set(value)!={'profile','text'}: raise Stop('invalid_manifest')
                m=manifest(value['profile'],value['text']); return dict(manifest=m,hash=digest(m),state='local_preview')
            if operation=='login':
                if value!={}: raise Stop('invalid_request')
                with store.lock(): pass
                subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'login','--root',str(root)],
                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,stdin=subprocess.DEVNULL,
                    env={k:os.environ[k] for k in ('PATH','HOME','TMPDIR') if k in os.environ},start_new_session=True)
                return dict(state='private_handoff',instruction='Sign in to Zhihu in the dedicated browser, then close that browser and verify your public profile here.')
            if operation=='verify':
                if set(value)!={'profile'}: raise Stop('invalid_request')
                account=profile(value['profile'])
                with store.lock(), browser(root) as ctx:
                    signals=ZhihuUI(ctx).identity(account)
                    previous=store.get('connection') or {}
                    if previous.get('profile') not in (None,account): raise Stop('identity_mismatch')
                    store.put('connection',dict(profile=account,verifiedAt=time.time(),identitySignals=signals,
                              liveTestVerified=previous.get('liveTestVerified',False)))
                return store.status()
            if operation=='publish':
                if set(value)!={'manifest','approvedHash','publicationConsent'} or value['publicationConsent'] is not True: raise Stop('exact_approval_required')
                m=validate(value['manifest'])
                if value['approvedHash']!=digest(m): raise Stop('exact_approval_required')
                connection=store.status()
                if connection['state']!='connected_identity' or connection['profile']!=m['profile']: raise Stop('verify_exact_profile_first')
                existing=store.get(digest(m))
                if existing: return existing
                with browser(root) as ctx: return execute(store,m,value['approvedHash'],ZhihuUI(ctx))
            if operation=='reconcile':
                if set(value)!={'hash','permalink'} or not re.fullmatch('[a-f0-9]{64}',value.get('hash','')): raise Stop('invalid_request')
                permalink(value['permalink'])
                with browser(root) as ctx: return reconcile(store,value['hash'],value['permalink'],ZhihuUI(ctx))
            raise Stop('unsupported_operation')
        except Stop as error: raise StudioError(str(error),'Zhihu stopped: '+str(error).replace('_',' ')+'.',409) from None
        except Exception: raise StudioError('zhihu_browser_unavailable','Zhihu browser operation could not complete. Close sign-in windows before verifying; check an uncertain post before retrying.',503) from None
        finally: store.close()
    @app.get('/api/connections/zhihu/status')
    def status(): return work('status',{})
    @app.post('/api/connections/zhihu/{operation}')
    async def action(operation: str, request: Request):
        return await run_in_threadpool(work,operation,await body_parser(request))

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('operation',choices=['login','status']); parser.add_argument('--root',type=Path,default=DEFAULT_ROOT)
    args=parser.parse_args()
    try:
        if args.operation=='login': login(args.root)
        else:
            s=Store(args.root)
            try: print(canonical(s.status()))
            finally: s.close()
    except Exception: print('{"state":"browser_unavailable"}'); sys.exit(1)
