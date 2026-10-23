"""The on-call engine: evaluator alerts in, incidents, escalation steps, deliveries and an audit trail out.

    engine = Engine(policy, store, {'push': p, 'email': e, 'phone': c}, roster=roster)
    engine.process(alerts, now)       # one evaluation (each minute): route, dedupe, suppress, clear, then advance()
    engine.advance(now)               # timers only: due escalation steps, fallbacks
    engine.acknowledge(incident_id, person, channel, now)    # stops the chain; records it
    engine.resolve(incident_id, person, now)
    engine.health(now)                # the dashboard view

Pure apart from the injected store and providers: the caller passes `now` (epoch seconds), so tests and drills run on a
simulated clock. The integration entry point stage() does nothing unless RAFII_ONCALL_ENGINE_ENABLED is exactly 'true'.

Semantics (docs/ops/h07-oncall-policy.json, H07-POLICY-MAP.md):
- Priority: the policy table maps (rule, severity, evidence) to P0, P1 or P2. A live incident's priority only rises; a
  rise restarts an unacknowledged chain at the new priority, and only informs the person who acknowledged one.
- Deduplication: one live incident per dedupe key (rule id, plus the alert's optional 'scope'); every notification has
  a unique delivery key (incident, priority, round.step, person, channel) claimed before the provider is called.
- Suppression: maintenance windows and inhibition (a cause suppresses its symptoms) hold the chain; rules in
  neverSuppress always page. Flapping: an alert back within reopenWithinSeconds reopens the same incident and keeps its
  chain clock, so it neither re-sends step 0 nor escapes escalation. Auto-resolve after resolveAfterClearEvaluations
  clear evaluations, never while a no-data rule fires (absence then proves nothing), never for the engine's own alerts.
- Escalation: steps fire at chain start + after. A duty step counts only duty seconds and fires only in duty hours; its
  outsideHours channels go at once. Each step's person is fixed when the step first fires.
- Fallback: when a step's first channel is not delivered, the next step of the round fires now; when no channel of a
  step is delivered, ONCALL_DELIVERY_FAILED (P0) opens, except for the engine's own alerts (no loops: the heartbeat
  counts those for the external watchdog).
- Storm: per person and channel, at most N notifications per window; the rest wait (pages) or are skipped (records),
  and one summary per window says so.
"""
import re
import uuid

from . import ENV_AUTO_HOLD, ENV_ENABLED, enabled
from .policy import (CHANNELS, RULE, SEVERITIES, duty_seconds, in_duty, on_call, priority_for, rank, roster_problems,
                     validate_roster)
from .providers import ACK_CHANNELS, NOT_DELIVERED, DeliveryResult, NullProvider, ack_token, compose, result, verify_ack_token
from .store import Conflict

META = ('ONCALL_ROSTER_INVALID', 'ONCALL_DELIVERY_FAILED', 'ONCALL_AUTO_HOLD_ENGAGED', 'ONCALL_AUTO_HOLD_FAILED',
        'ONCALL_HEARTBEAT_STALE', 'ONCALL_ENGINE_GAP')
STICKY = tuple(rule for rule in META if rule != 'ONCALL_ROSTER_INVALID')   # resolved by a person, never by absence
LOST_AFTER_SECONDS = 120   # a claimed delivery with no outcome after this counts as not delivered
ACK_LINK_SECONDS = 86400
_SCOPE = re.compile(r'^[A-Za-z0-9_.:-]{1,80}$')


def dedupe_key(alert):
    scope = alert.get('scope')
    return alert['id'] + (':' + scope if isinstance(scope, str) and _SCOPE.match(scope) else '')


def meta_alert(rule, severity, message, **evidence):
    return {'id': rule, 'class': 'ONCALL', 'severity': severity, 'message': message, 'evidence': evidence}


def _clean(text, limit=500):
    return re.sub(r'\s+', ' ', re.sub(r'[^\x20-\x7e]', ' ', str(text or ''))).strip()[:limit]


