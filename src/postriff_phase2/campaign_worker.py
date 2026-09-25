"""Bounded recurring draft worker. Uses the existing writing pipeline, never publishing APIs directly.

Version 3 (staged) runs go through automation_runs: research, drafting and per-destination items, then the
advance sweep, which queues approved posts only through the Phase 2 review and approve chain (publisher.py)."""
import copy
from contextlib import contextmanager
import datetime as dt
import json
import logging
import time
import zoneinfo

from postriff_alpha.domain import AlphaError
from . import campaigns, insights
from .planning_store import sync
from .permissions import Membership, require


def validate(state, binding):
    if state.get('accountDeletion'):
        raise AlphaError('Account deletion is pending.', 409)
    root = state.get('raffi', {}).get('campaignPlanning', {})
    task = next((t for t in root.get('recurringTasks', []) if t['id'] == binding['taskId']), None)
    campaign = next((c for c in root.get('campaigns', []) if c['id'] == binding['campaignId']), None)
    occurrence = next((o for o in root.get('occurrences', []) if o['id'] == binding['occurrenceId']), None)
    if not task or not campaign or not occurrence or task['status'] != 'active' or occurrence['state'] != 'running' or campaign['version'] != binding['campaignVersion'] or task.get('definitionDigest') != binding['definitionDigest']:
        raise AlphaError('Recurring draft authority changed. Review a new schedule.', 409)


