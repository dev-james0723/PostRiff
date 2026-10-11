"""Disposable SQL legacy automation compatibility; every provider/model is synthetic."""
import json
import os
from pathlib import Path
import runpy
import psycopg

with psycopg.connect(os.environ['POSTRIFF_TEST_DSN']) as db:
    assert db.execute("SELECT to_regclass('public.pr_agent_permission_state'), "
                      "to_regclass('public.pr_agent_grants')").fetchone()==(None,None)

# Retain all existing owner grant, exact approval, pause, revocation and
# independent account assertions. This is compatibility, never real acceptance.
runpy.run_path(str(Path(__file__).with_name('postgres_mastodon_automation.py')),run_name='__main__')
print(json.dumps({'status':'PASS','execution':'disposable SQL; synthetic provider/model',
    'permissionTables':'ABSENT','configuredSecurityModeChanged':False,
    'realMastodonAcceptance':False,'paidModelCalls':0}))
