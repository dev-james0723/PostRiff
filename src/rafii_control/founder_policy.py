"""Fresh-MFA settings for the owner's internal tenant, with CAS and audit history."""
import json
import uuid
import time
from types import SimpleNamespace
from postriff_alpha.domain import AlphaError
from postriff_phase2 import founder_policy as policy
from postriff_phase2.billing import ops_metadata
from postriff_phase2.hosted import audit
from . import founder_ops, http
from .auth import ControlError


def sync_defaults(app, workspace, operator, settings, now):
    """Commit contact defaults and the two future briefing slots atomically.
    The revision receipt makes a crash between the two databases recoverable.
    Existing delivery consent and channel switches are preserved.
    """
    get_store = getattr(app, 'founder_store', None)
    if not callable(get_store):
        return 'unavailable'
    store = get_store().store
    from .founder_schedules import next_occurrence
    try:
        with store.transaction() as con:
            con.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', ('founder_ops:' + store.environment + ':' + operator,))
            row = con.execute('SELECT policy_revision FROM rafii_control.founder_settings WHERE operator_id=%s AND environment=%s', (operator, store.environment)).fetchone()
            if row and row['policy_revision'] >= settings['revision']:
                return 'applied'
            con.execute('INSERT INTO rafii_control.founder_contact_policy(operator_id,environment,quiet_start,quiet_end,time_zone,daily_cap,concurrent_cap,budget_usd_micro_daily) '
                        'VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(operator_id,environment) DO UPDATE SET '
                        'quiet_start=excluded.quiet_start,quiet_end=excluded.quiet_end,time_zone=excluded.time_zone,daily_cap=excluded.daily_cap,'
                        'concurrent_cap=excluded.concurrent_cap,budget_usd_micro_daily=excluded.budget_usd_micro_daily,revision=founder_contact_policy.revision+1,updated_at=now()',
                        (operator, store.environment, settings['quietStart'], settings['quietEnd'], settings['timeZone'], settings['automaticCallAttemptsDaily'],
                         settings['concurrentCalls'], settings['dailySpendUsdMicro'] if settings['dailySpendMode'] == 'limited' else 10_000_000_000))
            for kind, local_time, weekdays in (('daily', settings['dailyBriefingTime'], list(range(7))),
                                               ('weekly', settings['weeklyReviewTime'], [settings['weeklyReviewDay']])):
                schedule_id = str(uuid.uuid5(uuid.UUID(workspace), 'founder-default:' + kind))
                # Preserve independent schedules the owner already configured;
                # they need explicit reconciliation before a second slot appears.
                existing = con.execute('SELECT id::text AS id FROM rafii_control.founder_briefing_schedules WHERE operator_id=%s AND environment=%s AND kind=%s AND id<>%s',
                                       (operator, store.environment, kind, schedule_id)).fetchone()
                if existing:
                    raise ControlError('REVISION_CONFLICT', 409)
                due = next_occurrence({'local_time': local_time, 'weekdays': weekdays, 'time_zone': settings['timeZone']}, now)['scheduledFor']
                con.execute('INSERT INTO rafii_control.founder_briefing_schedules(id,operator_id,environment,kind,local_time,weekdays,time_zone,next_at) '
                            'VALUES(%s,%s,%s,%s,%s,%s,%s,to_timestamp(%s)) ON CONFLICT(id) DO UPDATE SET '
                            'local_time=excluded.local_time,weekdays=excluded.weekdays,time_zone=excluded.time_zone,next_at=excluded.next_at,revision=founder_briefing_schedules.revision+1',
                            (schedule_id, operator, store.environment, kind, local_time, weekdays, settings['timeZone'], due))
            con.execute('UPDATE rafii_control.founder_settings SET policy_revision=%s,updated_at=now() WHERE operator_id=%s AND environment=%s',
                        (settings['revision'], operator, store.environment))
        return 'applied'
    except Exception:
        return 'pending'


def _workspace(app, principal):
    operator = principal['operator']['user_id']
    workspace, _ = founder_ops.resolve(getattr(app, 'flags', None) or {}, founder_ops._store(app), operator)
    if not workspace:
        raise founder_ops.OpsPolicyDisabled('ops_workspace_not_ready')
    return workspace, operator


def _factory(app):
    if getattr(app, 'runtime', None) is None:
        raise ControlError('SOURCE_UNAVAILABLE', 503)
    return founder_ops._consumer_factory(app.consumer())


