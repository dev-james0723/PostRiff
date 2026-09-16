"""Free text-only X publishing through X's web composer and native scheduler.

The browser profile is isolated and persistent. No X API, cookies export, paid
credits, blind retry, or generic-success inference is used.
"""
from __future__ import annotations
import contextlib, fcntl, hashlib, json, os, re, sqlite3, subprocess, sys, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path

VERSION = 'x-browser/1'
DEFAULT_ROOT = Path.home() / 'Library/Application Support/JamesAuStudio/x-browser'

class Stop(ValueError): pass
def canonical(v): return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def digest(v): return hashlib.sha256(canonical(v).encode()).hexdigest()

def profile(value):
    if not isinstance(value,str): raise Stop('invalid_profile')
    value=value.strip()
    if value.startswith('https://x.com/'): value=value.removeprefix('https://x.com/')
    value=value.lstrip('@')
    if not re.fullmatch(r'[A-Za-z0-9_]{1,15}',value): raise Stop('invalid_profile')
    return 'https://x.com/'+value

def scheduled_at(value):
    if value is None: return None
    if not isinstance(value,str): raise Stop('invalid_schedule')
    try: dt=datetime.fromisoformat(value.replace('Z','+00:00'))
    except ValueError: raise Stop('invalid_schedule') from None
    if dt.tzinfo is None or dt.astimezone(timezone.utc).timestamp() < time.time()+120: raise Stop('invalid_schedule')
    return dt.astimezone(timezone.utc).isoformat().replace('+00:00','Z')

def manifest(account,text,when=None):
    if not isinstance(text,str) or not text.strip() or len(text)>280 or any(ord(c)<32 and c not in '\n\t' for c in text): raise Stop('invalid_text')
    at=scheduled_at(when)
    return dict(version=VERSION,channel='x',nativeFormat='x.post',profile=profile(account),text=text,
                audience='public',timing='scheduled' if at else 'now',scheduledAt=at,media=[],derivatives=[])

def validate(v):
    if not isinstance(v,dict) or v != manifest(v.get('profile'),v.get('text'),v.get('scheduledAt')): raise Stop('invalid_manifest')
    return v

def permalink(value):
    if not isinstance(value,str) or not re.fullmatch(r'https://x\.com/[A-Za-z0-9_]{1,15}/status/[0-9]+',value): raise Stop('invalid_permalink')
    return value

def private_dir(root):
    root=Path(os.path.abspath(root))
    if root.is_symlink(): raise Stop('unsafe_private_path')
    root.mkdir(parents=True,exist_ok=True,mode=0o700); root.chmod(0o700); return root

