"""Reproduce the existing Trends/Growth Loop suites on an owned temporary cluster.

External identities/model adapters are synthetic. No production credentials,
provider network calls or application settings are used.
"""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[4]
PG = Path(os.environ.get('POSTRIFF_PG_BIN', '/opt/homebrew/opt/postgresql@17/bin'))
PORT = 56451  # Existing test_trend_integration.py explicitly permits this target.
if any(os.environ.get(k) for k in ('PGSERVICE','PGSERVICEFILE','PGHOSTADDR','PGOPTIONS')):
    raise ValueError('Redirecting PostgreSQL environment is not permitted')
os.chdir(ROOT)
os.environ['LC_ALL']='C'
with socket.socket() as probe:
    probe.bind(('127.0.0.1',PORT))
with tempfile.TemporaryDirectory(prefix='rafii-review-trends-') as tmp:
    data=Path(tmp)/'data'; log=Path(tmp)/'postgres.log'
    subprocess.run([str(PG/'initdb'),'-D',str(data),'-A','trust','--no-locale','-E','UTF8'],check=True,stdout=subprocess.DEVNULL)
    subprocess.run([str(PG/'pg_ctl'),'-D',str(data),'-l',str(log),'-o',f'-h 127.0.0.1 -p {PORT}','-w','start'],check=True,stdout=subprocess.DEVNULL)
    try:
        database='trend_exposure_rafii_'+os.urandom(6).hex()
        subprocess.run([str(PG/'createdb'),'-h','127.0.0.1','-p',str(PORT),database],check=True)
        dsn=f'host=127.0.0.1 port={PORT} dbname={database}'
        subprocess.run([str(PG/'psql'),dsn,'-v','ON_ERROR_STOP=1','-q','-f','tests/phase2/rls.sql'],check=True,stdout=subprocess.DEVNULL)
        env={**os.environ,'PYTHONPATH':'src:tests','TREND_SERVICE_TEST_DSN':dsn,'TREND_EXPOSURE_TEST_DSN':dsn,'POSTRIFF_TEST_DSN':dsn,'POSTRIFF_RESEARCH':'0','POSTRIFF_LOCAL_CLI':'0'}
        results=[subprocess.run([sys.executable,'-m','unittest','test_trend_learning','test_trend_exposures','test_trend_integration'],env=env).returncode,
                 subprocess.run([sys.executable,'tests/phase2/postgres_growth_loop.py'],env=env).returncode]
        print(json.dumps({'sourceSha':os.environ['POSTRIFF_SOURCE_SHA'],'execution':'real isolated PG; synthetic external inputs; zero real model/provider calls','exitCodes':results}))
    finally:
        subprocess.run([str(PG/'pg_ctl'),'-D',str(data),'-m','fast','-w','stop'],check=True,stdout=subprocess.DEVNULL)
raise SystemExit(any(results))