def _read(cur, workspace, operator):
    marker = ops_metadata(cur, workspace)
    if not marker or marker['operatorId'] != operator:
        raise ControlError('SCOPE_DENIED', 403)
    current = marker.get('policy')
    settings = policy.policy_from_marker(marker) if current else policy.defaults()
    return marker, settings, bool(current)


def _public(cur, workspace, settings, applied):
    spend = policy.spending(cur, workspace, settings)
    cur.execute("SELECT provider,model,coalesce(meta->>'service',dimension) AS service,coalesce(meta->>'action',dimension) AS action,"
                "(at AT TIME ZONE %s)::date::text AS day,sum(actual_usd_micro) AS actual,count(*) AS entries "
                "FROM public.pr_usage_ledger WHERE workspace_id=%s AND cost_state='actual' AND at>now()-interval '60 days' "
                "GROUP BY provider,model,service,action,day ORDER BY day DESC,provider,model LIMIT 250", (settings['timeZone'], workspace))
    ledger = [{'provider': r[0], 'model': r[1], 'service': r[2], 'action': r[3], 'date': r[4],
               'actualUsdMicro': int(r[5]), 'entries': int(r[6])} for r in cur.fetchall()]
    return {'workspaceId': workspace, 'settings': settings, 'applied': applied, 'revision': settings['revision'] if applied else 0,
            'spending': spend, 'ledger': ledger, 'ledgerWindowDays': 60,
            'historyRetention': 'immutable', 'channelsActivated': False}


def get_policy(app, principal, request):
    workspace, operator = _workspace(app, principal)
    try:
        with _factory(app)() as db:
            with db.cursor() as cur:
                _, settings, applied = _read(cur, workspace, operator)
                return _public(cur, workspace, settings, applied)
    except ControlError:
        raise
    except Exception as error:
        founder_ops._unavailable(error)


def save_policy(app, principal, request):
    body = request.get('body') or {}
    if body.get('mode') != 'live' or set(body) != {'mode', 'revision', 'changes'} or type(body['revision']) is not int:
        raise ControlError('VALIDATION_FAILED', 400)
    workspace, operator = _workspace(app, principal)
    try:
        with _factory(app)() as db:
            with db.cursor() as cur:
                cur.execute('SELECT id FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (workspace,))
                _, current, applied = _read(cur, workspace, operator)
                revision = current['revision'] if applied else 0
                if body['revision'] != revision:
                    raise ControlError('REVISION_CONFLICT', 409)
                updated = policy.validate(current, body['changes'])
                updated.update(revision=revision + 1, approvalRef='founder-settings-' + uuid.uuid4().hex)
                cur.execute("UPDATE public.pr_workspaces SET state=jsonb_set(state,'{founderOps,policy}',%s::jsonb),revision=revision+1 WHERE id=%s",
                            (json.dumps(updated), workspace))
                audit(cur, workspace, operator, 'founder.settings.changed', '', {'previousRevision': revision, 'settings': {k: v for k, v in updated.items() if k != 'replyTo'}, 'replyToConfigured': bool(updated['replyTo'])})
                result = _public(cur, workspace, updated, True)
            db.commit()
        result['defaultSync'] = sync_defaults(app, workspace, operator, updated, request.get('now', time.time()))
        return result
    except ControlError:
        raise
    except AlphaError as error:
        raise ControlError('VALIDATION_FAILED', error.status) from None
    except Exception as error:
        founder_ops._unavailable(error)


http.register_route('GET', r'/founder-policy', 'control.read', 'founder_policy', 'get_policy', demo_ok=True)
http.register_route('PUT', r'/founder-policy', 'control.settings', 'founder_policy', 'save_policy', budget='founder.action')


def sync_stage(fstore, service, values, now):
    app = SimpleNamespace(queries=SimpleNamespace(store=fstore.store), flags=values, runtime=lambda: service,
                          consumer=lambda: service, founder_store=lambda: fstore)
    states = []
    for row in fstore.founder_operators()[:20]:
        try:
            operator = str(row['user_id'])
            workspace, _ = founder_ops.resolve(values, fstore.store, operator)
            if not workspace:
                continue
            with _factory(app)() as db, db.cursor() as cur:
                _, settings, applied = _read(cur, workspace, operator)
            if applied:
                states.append(sync_defaults(app, workspace, operator, settings, now))
        except Exception:
            states.append('unavailable')
    return {'states': states, 'channelsActivated': False}


from .founder_cron import register_stage
register_stage('founder_policy_defaults', sync_stage)
