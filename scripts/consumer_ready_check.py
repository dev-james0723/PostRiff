"""Run one local gate, preserving full output and source identity. No env loading."""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/consumer-ready/evidence'

def fingerprint():
    files = []
    for folder in ('src', 'skills', '.github', 'api', 'migrations/postriff', 'web/src', 'web/tests', 'tests', 'scripts'):
        files.extend(p for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc')
    files.extend(ROOT/p for p in ('.node-version','requirements.txt','requirements-dev.txt','.python-version','vercel.json','.vercelignore','web/package.json','web/package-lock.json','web/next.config.ts','web/tsconfig.json','web/.nvmrc','docs/consumer-ready/secret-allowlist.json'))
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(set(files)) if p.is_file()}
    return {'sha256': hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest(), 'files': hashes}

def main():
    name, *cmd = sys.argv[1:]
    OUT.mkdir(parents=True,exist_ok=True)
    before = fingerprint(); start = dt.datetime.now(dt.timezone.utc).isoformat(); tick=time.monotonic()
    env = dict(os.environ, PYTHONPATH='src:tests', POSTRIFF_RESEARCH='0')
    # Tests must inject their own external transports; never inherit provider credentials.
    for key in tuple(env):
        if any(term in key for term in ('API_KEY','DATABASE_URL','SUPABASE','STRIPE_SECRET','OAUTH_CLIENT_SECRET','SENTRY_AUTH_TOKEN')):
            env.pop(key)
    with (OUT/f'{name}.log').open('w') as log:
        result = subprocess.run(cmd,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
    after=fingerprint()
    record={'name':name,'command':cmd,'cwd':str(ROOT),'startedAt':start,'finishedAt':dt.datetime.now(dt.timezone.utc).isoformat(),'seconds':round(time.monotonic()-tick,2),'exitCode':result.returncode,'head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'source':before['sha256'],'sourceUnchanged':before==after,'status':'PASS' if result.returncode==0 and before==after else 'FAIL' if result.returncode else 'INVALIDATED','log':str((OUT/f'{name}.log').relative_to(ROOT))}
    (OUT/f'{name}.json').write_text(json.dumps(record,indent=2)+'\n')
    (OUT/f'{name}-source.json').write_text(json.dumps(before,indent=2)+'\n')
    print(json.dumps(record))
    return result.returncode or (0 if before==after else 2)

if __name__=='__main__': sys.exit(main())
