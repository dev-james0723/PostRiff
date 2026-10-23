#!/usr/bin/env python3
"""Evaluate the Discord operations health snapshot against the H-07 alert rules. Standard library only.

    evaluate(snapshot, thresholds, now=None) -> [{'id', 'class', 'severity', 'message', 'evidence'}, ...]

Pure: no network, database or clock of its own except the optional `now` (epoch seconds) used to see whether the
snapshot itself is stale. Rules are data-driven by docs/ops/discord-alert-thresholds.json. Six classes: BACKLOG,
DELIVERY, RATE_LIMIT, SILENT_HALT, CROSS_TENANT and CONFIG. Severity is 'page', 'warn' or 'info' (the meaning for the
person holding the pager is in the thresholds file and docs/ops/PHONE-RUNBOOK.md). A section the snapshot does not
carry (the SQL twin has no process view; a failed section says 'unavailable') makes its rules silent, except that a
missing or failed snapshot is itself a SILENT_HALT page: the absence of the signal is an alarm.

The snapshot is the payload of GET /api/ops/discord/health (src/postriff_phase2/discord/ops.py) or the read-only SQL
twin (docs/ops/discord-ops-snapshot.sql). Fleet-wide numbers that only the function logs know (cross-tenant denials,
lane invocations) can be added under snapshot['fleet'] with parse_logs().

Command line:
    discord_ops_check.py evaluate SNAPSHOT.json [--thresholds FILE] [--phase pre_open|canary|open] [--logs FILE]
                                                [--previous ALERTS.json] [--now EPOCH]
    discord_ops_check.py fetch URL [--timeout 10]   (bearer from DISCORD_OPS_BEARER; prints the snapshot, never the
                                                    bearer; a failed fetch prints an 'unavailable' snapshot)
Exit code of evaluate: 2 when any alert pages, 1 when the worst is a warning, 0 otherwise.
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_THRESHOLDS = ROOT / 'docs' / 'ops' / 'discord-alert-thresholds.json'
SEVERITIES = ('page', 'warn', 'info')
CLASSES = ('BACKLOG', 'DELIVERY', 'RATE_LIMIT', 'SILENT_HALT', 'CROSS_TENANT', 'CONFIG')
PHASES = ('pre_open', 'canary', 'open')
GUARD_KINDS = ('policy', 'global', 'credential', 'invalid')
QUIET_STOPS = ('idle', 'time_budget', 'step_budget', 'rate_wait', 'operator_hold')
LANE_COUNTERS = ('claimed', 'posted', 'verified', 'held', 'uncertain', 'deadLetters', 'rateDelayed', 'leaseLost')
DENIAL_EVENT = 'security.cross_tenant_denied'


def load_thresholds(path=DEFAULT_THRESHOLDS):
    return json.loads(Path(path).read_text())


def _number(value):
    return value if type(value) in (int, float) else None


def _section(snapshot, name):
    value = snapshot.get(name) if isinstance(snapshot, dict) else None
    return value if isinstance(value, dict) and value.get('status', 'observed') not in ('unavailable',) else None


def _alert(rule, cls, severity, message, **evidence):
    return {'id': rule, 'class': cls, 'severity': severity, 'message': message,
            'evidence': {key: value for key, value in evidence.items() if value is not None}}


def _over(value, warn, page):
    """'page' when value >= page, 'warn' when value >= warn, else None (None thresholds are off)."""
    if value is None:
        return None
    if page is not None and value >= page:
        return 'page'
    if warn is not None and value >= warn:
        return 'warn'
    return None


# --- the six classes ---------------------------------------------------------------------------------------------------

def backlog(snapshot, t, out):
    queue = _section(snapshot, 'queue')
    lag = _number(queue.get('oldestDueLagSeconds')) if queue else None
    t = t['backlog']
    level = None if lag is None else 'page' if lag > t['page_lag_seconds'] else 'warn' if lag > t['warn_lag_seconds'] else None
    if level:
        out.append(_alert('BACKLOG_LAG', 'BACKLOG', level,
                          'The oldest due Discord work is %d s late (warn above %d s, page above %d s). During a declared '
                          'burst the warn level is expected; the page level is not.' % (lag, t['warn_lag_seconds'], t['page_lag_seconds']),
                          oldestDueLagSeconds=lag, dueWorkspaces=queue.get('dueWorkspaces')))


def delivery(snapshot, t, out):
    d = _section(snapshot, 'deliveries')
    traffic = (snapshot.get('coordinator') or {}).get('traffic') if isinstance(snapshot.get('coordinator'), dict) else None
    t = t['delivery']
    if d:
        uncertain = int(d.get('uncertain') or 0)
        stuck = int(d.get('stuckSent') or 0)
        system = int(d.get('rejectedSystem') or 0) + uncertain + stuck
        customer = int(d.get('rejectedCustomer') or 0)
        attempts = (int(d.get('accepted') or 0) + customer + int(d.get('rejectedSystem') or 0)
                    + int(d.get('rateLimited') or 0) + uncertain + stuck)
        partial = None if d.get('windowCovered', True) else 'the sample did not reach back 15 minutes: counts are lower bounds'
        level = _over(uncertain, t['uncertain_warn'], t['uncertain_page'])
        if level:
            out.append(_alert('DELIVERY_UNCERTAIN', 'DELIVERY', level,
                              '%d Discord creates in 15 minutes may have reached Discord with no answer recorded. Never '
                              'resend; reconcile by read-back only. Three or more is a stop condition.' % uncertain,
                              uncertain=uncertain, attempts=attempts, note=partial))
        share = system / attempts if attempts else 0.0
        level = None
        if attempts >= t['min_attempts_for_share']:
            level = 'page' if share >= t['system_share_page'] else 'warn' if share >= t['system_share_warn'] else None
        if level is None and system >= t['system_failures_warn']:
            level = 'warn'
        if level:
            out.append(_alert('DELIVERY_SYSTEM_FAILURES', 'DELIVERY', level,
                              '%d of %d Discord create attempts in 15 minutes failed for a reason on our side (%.1f%%).'
                              % (system, attempts, 100 * share), systemFailures=system, attempts=attempts,
                              share=round(share, 4), rejectedSystem=d.get('rejectedSystem'), uncertain=uncertain,
                              stuckSent=stuck, note=partial))
        if attempts >= t['min_attempts_for_share'] and customer / attempts >= t['customer_share_warn']:
            out.append(_alert('DELIVERY_CUSTOMER_FAILURES', 'DELIVERY', 'warn',
                              '%d of %d create attempts were refused by Discord for the customer\'s server set-up (403 '
                              'or 404). Shown to each customer with the reason; this many may mean the permission check '
                              'before sending is not working.' % (customer, attempts),
                              rejectedCustomer=customer, attempts=attempts))
        if stuck >= t['stuck_sent_warn']:
            out.append(_alert('DELIVERY_STUCK_SENT', 'DELIVERY', 'warn',
                              '%d creates were sent and never answered for over two minutes (a process stopped '
                              'mid-request). Reconcile by read-back; see docs/w02/monitoring.sql M5.' % stuck,
                              stuckSent=stuck, stuckSentTotal=d.get('stuckSentTotal')))
    if isinstance(traffic, dict) and traffic.get('status', 'observed') != 'unavailable':
        unauthorized = int(traffic.get('unauthorized') or 0)
        if unauthorized >= t['unauthorized_page']:
            out.append(_alert('DELIVERY_UNAUTHORIZED', 'DELIVERY', 'page',
                              'Discord answered 401 to %d requests in 15 minutes: the bot token may have been reset or '
                              'leaked. The coordinator holds that credential, so Discord work stops (RUNBOOK-INCIDENT 4.D).'
                              % unauthorized, unauthorized=unauthorized))
        responses, errors = int(traffic.get('responses5m') or 0), int(traffic.get('serverErrors5m') or 0)
        if responses >= t['min_responses_for_server_errors'] and errors / responses > t['server_error_share_warn']:
            out.append(_alert('DELIVERY_DISCORD_5XX', 'DELIVERY', 'warn',
                              'Discord server errors are %.1f%% of %d responses in 5 minutes. Usually a Discord outage: '
                              'do not roll back (RUNBOOK-INCIDENT 4.A).' % (100 * errors / responses, responses),
                              serverErrors=errors, responses=responses))


def rate_limit(snapshot, t, out):
    t = t['rate_limit']
    coordinator = _section(snapshot, 'coordinator')
    config = snapshot.get('config') if isinstance(snapshot.get('config'), dict) else None
    traffic = coordinator.get('traffic') if coordinator else None
    if traffic and traffic.get('status', 'observed') != 'unavailable':
        policy = (config or {}).get('policy') or {}
        row = ((coordinator or {}).get('guards') or {}).get('policy') or {}
        # The process view knows the reviewed policy; the SQL twin reads the same numbers from the policy row.
        capacity = _number(policy.get('appCapacity')) or _number(row.get('limit'))
        window = _number(policy.get('appWindowSeconds')) or _number(row.get('windowSeconds'))
        admitted = _number(traffic.get('admissions60s'))
        if capacity and window and admitted is not None:
            saturation = admitted / (capacity * 60.0 / window)
            if saturation >= t['saturation_warn']:
                out.append(_alert('RATE_APP_BUDGET_SPENT', 'RATE_LIMIT', 'warn',
                                  'The application request budget was spent for the whole last minute (%d of %d '
                                  'admissions). Expected during a declared burst; otherwise something is sending more '
                                  'than it should.' % (admitted, capacity * 60 / window),
                                  admissions60s=admitted, saturation=round(saturation, 3)))
        invalid = int(traffic.get('invalid10m') or 0)
        if invalid > t['invalid_10m_page']:
            out.append(_alert('RATE_INVALID_REQUESTS', 'RATE_LIMIT', 'page',
                              '%d invalid Discord requests in 10 minutes (page above %d; Discord restricts the IP above '
                              '10,000). Close the gate and read RUNBOOK-INCIDENT 4.B.' % (invalid, t['invalid_10m_page']),
                              invalid10m=invalid))
        r429, global429 = int(traffic.get('responses429') or 0), int(traffic.get('responses429Global') or 0)
        level = _over(global429, t['global_429_warn'], t['global_429_page'])
        if level is None and r429 >= t['responses_429_warn']:
            level = 'warn'
        if level:
            out.append(_alert('RATE_429', 'RATE_LIMIT', level,
                              'Discord answered 429 to %d requests in 15 minutes (%d global). The coordinator should '
                              'prevent these; a global 429 pauses every loop.' % (r429, global429),
                              responses429=r429, responses429Global=global429))
    if coordinator:
        guards = coordinator.get('guards') or {}
        kinds = coordinator.get('kinds') or {}
        credential = guards.get('credential') or {}
        if credential.get('hold'):
            out.append(_alert('RATE_CREDENTIAL_HOLD', 'RATE_LIMIT', 'page',
                              'The coordinator holds the bot credential (it does so after a 401): every Discord request '
                              'is refused. The bot token was probably reset or revoked (RUNBOOK-INCIDENT 4.D).'))
        embargoed = {kind: guards[kind] for kind in GUARD_KINDS
                     if isinstance(guards.get(kind), dict) and (guards[kind].get('blocked') or guards[kind].get('circuit'))}
        long = [kind for kind in GUARD_KINDS
                if int((kinds.get(kind) or {}).get('openOver5Min') or 0) > 0
                or (_number((embargoed.get(kind) or {}).get('embargoSeconds')) or 0) > t['embargo_page_seconds']]
        if embargoed or long:
            out.append(_alert('RATE_EMBARGO', 'RATE_LIMIT', 'page' if long else 'warn',
                              'An application-wide Discord embargo is active on %s%s. Loops sleep it out; nothing '
                              'destructive is needed (RUNBOOK-INCIDENT 4.A).' % (', '.join(sorted(set(embargoed) | set(long))),
                                                                              ' for more than 5 minutes' if long else ''),
                              kinds=sorted(set(embargoed) | set(long)),
                              longestSeconds=max([_number(g.get('embargoSeconds')) or 0 for g in embargoed.values()], default=None)))
        invalid = guards.get('invalid') or {}
        ratio = _number(invalid.get('remainingRatio'))
        if ratio is not None:
            level = 'page' if ratio < t['invalid_remaining_page'] else 'warn' if ratio < t['invalid_remaining_warn'] else None
            if level:
                out.append(_alert('RATE_INVALID_BUDGET', 'RATE_LIMIT', level,
                                  'Only %d%% of the invalid-request budget is left in this window (page below %d%%: '
                                  'ban danger). Close the gate (step 1) and find the source of the 401/403/429 answers.'
                                  % (100 * ratio, 100 * t['invalid_remaining_page']),
                                  remainingRatio=ratio, remaining=invalid.get('remaining'), limit=invalid.get('limit'),
                                  resetSeconds=invalid.get('resetSeconds')))
        transient = sum(max(0, int((kinds.get(kind) or {}).get('circuits') or 0)
                            - int((kinds.get(kind) or {}).get('persistentCircuits') or 0)) for kind in ('route', 'resource'))
        if transient >= t['transient_route_circuits_warn']:
            out.append(_alert('RATE_ROUTE_CIRCUITS', 'RATE_LIMIT', 'warn',
                              '%d Discord routes have a short circuit open after repeated server errors.' % transient,
                              transientCircuits=transient))
    if config and config.get('rateLimitsV1'):
        policy = config.get('policy') or {}
        days = _number(policy.get('daysLeft'))
        if not policy.get('present') or policy.get('valid') is False:
            out.append(_alert('RATE_POLICY', 'RATE_LIMIT', 'page',
                              'The reviewed rate policy is %s: every Discord request is refused before it is sent '
                              '(RUNBOOK-INCIDENT 4.C).' % ('missing' if not policy.get('present') else 'not valid now'),
                              daysLeft=days))
        elif days is not None and days < t['policy_days_warn']:
            out.append(_alert('RATE_POLICY', 'RATE_LIMIT', 'page' if days < t['policy_days_page'] else 'warn',
                              'The reviewed rate policy expires in %.1f days; renewal needs a new build and a '
                              'promotion (RUNBOOK-INCIDENT 4.C).' % days, daysLeft=days))


def silent_halt(snapshot, t, out, now=None):
    t = t['silent_halt']
    if not isinstance(snapshot, dict) or snapshot.get('unavailable'):
        reason = snapshot.get('reason') if isinstance(snapshot, dict) else 'missing'
        out.append(_alert('SILENT_HALT_HEALTH_UNANSWERED', 'SILENT_HALT', 'page',
                          'The health payload did not answer (%s). Treat it as a halt until shown otherwise.' % reason,
                          reason=reason))
        return
    observed = _number(snapshot.get('observedAt'))
    if now is not None and observed is not None and now - observed > t['health_max_age_seconds']:
        out.append(_alert('SILENT_HALT_HEALTH_UNANSWERED', 'SILENT_HALT', 'page',
                          'The newest health snapshot is %d s old.' % (now - observed), ageSeconds=round(now - observed, 1)))
    queue, coordinator = _section(snapshot, 'queue'), _section(snapshot, 'coordinator')
    errors = snapshot.get('errors') if isinstance(snapshot.get('errors'), list) else []
    if snapshot.get('source') == 'health_route' and (observed is None or (not queue and not coordinator)):
        out.append(_alert('SILENT_HALT_DATABASE', 'SILENT_HALT', 'page',
                          'The health payload could not read the database: no claim, send or hold can be seen.',
                          errors=[e.get('section') for e in errors if isinstance(e, dict)]))
    elif not queue and coordinator:
        out.append(_alert('SILENT_HALT_PROJECTION', 'SILENT_HALT', 'page',
                          'The Discord due-work projection cannot be read; the lane stops with "schema" and claims nothing.'))
    progress = snapshot.get('progress') if isinstance(snapshot.get('progress'), dict) else {}
    lag = _number(queue.get('oldestDueLagSeconds')) if queue else None
    if lag is not None and lag > t['due_lag_seconds'] and progress.get('status') in ('observed', None):
        claim, admission = _number(progress.get('lastClaimAgeSeconds')), _number(progress.get('lastAdmissionAgeSeconds'))
        if (claim is None or claim > t['quiet_seconds']) and (admission is None or admission > t['quiet_seconds']):
            held = bool((((coordinator or {}).get('guards') or {}).get('policy') or {}).get('hold'))
            out.append(_alert('SILENT_HALT_NO_PROGRESS', 'SILENT_HALT', 'warn' if held else 'page',
                              'Discord work has been due for %d s and nothing was claimed or admitted for %s. %s'
                              % (lag, 'ever' if claim is None and admission is None else 'more than %d s' % t['quiet_seconds'],
                                 'The operator hold explains it.' if held else
                                 'The senders are not running (shard crons, the minute cron, or a stop).'),
                              oldestDueLagSeconds=lag, lastClaimAgeSeconds=claim, lastAdmissionAgeSeconds=admission,
                              operatorHold=held or None))
    lane = snapshot.get('lane') if isinstance(snapshot.get('lane'), dict) else None
    if lane and lane.get('enabled') and not lane.get('ready'):
        blocker = lane.get('blocker')
        level = 'page' if blocker == 'coordinator_unavailable' else 'warn'
        out.append(_alert('SILENT_HALT_LANE_NOT_READY', 'SILENT_HALT', level,
                          'The W-02 lane flag is on but the lane cannot run here (%s). %s' % (
                              blocker, {'coordinator_unavailable': 'No path can send: posts are held or wait.',
                                        'configuration': 'The minute cron keeps sending on the frozen path.',
                                        'coordinator_degraded': 'This process only; lanes in other processes send.'}.get(blocker, '')),
                          blocker=blocker))
    guards = (coordinator or {}).get('guards') or {}
    if (guards.get('policy') or {}).get('hold'):
        out.append(_alert('SILENT_HALT_OPERATOR_HOLD', 'SILENT_HALT', 'warn',
                          'The operator hold is on: Discord sends nothing and posts wait. Approvals lapse after an hour, '
                          'so long holds mean re-approvals. Lift it only on the Release Captain\'s word.'))
    fleet = snapshot.get('fleet') if isinstance(snapshot.get('fleet'), dict) else None
    window = _number((fleet or {}).get('windowSeconds'))
    if fleet and lane and lane.get('enabled') and window is not None and window >= t['min_lane_window_seconds']:
        lines = int(fleet.get('laneLines') or 0)
        if lines == 0:
            out.append(_alert('SILENT_HALT_NO_SHARDS', 'SILENT_HALT', 'page',
                              'The lane flag is on and no shard invocation was logged in %d s: the shard crons do not '
                              'reach the function.' % window, windowSeconds=window))
        abnormal = {k: v for k, v in (fleet.get('laneStops') or {}).items() if k not in QUIET_STOPS and v}
        if abnormal:
            out.append(_alert('SILENT_HALT_LANE_STOPS', 'SILENT_HALT', 'warn',
                              'Shard invocations stopped for %s.' % ', '.join(sorted(abnormal)), stops=abnormal))


def cross_tenant(snapshot, t, out):
    t = t['cross_tenant']
    security = snapshot.get('security') if isinstance(snapshot.get('security'), dict) else {}
    fleet = snapshot.get('fleet') if isinstance(snapshot.get('fleet'), dict) else {}
    sources = [s for s in (security.get('instance'), fleet.get('denials')) if isinstance(s, dict)]
    top = max([int(s.get('topActorDenials10m') or 0) for s in sources], default=0)
    discord = max([int((s.get('denied') or {}).get('discord') or 0) for s in sources], default=0)
    level = _over(top, t['actor_denials_warn'], t['actor_denials_page'])
    if level:
        out.append(_alert('CROSS_TENANT_PROBING', 'CROSS_TENANT', level,
                          'One member was refused other workspaces %d times in 10 minutes: probing, or a stuck client. '
                          'Find the actor key in the logs; on page, hold first (RUNBOOK-INCIDENT 4.H).' % top,
                          topActorDenials10m=top, scope='fleet_logs' if fleet.get('denials') else 'instance'))
    if discord >= t['discord_denials_warn']:
        out.append(_alert('CROSS_TENANT_DISCORD', 'CROSS_TENANT', 'warn',
                          '%d cross-workspace denials on Discord routes in 15 minutes.' % discord, discordDenials=discord))
    responses = security.get('responses4xx') if isinstance(security.get('responses4xx'), dict) else {}
    discord_4xx = int(responses.get('discord') or 0) if responses.get('status') == 'observed' else 0
    if discord_4xx >= t['discord_4xx_warn']:
        out.append(_alert('CROSS_TENANT_DISCORD_4XX', 'CROSS_TENANT', 'warn',
                          '%d client errors on Discord routes in 15 minutes (a superset of denials; tune after a '
                          'baseline).' % discord_4xx, responses4xx=discord_4xx))
    probe = security.get('probe') if isinstance(security.get('probe'), dict) else None
    if probe and int(probe.get('failed') or 0) > 0:
        out.append(_alert('CROSS_TENANT_PROBE_FAILED', 'CROSS_TENANT', 'page',
                          'The Q-05 isolation probe reports %d failing cases: a cross-tenant read or write was allowed.'
                          % int(probe['failed']), failed=int(probe['failed'])))


def config(snapshot, t, out, phase):
    c = snapshot.get('config') if isinstance(snapshot.get('config'), dict) else None
    if not c:
        return
    t = t['config']
    gate, cap = c.get('gate') or {}, c.get('cap') or {}
    if gate.get('misconfigured') or cap.get('misconfigured'):
        out.append(_alert('CONFIG_MISCONFIGURED', 'CONFIG', 'page',
                          'The connect gate or the server cap is misconfigured on the serving build, so it fails closed.',
                          gate=gate.get('misconfigured'), cap=cap.get('misconfigured')))
    if phase == 'open':
        if gate.get('mode') != t['expected_gate']:
            out.append(_alert('CONFIG_GATE', 'CONFIG', 'page',
                              'After the opening the serving build\'s connect gate is %s, not %s: new customers see "not '
                              'open yet".' % (gate.get('mode'), t['expected_gate']), mode=gate.get('mode'),
                              workspaces=gate.get('workspaces')))
        value = _number(cap.get('value'))
        if not cap.get('unlimited') and (value is None or value < t['expected_cap']):
            out.append(_alert('CONFIG_CAP', 'CONFIG', 'page',
                              'The serving build\'s server cap is %s, below %d (a build without the cap line falls back '
                              'to 90).' % (value, t['expected_cap']), cap=value, expected=t['expected_cap']))
    if phase == 'canary' and (gate.get('mode') == 'open' or (gate.get('mode') == 'list'
                                                            and int(gate.get('workspaces') or 0) > t['canary_max_workspaces'])):
        out.append(_alert('CONFIG_GATE', 'CONFIG', 'page',
                          'The canary build\'s connect gate is %s (%s workspaces): wider than the tester-only gate.'
                          % (gate.get('mode'), gate.get('workspaces')), mode=gate.get('mode'), workspaces=gate.get('workspaces')))
    servers = c.get('servers') if isinstance(c.get('servers'), dict) else {}
    ratio = _number(servers.get('ratio'))
    level = _over(ratio, t['cap_used_warn'], t['cap_used_page'])
    if level:
        out.append(_alert('CONFIG_CAP_USED', 'CONFIG', level,
                          '%d of %s server slots are used (%.0f%%). Compare with the Developer Portal count and decide '
                          'the next cap (RUNBOOK-LAUNCH section 6).' % (servers.get('used') or 0, cap.get('value'), 100 * ratio),
                          used=servers.get('used'), cap=cap.get('value'), ratio=ratio))
    if phase in ('canary', 'open'):
        if c.get('reviewed') is False:
            out.append(_alert('CONFIG_REVIEWED', 'CONFIG', 'page',
                              'The Direct publishing review flag is off on the serving build: Discord publishing shows as '
                              'unsupported.'))
        missing = [name for name in t['expected_flags'] if c.get(name) is not True]
        if missing:
            out.append(_alert('CONFIG_FLAGS', 'CONFIG', 'page',
                              'Discord switches off on the serving build: %s.' % ', '.join(missing), missing=missing))
    if t.get('expected_lane_flag') is not None and bool(c.get('laneFlag')) != t['expected_lane_flag']:
        out.append(_alert('CONFIG_LANE_FLAG', 'CONFIG', 'warn',
                          'The W-02 lane flag is %s, expected %s.' % (c.get('laneFlag'), t['expected_lane_flag'])))
    if c.get('killSwitch') or c.get('executionEnabled') is False:
        out.append(_alert('CONFIG_KILL_SWITCH', 'CONFIG', 'warn',
                          'Discord execution is switched off on the serving build (the kill switch or a missing '
                          'review): expected only during an abort.', killSwitch=c.get('killSwitch')))
    build = snapshot.get('build') if isinstance(snapshot.get('build'), dict) else {}
    for key, name in (('expected_source_revision', 'sourceRevision'), ('expected_deployment_id', 'deploymentId')):
        if t.get(key) and build.get(name) and build[name] != t[key]:
            out.append(_alert('CONFIG_BUILD', 'CONFIG', 'warn',
                              'The serving build is not the recorded one (%s differs).' % name, field=name))


def evaluate(snapshot, thresholds, now=None, phase=None):
    """Every alert the snapshot implies, pages first. Deterministic for equal inputs."""
    phase = phase or thresholds.get('phase', 'pre_open')
    if phase not in PHASES:
        raise ValueError('unknown phase')
    out = []
    silent_halt(snapshot, thresholds, out, now)
    if isinstance(snapshot, dict) and not snapshot.get('unavailable'):
        backlog(snapshot, thresholds, out)
        delivery(snapshot, thresholds, out)
        rate_limit(snapshot, thresholds, out)
        cross_tenant(snapshot, thresholds, out)
        config(snapshot, thresholds, out, phase)
    return sorted(out, key=lambda a: (SEVERITIES.index(a['severity']), CLASSES.index(a['class']), a['id']))


def transitions(previous, current):
    """Which alert ids opened, continue or cleared between two evaluations (for notifying once, and for receipts)."""
    before = {a['id']: a['severity'] for a in previous or []}
    after = {a['id']: a['severity'] for a in current or []}
    return {'opened': sorted(set(after) - set(before)), 'continuing': sorted(set(after) & set(before)),
            'cleared': sorted(set(before) - set(after)),
            'escalated': sorted(k for k in set(after) & set(before)
                                if SEVERITIES.index(after[k]) < SEVERITIES.index(before[k]))}


def parse_logs(lines, window_seconds):
    """Fleet numbers from function log lines of one window (the caller selects the window): cross-tenant denials by
    family and by actor key (keys are counted, never returned), shard invocations and their stop reasons."""
    families, actors, stops, counters = {}, {}, {}, dict.fromkeys(LANE_COUNTERS, 0)
    lane_lines = lagging = 0
    for line in lines:
        start = line.find('{')
        if start < 0:
            continue
        try:
            event = json.loads(line[start:])
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get('event') == DENIAL_EVENT:
            count = 1 + int(event.get('suppressed') or 0)
            family = event.get('routeFamily') if event.get('routeFamily') in ('discord', 'connections', 'workspace') else 'other'
            families[family] = families.get(family, 0) + count
            key = str(event.get('actorKey'))
            actors[key] = actors.get(key, 0) + count
        elif event.get('event') == 'discord.lane.completed':
            lane_lines += 1
            stop = str(event.get('stoppedBy'))
            stops[stop] = stops.get(stop, 0) + 1
            for name in LANE_COUNTERS:
                value = (event.get('counters') or {}).get(name)
                counters[name] += value if type(value) is int else 0
        elif event.get('event') == 'discord.lane.lagging':
            lagging += 1
    return {'windowSeconds': window_seconds, 'laneLines': lane_lines, 'laneStops': stops, 'laneCounters': counters,
            'lagging': lagging,
            'denials': {'scope': 'fleet_logs', 'denied': families, 'deniedTotal': sum(families.values()),
                        'actors10m': len(actors), 'topActorDenials10m': max(actors.values(), default=0)}}


def fetch(url, bearer, timeout=10.0):
    """GET the health payload. Any failure becomes an 'unavailable' snapshot (an alarm), never an exception."""
    request = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + bearer, 'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read(1_000_000))
    except urllib.error.HTTPError as error:
        return {'unavailable': True, 'reason': 'http_%d' % error.code}
    except (urllib.error.URLError, TimeoutError, OSError):
        return {'unavailable': True, 'reason': 'unreachable'}
    except ValueError:
        return {'unavailable': True, 'reason': 'not_json'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n', 1)[0])
    commands = parser.add_subparsers(dest='command', required=True)
    run = commands.add_parser('evaluate')
    run.add_argument('snapshot', help='a snapshot JSON file, or - for standard input')
    run.add_argument('--thresholds', default=str(DEFAULT_THRESHOLDS))
    run.add_argument('--phase', choices=PHASES)
    run.add_argument('--logs', help='function log lines of the window to add as fleet numbers')
    run.add_argument('--window-seconds', type=float, default=600.0, help='the window the --logs lines cover')
    run.add_argument('--previous', help='the alerts JSON of the previous evaluation, to report transitions')
    run.add_argument('--now', type=float)
    get = commands.add_parser('fetch')
    get.add_argument('url')
    get.add_argument('--timeout', type=float, default=10.0)
    args = parser.parse_args(argv)
    if args.command == 'fetch':
        import os
        bearer = os.environ.get('DISCORD_OPS_BEARER', '')
        print(json.dumps(fetch(args.url, bearer, args.timeout) if bearer else {'unavailable': True, 'reason': 'no_bearer'}))
        return 0
    text = sys.stdin.read() if args.snapshot == '-' else Path(args.snapshot).read_text()
    try:
        snapshot = json.loads(text)
    except ValueError:
        snapshot = {'unavailable': True, 'reason': 'not_json'}
    if args.logs and isinstance(snapshot, dict) and not snapshot.get('unavailable'):
        snapshot['fleet'] = parse_logs(Path(args.logs).read_text().splitlines(), args.window_seconds)
    alerts = evaluate(snapshot, load_thresholds(args.thresholds), now=args.now if args.now is not None else time.time(),
                      phase=args.phase)
    report = {'alerts': alerts, 'worst': alerts[0]['severity'] if alerts else None}
    if args.previous:
        report['transitions'] = transitions(json.loads(Path(args.previous).read_text()).get('alerts', []), alerts)
    print(json.dumps(report, indent=1, sort_keys=True))
    return 2 if any(a['severity'] == 'page' for a in alerts) else 1 if any(a['severity'] == 'warn' for a in alerts) else 0


if __name__ == '__main__':
    sys.exit(main())
