"""Synthetic in-app events for the isolated notification browser run. No provider call."""
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
    cur.execute("SELECT 1 FROM pr_memberships WHERE workspace_id=%s AND user_id=%s AND status='active'", (workspace, principal))
    assert cur.fetchone(), 'Only the synthetic caller workspace'
    if action == 'clear':
        cur.execute('DELETE FROM pr_notification_events WHERE workspace_id=%s', (workspace,))
        result = {'cleared': True}
    elif action.startswith('seed-'):
        kinds = {
            'seed-one': [('publish.verified', 'Post published', '/app/analytics')],
            'seed-three': [
                ('campaign.approval_required', 'Draft needs approval', '/app/queue'),
                ('publish.failed', 'Publishing failed', '/app/channels'),
                ('publish.verified', 'Post published', '/app/analytics'),
            ],
            'seed-four': [
                ('campaign.approval_required', 'Draft needs approval', '/app/queue'),
                ('publish.failed', 'Publishing failed', '/app/channels'),
                ('security.new_device', 'New device sign-in', '/app/account/profile'),
                ('publish.verified', 'Post published', '/app/analytics'),
            ],
        }[action]
        cur.execute('DELETE FROM pr_notification_events WHERE workspace_id=%s', (workspace,))
        result = []
        for kind, title, href in kinds:
            result.append(store.emit(
                cur, workspace_id=workspace, event_type=kind,
                dedupe_key='notification-browser:' + uuid.uuid4().hex,
                payload={'title': title, 'href': href, 'reason': 'Synthetic acceptance event.'},
                actor=principal, now=time.time(), email_available=False, push_enabled=False,
                channel_filter={'in_app'},
            ))
    else:
        raise ValueError('Unknown local fixture action')
    print(json.dumps(result))
