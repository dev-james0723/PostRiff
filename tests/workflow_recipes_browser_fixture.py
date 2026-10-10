"""Synthetic signed-session claims and data for cloud-only disposable recipe browser acceptance."""
import json
import os
import sys
import time
import uuid
from pathlib import Path


def seed(service, verifier, dsn):
    if sys.platform!='linux' or os.environ.get('CI')!='true' or 'port=55479' not in dsn or '127.0.0.1' not in dsn:
        raise RuntimeError('Recipe fixture requires cloud Linux and the disposable loopback database')
    from postriff_phase2.agent_runtime_v2 import agent_permissions, domain_tools
    root=Path(__file__).resolve().parents[1]
    with service.repository.connection_factory() as db:
        for name in ('102_agent_ui_artifacts.sql','108_agent_tasks.sql','113_workflow_recipes.sql'):
            db.execute((root/'migrations/postriff'/name).read_text())
    domain_tools.ensure_registered()
    # A dev identity is explicitly a fixture, not production reauthentication proof.
    started=time.time()
    verifier.method_time=lambda token,principal:('password',started)
    verifier.aal=lambda token,principal:'aal2'
    items=[]
    for engine in ('chromium','webkit'):
        for width in (1440,390):
            principal=str(uuid.uuid5(uuid.NAMESPACE_URL,f'workflow-recipe-browser/{engine}/{width}'))
            token='dev:'+principal
            w=service.bootstrap(token,'studio')['workspaceId']
            with service.repository.transaction(token,w) as (cur,row,actor):
                agent_permissions.apply_decision(cur,workspace_id=w,principal=actor,member=service.ideas._member(row),state=service.ideas._state(row),token=token,
                    payload={'preset':'recommended','expectedEpoch':0,'consentVersion':agent_permissions.CONSENT_VERSION,'copyDigest':agent_permissions.COPY_DIGEST,
                             'confirmed':True,'source':'settings','idempotencyKey':'browser-'+uuid.uuid4().hex},now=time.time(),mode='enforce')
                asset=uuid.uuid4().hex
                cur.execute("INSERT INTO public.pr_library_assets(id,workspace_id,created_by,original_filename,display_title,kind,mime,extension,bytes,bucket,object_name,processing_status,summary) VALUES(%s,%s,%s,'notes.txt','Rehearsal notes','document','text/plain','txt',20,'postriff-library',%s,'ready','SECRET FILE BODY NOT IN REPORT')",(asset,w,actor,asset+'.txt'))
            items.append({'engine':engine,'width':width,'principal':principal,'workspaceId':w,'assetId':asset})
    allowlist=','.join(item['workspaceId'] for item in items)
    os.environ.update(RAFII_AGENT_V2_ENABLED='1',RAFII_TASK_ENGINE_ENABLED='1',RAFII_TASK_ENGINE_AUTHORITATIVE='1',RAFII_TASK_ENGINE_WORKSPACES=allowlist,
                      RAFII_AGENT_PERMISSIONS_ENABLED='1',RAFII_AGENT_PERMISSIONS_ENFORCED='1',RAFII_AGENT_PERMISSIONS_WORKSPACES=allowlist,
                      RAFII_WORKFLOW_RECIPES_ENABLED='1',RAFII_WORKFLOW_RECIPES_WORKSPACES=allowlist)
    Path(os.environ['RAFII_RECIPE_EVIDENCE']).joinpath('fixture.json').write_text(json.dumps(items))
