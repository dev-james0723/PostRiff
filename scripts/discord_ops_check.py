#!/usr/bin/env python3
"""Evaluate the Discord operations health snapshot against the H-07 alert rules. Standard library only.

    evaluate(snapshot, thresholds, now=None, phase='open', previous=None)
        -> [{'id', 'class', 'severity', 'message', 'evidence'[, 'scope']}, ...]

Pure: no network, database or clock of its own except the optional `now` (epoch seconds) used to see whether the
snapshot itself is stale, and the optional previous report (persistence and deltas). Rules are data-driven by
docs/ops/discord-alert-thresholds.json. Six classes: BACKLOG, DELIVERY, RATE_LIMIT, SILENT_HALT, CROSS_TENANT and
CONFIG; 40 alert ids. Severity is 'page', 'warn' or 'info' (the meaning for the person holding the pager is in the
thresholds file and docs/ops/PHONE-RUNBOOK.md). The absence of the signal is an alarm: a missing, failed or malformed
snapshot (wrong kind, version or source, or a required section missing) is SILENT_HALT_HEALTH_UNANSWERED, and every
section the payload could not read (one entry of errors[]) is SILENT_HALT_SECTION for that section: a warning the first
time, a page when the previous evaluation had it too. A section the snapshot does not carry by design (the SQL twin has
no process view) makes only its own rules silent.

The snapshot is the payload of GET /api/ops/discord/health (src/postriff_phase2/discord/ops.py) or the read-only SQL
twin (docs/ops/discord-ops-snapshot.sql). Fleet-wide numbers that only the function logs know (cross-tenant denials,
lane invocations) can be added under snapshot['fleet'] with parse_logs().

Command line:
    discord_ops_check.py evaluate SNAPSHOT.json --phase pre_open|canary|open [--thresholds FILE] [--logs FILE]
                                                [--previous REPORT.json] [--now EPOCH]
    discord_ops_check.py fetch URL [--timeout 10]   (bearer from DISCORD_OPS_BEARER; https only, or http to this
                                                    machine; no redirects; one overall deadline; prints the snapshot,
                                                    never the bearer; a failed fetch prints an 'unavailable' snapshot)
--phase is required: the configuration rules depend on it. --previous is the report a previous run printed; its
'memory' carries what persistence and deltas need.
Exit code of evaluate: 2 when any alert pages, 1 when the worst is a warning, 0 otherwise, 3 when the evaluation
itself failed (an internal error is never mistaken for a warning).
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
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
KIND = 'rafii.discord.ops.health'
# The sections each source must carry (a missing one is a malformed snapshot, not a quiet one).
REQUIRED = {'health_route': ('queue', 'deliveries', 'progress', 'coordinator', 'config', 'lane', 'security', 'errors'),
            'sql': ('queue', 'deliveries', 'progress', 'coordinator', 'servers', 'errors'),
            'logs': ('fleet',)}
LOOPBACK = ('127.0.0.1', 'localhost', '::1')


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


def delivery(snapshot, t, out, memory=None):
    d = _section(snapshot, 'deliveries')
    traffic = (snapshot.get('coordinator') or {}).get('traffic') if isinstance(snapshot.get('coordinator'), dict) else None
    unresolved = _section(snapshot, 'unresolved') or {}
    open_uncertain = int(unresolved.get('uncertainPublishes') or 0)
    open_stuck = int(unresolved.get('stuckSentPublishes') or 0)
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
        if level is None and open_uncertain > 0:
            level = 'warn'
        if level:
            out.append(_alert('DELIVERY_UNCERTAIN', 'DELIVERY', level,
                              '%d Discord creates in 15 minutes may have reached Discord with no answer recorded, and %d such '
                              'admissions are unresolved in all. Never resend; reconcile by read-back only. Three or more in '
                              '15 minutes is a stop condition; the warning stays until each one is reviewed (W-02 '
                              'OPEN-QUESTIONS Q3).' % (uncertain, open_uncertain),
                              uncertain=uncertain, unresolved=open_uncertain or None, attempts=attempts, note=partial))
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
        if max(stuck, open_stuck) >= t['stuck_sent_warn']:
            out.append(_alert('DELIVERY_STUCK_SENT', 'DELIVERY', 'warn',
                              '%d creates were sent and never answered for over two minutes (a process stopped '
                              'mid-request), %d in 15 minutes. Reconcile by read-back; see docs/w02/monitoring.sql M5.'
                              % (max(stuck, open_stuck), stuck),
                              stuckSent=stuck, stuckSentTotal=d.get('stuckSentTotal'), unresolved=open_stuck or None))
    elif open_uncertain > 0 or open_stuck >= t['stuck_sent_warn']:
        # The 15-minute ledger is unavailable but the unresolved counts were read: they still stand.
        if open_uncertain > 0:
            out.append(_alert('DELIVERY_UNCERTAIN', 'DELIVERY', 'warn', '%d Discord create admissions are uncertain and '
                              'unresolved. Never resend; reconcile by read-back only.' % open_uncertain, unresolved=open_uncertain))
        if open_stuck >= t['stuck_sent_warn']:
            out.append(_alert('DELIVERY_STUCK_SENT', 'DELIVERY', 'warn', '%d creates were sent and never answered. Reconcile '
                              'by read-back; see docs/w02/monitoring.sql M5.' % open_stuck, unresolved=open_stuck))
    platform = _section(snapshot, 'platform') or {}
    before = ((memory or {}).get('platform') or {}) if isinstance(memory, dict) else {}
    for name, rule, limit, what in (('publicationHeld', 'DELIVERY_HELD_GROWTH', t['held_growth_warn'],
                                     'became held (an approval ran out or a rate wait outlasted it: each needs the '
                                     'customer to approve again)'),
                                    ('publicationFailed', 'DELIVERY_FAILED_GROWTH', t['failed_growth_warn'], 'failed')):
        now_count, then_count = _number(platform.get(name)), _number(before.get(name))
        if now_count is not None and then_count is not None and now_count - then_count >= limit:
            out.append(_alert(rule, 'DELIVERY', 'warn', '%d more publications %s since the previous check (all platforms; '
                              'the platform snapshot of migration 060).' % (now_count - then_count, what),
                              growth=now_count - then_count, total=now_count))
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


def malformed(snapshot):
    """Why a snapshot that answered cannot be trusted as a whole (None when it can)."""
    if snapshot.get('version') != 1:
        return 'version'
    source = snapshot.get('source')
    if source not in REQUIRED:
        return 'source'
    if source != 'logs' and snapshot.get('kind') != KIND:
        return 'kind'
    missing = [name for name in REQUIRED[source]
               if not isinstance(snapshot.get(name), list if name == 'errors' else dict)]
    return 'missing:' + ','.join(missing) if missing else None


def silent_halt(snapshot, t, out, now=None, previous=None):
    t = t['silent_halt']
    if not isinstance(snapshot, dict) or snapshot.get('unavailable'):
        reason = snapshot.get('reason') if isinstance(snapshot, dict) else 'missing'
        out.append(_alert('SILENT_HALT_HEALTH_UNANSWERED', 'SILENT_HALT', 'page',
                          'The health payload did not answer (%s). Treat it as a halt until shown otherwise.' % reason,
                          reason=reason))
        return
    wrong = malformed(snapshot)
    if wrong:
        out.append(_alert('SILENT_HALT_HEALTH_UNANSWERED', 'SILENT_HALT', 'page',
                          'The health payload answered but is malformed (%s): its rules cannot be trusted. Treat it as a '
                          'halt until shown otherwise.' % wrong, reason='malformed', detail=wrong))
    for entry in snapshot.get('errors') if isinstance(snapshot.get('errors'), list) else []:
        name = entry.get('section') if isinstance(entry, dict) else None
        if not isinstance(name, str) or name == 'database' or not name.isidentifier():
            continue
        persistent = ('SILENT_HALT_SECTION', name) in (previous or {})
        alert = _alert('SILENT_HALT_SECTION', 'SILENT_HALT', 'page' if persistent else 'warn',
                       'The health payload could not read its %s section (%s)%s: the rules that need it are blind.'
                       % (name, entry.get('error'), ' for two checks in a row' if persistent else ''),
                       section=name, error=entry.get('error'))
        alert['scope'] = name
        out.append(alert)
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
    held = bool((((coordinator or {}).get('guards') or {}).get('policy') or {}).get('hold'))
    if lag is not None and lag > t['due_lag_seconds']:
        # An age the payload could not read (the ledger section failed) counts as no progress: absence is not proof.
        claim, admission = _number(progress.get('lastClaimAgeSeconds')), _number(progress.get('lastAdmissionAgeSeconds'))
        if (claim is None or claim > t['quiet_seconds']) and (admission is None or admission > t['quiet_seconds']):
            out.append(_alert('SILENT_HALT_NO_PROGRESS', 'SILENT_HALT', 'warn' if held else 'page',
                              'Discord work has been due for %d s and nothing was claimed or admitted for %s. %s'
                              % (lag, 'ever' if claim is None and admission is None else 'more than %d s' % t['quiet_seconds'],
                                 'The operator hold explains it.' if held else
                                 'The senders are not running (shard crons, the minute cron, or a stop).'),
                              oldestDueLagSeconds=lag, lastClaimAgeSeconds=claim, lastAdmissionAgeSeconds=admission,
                              operatorHold=held or None, ledger='unread' if progress.get('status') != 'observed' else None))
        ages = [a for a in (_number(progress.get('lastAcceptedCreateAgeSeconds')), _number(progress.get('lastReadbackAgeSeconds')))
                if a is not None]
        quiet = min(ages) if ages else lag
        level = _over(quiet, t['no_create_warn_seconds'], t['no_create_page_seconds'])
        if level:
            out.append(_alert('SILENT_HALT_NO_CREATE', 'SILENT_HALT', 'warn' if held else level,
                              'Discord work has been due for %d s and no create was accepted and no read-back succeeded for '
                              '%d s. %s' % (lag, quiet, 'The operator hold explains it.' if held else
                                            'Claims may continue, but nothing reaches Discord: refusals, rate waits or a '
                                            'stuck worker.'),
                              oldestDueLagSeconds=lag, quietSeconds=quiet, operatorHold=held or None))
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
                          'The operator hold is on: Discord sends nothing and posts wait. A post needs a new approval from '
                          'about 55 minutes after its own scheduled time, and while the lane does not own Discord each '
                          'created post\'s read-back is parked for 24 hours. Lift it only on the Release Captain\'s word.'))
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
                          'Each refusal is the gate working (no data left). Find the actor key in the logs and check the '
                          'isolation probe; hold only if the probe fails or exposure is confirmed (PHONE-RUNBOOK).' % top,
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


def _previous(previous):
    """(alerts by (id, scope), memory) from a previous report, or from a bare list of alerts."""
    if isinstance(previous, dict):
        alerts, memory = previous.get('alerts') or [], previous.get('memory') or {}
    else:
        alerts, memory = previous or [], {}
    keyed = {(a.get('id'), a.get('scope')): a.get('severity') for a in alerts if isinstance(a, dict)}
    return keyed, memory if isinstance(memory, dict) else {}


def memory(snapshot):
    """What the next evaluation needs from this one: the platform counters (for growth)."""
    platform = _section(snapshot, 'platform') if isinstance(snapshot, dict) else None
    return {'platform': {k: platform[k] for k in ('publicationHeld', 'publicationFailed') if _number((platform or {}).get(k)) is not None}
            if platform else {}}


def evaluate(snapshot, thresholds, now=None, phase='open', previous=None):
    """Every alert the snapshot implies, pages first. Deterministic for equal inputs. `phase` defaults to the strictest
    ('open'); `previous` is the previous report (or its alert list) for persistence and growth."""
    phase = phase or 'open'
    if phase not in PHASES:
        raise ValueError('unknown phase')
    before, remembered = _previous(previous)
    out = []
    silent_halt(snapshot, thresholds, out, now, before)
    if isinstance(snapshot, dict) and not snapshot.get('unavailable'):
        backlog(snapshot, thresholds, out)
        delivery(snapshot, thresholds, out, remembered)
        rate_limit(snapshot, thresholds, out)
        cross_tenant(snapshot, thresholds, out)
        config(snapshot, thresholds, out, phase)
    return sorted(out, key=lambda a: (SEVERITIES.index(a['severity']), CLASSES.index(a['class']), a['id'], a.get('scope') or ''))


def _label(alert):
    return alert['id'] + ('/' + alert['scope'] if alert.get('scope') else '')


def transitions(previous, current):
    """Which alerts opened, continue or cleared between two evaluations (for notifying once, and for receipts). An alert
    with a scope (one failing section) is labelled id/scope."""
    before = {_label(a): a['severity'] for a in previous or []}
    after = {_label(a): a['severity'] for a in current or []}
    return {'opened': sorted(set(after) - set(before)), 'continuing': sorted(set(after) & set(before)),
            'cleared': sorted(set(before) - set(after)),
            'escalated': sorted(k for k in set(after) & set(before)
                                if SEVERITIES.index(after[k]) < SEVERITIES.index(before[k]))}


def parse_logs(lines, window_seconds):
    """Fleet numbers from function log lines of one window (the caller selects the window): cross-tenant denials by
    family and by actor key (keys are counted, never returned), shard invocations and their stop reasons."""
    families, actors, stops, counters = {}, {}, {}, dict.fromkeys(LANE_COUNTERS, 0)
    running = {}
    lane_lines = lagging = 0
    for line in lines:
        event = _event(line)
        if event is None:
            continue
        if event.get('event') == DENIAL_EVENT:
            family = event.get('routeFamily') if event.get('routeFamily') in ('discord', 'connections', 'workspace') else 'other'
            key = str(event.get('actorKey'))
            if type(event.get('count')) is int and type(event.get('minute')) is int:
                # Running count within one minute (lines at 1, 10, 100, 1,000 and on the minute's flush; the
                # instance is part of the key): the largest one is that minute's total for the line's process.
                slot = (key, family, event['minute'], str(event.get('instance')))
                running[slot] = max(running.get(slot, 0), event['count'])
                continue
            count = 1 + int(event.get('suppressed') or 0)   # the earlier line format
            families[family] = families.get(family, 0) + count
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
    for (key, family, _minute, _instance), count in running.items():
        families[family] = families.get(family, 0) + count
        actors[key] = actors.get(key, 0) + count
    return {'windowSeconds': window_seconds, 'laneLines': lane_lines, 'laneStops': stops, 'laneCounters': counters,
            'lagging': lagging,
            'denials': {'scope': 'fleet_logs', 'denied': families, 'deniedTotal': sum(families.values()),
                        'actors10m': len(actors), 'topActorDenials10m': max(actors.values(), default=0)}}


def _event(line):
    """One JSON log event from a line, unwrapping a log drain's {"message": "..."} envelope; None when there is none."""
    start = line.find('{') if isinstance(line, str) else -1
    if start < 0:
        return None
    try:
        event = json.loads(line[start:])
    except ValueError:
        return None
    if isinstance(event, dict) and 'event' not in event and isinstance(event.get('message'), str):
        return _event(event['message'])
    return event if isinstance(event, dict) else None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect is an answer, not a new destination: the bearer is never sent anywhere else."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


