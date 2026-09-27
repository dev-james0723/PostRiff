"""Synthetic notification state for the loopback-only browser harness; no provider or model call."""
import json
import sys
import time
import uuid
import psycopg
from postriff_phase2.notifications import store

action, port, principal, workspace = sys.argv[1:]
assert port.isdigit() and 1024 <= int(port) <= 65535
principal, workspace = str(uuid.UUID(principal)), str(uuid.UUID(workspace))
with psycopg.connect(f'host=127.0.0.1 port={port} dbname=postgres') as db:
    cur = db.cursor()
    cur.execute('SELECT 1 FROM pr_memberships WHERE workspace_id=%s AND user_id=%s AND status=\'active\'',(workspace,principal))
    assert cur.fetchone(), 'Only the synthetic caller workspace'
    if action=='seed':
        cur.execute("INSERT INTO pr_push_subscriptions(user_id,endpoint_sha256,endpoint_ciphertext,p256dh_ciphertext,auth_ciphertext,key_id) VALUES(%s,%s,'synthetic','synthetic','synthetic','synthetic') ON CONFLICT DO NOTHING",(principal,uuid.uuid4().hex*2))
        result=store.emit(cur,workspace_id=workspace,event_type='publish.failed',dedupe_key='browser:'+uuid.uuid4().hex,
                          payload={'href':'/app/channels'},now=time.time(),email_available=False,push_enabled=True,
                          sms_context_for=lambda c,r,_e:store.sms_context(c,r['userId'],enabled=True,escalation_enabled=True))
        print(json.dumps(result))
    elif action=='state':
        cur.execute("SELECT channel,status,failure_detail FROM pr_notification_deliveries WHERE user_id=%s AND workspace_id=%s ORDER BY created_at",(principal,workspace))
        print(json.dumps({'deliveries':[dict(zip(('channel','status','reason'),r)) for r in cur.fetchall()]}))
    elif action=='stop':
        from postriff_phase2.notifications.sms_delivery import provider_stop
        cur.execute('SELECT phone_hash FROM pr_phone_numbers WHERE user_id=%s',(principal,))
        provider_stop(cur,principal,cur.fetchone()[0])
        print(json.dumps({'execution':'synthetic provider-stop settings state'}))
    else: raise ValueError('Unknown local fixture action')
