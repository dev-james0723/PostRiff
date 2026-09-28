"""Portable isolated PostgreSQL suites; full logs; a new cluster per group."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
ROOT=Path(__file__).resolve().parents[1]
PG=Path(os.environ.get('POSTRIFF_PG_BIN','/opt/homebrew/opt/postgresql@17/bin'))
DSN='host=127.0.0.1 port=55438 dbname=postgres'
os.environ['LC_ALL']='C';os.environ['POSTRIFF_RESEARCH']='0'

def main():
    if not (PG/'initdb').is_file():
        print(json.dumps({'status':'VALIDATION_UNAVAILABLE','reason':f'{PG}/initdb missing; set POSTRIFF_PG_BIN'}));return 3
    # Browser seed helpers require their own CLI arguments; only integration
    # suites belong in this runner's disposable-cluster catalogue.
    scripts=[p for p in sorted((ROOT/'tests/phase2').glob('postgres_*.py')) if p.name not in ('postgres_repository.py','postgres_safety.py')]
    if sys.argv[1:]: scripts=[p for p in scripts if p.stem in sys.argv[1:]]
    if not scripts: raise ValueError('No selected PostgreSQL tests')
    results=[]
    for script in scripts:
        with tempfile.TemporaryDirectory(prefix='consumer-pg-') as tmp:
            data=Path(tmp)/'data'
            subprocess.run([str(PG/'initdb'),'-D',str(data),'-A','trust','--no-locale','-E','UTF8'],check=True,stdout=subprocess.DEVNULL)
            server_log=Path(tmp)/'postgres.log'
            try:
                subprocess.run([str(PG/'pg_ctl'),'-D',str(data),'-l',str(server_log),'-o','-h 127.0.0.1 -p 55438','-w','start'],check=True,stdout=subprocess.DEVNULL)
            except subprocess.CalledProcessError:
                # TemporaryDirectory otherwise removes the only startup diagnostic.
                # This cluster has no application credentials or customer records.
                if server_log.exists():print(server_log.read_text(),flush=True)
                raise
            try:
                subprocess.run([str(PG/'psql'),DSN,'-v','ON_ERROR_STOP=1','-q','-f',str(ROOT/'tests/phase2/rls.sql')],check=True,stdout=subprocess.DEVNULL)
                group=[script]
                if script.name=='postgres_plan_guards.py':group.insert(0,ROOT/'tests/phase2/postgres_repository.py')
                if script.name=='postgres_instagram_lifecycle.py':group.append(ROOT/'tests/phase2/postgres_safety.py')
                for path in group:
                    print('RUN '+str(path.relative_to(ROOT)),flush=True);start=time.monotonic()
                    result=subprocess.run([sys.executable,str(path)],cwd=ROOT,env={**os.environ,'POSTRIFF_TEST_DSN':DSN})
                    results.append({'script':str(path.relative_to(ROOT)),'exitCode':result.returncode,'seconds':round(time.monotonic()-start,2)})
            finally:
                subprocess.run([str(PG/'pg_ctl'),'-D',str(data),'-m','fast','-w','stop'],check=True,stdout=subprocess.DEVNULL)
    print(json.dumps({'execution':'local-db; synthetic external services','results':results}),flush=True)
    return int(any(r['exitCode'] for r in results))
if __name__=='__main__':sys.exit(main())