MAX_BODY = 1_000_000


def fetch(url, bearer, timeout=10.0):
    """GET the health payload: https only (plain http only to this machine), no redirects, one overall deadline, at most
    MAX_BODY bytes. Any failure becomes an 'unavailable' snapshot (an alarm), never an exception."""
    parts = urllib.parse.urlsplit(str(url))
    if not (parts.scheme == 'https' or (parts.scheme == 'http' and parts.hostname in LOOPBACK)):
        return {'unavailable': True, 'reason': 'insecure_url'}
    deadline = time.monotonic() + float(timeout)
    request = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + bearer, 'Accept': 'application/json'})
    try:
        with urllib.request.build_opener(_NoRedirect).open(request, timeout=timeout) as response:
            body = b''
            while True:
                left = deadline - time.monotonic()
                if left <= 0:
                    return {'unavailable': True, 'reason': 'deadline'}
                try:
                    response.fp.raw._sock.settimeout(left)   # each read may take only what is left of the deadline
                except AttributeError:
                    pass
                chunk = response.read1(65536)          # what has arrived, at most one receive: the deadline holds
                if not chunk:
                    break
                body += chunk
                if len(body) > MAX_BODY:
                    return {'unavailable': True, 'reason': 'too_large'}
            return json.loads(body)
    except urllib.error.HTTPError as error:
        return {'unavailable': True, 'reason': 'http_%d' % error.code}
    except (urllib.error.URLError, TimeoutError, OSError):
        return {'unavailable': True, 'reason': 'deadline' if time.monotonic() >= deadline else 'unreachable'}
    except ValueError:
        return {'unavailable': True, 'reason': 'not_json'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n', 1)[0])
    commands = parser.add_subparsers(dest='command', required=True)
    run = commands.add_parser('evaluate')
    run.add_argument('snapshot', help='a snapshot JSON file, or - for standard input')
    run.add_argument('--thresholds', default=str(DEFAULT_THRESHOLDS))
    run.add_argument('--phase', choices=PHASES, required=True)
    run.add_argument('--logs', help='function log lines of the window to add as fleet numbers')
    run.add_argument('--window-seconds', type=float, default=600.0, help='the window the --logs lines cover')
    run.add_argument('--previous', help='the report of the previous evaluation: transitions, persistence and growth')
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
    try:
        text = sys.stdin.read() if args.snapshot == '-' else Path(args.snapshot).read_text()
        try:
            snapshot = json.loads(text)
        except ValueError:
            snapshot = {'unavailable': True, 'reason': 'not_json'}
        if args.logs and isinstance(snapshot, dict) and not snapshot.get('unavailable'):
            snapshot['fleet'] = parse_logs(Path(args.logs).read_text().splitlines(), args.window_seconds)
        previous = json.loads(Path(args.previous).read_text()) if args.previous else None
        alerts = evaluate(snapshot, load_thresholds(args.thresholds), now=args.now if args.now is not None else time.time(),
                          phase=args.phase, previous=previous)
        report = {'alerts': alerts, 'worst': alerts[0]['severity'] if alerts else None, 'memory': memory(snapshot)}
        if previous is not None:
            report['transitions'] = transitions(_previous_alerts(previous), alerts)
    except Exception as error:   # exit 3: the check itself failed, which is never a mere warning
        print(json.dumps({'error': type(error).__name__, 'worst': None}))
        return 3
    print(json.dumps(report, indent=1, sort_keys=True))
    return 2 if any(a['severity'] == 'page' for a in alerts) else 1 if any(a['severity'] == 'warn' for a in alerts) else 0


def _previous_alerts(previous):
    return (previous.get('alerts') or []) if isinstance(previous, dict) else (previous or [])


if __name__ == '__main__':
    sys.exit(main())
