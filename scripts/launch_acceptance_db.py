"""Run every hosted DB script in its own disposable database, never a live DSN."""
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
OUT=Path(os.environ.get('POSTRIFF_VALIDATION_OUT') or ROOT/'docs/launch-20260923/evidence/continuation/db-suite')
if not OUT.resolve().is_relative_to(ROOT): raise SystemExit('Validation output must stay in this repository.')
OUT.mkdir(parents=True,exist_ok=True)

def fingerprint():
    files=[p for base in ('src','tests/phase2','migrations/postriff') for p in (ROOT/base).rglob('*') if p.is_file() and p.suffix in ('.py','.sql')]
    return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}

before=fingerprint();results=[]
for script in sorted((ROOT/'tests/phase2').glob('postgres*.py')):
    with socket.socket() as probe:
        if probe.connect_ex(('127.0.0.1',55438))==0:
            raise SystemExit('Disposable test port belongs to another process; refusing to interfere.')
    started=time.monotonic()
    prerequisites=['tests/phase2/postgres_repository.py'] if script.name in ('postgres_safety.py','postgres_plan_guards.py') else []
    with (OUT/(script.stem+'.log')).open('w') as log:
        result=subprocess.run([sys.executable,'scripts/postriff_disposable_postgres.py',*prerequisites,str(script.relative_to(ROOT))],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,env={**os.environ,'PYTHONPATH':'src:tests','POSTRIFF_RESEARCH':'0'},timeout=180)
    results.append({'script':str(script.relative_to(ROOT)),'exit':result.returncode,'seconds':round(time.monotonic()-started,2)})
    print(json.dumps(results[-1]),flush=True)
after=fingerprint()
changed=[name for name in set(before)|set(after) if before.get(name)!=after.get(name)]
summary={'results':results,'sourceUnchanged':not changed,'changedDuringTests':changed,'passed':sum(row['exit']==0 for row in results),'failed':[row['script'] for row in results if row['exit']]}
(OUT/'summary.json').write_text(json.dumps(summary,indent=2))
print(json.dumps(summary),flush=True)
sys.exit(0 if not summary['failed'] and not changed else 1)