class Store:
    def __init__(self,root):
        self.root=private_dir(root); p=self.root/'state.sqlite3'
        if p.is_symlink(): raise Stop('unsafe_private_path')
        fd=os.open(p,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600); os.close(fd); p.chmod(0o600)
        self.db=sqlite3.connect(p,isolation_level=None); self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS records (key TEXT PRIMARY KEY,value TEXT NOT NULL)')
    def close(self): self.db.close()
    def get(self,k):
        row=self.db.execute('SELECT value FROM records WHERE key=?',(k,)).fetchone(); return json.loads(row[0]) if row else None
    def put(self,k,v): self.db.execute('INSERT OR REPLACE INTO records VALUES (?,?)',(k,canonical(v))); return v
    @contextlib.contextmanager
    def lock(self):
        fd=os.open(self.root/'browser.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        try:
            try: fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError: raise Stop('browser_busy_close_login_window') from None
            yield
        finally: os.close(fd)
    def status(self):
        c=self.get('connection') or {}; fresh=time.time()-c.get('verifiedAt',0)<900
        return dict(provider='x',route='controlled_browser',routeDriver=VERSION,state='connected_identity' if fresh else 'login_or_verification_required',
                    profile=c.get('profile'),username=c.get('username'),identitySignals=c.get('identitySignals',[]) if fresh else [],
                    publishReady=bool(fresh),publishing=False,liveTestVerified=bool(c.get('liveTestVerified')),cost='free_no_api')

@contextlib.contextmanager
def browser(root):
    from playwright.sync_api import sync_playwright
    edge='/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge'
    edge_data=Path.home()/'Library/Application Support/Microsoft Edge'
    with sync_playwright() as pw:
        ctx=pw.chromium.launch_persistent_context(str(edge_data),executable_path=edge,
                args=['--profile-directory=Profile 3'],headless=False,accept_downloads=False,chromium_sandbox=True)
        try: yield ctx
        finally: ctx.close()

class XUI:
    def __init__(self,ctx): self.ctx=ctx; self.page=ctx.new_page(); self.page.set_default_timeout(12000)
    def one(self,loc):
        try: loc.wait_for(state='visible')
        except Exception: raise Stop('ui_changed') from None
        if loc.count()!=1 or not loc.is_visible(): raise Stop('ui_changed')
        return loc
    def identity(self,account):
        p=self.ctx.new_page(); p.set_default_timeout(12000)
        try:
            p.goto('https://x.com/home',wait_until='domcontentloaded')
            if '/i/flow/login' in p.url: raise Stop('private_handoff_required')
            handle=account.rsplit('/',1)[1]
            self.one(p.locator(f'a[href="/{handle}"]').first)
            self.one(p.get_by_role('button',name='Account menu'))
            return ['authenticated_account_menu','own_profile_link']
        finally: p.close()
    def links(self,account):
        self.page.goto(account,wait_until='domcontentloaded'); handle=account.rsplit('/',1)[1]
        return {'https://x.com'+h for h in self.page.locator(f'a[href^="/{handle}/status/"]').evaluate_all("els=>els.map(e=>e.getAttribute('href')).filter(Boolean)") if re.fullmatch(f'/{re.escape(handle)}/status/[0-9]+',h)}
    def compose(self,text,at):
        self.page.goto('https://x.com/compose/post',wait_until='domcontentloaded')
        box=self.one(self.page.get_by_role('textbox',name='Post text')); box.fill(text)
        if box.inner_text()!=text: raise Stop('rendered_text_mismatch')
        if at:
            self.one(self.page.get_by_role('button',name='Schedule post')).click()
            dt=datetime.fromisoformat(at.replace('Z','+00:00')).astimezone()
            for label,val in [('Month',dt.strftime('%B')),('Day',str(dt.day)),('Year',str(dt.year)),('Hour',str(int(dt.strftime('%I')))),('Minute',dt.strftime('%M')),('AM/PM',dt.strftime('%p'))]:
                self.one(self.page.get_by_role('combobox',name=label)).select_option(label=val)
            self.one(self.page.get_by_role('button',name='Confirm')).click()
            self.one(self.page.get_by_role('button',name='Schedule',exact=True))
        else: self.one(self.page.get_by_role('button',name='Post',exact=True))
    def submit(self,scheduled): self.one(self.page.get_by_role('button',name='Schedule' if scheduled else 'Post',exact=True)).click()
    def verify_post(self,url,value):
        permalink(url); self.page.goto(url,wait_until='domcontentloaded')
        article=self.one(self.page.locator('article').filter(has=self.page.locator(f'a[href="/{value["profile"].rsplit("/",1)[1]}"]')).first)
        if self.one(article.locator('[data-testid="tweetText"]')).inner_text()!=value['text']: raise Stop('wrong_content')
        return dict(permalink=url,textHash=digest(value['text']),independentRead=True)
    def find_new(self,before,value):
        for _ in range(3):
            for url in sorted(self.links(value['profile'])-set(before)):
                try: return self.verify_post(url,value)
                except Stop: pass
            self.page.wait_for_timeout(1500)
        raise Stop('publication_unresolved')
    def verify_scheduled(self,value):
        self.page.goto('https://x.com/compose/post',wait_until='domcontentloaded'); self.one(self.page.get_by_role('button',name='Schedule post')).click(); self.one(self.page.get_by_role('button',name='Scheduled posts')).click()
        if self.page.get_by_text(value['text'],exact=True).count()!=1: raise Stop('scheduled_post_unresolved')
        return dict(scheduledAt=value['scheduledAt'],textHash=digest(value['text']),nativeQueueMatch=True)

def execute(store,value,approved_hash,ui):
    validate(value); key=digest(value)
    if approved_hash!=key: raise Stop('exact_approval_required')
    with store.lock():
        old=store.get(key)
        if old: return old
        ui.identity(value['profile']); before=[] if value['timing']=='scheduled' else sorted(ui.links(value['profile']))
        rec=dict(state='attempting',stage='compose_started',manifest=value,hash=key,previousLinks=before,claimedAt=time.time()); store.put(key,rec)
        try:
            ui.compose(value['text'],value['scheduledAt']); ui.identity(value['profile'])
            rec.update(state='submitting',stage='schedule_started' if value['timing']=='scheduled' else 'submit_started'); store.put(key,rec)
            ui.submit(value['timing']=='scheduled')
            ev=ui.verify_scheduled(value) if value['timing']=='scheduled' else ui.find_new(before,value)
            rec.update(state='scheduled_verified' if value['timing']=='scheduled' else 'published_verified',evidence=ev)
            c=store.get('connection') or {}; store.put('connection',{**c,'liveTestVerified':True})
        except Exception as e: rec.update(state='unknown',reason='reconcile_before_retry',failureCode=str(e) if isinstance(e,Stop) else type(e).__name__)
        return store.put(key,rec)

def login(root):
    s=Store(root)
    try:
        with s.lock():
            # Google rejects Chrome launched by Playwright during federated sign-in.
            # Launch stock Chrome for the private login, while retaining the same
            # isolated profile that controlled runs use after the window closes.
            edge='/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge'
            if not Path(edge).is_file(): raise Stop('edge_not_installed')
            proc=subprocess.Popen([edge,'--user-data-dir='+str(private_dir(Path(root)/'edge-profile')),'--profile-directory=Default',
                                   '--no-first-run','--no-default-browser-check','https://x.com/i/flow/login'],
                                  stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            print(canonical({'state':'private_handoff','browser':'Microsoft Edge native'}),flush=True)
            proc.wait()
    finally: s.close()

def register_routes(app,data_dir,body_parser):
    from fastapi import Request
    from starlette.concurrency import run_in_threadpool
    from .studio import StudioError
    root=Path(data_dir)/'x-browser'
    def work(op,v):
        s=Store(root)
        try:
            if op=='status': return s.status()
            if op=='preview':
                if set(v)!={'profile','text','scheduledAt'}: raise Stop('invalid_request')
                m=manifest(v['profile'],v['text'],v['scheduledAt']); return {'manifest':m,'hash':digest(m),'state':'local_preview'}
            if op=='login':
                if v!={}: raise Stop('invalid_request')
                with s.lock(): pass
                subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'login','--root',str(root)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,stdin=subprocess.DEVNULL,env={k:os.environ[k] for k in ('PATH','HOME','TMPDIR') if k in os.environ},start_new_session=True)
                return {'state':'private_handoff','instruction':'Sign in to X in the dedicated Chrome window, then close it and verify @jamesaucreates in Studio.'}
            if op=='verify':
                if set(v)!={'profile'}: raise Stop('invalid_request')
                account=profile(v['profile'])
                with s.lock(),browser(root) as ctx:
                    signals=XUI(ctx).identity(account); old=s.get('connection') or {}
                    if old.get('profile') not in (None,account): raise Stop('identity_mismatch')
                    s.put('connection',dict(profile=account,username=account.rsplit('/',1)[1],verifiedAt=time.time(),identitySignals=signals,liveTestVerified=old.get('liveTestVerified',False)))
                return s.status()
            if op=='publish':
                if set(v)!={'manifest','approvedHash','publicationConsent'} or v['publicationConsent'] is not True: raise Stop('exact_approval_required')
                m=validate(v['manifest']); c=s.status()
                if c['state']!='connected_identity' or c['profile']!=m['profile']: raise Stop('verify_exact_profile_first')
                with browser(root) as ctx: return execute(s,m,v['approvedHash'],XUI(ctx))
            raise Stop('unsupported_operation')
        except Stop as e: raise StudioError(str(e),'X browser stopped: '+str(e).replace('_',' ')+'.',409) from None
        except Exception: raise StudioError('x_browser_unavailable','X browser operation could not complete; reconcile an uncertain post before retrying.',503) from None
        finally: s.close()
    @app.get('/api/connections/x-browser/status')
    def status(): return work('status',{})
    @app.post('/api/connections/x-browser/{operation}')
    async def action(operation:str,request:Request): return await run_in_threadpool(work,operation,await body_parser(request))

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(); p.add_argument('operation',choices=['login','status']); p.add_argument('--root',type=Path,default=DEFAULT_ROOT); a=p.parse_args()
    if a.operation=='login': login(a.root)
    else:
        s=Store(a.root)
        try: print(canonical(s.status()))
        finally: s.close()
