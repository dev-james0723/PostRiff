"""Transactional relational projection of workspace planning; JSON remains the read contract."""
import json


def sync(cur, workspace_id, before, state, actor):
    planning = state.get('raffi', {}).get('campaignPlanning', {})
    for item in planning.get('campaigns', []):
        cur.execute('INSERT INTO public.pr_campaigns(id,workspace_id,version,status,body,created_by) VALUES(%s,%s,%s,%s,%s::jsonb,%s) ON CONFLICT(id) DO UPDATE SET version=excluded.version,status=excluded.status,body=excluded.body,updated_at=now() WHERE pr_campaigns.workspace_id=excluded.workspace_id',
                    (item['id'], workspace_id, item['version'], item['status'], json.dumps(item), item['createdBy']))
    for item in planning.get('recurringTasks', []):
        cur.execute('INSERT INTO public.pr_recurring_tasks(id,workspace_id,campaign_id,version,status,body,next_at,created_by) VALUES(%s,%s,%s,%s,%s,%s::jsonb,to_timestamp(%s),%s) ON CONFLICT(id) DO UPDATE SET version=excluded.version,status=excluded.status,body=excluded.body,next_at=excluded.next_at,updated_at=now() WHERE pr_recurring_tasks.workspace_id=excluded.workspace_id',
                    (item['id'], workspace_id, item['campaignId'], item['version'], item['status'], json.dumps(item), (item.get('nextOccurrence') or {}).get('scheduledFor'), item['createdBy']))
    for item in planning.get('occurrences', []):
        cur.execute('INSERT INTO public.pr_recurring_occurrences(id,workspace_id,task_id,task_version,scheduled_for,state,idempotency_key,body) VALUES(%s,%s,%s,%s,to_timestamp(%s),%s,%s,%s::jsonb) ON CONFLICT(id) DO UPDATE SET state=excluded.state,body=excluded.body WHERE pr_recurring_occurrences.workspace_id=excluded.workspace_id',
                    (item['id'], workspace_id, item['taskId'], item['taskVersion'], item['scheduledFor'], item['state'], item['idempotencyKey'], json.dumps(item)))
    for item in state.get('raffi', {}).get('suggestions', []):
        cur.execute('INSERT INTO public.pr_suggestions(id,workspace_id,identity,status,body) VALUES(%s,%s,%s,%s,%s::jsonb) ON CONFLICT(workspace_id,identity) DO UPDATE SET status=excluded.status,body=excluded.body,updated_at=now()',
                    (item['id'], workspace_id, item['identity'], item['status'], json.dumps(item)))