class CampaignWorker:
    def __init__(self, service):
        self.service = service
        self.connection_factory = service.connection_factory
        self.clock = service.clock

    @staticmethod
    def _save(cur, workspace_id, state, actor):
        cur.execute('UPDATE pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s', (json.dumps(state), workspace_id))
        sync(cur, workspace_id, {}, state, actor)

    def _claim(self):
        now = self.clock()
        with self.connection_factory() as db, db.cursor() as cur:
            # The JSON predicate also discovers legacy schedules that predate the relational projection.
            cur.execute("SELECT id::text,state FROM pr_workspaces WHERE NOT state ? 'accountDeletion' AND (EXISTS (SELECT 1 FROM jsonb_array_elements(coalesce(state#>'{raffi,campaignPlanning,recurringTasks}','[]'::jsonb)) t WHERE t->>'status'='active' AND (t#>>'{nextOccurrence,scheduledFor}')::double precision<=%s) OR EXISTS (SELECT 1 FROM jsonb_array_elements(coalesce(state#>'{raffi,campaignPlanning,occurrences}','[]'::jsonb)) o WHERE o->>'state'='running' AND coalesce((o->>'leaseUntil')::double precision,0)<=%s)) ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED", (now, now))
            row = cur.fetchone()
            if not row: return None
            workspace_id, state = row
            root = state['raffi']['campaignPlanning']
            occurrence = next((o for o in root['occurrences'] if o['state'] == 'running' and o.get('leaseUntil', 0) <= now), None)
            due = lambda t: t['status'] == 'active' and (t.get('nextOccurrence') or {}).get('scheduledFor', float('inf')) <= now
            task = next((t for t in root['recurringTasks'] if t['id'] == occurrence['taskId']), None) if occurrence else next((t for t in root['recurringTasks'] if due(t)), None)
            if task is None:
                return None
            actor = task.get('activatedBy') or task['createdBy']
            campaign = next(c for c in root['campaigns'] if c['id'] == task['campaignId'])
            if occurrence is None:
                occurrence = campaigns.claim_occurrence(state, task['id'], task['nextOccurrence']['scheduledFor'], now)
            # Old UI activation granted no concrete writer/cost scope. Never reinterpret it as paid authority.
            if task.get('authorityVersion') not in (1, 2, 3) or task.get('route') == 'local-cli' or campaign['version'] != task.get('campaignVersion') or campaign.get('missingFacts'):
                occurrence.update(state='held', reason='new_preview_required')
                task.update(status='paused', pauseReason='new_preview_required')
                self._save(cur, workspace_id, state, actor)
                return {'held': True}
            # A staged run whose post is still ahead is drafted late instead of missed; one whose post time already
            # passed (PostRiff was down) is skipped, never drafted just to expire.
            publish_at = (occurrence.get('stages') or {}).get('publishAt')
            if campaigns.is_staged(task) and occurrence['state'] == 'pending' and publish_at is not None and publish_at < now - 60:
                occurrence.update(state='cancelled', reason='skipped', lifecycle='skipped')
                campaigns._history(occurrence, now, 'skipped', 'Rafii was unavailable until after this post\'s time, so the run was skipped.')
                campaigns.refresh_next(task, now)
                self._save(cur, workspace_id, state, actor)
                return {'skipped': True}
            late_ok = campaigns.is_staged(task) and (publish_at or 0) > now
            if occurrence['scheduledFor'] < now - 86400 and occurrence['state'] != 'running' and not late_ok:
                occurrence.update(state='missed', reason='over_24_hours_late')
                if occurrence.get('lifecycle'):
                    occurrence['lifecycle'] = 'skipped'
                    campaigns._history(occurrence, now, 'missed', 'Rafii was unavailable for more than a day at this run\'s time, so it was skipped.')
                campaigns.refresh_next(task, now)
                self._save(cur, workspace_id, state, actor)
                return {'missed': True}
            cur.execute("SELECT m.role,m.can_publish,m.can_reply,m.can_moderate,m.can_manage_connections FROM pr_memberships m JOIN pr_profiles p ON p.user_id=m.user_id WHERE m.workspace_id=%s AND m.user_id=%s AND m.status='active' AND p.deleted_at IS NULL", (workspace_id, actor))
            member = cur.fetchone()
            if not member or not Membership.from_row(*member).allows('owner'):
                occurrence.update(state='held', reason='owner_authority_unavailable'); task['status'] = 'paused'
                self._save(cur, workspace_id, state, actor); return {'held': True}
            # Accounts disconnected since activation are skipped with a note; with none left the run is held.
            kept, skipped = campaigns.connected_destinations(state, [task['destination']] if task.get('authorityVersion') == 1 else task['destinations'])
            labels = task.get('accountLabels') or {}
            staged = campaigns.is_staged(task)
            if staged and skipped:
                # A staged run still drafts for a disconnected account (the draft needs no account); its post is
                # blocked as "account disconnected" instead of silently dropped or falsely scheduled.
                kept = kept + [{key: d[key] for key in ('platform', 'language') if key in d} for d in skipped]
                skipped = []
            if skipped:
                occurrence['skippedDestinations'] = [{'platform': d['platform'], 'channelId': d.get('channelId'), 'account': labels.get(d.get('channelId'), '')} for d in skipped]
            if not kept:
                occurrence.update(state='held', reason='destinations_unavailable')
                task.update(status='paused', pauseReason='destinations_unavailable')
                self._save(cur, workspace_id, state, actor)
                return {'held': True}
            if not occurrence.get('conversationId'):
                cur.execute('INSERT INTO pr_conversations(workspace_id,created_by,title) VALUES(%s,%s,%s) RETURNING id::text', (workspace_id, actor, self._title(task, occurrence)))
                occurrence['conversationId'] = cur.fetchone()[0]
            occurrence.update(state='running', leaseUntil=now + 600)
            binding = {'taskId':task['id'], 'campaignId':campaign['id'], 'campaignVersion':campaign['version'], 'definitionDigest':task['definitionDigest'], 'occurrenceId':occurrence['id'], 'maxCostUsdMicro':task['maxCostUsdMicro']}
            if task.get('authorityVersion') in (2, 3):
                binding['contentType'] = task.get('contentType')
            if skipped:
                binding['notes'] = [f"{d['account'] or 'An account'} on {d['platform']} is no longer connected, so this run skipped it." for d in occurrence['skippedDestinations']]
            # Context the activated definition asked for, read now from this workspace only.
            context, extra_sources = {}, []
            countdown = campaigns.countdown_context(task['schedule'], occurrence['scheduledFor'])
            if countdown:
                context['countdown'] = countdown
            days = (task.get('include') or {}).get('recentPostsDays')
            if days:
                context['recentPosts'] = campaigns.recent_posts(state, occurrence['scheduledFor'], days)
            event = occurrence.get('event') or {}
            if event.get('kind') == 'new_source':
                # The new idea, link or document is read as a source of this run (with its usual consent rules).
                extra_sources.append(event['sourceId'])
                context['newMaterial'] = {'title': event.get('title', '')}
            elif event.get('kind') == 'strong_post':
                context['strongPost'] = {'platform': event.get('platform'), 'publishedAt': event.get('publishedAt'), 'text': event.get('text', ''),
                                         'observation': f"{event['value']:g} {event['metric']}, compared with a typical {event['typical']:g} across {event['sampleSize']} comparable posts"}
            if (task.get('include') or {}).get('evergreen'):
                if occurrence.get('evergreen') is None:
                    posts = insights.summary(cur, workspace_id, (state.get('phase2') or {}).get('jobs', []), now)['posts']
                    occurrence['evergreen'] = campaigns.evergreen_post(state, task, occurrence['scheduledFor'], posts) or {}
                    if occurrence['evergreen']:
                        task['evergreenUsed'] = (list(task.get('evergreenUsed') or []) + [occurrence['evergreen']['jobId']])[-200:]
                if occurrence['evergreen']:
                    context['evergreen'] = {key: occurrence['evergreen'][key] for key in ('platform', 'publishedAt', 'text')}
            self._save(cur, workspace_id, state, actor)
            return {'workspaceId':workspace_id, 'actor':actor, 'task':task, 'campaign':campaign, 'occurrence':occurrence, 'binding':binding, 'destinations':kept, 'context':context, 'sources':extra_sources, 'staged':staged}

    @staticmethod
    def _title(task, occurrence):
        """Conversation title: the automation's name and the run's local date (display only, never sent to a writer)."""
        if not task.get('name'):
            return 'Recurring campaign draft'
        try:
            day = dt.datetime.fromtimestamp(occurrence['scheduledFor'], zoneinfo.ZoneInfo(task['schedule']['timeZone'])).strftime('%a %d %b')
        except (KeyError, TypeError, ValueError, zoneinfo.ZoneInfoNotFoundError):
            return task['name'][:100]
        return f"{task['name'][:100]} · {day}"

    def tick(self):
        claim = self._claim()
        if not claim or 'workspaceId' not in claim: return claim or {'idle': True}
        if claim.get('staged'):
            from . import automation_runs
            return automation_runs.generate(self, claim)
        workspace_id, actor, binding = claim['workspaceId'], claim['actor'], claim['binding']
        # A private in-process capability, never a client token or an alternative HTTP authentication path.
        capability = object()
        repository = copy.copy(self.service.repository)
        def verify(token):
            if token is not capability: raise AlphaError('Invalid worker capability.', 403)
            return actor
        repository.verify_session = verify
        base_transaction = repository.transaction
        @contextmanager
        def transaction(token, requested_workspace):
            if requested_workspace != workspace_id: raise AlphaError('Workspace unavailable.', 403)
            with base_transaction(token, requested_workspace) as (cur, row, principal):
                require(Membership.from_row(*row[2:7]), 'owner')
                validate(row[1], binding)
                yield cur, row, principal
        repository.transaction = transaction
        ideas = copy.copy(self.service.ideas)
        ideas.repository = repository
        # Credit checks must read through the same worker-bound repository, not the service's original one.
        from .credit_requests import CreditRequests
        ideas.credit_requests = CreditRequests(ideas)
        ideas.recurring_binding = binding
        task, campaign, occurrence = claim['task'], claim['campaign'], claim['occurrence']
        result = None
        try:
            # No implicit research, fallback writer, publishing plan or extra sources.
            destinations = claim['destinations']
            # Only the activated definition reaches the writer: the brief, never the automation's display name.
            data = {'goal':campaign['goal'], 'audience':campaign['audience'], 'facts':campaign['facts'], **claim.get('context', {})}
            result = ideas.turn(workspace_id, capability, occurrence['conversationId'], {
                'text': self._lead(len(destinations), data) + json.dumps(data, ensure_ascii=False),
                'idempotencyKey':'recurring:' + occurrence['idempotencyKey'], 'model':task['route'], 'reasoning':task.get('reasoning', 'quick'),
                'sourceIds':list(dict.fromkeys(claim.get('sources', []) + task['contextSourceIds'])), 'destinations':destinations,
                'research':False, 'voiceMode':task.get('voiceMode', 'neutral'), 'timeZone':task['schedule']['timeZone'],
            })
        except Exception:
            # Reconcile a committed run even if the HTTP-style call raised after provider I/O.
            with self.connection_factory() as db, db.cursor() as cur:
                cur.execute('SELECT id::text,status FROM pr_agent_runs WHERE workspace_id=%s AND idempotency_key=%s', (workspace_id, 'recurring:' + occurrence['idempotencyKey']))
                run = cur.fetchone()
                if run: result = {'runId':run[0], 'status':run[1]}
        with self.connection_factory() as db, db.cursor() as cur:
            cur.execute('SELECT state FROM pr_workspaces WHERE id=%s FOR UPDATE', (workspace_id,))
            row = cur.fetchone()
            if not row: return {'held': True}
            state = row[0]; root = state['raffi']['campaignPlanning']
            current = next(o for o in root['occurrences'] if o['id'] == occurrence['id'])
            try: validate(state, binding)
            except AlphaError: return {'cancelled': True}
            if result and result['status'] in ('completed', 'applied'):
                cur.execute('SELECT usage FROM pr_agent_runs WHERE id::text=%s', (result['runId'],))
                usage = (cur.fetchone() or [None])[0]
                cost = usage.get('costUsd') if isinstance(usage, dict) else None
                current.update(state='completed', runId=result['runId'], completedAt=self.clock(), draftCount=len(claim['destinations']),
                               costUsdMicro=round(float(cost) * 1_000_000) if isinstance(cost, (int, float)) else 0)
                c = next(c for c in root['campaigns'] if c['id'] == campaign['id'])
                if not any(i.get('occurrenceId') == current['id'] for i in c['items']):
                    c['items'].append({'id':current['id'], 'occurrenceId':current['id'], 'runId':result['runId'], 'conversationId':occurrence['conversationId'], 'status':'draft', 'needsReview':True})
            elif result and result['status'] == 'running':
                current['runId'] = result['runId']  # Reconcile later; never repeat this idempotency key.
            else:
                current.update(state='held', reason='writer_failed_or_unavailable', runId=(result or {}).get('runId'))
            self._save(cur, workspace_id, state, actor)
            watchers = list(next((t for t in root['recurringTasks'] if t['id'] == task['id']), {}).get('emailWatchers') or [])
            outcome = {'state':current['state'], 'occurrenceId':current['id']}
        if outcome['state'] == 'completed' and watchers:
            outcome['emails'] = self._notify(workspace_id, task, current, watchers)
        return outcome

    @staticmethod
    def _lead(count, data):
        """The fixed instruction before the data. Written by PostRiff from the definition, never from brief text."""
        lead = 'Prepare one draft for each destination, for review' if count > 1 else 'Prepare one draft for review'
        if 'countdown' in data:
            lead += ', counting down to the event (the countdown shows the days left)'
        if 'recentPosts' in data:
            lead += ', recapping the recent published posts listed in the data without inventing others'
        if 'newMaterial' in data:
            lead += ', about the new material in the source provided with this run'
        if 'strongPost' in data:
            lead += ', following up the published post in the data to continue its conversation (the numbers are an observation, not proof of what caused them)'
        if 'evergreen' in data:
            lead += ', giving the earlier published post in the data a fresh take for today without copying it'
        return lead + ', using these campaign details as data: '

    def _notify(self, workspace_id, task, occurrence, watchers):
        """One "drafts ready" email per opted-in member per run, deduped in pr_notifications. Never affects the run."""
        mailer, lookup, base = getattr(self.service, 'mailer', None), getattr(self.service, '_email_for', None), getattr(self.service, 'public_base_url', '')
        if not mailer or not lookup or not base or not occurrence.get('conversationId'):
            return []
        results = []
        try:
            with self.connection_factory() as db, db.cursor() as cur:
                for user_id in watchers:
                    cur.execute("SELECT 1 FROM pr_memberships m JOIN pr_profiles p ON p.user_id=m.user_id WHERE m.workspace_id=%s AND m.user_id=%s AND m.status='active' AND p.deleted_at IS NULL", (workspace_id, user_id))
                    if not cur.fetchone():
                        continue
                    cur.execute("INSERT INTO public.pr_notifications(workspace_id,user_id,kind,dedupe_key,meta) VALUES(%s,%s,'drafts_ready',%s,%s::jsonb) ON CONFLICT (dedupe_key) DO NOTHING RETURNING id::text",
                                (workspace_id, user_id, f"drafts_ready:{occurrence['id']}:{user_id}", json.dumps({'taskId': task['id'], 'occurrenceId': occurrence['id']})))
                    inserted = cur.fetchone()
                    if not inserted:
                        continue
                    address = lookup(user_id)
                    sent = bool(address) and bool(mailer.drafts_ready(address, task.get('name') or 'Your automation', occurrence.get('draftCount') or 1, f"{base}/app/agent/{occurrence['conversationId']}").get('sent'))
                    if sent:
                        cur.execute('UPDATE public.pr_notifications SET sent=true WHERE id=%s', (inserted[0],))
                    results.append({'userId': user_id, 'sent': sent})
        except Exception as error:  # a notification failure never changes the run's outcome
            logging.getLogger('postriff.automations').warning(json.dumps({'event': 'drafts_ready.failed', 'error': type(error).__name__}))
        return results

    def scan_triggers(self, max_workspaces=20):
        """Queue events for active triggers: new material in Ideas and strong recent posts. Saves a workspace
        only when something new was seen, so an idle scan never changes its revision."""
        now, queued = self.clock(), 0
        kinds = list(campaigns.EVENT_KINDS)
        with self.connection_factory() as db, db.cursor() as cur:
            cur.execute("SELECT id::text,state FROM pr_workspaces WHERE NOT state ? 'accountDeletion' AND EXISTS (SELECT 1 FROM jsonb_array_elements(coalesce(state#>'{raffi,campaignPlanning,recurringTasks}','[]'::jsonb)) t WHERE t->>'status'='active' AND t#>>'{schedule,kind}' = ANY(%s)) ORDER BY id LIMIT %s FOR UPDATE SKIP LOCKED", (kinds, max_workspaces))
            for workspace_id, state in cur.fetchall():
                tasks = [t for t in state['raffi']['campaignPlanning']['recurringTasks'] if t['status'] == 'active' and campaigns.is_event(t['schedule'])]
                posts, changed, actor = None, False, None
                for task in tasks:
                    if task['schedule']['kind'] == 'on_new_source':
                        events = campaigns.new_source_events(state, task)
                    else:
                        if posts is None:
                            posts = insights.summary(cur, workspace_id, (state.get('phase2') or {}).get('jobs', []), now)['posts']
                        events = campaigns.strong_post_events(state, task, posts, now)
                    before = len(task.get('pendingEvents') or [])
                    if campaigns.enqueue_events(state, task, events, now):
                        changed, actor = True, task.get('activatedBy') or task['createdBy']
                        queued += len(task.get('pendingEvents') or []) - before
                if changed:
                    self._save(cur, workspace_id, state, actor)
        return queued

    def tick_many(self, max_runs=5, max_seconds=90):
        """Cron entry: queue trigger events, then prepare up to `max_runs` due runs (any workspaces) within `max_seconds`."""
        try:
            self.scan_triggers()
        except Exception as error:  # a scan failure never blocks scheduled runs
            logging.getLogger('postriff.automations').warning(json.dumps({'event': 'trigger_scan.failed', 'error': type(error).__name__}))
        started, results = time.monotonic(), []
        while len(results) < max_runs and time.monotonic() - started < max_seconds:
            result = self.tick()
            if result == {'idle': True}:
                break
            results.append(result)
        try:
            # Staged automations: expire, queue and follow posts; resume pauses that ended; send notices.
            from . import automation_runs
            advanced = automation_runs.advance(self)
        except Exception as error:  # a sweep failure never blocks scheduled runs
            logging.getLogger('postriff.automations').warning(json.dumps({'event': 'advance.failed', 'error': type(error).__name__}))
            advanced = {'error': type(error).__name__}
        if not results and not advanced.get('workspaces') and not advanced.get('commits'):
            return {'idle': True}
        return {'runs': results, 'advance': advanced}
