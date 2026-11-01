"""Portable isolated PostgreSQL suites; full logs; a new cluster per group."""
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import sys
import tempfile
import time
ROOT=Path(__file__).resolve().parents[1]
PG=Path(os.environ.get('POSTRIFF_PG_BIN','/opt/homebrew/opt/postgresql@17/bin'))
DSN='host=127.0.0.1 port=55438 dbname=postgres'
os.environ['LC_ALL']='C';os.environ['POSTRIFF_RESEARCH']='0'

OWNED_CLOUD_ONLY={
    'postgres_discord_authorization.py':'bash scripts/discord-p4-validation-cloud.sh',
    'postgres_discord_connections.py':'bash scripts/discord-p4-validation-cloud.sh',
    'postgres_discord_worker.py':'bash scripts/discord-p4-validation-cloud.sh',
    'postgres_discord_rate_limits.py':'bash scripts/discord-p4-validation-cloud.sh',
    'postgres_discord_capacity.py':'bash scripts/discord-capacity-cloud.sh with an explicit predeclared stage',
    'postgres_discord_admission_index_probe.py':'bash scripts/discord-validation-cloud.sh --scope-store-probe (diagnostic only)',
    'postgres_discord_engagement.py':'bash scripts/discord-p4-validation-cloud.sh',
}

def select_scripts(candidates, requested):
    # These fixtures require their own owned directory/role/egress proof. They
    # cannot inherit a generic cluster or have that safety boundary weakened.
    for name,route in OWNED_CLOUD_ONLY.items():
        if Path(name).stem in requested:
            raise ValueError('Use the guarded cloud route: '+route)
    selected=[p for p in candidates if p.name not in OWNED_CLOUD_ONLY]
    return [p for p in selected if p.stem in requested] if requested else selected

def main():
    if not (PG/'initdb').is_file():
        print(json.dumps({'status':'VALIDATION_UNAVAILABLE','reason':f'{PG}/initdb missing; set POSTRIFF_PG_BIN'}));return 3
    # Browser seed helpers require their own CLI arguments; only integration
    # suites belong in this runner's disposable-cluster catalogue.
    scripts=[p for p in sorted((ROOT/'tests/phase2').glob('postgres_*.py')) if p.name not in ('postgres_repository.py','postgres_safety.py')]
    scripts=select_scripts(scripts,sys.argv[1:])
    if not scripts: raise ValueError('No selected PostgreSQL tests')
    print(json.dumps({'ordinaryFixtureCount':len(scripts),'ownedCloudOnlyRoutes':OWNED_CLOUD_ONLY,
        'discordP0P4':'Required separately by consumer-ready workflow; capacity uses explicit P8 jobs'}),flush=True)
    results=[]
    for script in scripts:
        with tempfile.TemporaryDirectory(prefix='consumer-pg-') as tmp:
            data=Path(tmp)/'data'
            subprocess.run([str(PG/'initdb'),'-D',str(data),'-A','trust','--no-locale','-E','UTF8'],check=True,stdout=subprocess.DEVNULL)
            server_log=Path(tmp)/'postgres.log'
            try:
                subprocess.run([str(PG/'pg_ctl'),'-D',str(data),'-l',str(server_log),'-o','-h 127.0.0.1 -p 55438 -k '+shlex.quote(tmp),'-w','start'],check=True,stdout=subprocess.DEVNULL)
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