class Engine:
    def __init__(self, policy, store, providers=None, *, roster=None, ids=None, ack_secret=None, ack_base=None, hold=None,
                 actor='oncall-engine'):
        self.policy, self.store = policy, store
        self.roster = validate_roster(roster) if roster is not None else policy['roster']
        self.providers = {channel: (providers or {}).get(channel) or NullProvider(channel) for channel in CHANNELS}
        self.ids = ids or (lambda: str(uuid.uuid4()))
        self.ack_secret, self.ack_base, self.hold, self.actor = ack_secret, ack_base, hold, actor
        self.claims = 0   # deliveries claimed by this engine (an action list reports only steps that claimed one)

    # --- audit -------------------------------------------------------------------------------------------------------------
    def _event(self, kind, now, incident=None, once=None, actor=None, **detail):
        return self.store.append({'incidentId': incident['id'] if incident else None, 'at': float(now), 'kind': kind,
                                  'actor': actor or self.actor, 'detail': detail}, once=once)

    def _save(self, incident, **changes):
        """Apply changes with the optimistic version; on a conflict, re-read and re-apply once."""
        for attempt in (0, 1):
            row = dict(incident, **changes)
            try:
                return self.store.update_incident(row)
            except Conflict:
                if attempt:
                    raise
                incident = self.store.incident(incident['id'])
                if incident is None:
                    raise
        return None

    # --- evaluation ----------------------------------------------------------------------------------------------------------
    def process(self, alerts, now):
        now = float(now)
        alerts = [dict(a) for a in alerts or () if isinstance(a, dict) and RULE.match(str(a.get('id', ''))) and a.get('severity') in SEVERITIES]
        beat = self.store.heartbeat()
        max_age = self.policy['heartbeat']['maxAgeSeconds']
        if beat and now - float(beat.get('at') or 0) > max_age:
            alerts.append(meta_alert('ONCALL_ENGINE_GAP', 'warn', 'The on-call engine did not run for %d s; alerts in that time were '
                                     'not routed. Check what was missed.' % (now - beat['at']), gapSeconds=round(now - beat['at'])))
        problems = roster_problems(self.policy, self.roster)
        if problems:
            alerts.append(meta_alert('ONCALL_ROSTER_INVALID', 'page', 'The on-call roster cannot carry P0: %s.' % ', '.join(problems),
                                     problems=problems))
        firing = {alert['id'] for alert in alerts}
        no_data = bool(firing & set(self.policy['suppression']['noDataRules']))
        routed = self._route(alerts)
        for key, (alert, priority) in routed.items():
            self.observe(alert, priority, now, key=key, firing=firing)
        if self.hold is not None:
            for alert in self.hold.consider(self, now):
                self.observe(alert, priority_for(alert, self.policy) or 'P0', now)
                routed.setdefault(dedupe_key(alert), (alert, None))
        cleared = []
        for incident in self.store.live():
            if incident['key'] not in routed:
                cleared.extend(self._clear(incident, no_data, now))
        actions = self.advance(now)
        self.beat(now, evaluated=True)
        return {'routed': sorted(routed), 'resolved': cleared, 'actions': actions, 'noData': no_data}

    def _route(self, alerts):
        routed = {}
        for alert in alerts:
            priority = priority_for(alert, self.policy)
            if priority is None:
                continue
            key = dedupe_key(alert)
            if key not in routed or rank(priority) > rank(routed[key][1]):
                routed[key] = (alert, priority)
        return routed

    def suppressed_by(self, rule, firing, now):
        rules = self.policy['suppression']
        if rule in rules['neverSuppress']:
            return None
        for window in rules['maintenance']:
            if window['start'] <= now < window['end'] and ('*' in window['rules'] or rule in window['rules']):
                return 'maintenance'
        for row in rules['inhibit']:
            if row['when'] in firing and rule in row['suppress']:
                return 'inhibit:' + row['when']
        return None

    def observe(self, alert, priority, now, *, key=None, firing=None):
        """Open, refresh, reopen or raise the incident for one routed alert."""
        key = key or dedupe_key(alert)
        firing = firing if firing is not None else {alert['id']}
        suppressed = self.suppressed_by(alert['id'], firing, now)
        incident = self.store.latest(key)
        message = _clean(alert.get('message'))
        if incident and incident['state'] == 'resolved' and now - incident['resolvedAt'] <= self.policy['suppression']['reopenWithinSeconds']:
            state = 'acknowledged' if incident.get('acknowledgedAt') else 'open'
            after = now - incident['resolvedAt']
            incident = self._save(incident, state=state, resolvedAt=None, resolution=None, updatedAt=now)
            self._event('reopened', now, incident, afterSeconds=round(after, 1), state=state)
        if incident is None or incident['state'] == 'resolved':
            row = {'id': self.ids(), 'key': key, 'rule': alert['id'], 'class': _clean(alert.get('class'), 20) or None,
                   'severity': alert['severity'], 'priority': priority, 'state': 'open', 'openedAt': now, 'lastSeenAt': now,
                   'updatedAt': now, 'chainStartedAt': None if suppressed else now, 'suppressedBy': suppressed, 'forcedStep': -1,
                   'clearCount': 0, 'seenCount': 1, 'notified': [], 'steps': {}, 'message': message, 'acknowledgedAt': None,
                   'acknowledgedBy': None, 'ackChannel': None, 'resolvedAt': None, 'resolution': None}
            try:
                incident = self.store.insert_incident(row)
            except Conflict:
                return self.observe(alert, priority, now, key=key, firing=firing)
            self._event('opened', now, incident, priority=priority, severity=alert['severity'], suppressedBy=suppressed)
            return incident
        changes = {'lastSeenAt': now, 'seenCount': incident['seenCount'] + 1, 'clearCount': 0, 'severity': alert['severity'],
                   'message': message}
        events, raised_while_acknowledged = [], False
        if rank(priority) > rank(incident['priority']):
            events.append(('raised', {'from': incident['priority'], 'to': priority}))
            changes['priority'] = priority
            if incident['state'] == 'open':
                changes.update(chainStartedAt=None if suppressed else now, forcedStep=-1, steps={})
            else:
                raised_while_acknowledged = True
        if suppressed and suppressed != incident['suppressedBy']:
            changes['suppressedBy'] = suppressed
            events.append(('suppressed', {'by': suppressed}))
        elif not suppressed and incident['suppressedBy']:
            changes['suppressedBy'] = None
            events.append(('unsuppressed', {'was': incident['suppressedBy']}))
            if incident['state'] == 'open':
                changes.update(chainStartedAt=now, forcedStep=-1)
        elif not suppressed and incident['state'] == 'open' and incident['chainStartedAt'] is None:
            changes['chainStartedAt'] = now
        if events or changes.get('priority'):
            changes['updatedAt'] = now
        incident = self._save(incident, **changes)
        for kind, detail in events:
            self._event(kind, now, incident, **detail)
        if raised_while_acknowledged and incident.get('acknowledgedBy'):
            for channel in ('push', 'email'):
                self._deliver(incident, incident['acknowledgedBy'], channel, 'record',
                              '%s:record:raised-%s:%s:%s' % (incident['id'], incident['priority'], incident['acknowledgedBy'], channel),
                              now, what='raised to %s while acknowledged' % incident['priority'])
        return incident

    def _clear(self, incident, no_data, now):
        if incident['rule'] in STICKY:
            return []
        if no_data and incident['rule'] not in self.policy['suppression']['noDataRules']:
            return []
        count = incident['clearCount'] + 1
        if count >= self.policy['suppression']['resolveAfterClearEvaluations']:
            self._resolve(incident, now, 'auto', self.actor)
            return [incident['id']]
        self._save(incident, clearCount=count)
        return []

    # --- people's actions ----------------------------------------------------------------------------------------------------
    def acknowledge(self, incident_id, person, channel, now, *, version=None):
        now = float(now)
        incident = self.store.incident(incident_id)
        if incident is None:
            return {'ok': False, 'reason': 'not_found'}
        if channel not in ACK_CHANNELS or person not in self.roster['people']:
            reason = 'bad_channel' if channel not in ACK_CHANNELS else 'unknown_person'
            self._event('ack_refused', now, incident, actor='unknown' if reason == 'unknown_person' else person, reason=reason)
            return {'ok': False, 'reason': reason}
        if version is not None and version != incident['version']:
            return {'ok': False, 'reason': 'stale_version'}
        if incident['state'] == 'acknowledged':
            return {'ok': True, 'already': True, 'by': incident['acknowledgedBy']}
        if incident['state'] == 'resolved':
            return {'ok': False, 'reason': 'resolved'}
        incident = self._save(incident, state='acknowledged', acknowledgedAt=now, acknowledgedBy=person, ackChannel=channel, updatedAt=now)
        self._event('acknowledged', now, incident, actor=person, channel=channel, secondsToAcknowledge=round(now - incident['openedAt'], 1))
        if 'acknowledged' in self.policy['records'][incident['priority']]:
            self._records(incident, 'acknowledged', now)
        return {'ok': True, 'incident': incident['id'], 'by': person}

    def acknowledge_token(self, token, now, channel):
        if not self.ack_secret:
            return {'ok': False, 'reason': 'no_ack_secret'}
        found = verify_ack_token(self.ack_secret, token, now)
        if not found:
            self._event('ack_refused', now, None, actor='unknown', reason='bad_token')
            return {'ok': False, 'reason': 'bad_token'}
        return self.acknowledge(found[0], found[1], channel, now)

    def resolve(self, incident_id, person, now):
        incident = self.store.incident(incident_id)
        if incident is None:
            return {'ok': False, 'reason': 'not_found'}
        if person not in self.roster['people']:
            self._event('resolve_refused', now, incident, actor='unknown', reason='unknown_person')
            return {'ok': False, 'reason': 'unknown_person'}
        if incident['state'] == 'resolved':
            return {'ok': True, 'already': True}
        self._resolve(incident, float(now), 'manual', person)
        return {'ok': True}

    def _resolve(self, incident, now, resolution, actor):
        incident = self._save(incident, state='resolved', resolvedAt=now, resolution=resolution, updatedAt=now, clearCount=0)
        self._event('resolved', now, incident, actor=actor, resolution=resolution, acknowledged=bool(incident.get('acknowledgedAt')))
        if 'resolved' in self.policy['records'][incident['priority']]:
            self._records(incident, 'resolved', now)
        return incident

    def _records(self, incident, what, now):
        for person in incident['notified']:
            self._deliver(incident, person, 'email', 'record', '%s:record:%s:%s:email' % (incident['id'], what, person), now, what=what)

    # --- escalation ----------------------------------------------------------------------------------------------------------
    def advance(self, now):
        now, actions, seen = float(now), [], set()
        for _ in range(3):   # a second pass pages an ONCALL_DELIVERY_FAILED opened by the first one at once
            pending = [i for i in self.store.live() if i['id'] not in seen and i['state'] == 'open' and not i['suppressedBy']
                       and i['chainStartedAt'] is not None]
            if not pending:
                break
            for incident in pending:
                seen.add(incident['id'])
                actions.extend(self._escalate(incident, now))
        return actions

    def _escalate(self, incident, now):
        priority = incident['priority']
        chain, repeat = self.policy['escalation'][priority], self.policy['repeat'][priority]
        start, duty_now, duty_elapsed, actions = incident['chainStartedAt'], in_duty(now, self.policy), None, []
        for round_ in range(repeat['rounds']):
            for index, step in enumerate(chain):
                position = round_ * len(chain) + index
                offset = round_ * repeat['periodSeconds'] + step['after']
                forced = position <= incident['forcedStep']
                if step['hours'] == 'duty':
                    if duty_elapsed is None:
                        duty_elapsed = duty_seconds(start, now, self.policy)
                    full = duty_now and (duty_elapsed >= offset or forced)
                    channels = step['channels'] if full else (step['outsideHours'] if not duty_now and now - start >= offset else [])
                else:
                    full = now - start >= offset or forced
                    channels = step['channels'] if full else []
                if not channels:
                    continue
                actions.extend(self._run_step(incident, round_, index, position, step, channels, full, now))
                incident = self.store.incident(incident['id'])
                if incident is None or incident['state'] != 'open' or incident['priority'] != priority:
                    return actions
        return actions

    def _run_step(self, incident, round_, index, position, step, channels, full, now):
        label = '%d.%d' % (round_, index)
        step_key = '%s:%s:%s' % (incident['id'], incident['priority'], label)
        person = incident['steps'].get(label)
        if person is None:
            primary, backup = on_call(now, self.policy, self.roster)
            person = primary if step['to'] == 'primary' else backup
            if person is not None and person in self.roster['people']:
                incident = self._save(incident, steps=dict(incident['steps'], **{label: person}),
                                      notified=incident['notified'] + ([person] if person not in incident['notified'] else []))
        if person is None or person not in self.roster['people']:
            if self._event('no_recipient', now, incident, once=step_key + ':no_recipient', step=label, to=step['to']):
                self._after_step(incident, round_, position, label, ['no_recipient'], now)
            return [{'incident': incident['id'], 'step': label, 'to': step['to'], 'person': None, 'statuses': ['no_recipient']}]
        started = self._event('step', now, incident, once=step_key + (':step' if full else ':outside'), step=label, to=step['to'],
                              person=person, channels=channels, partial=not full)
        claims = self.claims
        statuses = [self._deliver(incident, person, channel, 'page', '%s:%s:%s' % (step_key, person, channel), now, step=label)
                    for channel in channels]
        self._after_step(incident, round_, position, label, statuses, now)
        if not started and claims == self.claims:
            return []
        return [{'incident': incident['id'], 'rule': incident['rule'], 'priority': incident['priority'], 'step': label, 'to': step['to'],
                 'person': person, 'channels': channels, 'statuses': statuses}]

    def _after_step(self, incident, round_, position, label, statuses, now):
        chain = self.policy['escalation'][incident['priority']]
        last_in_round = (round_ + 1) * len(chain) - 1
        failed = [status in NOT_DELIVERED or status == 'no_recipient' for status in statuses]
        if (failed and failed[0] and self.policy['fallback']['escalateNowWhenFirstChannelFails'] and position < last_in_round
                and incident['forcedStep'] < position + 1):
            incident = self._save(incident, forcedStep=position + 1)
            self._event('fallback', now, incident, fromStep=label, status=statuses[0])
        if failed and all(failed):
            if incident['rule'] in META:
                self._event('delivery_failed', now, incident, once='%s:%s:meta-loop' % (incident['id'], label), step=label)
            else:
                alert = meta_alert('ONCALL_DELIVERY_FAILED', 'page', 'No channel delivered step %s of %s (%s) to its person.'
                                   % (label, incident['rule'], incident['priority']), rule=incident['rule'], step=label)
                if self._event('delivery_failed', now, incident, once='%s:%s:%s:failed' % (incident['id'], incident['priority'], label), step=label):
                    self.observe(alert, priority_for(alert, self.policy) or 'P0', now)

    # --- delivery ------------------------------------------------------------------------------------------------------------
    def _deliver(self, incident, person, channel, kind, key, now, *, step=None, what=None):
        existing = self.store.delivery(key)
        if existing:
            if existing['status'] == 'pending' and now - existing['claimedAt'] > LOST_AFTER_SECONDS:
                return 'lost'
            return existing['status']
        storm = self.policy['suppression']['storm']
        limit = storm['limits'].get(channel)
        if limit and kind != 'summary' and self.store.recent(person, channel, now - storm['windowSeconds']) >= limit:
            if kind == 'record':
                self._event('storm_skipped', now, incident, once=key + ':skipped', person=person, channel=channel, what=what)
            else:
                self._event('storm_held', now, incident, once=key + ':held', person=person, channel=channel, step=step)
            window = int(now // storm['windowSeconds'])
            self._deliver(incident, person, channel, 'summary', 'summary:%s:%s:%d' % (person, channel, window), now)
            return 'held' if kind == 'page' else 'skipped'
        if not self.store.claim({'key': key, 'incidentId': incident['id'], 'person': person, 'channel': channel, 'kind': kind,
                                 'step': step if kind == 'page' else kind, 'claimedAt': now}):
            row = self.store.delivery(key)
            return row['status'] if row else 'pending'
        self.claims += 1
        destination = (self.roster['people'].get(person) or {}).get(channel)
        if destination is None:
            outcome = result('unconfigured', reason='no_destination')
        else:
            link = None
            if self.ack_secret and self.ack_base and kind == 'page':
                link = '%s?t=%s' % (self.ack_base, ack_token(self.ack_secret, incident['id'], person, now + ACK_LINK_SECONDS))
            message = compose(channel, kind, incident, person, destination, zone=self.policy['timeZone'], what=what, ack_url=link,
                              step=step)
            try:
                outcome = self.providers[channel].send(message)
            except Exception:
                outcome = result('failed', reason='provider_exception')
            if not isinstance(outcome, DeliveryResult):
                outcome = result('failed', reason='bad_provider_result')
        self.store.finish(key, outcome.status, outcome.reference, outcome.reason, now)
        self._event('delivery', now, incident, person=person, channel=channel, notice=kind, step=step, status=outcome.status,
                    reason=outcome.reason)
        return outcome.status

    # --- the heartbeat and the dashboard -------------------------------------------------------------------------------------
    def beat(self, now, *, evaluated=False):
        live = self.store.live()
        previous = self.store.heartbeat() or {}
        unacked = [i for i in live if i['priority'] == 'P0' and i['state'] == 'open' and not i['suppressedBy']]
        row = {'version': 1, 'at': float(now), 'lastEvaluationAt': float(now) if evaluated else previous.get('lastEvaluationAt'),
               'open': {p: sum(1 for i in live if i['priority'] == p) for p in ('P0', 'P1', 'P2')},
               'unacknowledgedP0': len(unacked),
               'oldestUnacknowledgedP0Seconds': round(max(now - i['openedAt'] for i in unacked), 1) if unacked else None,
               'deliveryFailures1h': self.store.failures(now - 3600),
               'rosterProblems': roster_problems(self.policy, self.roster),
               'autoHold': 'armed' if self.hold is not None and self.hold.armed else 'off'}
        self.store.save_heartbeat(row)
        return row

    def health(self, now):
        live = self.store.live()
        primary, backup = on_call(now, self.policy, self.roster)
        return {'onCall': {'primary': primary, 'backup': backup}, 'inDuty': in_duty(now, self.policy),
                'live': [{'id': i['id'], 'rule': i['rule'], 'priority': i['priority'], 'state': i['state'], 'openedAt': i['openedAt'],
                          'suppressedBy': i['suppressedBy'], 'version': i['version']} for i in live],
                'heartbeat': self.store.heartbeat(), 'rosterProblems': roster_problems(self.policy, self.roster)}


def heartbeat_alerts(row, now, policy):
    """What an independent watchdog concludes from the engine's heartbeat row alone (the alert about the alerting).
    Any 'page' result should fail the watchdog run."""
    max_age = policy['heartbeat']['maxAgeSeconds']
    if not isinstance(row, dict) or type(row.get('at')) not in (int, float):
        return [meta_alert('ONCALL_HEARTBEAT_STALE', 'page', 'The on-call engine has never written a heartbeat.')]
    out = []
    age = float(now) - row['at']
    if age > max_age:
        out.append(meta_alert('ONCALL_HEARTBEAT_STALE', 'page', 'The on-call engine heartbeat is %d s old: nothing is being routed.'
                              % age, ageSeconds=round(age)))
    if row.get('rosterProblems'):
        out.append(meta_alert('ONCALL_ROSTER_INVALID', 'page', 'The on-call roster cannot carry P0.', problems=list(row['rosterProblems'])))
    if (row.get('deliveryFailures1h') or 0) > 0:
        out.append(meta_alert('ONCALL_DELIVERY_FAILED', 'warn', '%d notifications were not delivered in the last hour.'
                              % row['deliveryFailures1h'], failures=row['deliveryFailures1h']))
    chain = policy['escalation']['P0'][-1]['after']
    oldest = row.get('oldestUnacknowledgedP0Seconds')
    if type(oldest) in (int, float) and oldest > chain + 300:
        out.append(meta_alert('ONCALL_P0_UNACKNOWLEDGED', 'page', 'A P0 has been unacknowledged for %d s, past the whole chain.' % oldest,
                              ageSeconds=oldest))
    return out


def stage(values, alerts, now, *, policy, store, providers, roster=None, hold_executor=None, ack_secret=None, ack_base=None):
    """The founder cron integration point (option A). Nothing happens unless RAFII_ONCALL_ENGINE_ENABLED is exactly
    'true'; the automatic hold additionally needs RAFII_ONCALL_AUTO_HOLD_ENABLED exactly 'true' and an executor."""
    if not enabled(values, ENV_ENABLED):
        return {'skipped': 'disabled'}
    hold = None
    if enabled(values, ENV_AUTO_HOLD) and hold_executor is not None:
        from .autohold import AutoHold
        hold = AutoHold(policy, hold_executor)
    engine = Engine(policy, store, providers, roster=roster, hold=hold, ack_secret=ack_secret, ack_base=ack_base)
    return engine.process(alerts, now)
