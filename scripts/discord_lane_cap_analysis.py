"""Analysis and receipt for the W-02 capacity harness (scripts/discord_lane_capacity_run.py).

Every timing comes from the mock Discord's own clock (mock/mock-requests.jsonl): a post counts as sent when the mock
created a message for its nonce, its lateness is that creation time minus the post's due time from the seed manifest,
and it counts as verified at the mock when the mock answered the read-back of that message. The application's own
records (job states in the database, the lane's counters) are reported next to them as claims and cross-checked,
never used for a timing. docs/w02/capacity-standard.json is applied as written: PASS or FAIL only for what this run
measured, NOT MEASURED otherwise; injected failures are excluded from the organic Discord-limit counts and reported
on their own.
"""
import json
import math
import os
from collections import Counter, defaultdict

CREATE = 'POST /channels/{id}/messages'
READBACK = 'GET /channels/{id}/messages/{id}'
# The real per-post path of the tree under test, one entry per Discord request (route class, credential): the claim
# that sends proves the person's grant (OAuthService -> DiscordConnections.installation_identity -> GET /oauth2/@me
# with the person's bearer), reads the permission witness (server, bot member, person member, channel list) and
# creates; a later claim reads the message back. Seven requests per post; nothing else is needed per post.
IDEAL = {('GET /oauth2/@me', 'user'): 1, ('GET /guilds/{id}', 'bot'): 1, ('GET /guilds/{id}/members/{id}', 'bot'): 2,
         ('GET /guilds/{id}/channels', 'bot'): 1, (CREATE, 'bot'): 1, (READBACK, 'bot'): 1}
PREFLIGHT = tuple(key for key in IDEAL if key[0] not in (CREATE, READBACK))
# The bot's own identity (cached per process for 60 s by the tree under test): not per post.
IDENTITY = (('GET /users/@me', 'bot'), ('GET /oauth2/applications/@me', 'bot'))


def load_json(path):
    with open(path) as handle:
        return json.load(handle)


def load_jsonl(path):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path) as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def quantile(values, q):
    """Nearest-rank quantile; infinite values (never sent) sort last."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(q * len(ordered)))
    return ordered[rank - 1]


def describe(values):
    finite = [v for v in values if v is not None and math.isfinite(v)]
    return {'count': len(values), 'finite': len(finite),
            'median': quantile(values, .5), 'p95': quantile(values, .95), 'p99': quantile(values, .99),
            'max': max(values) if values else None, 'mean': (sum(finite) / len(finite)) if finite else None}


def per_post(manifest, requests):
    """Join the seed manifest with the mock's own request log: every create, first create, first read-back."""
    by_nonce = {row['nonce']: row for row in manifest}
    creates_by_nonce, creates_by_post = defaultdict(list), defaultdict(list)
    attempts_by_nonce = Counter()
    readback_by_message, message_post = {}, {}
    foreign_creates = 0
    for record in requests:
        if record.get('route') == CREATE and record.get('nonce'):
            attempts_by_nonce[record['nonce']] += 1
        if record.get('created'):
            copies = int(record.get('copies') or 1)
            for _ in range(copies):
                creates_by_nonce[record.get('nonce')].append(record['processed'])
                if record.get('post') is not None:
                    creates_by_post[record['post']].append(record['processed'])
            if record.get('nonce') not in by_nonce:
                foreign_creates += copies
            if record.get('message'):
                message_post[record['message']] = record.get('post')
        if record.get('readback') and record.get('status') == 200:
            readback_by_message.setdefault(record['readback'], record['processed'])
    readback_by_post = {}
    for message, at in readback_by_message.items():
        post = message_post.get(message)
        if post is not None:
            readback_by_post[post] = min(at, readback_by_post.get(post, at))
    posts = {}
    for row in manifest:
        creates = sorted(creates_by_nonce.get(row['nonce'], []))
        posts[row['post']] = {
            'post': row['post'], 'index': row['index'], 'workspace': row['workspace'], 'due': row['due'],
            'nonce': row['nonce'], 'expiresAt': row['expiresAt'], 'creates': creates,
            'createdAt': creates[0] if creates else None, 'createAttempts': attempts_by_nonce.get(row['nonce'], 0),
            'creates_by_post': sorted(creates_by_post.get(row['post'], [])),
            'verifiedAtMock': readback_by_post.get(row['post'])}
    return posts, foreign_creates


def busiest_window(times, seconds):
    """The largest number of events inside any window of `seconds`."""
    times = sorted(times)
    best, start = 0, 0
    for end in range(len(times)):
        while times[end] - times[start] > seconds:
            start += 1
        best = max(best, end - start + 1)
    return best


def peak_trailing(times, seconds=1.0):
    """The largest number of events in any half-open span (t - seconds, t]: the mock's own trailing-second count."""
    times = sorted(times)
    best, start = 0, 0
    for end in range(len(times)):
        while times[end] - times[start] >= seconds:
            start += 1
        best = max(best, end - start + 1)
    return best


def peak_calendar_second(times):
    """The largest number of events inside one calendar second (floor of the epoch time)."""
    counts = Counter(int(math.floor(t)) for t in times)
    return max(counts.values()) if counts else 0


def tenant_of(record):
    """The workspace index a request served, where the mock could tell (person, server or channel)."""
    for key in ('tenant', 'guild', 'channel'):
        if record.get(key) is not None:
            return record[key]
    return None


def request_ledger(window, posts):
    """Every request the mock saw during the run, in exactly one bucket: the ideal real path (IDEAL, seven per post) or
    a named overhead. Essential = one preflight pass and one create per post that was sent, plus one read-back per post
    verified at the mock; the remainder is overhead, so the buckets add up to the total."""
    sent = sum(1 for p in posts.values() if p['createdAt'] is not None)
    verified = sum(1 for p in posts.values() if p['verifiedAtMock'] is not None)
    rows = {}
    for record in window:
        key = (record.get('route'), record.get('credential') or 'none')
        row = rows.get(key)
        if row is None:
            row = rows[key] = {'route': key[0], 'credential': key[1], 'idealPerPost': IDEAL.get(key, 0),
                               'requests': 0, 'answered2xx': 0, 'organic429': 0, 'injected': 0, 'otherStatus': 0}
        row['requests'] += 1
        status = record.get('status')
        if record.get('injected'):
            row['injected'] += 1
        elif status == 429:
            row['organic429'] += 1
        elif isinstance(status, int) and 200 <= status < 300:
            row['answered2xx'] += 1
        else:
            row['otherStatus'] += 1
    buckets = Counter()
    for key, row in rows.items():
        stage = verified if key == (READBACK, 'bot') else sent
        ideal = row['idealPerPost'] * stage
        ok = row['answered2xx']
        row['perVerifiedPost'] = (row['requests'] / verified) if verified else None
        row['essential'] = min(ok, ideal)
        row['beyondIdeal'] = max(0, ok - ideal)
        row['belowIdeal'] = max(0, ideal - ok)
        buckets['essential'] += row['essential']
        buckets['answered429'] += row['organic429']
        buckets['injectedFailures'] += row['injected']
        buckets['otherStatus'] += row['otherStatus']
        if key in IDENTITY:
            buckets['botIdentity'] += ok
        elif key in PREFLIGHT:
            buckets['extraPreflight'] += row['beyondIdeal']
        elif key == (CREATE, 'bot'):
            buckets['extraCreates'] += row['beyondIdeal']
        elif key == (READBACK, 'bot'):
            buckets['extraReadbacks'] += row['beyondIdeal']
        else:
            buckets['otherRoutes'] += ok
    total = len(window)
    # Successful preflight reads beyond one pass per sent post, split by workspace: up to one pass for each post of
    # that workspace that was never sent (work for a post that did not get through), the rest a repeated pass.
    posts_by_tenant, sent_by_tenant = Counter(), Counter()
    for p in posts.values():
        posts_by_tenant[p['index']] += 1
        sent_by_tenant[p['index']] += p['createdAt'] is not None
    reads = defaultdict(Counter)
    blind = set()  # preflight routes with a read the mock could not attribute (a mock older than the ledger)
    for record in window:
        key = (record.get('route'), record.get('credential') or 'none')
        if key in PREFLIGHT and isinstance(record.get('status'), int) and 200 <= record['status'] < 300 \
                and not record.get('injected'):
            tenant = tenant_of(record)
            if tenant is None:
                blind.add(key)
            else:
                reads[tenant][key] += 1
    unattributed = sum(rows[key]['beyondIdeal'] for key in blind)
    for_unsent = repeated = 0
    for tenant, by_key in reads.items():
        unsent = posts_by_tenant.get(tenant, 0) - sent_by_tenant.get(tenant, 0)
        for key, count in by_key.items():
            if key in blind:
                continue
            extra = max(0, count - IDEAL[key] * sent_by_tenant.get(tenant, 0))
            unsent_share = min(extra, IDEAL[key] * unsent)
            for_unsent += unsent_share
            repeated += extra - unsent_share
    # Preflight passes per sent post, from one-post workspaces (one GET /guilds/{id} per pass).
    passes = Counter()
    for tenant, by_key in reads.items():
        if posts_by_tenant.get(tenant) == 1 and sent_by_tenant.get(tenant) == 1:
            passes[by_key.get(('GET /guilds/{id}', 'bot'), 0)] += 1
    per = (lambda n: (n / verified) if verified else None)
    overhead = total - buckets['essential']
    return {
        'total': total, 'sentPosts': sent, 'verifiedPosts': verified,
        'essential': buckets['essential'], 'overhead': overhead,
        'perVerifiedPost': per(total), 'essentialPerVerifiedPost': per(buckets['essential']),
        'overheadPerVerifiedPost': per(overhead),
        'overheadBuckets': {k: buckets[k] for k in ('botIdentity', 'extraPreflight', 'answered429', 'injectedFailures',
                                                    'otherStatus', 'extraCreates', 'extraReadbacks', 'otherRoutes')},
        'extraPreflightSplit': {'repeatedPassesForSentPosts': repeated, 'forPostsNeverSent': for_unsent,
                                'unattributed': unattributed, 'attributedTotal': repeated + for_unsent},
        'preflightPassesPerSentPostOnePostWorkspaces': {str(k): v for k, v in sorted(passes.items())},
        'rows': sorted(rows.values(), key=lambda r: (-r['idealPerPost'], -r['requests'])),
    }


def grant_custody(ledger):
    """What the mock saw of the person's grant check: the real path asks GET /oauth2/@me once per sent post."""
    row = next((r for r in ledger['rows'] if (r['route'], r['credential']) == ('GET /oauth2/@me', 'user')), None)
    seen = row['answered2xx'] if row else 0
    sent = ledger['sentPosts']
    if not sent:
        return {'state': 'not measured', 'identityChecks': seen, 'sentPosts': sent}
    return {'state': 'real path' if seen >= sent else 'below one per sent post', 'identityChecks': seen,
            'sentPosts': sent}


def cron_gap(invocations, period, *, first_minute, last_minute):
    """Per shard: seconds of each cron period in which no loop of that shard was inside its handler."""
    by_shard = defaultdict(list)
    for item in invocations:
        path = item.get('path', '')
        if not path.startswith('/api/cron/discord-worker/'):
            continue
        start, end = item.get('handlerStartedAt'), item.get('handlerEndedAt')
        if start and end:
            by_shard[path].append((start, end))
    gaps = []
    for _, spans in by_shard.items():
        minute = first_minute
        while minute < last_minute:
            window_end = minute + period
            covered, cursor = 0.0, minute
            for start, end in sorted(spans):
                start, end = max(start, cursor), min(end, window_end)
                if end > start:
                    covered += end - start
                    cursor = end
            gaps.append(period - covered)
            minute += period
    if not gaps:
        return None
    return {'periodSeconds': period, 'shardPeriods': len(gaps), 'meanGapSeconds': sum(gaps) / len(gaps),
            'maxGapSeconds': max(gaps), 'minGapSeconds': min(gaps)}


def analyse(run_dir):
    config = load_json(os.path.join(run_dir, 'config.json'))
    manifest = load_jsonl(os.path.join(run_dir, 'seed-manifest.jsonl'))
    requests = load_jsonl(os.path.join(run_dir, 'mock', 'mock-requests.jsonl'))
    mock_summary = load_json(os.path.join(run_dir, 'mock', 'mock-summary.json'))
    final_states = load_json(os.path.join(run_dir, 'final-states.json'))
    folder = os.path.join(run_dir, 'invocations')
    invocations = []
    for name in sorted(os.listdir(folder)):
        if name.endswith('.json'):
            try:
                invocations.append(load_json(os.path.join(folder, name)))
            except ValueError:
                invocations.append({'path': name, 'exception': 'unreadable result'})
    events = load_jsonl(os.path.join(run_dir, 'invocations.jsonl'))
    spawned = [e for e in events if e.get('event') == 'spawned']
    samples = load_jsonl(os.path.join(run_dir, 'samples.jsonl'))
    pooler = None
    if os.path.exists(os.path.join(run_dir, 'pooler-final.json')):
        pooler = load_json(os.path.join(run_dir, 'pooler-final.json'))
    extra = load_json(os.path.join(run_dir, 'database-final.json')) if os.path.exists(
        os.path.join(run_dir, 'database-final.json')) else {}

    T = config['dueAt']
    posts, foreign_creates = per_post(manifest, requests)
    window = [r for r in requests if r['processed'] >= config['runStartedAt']]
    counters = mock_summary['counters']

    # Lateness from the mock's clock; a post never created counts as infinitely late.
    lateness_all = [(p['createdAt'] - p['due']) if p['createdAt'] is not None else math.inf for p in posts.values()]
    lateness_sent = [v for v in lateness_all if math.isfinite(v)]
    # Time to verified: due time to the read-back the mock answered (what the customer sees as confirmed).
    to_verified_all = [(p['verifiedAtMock'] - p['due']) if p['verifiedAtMock'] is not None else math.inf
                       for p in posts.values()]
    to_verified_done = [v for v in to_verified_all if math.isfinite(v)]
    create_to_verified = [p['verifiedAtMock'] - p['createdAt'] for p in posts.values()
                          if p['verifiedAtMock'] is not None and p['createdAt'] is not None]
    duplicates_nonce = sum(max(0, len(p['creates']) - 1) for p in posts.values())
    duplicates_post = sum(max(0, len(p['creates_by_post']) - 1) for p in posts.values())
    after_expiry = sum(1 for p in posts.values() for at in p['creates'] if at >= p['expiresAt'])
    sent = sum(1 for p in posts.values() if p['createdAt'] is not None)
    verified_mock = sum(1 for p in posts.values() if p['verifiedAtMock'] is not None)
    last_create = max((p['createdAt'] for p in posts.values() if p['createdAt'] is not None), default=None)
    last_verified = max((p['verifiedAtMock'] for p in posts.values() if p['verifiedAtMock'] is not None), default=None)
    first_create = min((p['createdAt'] for p in posts.values() if p['createdAt'] is not None), default=None)
    unverified_at_last_create = (sum(1 for p in posts.values() if p['verifiedAtMock'] is None
                                     or p['verifiedAtMock'] > last_create) if last_create is not None else None)

    states = Counter(final_states.get('byPost', {}).get(p, 'missing') for p in posts)
    db_verified = states.get('verified', 0)
    # Every post not verified at the mock, by its final database state and by whether the mock saw any create
    # attempt for it (an 'uncertain' post with no attempt was never sent; one with an attempt needs reconciliation).
    unverified = Counter()
    for post_id, p in posts.items():
        if p['verifiedAtMock'] is None:
            state = final_states.get('byPost', {}).get(post_id, 'missing')
            unverified['%s, %s' % (state, 'create attempted at the mock' if p['createAttempts'] or p['creates']
                                   else 'no create at the mock')] += 1

    # Requests, as the mock saw them during the run (seeding used an in-process world and is not in this log).
    routes = Counter(r['route'] for r in window)
    statuses = Counter(str(r.get('status')) for r in window)
    credentials = Counter(r.get('credential') for r in window)
    injected = Counter(r.get('injected') for r in window if r.get('injected'))
    organic_create_429 = sum(1 for r in window if r.get('route') == CREATE and r.get('status') == 429 and not r.get('injected'))
    organic_global_429 = sum(1 for r in window if r.get('global429') and not r.get('injected'))
    invalid_times = [r['processed'] for r in window if r.get('status') in (401, 403, 429)]
    misrouted = sum(1 for r in window if r.get('misrouted'))
    misrouted_by_harness = sum(int(i.get('misroutedByHarness') or 0) for i in invocations)
    requests_per_verified = (len(window) / verified_mock) if verified_mock else None
    ledger = request_ledger(window, posts)
    custody = grant_custody(ledger)
    per_minute = Counter(int((p['createdAt'] - T) // 60) for p in posts.values() if p['createdAt'] is not None)

    # Normal load (S0): shares sent within 2, 5 and 15 minutes of each post's own due time.
    total = len(posts) or 1
    normal = {'within2': sum(1 for v in lateness_all if v <= 120) / total,
              'within5': sum(1 for v in lateness_all if v <= 300) / total,
              'within15': sum(1 for v in lateness_all if v <= 900) / total,
              'notSentShare': (len(posts) - sent) / total}

    # Fairness: small workspaces (at most five posts) against the hot workspace, if there is one.
    by_workspace = defaultdict(list)
    for p in posts.values():
        by_workspace[p['index']].append(p)
    sizes = {index: len(items) for index, items in by_workspace.items()}
    fairness = None
    if config.get('hotPosts'):
        hot_index = max(sizes, key=sizes.get)
        hot_posts = by_workspace[hot_index]
        hot_created = [p['createdAt'] for p in hot_posts if p['createdAt'] is not None]
        hot_last = max(hot_created) if hot_created and len(hot_created) == len(hot_posts) else math.inf
        completions = []
        for index, items in by_workspace.items():
            if index == hot_index or len(items) > 5:
                continue
            times = [p['createdAt'] for p in items]
            completions.append(max(times) - T if all(t is not None for t in times) else math.inf)
        hot_lateness = [(p['createdAt'] - p['due']) if p['createdAt'] is not None else math.inf for p in hot_posts]
        small_done_by = max(completions) if completions else None
        fairness = {'hotWorkspace': hot_index, 'hotPosts': len(hot_posts), 'hotSent': len(hot_created),
                    'hotLastCreateAfterT': (max(hot_created) - T) if hot_created else None,
                    'hotLateness': describe(hot_lateness), 'smallWorkspaces': len(completions),
                    'smallCompletionAfterT': describe(completions),
                    'smallAllDoneWhileHotActive': bool(small_done_by is not None and math.isfinite(small_done_by)
                                                       and (not math.isfinite(hot_last) or T + small_done_by < hot_last))}

    # Workers (the cron invocations).
    lane = [i for i in invocations if i.get('path', '').startswith('/api/cron/discord-worker/')]
    minute = [i for i in invocations if i.get('path') == '/api/cron/worker']
    lane_counters, stopped = Counter(), Counter()
    for item in lane:
        body = item.get('body') or {}
        for key, value in (body.get('counters') or {}).items():
            if isinstance(value, (int, float)):
                lane_counters[key] += value
        stopped[str(body.get('stoppedBy', 'disabled' if body.get('enabled') is False else body.get('error', '?')))] += 1
    minute_discord = Counter()
    for item in minute:
        report = ((item.get('body') or {}).get('discordWorker') or {}).get('counters') or {}
        for key, value in report.items():
            if isinstance(value, (int, float)):
                minute_discord[key] += value
    cpu = [i.get('cpuUser', 0) + i.get('cpuSystem', 0) for i in invocations]
    rss = [i.get('maxRssKb', 0) for i in invocations]
    failures = [i for i in invocations if i.get('status') != 200 or i.get('exception')]
    killed = [e for e in events if e.get('event') == 'killed']
    handler_seconds = [i['handlerEndedAt'] - i['handlerStartedAt'] for i in lane
                       if i.get('handlerStartedAt') and i.get('handlerEndedAt')]
    start_delay = [i['handlerStartedAt'] - i['scheduledAt'] for i in invocations
                   if i.get('handlerStartedAt') and i.get('scheduledAt')]
    blocked = sum(i.get('blockedEgressCount', 0) for i in invocations)
    period = config['cronPeriodSeconds']
    drain_end = last_verified or last_create or T
    first = config.get('firstCronAt') or T
    gap = cron_gap(invocations, period, first_minute=max(first, math.floor(T / period) * period),
                   last_minute=max(first + period, first + period * math.ceil((drain_end - first) / period)))

    # Database and pooler.
    peak_backends = max((s.get('db', {}).get('backends', 0) for s in samples), default=None)
    peak_active = max((s.get('db', {}).get('active', 0) for s in samples), default=None)
    longest_sampled = max((s.get('db', {}).get('longestActiveSeconds') or 0 for s in samples), default=None)
    lock_waits = max((s.get('db', {}).get('lockWaits', 0) for s in samples), default=None)
    load = max((s.get('load1') or 0 for s in samples), default=None)
    cpu_series = [s['cpu']['postgres'] for s in samples if s.get('cpu', {}).get('postgres') is not None]
    pg_cpu = (cpu_series[-1] - cpu_series[0]) if len(cpu_series) > 1 else None
    database = {'peakBackendsSampled': peak_backends, 'peakActiveSampled': peak_active,
                'peakLockWaitsSampled': lock_waits, 'longestActiveStatementSampledSeconds': longest_sampled,
                'postgresCpuSeconds': pg_cpu, 'serverVersion': config.get('serverVersion'),
                **{k: v for k, v in extra.items() if k not in ('kills', 'lockInjections', 'admissionWindow')}}
    errors = Counter()
    if pooler:
        database['pooler'] = {k: pooler.get(k) for k in (
            'mode', 'poolSize', 'maxClients', 'latencyMs', 'connectRtts', 'waitTimeoutSeconds', 'clientPeak',
            'assignedPeak', 'waitingPeak', 'demandPeak', 'transactions', 'waitTimeouts', 'clientsRefused',
            'dirtyReleases', 'ignoredStartupOptions', 'errorsBySqlstate', 'waitSeconds', 'transactionHoldSeconds',
            'exchangeSeconds', 'cpuSeconds')}
        if pooler.get('mode') == 'pool' and pooler.get('poolSize'):
            database['poolerDemandShare'] = (pooler.get('demandPeak') or 0) / pooler['poolSize']
            errors.update(pooler.get('errorsBySqlstate') or {})
            database['statementTimeouts'] = (pooler.get('errorsBySqlstate') or {}).get('57014', 0)
        else:
            database['statementTimeouts'] = (extra.get('logErrorsBySqlstate') or {}).get('57014', 0)
    else:
        database['statementTimeouts'] = (extra.get('logErrorsBySqlstate') or {}).get('57014', 0)
    bouncer = [x['pgbouncer'] for x in samples if isinstance(x.get('pgbouncer'), dict) and 'error' not in x['pgbouncer']]
    if bouncer:
        database['pgbouncer'] = {'peakServerActive': max(b['svActive'] for b in bouncer),
                                 'peakClientsWaiting': max(b['clWaiting'] for b in bouncer),
                                 'peakDemand': max(b['svActive'] + b['clWaiting'] for b in bouncer),
                                 'longestWaitSeconds': max(b['maxWait'] for b in bouncer)}
        if config.get('poolSize'):
            database['poolerDemandShare'] = database['pgbouncer']['peakDemand'] / config['poolSize']
        database['statementTimeouts'] = (extra.get('logErrorsBySqlstate') or {}).get('57014', 0)
    for code, count in (extra.get('logErrorsBySqlstate') or {}).items():
        errors['postgresLog:' + code] += count

    kills = extra.get('kills') or []
    result = {
        'version': 2, 'scenario': config['scenario'], 'label': config['label'], 'sourceTree': config['sourceTree'],
        'sourceSha': config['sourceSha'], 'harnessSha': config.get('harnessSha'), 'dueAt': T,
        'informationOnly': config.get('informationOnly'),
        'posts': len(posts), 'workspaces': len(by_workspace), 'endReason': config.get('endReason'),
        'lateness': {'allPostsUnsentInfinite': describe(lateness_all), 'sentOnly': describe(lateness_sent),
                     'source': 'mock create time (mock clock) minus the due time from the seed manifest'},
        'timeToVerified': {'allPostsUnverifiedInfinite': describe(to_verified_all), 'verifiedOnly': describe(to_verified_done),
                           'createToVerified': describe(create_to_verified),
                           'source': 'mock read-back answer time (mock clock) minus the due time from the seed manifest'},
        'normal': normal,
        'drain': {'firstCreateAfterT': (first_create - T) if first_create else None,
                  'lastCreateAfterT': (last_create - T) if last_create else None,
                  'lastVerifiedAtMockAfterT': (last_verified - T) if last_verified else None,
                  'unverifiedAtLastCreate': unverified_at_last_create,
                  'allTerminalInDatabaseAfterT': (config.get('allTerminalAt') - T) if config.get('allTerminalAt') else None},
        'creationsPerMinute': {str(k): v for k, v in sorted(per_minute.items())},
        'outcomes': {'sentAtMock': sent, 'verifiedAtMock': verified_mock, 'verifiedInDatabase': db_verified,
                     'notVerified': len(posts) - verified_mock, 'databaseStates': dict(states),
                     'deadLetters': final_states.get('deadLetters', 0), 'notSent': len(posts) - sent,
                     'foreignCreates': foreign_creates, 'notVerifiedByStateAndAttempt': dict(unverified)},
        'duplicates': {'byNonce': duplicates_nonce, 'byPostId': duplicates_post,
                       'mockCounterNonce': counters.get('duplicateNonceCreates'),
                       'mockCounterPost': counters.get('duplicatePostCreates'),
                       'mockDoubleAccepted': counters.get('doubleAccepted')},
        'sendsAfterApprovalExpiry': after_expiry,
        'isolation': {'misroutedAtMock': misrouted, 'misroutedByHarness': misrouted_by_harness,
                      'createsChecked': sum(1 for r in window if r.get('created'))},
        'ceiling': {'policyCeiling': config['policyCeiling'], 'aboveTwentyFiveAll': counters.get('abovePolicyAll'),
                    'aboveFiftyBot': counters.get('aboveGlobalBot'), 'aboveFiftyAll': counters.get('aboveGlobalAll'),
                    'peakTrailingSecondAll': mock_summary.get('peakTrailingSecondAll'),
                    'peakTrailingSecondBot': mock_summary.get('peakTrailingSecondBot'),
                    'peakCalendarSecondAll': peak_calendar_second([r['processed'] for r in window]),
                    'peakTenSecondAveragePerSecond': busiest_window([r['processed'] for r in window], 10.0) / 10.0,
                    'busiest60sPerSecond': busiest_window([r['processed'] for r in window], 60.0) / 60.0,
                    'busiest300sPerSecond': busiest_window([r['processed'] for r in window], 300.0) / 300.0,
                    'coordinatorAdmissions': extra.get('admissionWindow')},
        'ledger': ledger, 'grantCustody': custody,
        'requests': {'total': len(window), 'perVerifiedPost': requests_per_verified, 'byRoute': dict(routes),
                     'byStatus': dict(statuses), 'byCredential': dict(credentials), 'injected': dict(injected),
                     'global429': counters.get('global429'), 'route429': counters.get('route429'),
                     'organicCreate429': organic_create_429, 'organicGlobal429': organic_global_429,
                     'invalidPeak10Minutes': busiest_window(invalid_times, 600.0),
                     'unauthorized': counters.get('unauthorized'), 'unknownRoute': counters.get('unknownRoute'),
                     'notFound': counters.get('notFound')},
        'fairness': fairness,
        'workers': {'invocations': len(invocations), 'spawned': len(spawned), 'laneInvocations': len(lane),
                    'minuteInvocations': len(minute), 'failedInvocations': len(failures),
                    'failureSamples': [{k: f.get(k) for k in ('path', 'status', 'exception', 'setupError')}
                                       for f in failures[:5]],
                    'killedAtFunctionLimit': sum(1 for e in killed if e.get('reason') == 'function_limit'),
                    'killedByInjector': sum(1 for e in killed if str(e.get('reason', '')).startswith('injected')),
                    'killedAtEnd': sum(1 for e in killed if e.get('reason') == 'end_of_run'),
                    'laneCounters': dict(lane_counters), 'laneStoppedBy': dict(stopped),
                    'minuteWorkerDiscordCounters': dict(minute_discord),
                    'cpuSecondsTotal': sum(cpu), 'cpuSecondsPerInvocation': describe(cpu),
                    'maxRssMb': (max(rss) / 1024) if rss else None,
                    'laneHandlerSeconds': describe(handler_seconds), 'startDelaySeconds': describe(start_delay),
                    'blockedEgress': blocked},
        'kills': kills, 'lockInjections': extra.get('lockInjections') or [],
        'cronGap': gap, 'database': database, 'errors': dict(errors), 'machineLoad1Max': load,
        'mockCpuSeconds': config.get('mockCpuSeconds'),
    }
    result['_posts'] = posts
    result['_states'] = final_states.get('byPost', {})
    result['_window'] = window
    result['_invocations'] = invocations
    return result


# --- the written standard ------------------------------------------------------------------------------------------

def _value(result, path):
    value = result
    for part in path.split('.'):
        if value is None:
            return None
        value = value.get(part) if isinstance(value, dict) else None
    return value


def all_measures(standard):
    return list(standard['measures']) + list((standard.get('normalLoad') or {}).get('measures') or [])


def judge(result, standard):
    rows = []
    for measure in all_measures(standard):
        applies, excluded = measure.get('appliesTo'), measure.get('notFor') or []
        if (applies and result['scenario'] not in applies) or result['scenario'] in excluded:
            rows.append({**measure, 'value': None, 'verdict': 'NOT APPLICABLE'})
            continue
        value = _value(result, measure['path'])
        if measure.get('scale') and isinstance(value, (int, float)):
            value = value * measure['scale']
        if value is None:
            verdict = 'NOT MEASURED'
        elif not result['outcomes']['sentAtMock'] and measure['op'] != 'report':
            verdict = 'NOT MEASURED'  # nothing was sent: a zero count proves nothing
        elif measure['op'] == '<=':
            verdict = 'PASS' if value <= measure['limit'] else 'FAIL'
        elif measure['op'] == '>=':
            verdict = 'PASS' if value >= measure['limit'] else 'FAIL'
        elif measure['op'] == '==':
            verdict = 'PASS' if value == measure['limit'] else 'FAIL'
        elif measure['op'] == 'report':
            verdict = 'REPORTED'
        else:
            verdict = 'NOT MEASURED'
        if result.get('informationOnly') and verdict in ('PASS', 'FAIL'):
            verdict = 'INFO ' + verdict
        rows.append({**measure, 'value': value, 'verdict': verdict})
    return rows


# --- expected behaviour of each scenario -----------------------------------------------------------------------------

def _line(rows, ident, name, ok, measured, expected):
    rows.append({'id': ident, 'name': name, 'expected': expected, 'measured': measured,
                 'verdict': 'NOT MEASURED' if ok is None else ('PASS' if ok else 'FAIL')})


def expectations(result, config, standard):
    """Explicit expected behaviour per scenario, as PASS/FAIL lines computed from the mock log and final states."""
    rows = []
    posts, window = result['_posts'], result['_window']
    states = result['_states']
    T = result['dueAt']
    wanted = set(config.get('expect') or ())
    o, d, w = result['outcomes'], result['duplicates'], result['workers']
    if 'no_duplicates' in wanted or 'standard' in wanted or 'normal_load' in wanted or 'all_verified' in wanted:
        _line(rows, 'no_duplicates', 'No post created twice (by nonce and by post id)',
              d['byNonce'] == 0 and d['byPostId'] == 0, '%d by nonce, %d by post id' % (d['byNonce'], d['byPostId']), '0')
    if 'no_late_sends' in wanted or 'standard' in wanted or 'normal_load' in wanted or 'all_verified' in wanted:
        _line(rows, 'no_late_sends', 'Nothing created after its approval expired', result['sendsAfterApprovalExpiry'] == 0,
              result['sendsAfterApprovalExpiry'], '0')
    if 'all_verified' in wanted:
        _line(rows, 'all_verified', 'Every post verified (mock read-back and database)',
              o['verifiedAtMock'] == result['posts'] and o['verifiedInDatabase'] == result['posts'],
              '%d of %d at the mock, %d in the database' % (o['verifiedAtMock'], result['posts'], o['verifiedInDatabase']),
              'all')
    if wanted & {'isolation', 'standard', 'normal_load'}:
        i = result['isolation']
        _line(rows, 'isolation', 'Every create reached its own tenant\'s channel; no create for an unknown post',
              i['misroutedAtMock'] == 0 and o['foreignCreates'] == 0,
              '%d misrouted of %d creates; %d unknown' % (i['misroutedAtMock'], i['createsChecked'], o['foreignCreates']),
              '0 misrouted, 0 unknown')
    if 'clean_workers' in wanted:
        _line(rows, 'clean_workers', 'Every invocation answered 200, none killed at the function limit, no egress refused',
              w['failedInvocations'] == 0 and w['killedAtFunctionLimit'] == 0 and w['blockedEgress'] == 0,
              '%d failed, %d killed at 300 s, %d refused egress' % (w['failedInvocations'], w['killedAtFunctionLimit'],
                                                                     w['blockedEgress']), '0, 0, 0')
    if 'baseline' in wanted:
        minutes = config['settings']['fixed_run_minutes'] or 10
        created = sum(1 for p in posts.values() if p['createdAt'] is not None and p['createdAt'] < T + 60 * minutes)
        verified = sum(1 for p in posts.values() if p['verifiedAtMock'] is not None and p['verifiedAtMock'] < T + 60 * minutes)
        rate = created / minutes
        result['baseline'] = {'minutes': minutes, 'created': created, 'verified': verified, 'createdPerMinute': rate,
                              'verifiedPerMinute': verified / minutes,
                              'extrapolatedHoursFor5000': (5000 / rate / 60) if rate else None}
        _line(rows, 'baseline_rate', 'Frozen minute worker: Discord posts created per minute (claim: 6 to 12)',
              None if not minutes else (6 <= rate <= 12),
              '%.1f created and %.1f verified per minute over %d min; 5,000 would take %s h' % (
                  rate, verified / minutes, minutes, '%.1f' % (5000 / rate / 60) if rate else 'n/a'), '6 to 12 per minute')
    if 'f429' in wanted:
        injected = [r for r in window if r.get('injected')]
        by_nonce_post = {p['nonce']: p['post'] for p in posts.values()}
        storm, resumed = [], []
        for rule in config.get('mockInjections') or []:
            if rule['kind'] != 'global429':
                continue
            hits = [r['processed'] for r in injected if r.get('injected') == 'global429' and rule['at'] <= r['processed'] < rule['at'] + rule.get('seconds', 1)]
            if not hits:
                continue
            embargo_from, embargo_to = min(hits) + 0.5, rule['at'] + rule.get('retryAfter', 5)
            during = [r for r in window if r.get('credential') == 'bot' and embargo_from <= r['processed'] < embargo_to
                      and r.get('injected') != 'global429']
            storm.append(len(during))
            after = [r['processed'] for r in window if r.get('created') and r['processed'] >= embargo_to]
            resumed.append((min(after) - embargo_to) if after else None)
        bound = 2 * max(1, len([r for r in config.get('routes', []) if 'discord-worker' in r]))
        _line(rows, 'f429_no_storm', 'Inside each global 429 embargo the mock sees at most the requests already admitted',
              None if not storm else all(n <= bound for n in storm), 'bot requests inside each embargo: %s' % storm,
              'at most %d (two per loop)' % bound)
        _line(rows, 'f429_recovery', 'Creates resume after each embargo', None if not resumed else all(r is not None and r < 60 for r in resumed),
              'seconds from the end of each embargo to the next create: %s' % [None if r is None else round(r, 1) for r in resumed],
              'within 60 s')
        # A create answered 429 (global window or route) is held for review and never resent (existing rule).
        create_hits = [r for r in injected if r.get('injected') in ('route429', 'global429') and r.get('route') == CREATE]
        hit_posts = sorted({r.get('post') or by_nonce_post.get(r.get('nonce')) for r in create_hits} - {None})
        resent = [p for p in hit_posts if len(posts[p]['creates']) > 0 or posts[p]['createAttempts'] > 1]
        held = [p for p in hit_posts if states.get(p) == 'held']
        _line(rows, 'f429_create_held', 'A post whose create got a 429 (global window or route) is held and never resent (existing rule)',
              None if not hit_posts else (not resent and len(held) == len(hit_posts)),
              '%d hit; %d held; %d sent again' % (len(hit_posts), len(held), len(resent)), 'all held, none resent')
        ban = [r for r in injected if r.get('injected') == 'html429']
        ban_guilds = sorted({r.get('guild') for r in ban if r.get('guild') is not None})
        ban_posts = [p for p in posts.values() if p['index'] in ban_guilds]
        ban_dupes = sum(max(0, len(p['creates']) - 1) for p in ban_posts)
        _line(rows, 'f429_ban_page', 'A ban page (HTML 429) holds that route; nothing is duplicated; its posts wait',
              None if not ban or not ban_guilds else ban_dupes == 0,  # no server named: nothing to follow
              '%d ban pages on %d servers; their %d posts: %s; duplicates %d' % (
                  len(ban), len(ban_guilds), len(ban_posts), dict(Counter(states.get(p['post'], '?') for p in ban_posts)), ban_dupes),
              'no duplicate; posts unsent or held until an operator lifts the hold')
        others = [p for p in posts.values() if p['post'] not in hit_posts and p['index'] not in ban_guilds]
        others_ok = sum(1 for p in others if p['verifiedAtMock'] is not None)
        _line(rows, 'f429_others_verified', 'Every post not hit by a create 429 or a ban page is verified',
              others_ok == len(others), '%d of %d' % (others_ok, len(others)), 'all')
    if 'f5xx' in wanted:
        injected = [r for r in window if r.get('injected') in ('create500', 'createTimeout') and r.get('post')]
        hit = {}
        for r in injected:
            hit.setdefault(r['post'], r)
        twice = [p for p in hit if len(posts[p]['creates']) > 1 or posts[p]['createAttempts'] > 1]
        landed_ok = all(len(posts[p]['creates']) == (1 if r.get('landed') else 0) for p, r in hit.items())
        uncertain = [p for p in hit if states.get(p) == 'uncertain']
        _line(rows, 'f5xx_never_resent', 'No post whose create got a 5xx or timed out is created again',
              None if not hit else not twice and landed_ok,
              '%d affected (%d landed); %d attempted twice' % (len(hit), sum(1 for r in hit.values() if r.get('landed')), len(twice)),
              'each attempted once')
        _line(rows, 'f5xx_uncertain', 'Each affected post ends uncertain for manual reconciliation',
              None if not hit else len(uncertain) == len(hit), 'states: %s' % dict(Counter(states.get(p, '?') for p in hit)),
              'all uncertain')
        others = [p for p in posts.values() if p['post'] not in hit]
        ok = sum(1 for p in others if p['verifiedAtMock'] is not None)
        _line(rows, 'f5xx_others_verified', 'Every other post is verified', ok == len(others), '%d of %d' % (ok, len(others)), 'all')
        leaked = (result['database'].get('admissionsByState') or {})
        _line(rows, 'f5xx_leaked_slots', 'Request admissions left without an observed answer (each keeps one slot of the 25/s budget, Q3)',
              None, '%s' % {k: v for k, v in leaked.items() if k in ('sent', 'uncertain', 'reserved', 'sealed')}, 'reported')
    if 'fcrash' in wanted:
        kills = result.get('kills') or []
        done = [k for k in kills if k.get('kind') in ('random', 'at_create')]
        planned = len(config['settings'].get('kills') or []) + int(config['settings'].get('kill_at_create') or 0)
        _line(rows, 'fcrash_kills', 'The planned SIGKILLs were delivered', len(done) >= planned,
              '%d delivered (%d random, %d during a create), %d missed' % (
                  len(done), sum(1 for k in done if k['kind'] == 'random'), sum(1 for k in done if k['kind'] == 'at_create'),
                  sum(1 for k in kills if k.get('kind') == 'at_create_missed')), '%d' % planned)
        verified_or_uncertain = sum(1 for p in posts if states.get(p) in ('verified', 'uncertain'))
        uncertain = sum(1 for p in posts if states.get(p) == 'uncertain')
        _line(rows, 'fcrash_outcome', 'Every post verified, or uncertain only where a kill hit a sealed send',
              verified_or_uncertain == len(posts) and uncertain <= len(done),
              'verified %d, uncertain %d, other %d' % (o['verifiedInDatabase'], uncertain, len(posts) - verified_or_uncertain),
              'uncertain at most the number of kills')
        _line(rows, 'fcrash_drained', 'The drain completed (no post left pending)', result.get('endReason') == 'every post terminal',
              result.get('endReason'), 'every post terminal')
    if 'fdb' in wanted:
        starved = [index for index in {p['index'] for p in posts.values()}
                   if not all(q['verifiedAtMock'] is not None for q in posts.values() if q['index'] == index)]
        _line(rows, 'fdb_no_starvation', 'No starvation: every workspace\'s posts verified', not starved,
              '%d workspaces with an unverified post' % len(starved), '0')
        _line(rows, 'fdb_injected', 'The lock injections ran', bool(result.get('lockInjections')),
              '%d lock holds' % len([x for x in result.get('lockInjections') or [] if 'from' in x]), 'at least one')
        _line(rows, 'fdb_errors', 'Database errors under contention (reported)', None, json.dumps(result['errors'], sort_keys=True), 'reported')
    if 'fexpiry' in wanted:
        held = sum(1 for p in posts if states.get(p) == 'held')
        other = sum(1 for p in posts if states.get(p) not in ('verified', 'held'))
        expiry = min((p['expiresAt'] for p in posts.values()), default=None)
        _line(rows, 'fexpiry_held', 'Posts not sent before their approval expired are held; none pending or failed',
              other == 0 and held > 0, 'verified %d, held %d, other %d (approvals expired at T+%.1f min)' % (
                  o['verifiedInDatabase'], held, other, ((expiry - T) / 60) if expiry else float('nan')), 'held > 0, other 0')
    if 'fstall' in wanted:
        stall = config['settings'].get('stall') or [0, 0]
        during = [r for r in window if r.get('created') and T + 60 * stall[0] <= r['processed'] < T + 60 * stall[1]]
        _line(rows, 'fstall_quiet', 'Nothing is sent while no cron fires', len(during) == 0, '%d creates' % len(during), '0')
        ok = sum(1 for p in posts.values() if p['verifiedAtMock'] is not None)
        _line(rows, 'fstall_recovered', 'Every post verified after the restore', ok == len(posts), '%d of %d' % (ok, len(posts)), 'all')
        drain = result['drain']['lastVerifiedAtMockAfterT']
        _line(rows, 'fstall_drain', 'Drain after the restore (reported)', None,
              '%s min after the crons came back' % (('%.1f' % ((drain - 60 * stall[1]) / 60)) if drain else 'n/a'), 'reported')
    if 'fflip' in wanted:
        flip = config['settings'].get('flag_off') or [0, 0]
        invocations = result['_invocations']
        off = [i for i in invocations if T + 60 * flip[0] <= (i.get('scheduledAt') or 0) < T + 60 * flip[1]]
        lane_off = [i for i in off if i.get('path', '').startswith('/api/cron/discord-worker/')]
        minute_off = [i for i in off if i.get('path') == '/api/cron/worker']
        disabled = sum(1 for i in lane_off if (i.get('body') or {}).get('enabled') is False)
        claims = sum(((i.get('body') or {}).get('discordWorker') or {}).get('counters', {}).get('claims', 0) for i in minute_off)
        _line(rows, 'fflip_off', 'While the flag is off the shards answer disabled and the minute worker claims Discord',
              None if not off else (disabled == len(lane_off) and claims > 0),
              '%d of %d shard answers disabled; minute worker Discord claims %d' % (disabled, len(lane_off), claims),
              'all disabled, claims > 0')
        after = [i for i in invocations if (i.get('scheduledAt') or 0) >= T + 60 * flip[1] and i.get('path', '').startswith('/api/cron/discord-worker/')]
        posted = sum(((i.get('body') or {}).get('counters') or {}).get('posted', 0) for i in after)
        _line(rows, 'fflip_on', 'After the flag is on again the lane sends', None if not after else posted > 0,
              'lane posted %d after T+%d min' % (posted, flip[1]), '> 0')
        ok = sum(1 for p in posts.values() if p['verifiedAtMock'] is not None)
        _line(rows, 'fflip_verified', 'Every post verified across the hand-over', ok == len(posts), '%d of %d' % (ok, len(posts)), 'all')
    if 'negative_misroute' in wanted:
        i = result['isolation']
        _line(rows, 'negative_misroute', 'Negative control: the isolation check fires for every misrouted create',
              i['misroutedByHarness'] > 0 and i['misroutedAtMock'] == i['misroutedByHarness'],
              '%d misrouted by the harness, %d detected by the mock' % (i['misroutedByHarness'], i['misroutedAtMock']), 'equal and > 0')
    if 'negative_duplicates' in wanted:
        _line(rows, 'negative_duplicates', 'Negative control: both duplicate counters report the double accepts',
              d['mockDoubleAccepted'] and d['byNonce'] == d['mockDoubleAccepted'] and d['byPostId'] == d['mockDoubleAccepted'],
              '%s double accepted; %d by nonce, %d by post id' % (d['mockDoubleAccepted'], d['byNonce'], d['byPostId']), 'equal and > 0')
    if 'negative_ceiling' in wanted:
        c = result['ceiling']
        _line(rows, 'negative_ceiling', 'Negative control: with the policy at %s/s the 25/s counter fires' % config['ratePolicy']['app_capacity'],
              bool(c['aboveTwentyFiveAll']), '%s requests above 25 and %s bot requests above 50 in a trailing second; peak %s' % (
                  c['aboveTwentyFiveAll'], c['aboveFiftyBot'], c['peakTrailingSecondAll']), '> 0')
        rate = (o['verifiedAtMock'] / ((result['drain']['lastVerifiedAtMockAfterT'] or 1))) if o['verifiedAtMock'] else 0
        _line(rows, 'information_only', 'INFORMATION ONLY: throughput with a 100/s ceiling (not a reviewed setting)', None,
              '%.2f verified posts per second; %s requests per post' % (rate, _fmt(result['requests']['perVerifiedPost'])),
              'reported')
    return rows


# --- the receipt ---------------------------------------------------------------------------------------------------

def _fmt(value, unit=''):
    if value is None:
        return 'n/a'
    if isinstance(value, float):
        if math.isinf(value):
            return 'never (not sent)'
        if unit == 'min':
            return '%.2f min' % value
        if unit == 's':
            return '%.1f s' % value
        return ('%.3f' % value if abs(value) < 10 else '%.1f' % value) if abs(value) < 1000 else '%.0f' % value
    return str(value) + ((' ' + unit) if unit and unit not in ('min', 's') else '')


def _minutes(value):
    return _fmt(value / 60 if isinstance(value, (int, float)) else None, 'min')


def receipt(result, verdicts, config, differences, expectations=()):
    lines = []
    counted = Counter(v['verdict'] for v in verdicts)
    failed = [v for v in verdicts if v['verdict'] == 'FAIL']
    exp_failed = [e for e in expectations if e['verdict'] == 'FAIL']
    lines.append('# Capacity receipt: %s (%s)' % (result['label'], result['scenario']))
    lines.append('')
    if config.get('partial'):
        lines.append('**PARTIAL: this run was interrupted (%s). The figures cover the run up to the interruption only; '
                     'a drain or lateness figure here is not a complete measurement.**' % config.get('endReason'))
        lines.append('')
    lines.append('Source tree under test: `%s`, commit `%s`. Harness commit `%s`. Due time T: %s. Ended: %s. '
                 'Generated by `scripts/discord_lane_capacity_run.py`; every timing is the mock Discord\'s own clock.' % (
                     result['sourceTree'], result['sourceSha'], result.get('harnessSha'), config['dueAtIso'],
                     result.get('endReason')))
    lines.append('')
    if config.get('description'):
        lines.append('Scenario: ' + config['description'])
        lines.append('')
    if result.get('informationOnly'):
        lines.append('**INFORMATION ONLY: this run used a setting that is not reviewed (for example a rate policy above '
                     '25/s). Nothing here is evidence for the release.**')
        lines.append('')
    lines.append('**Against `docs/w02/capacity-standard.json`: %s.** %s' % (
        ', '.join('%d %s' % (n, k) for k, n in sorted(counted.items()) if k != 'NOT APPLICABLE') or 'nothing applicable',
        'This run does NOT meet the standard.' if failed else
        ('NOT MEASURED items are not a pass.' if counted.get('NOT MEASURED') else '')))
    if expectations:
        lines.append('**Expected behaviour of this scenario: %s.**' % ', '.join(
            '%d %s' % (n, k) for k, n in sorted(Counter(e['verdict'] for e in expectations).items())))
    lines.append('')
    lines.append('## How this run differs from production (read this before any number)')
    lines.append('')
    for item in differences:
        lines.append('- ' + item)
    lines.append('')
    applicable = [v for v in verdicts if v['verdict'] != 'NOT APPLICABLE']
    if applicable:
        lines.append('## Against the standard')
        lines.append('')
        lines.append('| Measure | Limit | Measured | Verdict |')
        lines.append('|---|---|---|---|')
        for v in applicable:
            limit = ('%s %s' % (v['op'], _fmt(v['limit'], v.get('unit', '')))) if v['op'] != 'report' else 'report'
            lines.append('| %s | %s | %s | **%s** |' % (v['name'], limit, _fmt(v['value'], v.get('unit', '')), v['verdict']))
        lines.append('')
    if expectations:
        lines.append('## Expected behaviour')
        lines.append('')
        lines.append('| Check | Expected | Measured | Verdict |')
        lines.append('|---|---|---|---|')
        for e in expectations:
            lines.append('| %s | %s | %s | **%s** |' % (e['name'], e['expected'], e['measured'], e['verdict']))
        lines.append('')
    late, sent_only = result['lateness']['allPostsUnsentInfinite'], result['lateness']['sentOnly']
    lines.append('## Lateness, drain, outcomes')
    lines.append('')
    lines.append('| | median | p95 | p99 | max |')
    lines.append('|---|---|---|---|---|')
    tv = result.get('timeToVerified') or {}
    rows = [('lateness (due to create): all %d posts (never sent = infinite)' % late['count'], late),
            ('lateness: sent posts only (%d)' % sent_only['count'], sent_only)]
    if tv:
        rows += [('time to verified (due to answered read-back): all %d posts (never verified = infinite)' %
                  tv['allPostsUnverifiedInfinite']['count'], tv['allPostsUnverifiedInfinite']),
                 ('time to verified: verified posts only (%d)' % tv['verifiedOnly']['count'], tv['verifiedOnly']),
                 ('create to verified read-back (%d)' % tv['createToVerified']['count'], tv['createToVerified'])]
    for name, d in rows:
        lines.append('| %s | %s | %s | %s | %s |' % (name, *(_minutes(d[k]) for k in ('median', 'p95', 'p99', 'max'))))
    lines.append('')
    drain = result['drain']
    lines.append('Drain: first create %s after T, last create %s, last verified read-back at the mock %s, every job '
                 'terminal in the database %s.' % tuple(_minutes(drain[k]) for k in (
                     'firstCreateAfterT', 'lastCreateAfterT', 'lastVerifiedAtMockAfterT', 'allTerminalInDatabaseAfterT')))
    if drain.get('unverifiedAtLastCreate') is not None:
        lines.append('Posts not yet verified at the mock when the last create happened: %d of %d (each shows as sent '
                     'but not confirmed until its read-back).' % (drain['unverifiedAtLastCreate'], result['posts']))
    n = result['normal']
    lines.append('Sent within 2 / 5 / 15 min of the due time: %.1f%% / %.1f%% / %.1f%%; not sent %.2f%%.' % (
        100 * n['within2'], 100 * n['within5'], 100 * n['within15'], 100 * n['notSentShare']))
    if result.get('baseline'):
        b = result['baseline']
        lines.append('')
        lines.append('Baseline: %d posts created and %d verified in %d minutes (%.1f created per minute); 5,000 would '
                     'take about %s hours at that rate.' % (b['created'], b['verified'], b['minutes'], b['createdPerMinute'],
                                                            '%.1f' % b['extrapolatedHoursFor5000'] if b['extrapolatedHoursFor5000'] else 'n/a'))
    lines.append('')
    o = result['outcomes']
    lines.append('Outcomes: %d posts in %d workspaces; sent at the mock %d; verified at the mock %d (database %d); '
                 'database states %s; dead letters %d; creates for unknown nonces %d.' % (
                     result['posts'], result['workspaces'], o['sentAtMock'], o['verifiedAtMock'], o['verifiedInDatabase'],
                     json.dumps(o['databaseStates'], sort_keys=True), o['deadLetters'], o['foreignCreates']))
    if o.get('notVerifiedByStateAndAttempt'):
        lines.append('')
        lines.append('Not verified at the mock, by final database state and whether the mock saw a create attempt: %s. '
                     '(An uncertain post with no create at the mock was never sent; it still waits for manual '
                     'reconciliation under the existing rule.)' % ', '.join(
                         '%s: %d' % item for item in sorted(o['notVerifiedByStateAndAttempt'].items())))
    lines.append('')
    lines.append('Creations per minute after T (minute: posts): ' + (', '.join(
        '%s: %d' % item for item in result['creationsPerMinute'].items()) or 'none') + '.')
    lines.append('')
    if result.get('fairness'):
        f = result['fairness']
        lines.append('## Fairness')
        lines.append('')
        lines.append('Hot workspace %s: %d posts, %d sent, last create %s after T; its lateness median %s, p95 %s, max '
                     '%s. Small workspaces (at most five posts): %d; time until each was fully sent: median %s, p95 %s, '
                     'max %s; all done while the hot workspace was still sending: %s.' % (
                         f['hotWorkspace'], f['hotPosts'], f['hotSent'], _minutes(f['hotLastCreateAfterT']),
                         *(_minutes(f['hotLateness'][k]) for k in ('median', 'p95', 'max')), f['smallWorkspaces'],
                         *(_minutes(f['smallCompletionAfterT'][k]) for k in ('median', 'p95', 'max')),
                         f['smallAllDoneWhileHotActive']))
        lines.append('')
    r, c = result['requests'], result['ceiling']
    lines.append('## Requests at the mock')
    lines.append('')
    lines.append('%d requests during the run, %s per verified post. Organic 429s: %d global, %d on creates (route 429s '
                 'in total %s). Injected: %s. Unauthorized %s, not found %s, unknown route %s. Peak in any trailing '
                 'second: %s (all credentials), %s (bot token); busiest 10 s averaged %.1f per second. Requests above 25 '
                 'in a trailing second: %s; bot requests above 50: %s. Invalid requests in the busiest 10 minutes: %s.' % (
                     r['total'], _fmt(r['perVerifiedPost']), r['organicGlobal429'], r['organicCreate429'], r['route429'],
                     json.dumps(r['injected'], sort_keys=True), r['unauthorized'], r['notFound'], r['unknownRoute'],
                     c['peakTrailingSecondAll'], c['peakTrailingSecondBot'], c['peakTenSecondAveragePerSecond'],
                     c['aboveTwentyFiveAll'], c['aboveFiftyBot'], r['invalidPeak10Minutes']))
    lines.append('')
    admissions = c.get('coordinatorAdmissions')
    lines.append('Ceiling, report only (the policy_ceiling verdict above counts per trailing second at the mock): most '
                 'requests in any calendar second at the mock %s.%s' % (
                     c.get('peakCalendarSecondAll'),
                     (' The coordinator\'s own admission table (database clock, rows reserved during the run: %s; by '
                      'credential %s): most in any trailing second %s, in any calendar second %s.%s' % (
                          admissions.get('count'), json.dumps(admissions.get('byCredential'), sort_keys=True),
                          admissions.get('peakTrailingSecond'), admissions.get('peakCalendarSecond'),
                          (' Admission to observation (d): mean %s s, median %s s, p95 %s s; an admission still in '
                           'flight at a window restart is charged again, so the usable rate is about 25/(1 + d) = %s '
                           'per second (inference, docs/w02/REQUEST-BUDGET.md section 1).' % (
                               _fmt(admissions['admissionToOutcomeSeconds']['mean']),
                               _fmt(admissions['admissionToOutcomeSeconds']['median']),
                               _fmt(admissions['admissionToOutcomeSeconds']['p95']),
                               _fmt(25 / (1 + admissions['admissionToOutcomeSeconds']['mean'])))
                           if (admissions.get('admissionToOutcomeSeconds') or {}).get('mean') is not None else '')))
                     if admissions else ' Coordinator admission figures: not collected by this harness version.'))
    lines.append('')
    lines.append('Sustained rate at the mock: busiest 60 s averaged %s requests per second, busiest 300 s %s.' % (
        _fmt(c.get('busiest60sPerSecond')), _fmt(c.get('busiest300sPerSecond'))))
    lines.append('')
    ledger = result.get('ledger')
    if ledger:
        custody = result.get('grantCustody') or {}
        lines.append('### Request ledger')
        lines.append('')
        lines.append('Grant custody: the harness runs the application\'s real grant path against the mock '
                     '(OAuthService -> DiscordConnections.installation_identity -> GET /oauth2/@me with the person\'s '
                     'bearer); the lane fixture\'s Grants stub (tests/discord_lane_fixture.py) is not used. Measured: %d '
                     'identity checks answered for %d sent posts (%s).' % (
                         custody.get('identityChecks', 0), custody.get('sentPosts', 0), custody.get('state')))
        lines.append('')
        per = (lambda n: _fmt(n / ledger['verifiedPosts']) if ledger['verifiedPosts'] else 'n/a')
        per_sent = (lambda n: _fmt(n / ledger['sentPosts']) if ledger['sentPosts'] else 'n/a')
        lines.append('%d requests for %d sent and %d verified posts: %s per verified post (%s per sent post). Essential '
                     '(the ideal real path, 7 per post once every sent post is verified: one grant check, four '
                     'permission-witness reads and the create per sent post, one read-back per verified post): %d; '
                     'overhead: %d, %s per sent post.' % (
                         ledger['total'], ledger['sentPosts'], ledger['verifiedPosts'], per(ledger['total']),
                         per_sent(ledger['total']), ledger['essential'], ledger['overhead'], per_sent(ledger['overhead'])))
        lines.append('')
        lines.append('| Route class | Credential | Ideal per post | Requests | 2xx | 429 (organic) | injected | other status '
                     '| Per verified post | Beyond ideal | Below ideal |')
        lines.append('|---|---|---|---|---|---|---|---|---|---|---|')
        for row in ledger['rows']:
            lines.append('| `%s` | %s | %d | %d | %d | %d | %d | %d | %s | %d | %d |' % (
                row['route'], row['credential'], row['idealPerPost'], row['requests'], row['answered2xx'],
                row['organic429'], row['injected'], row['otherStatus'], _fmt(row['perVerifiedPost']),
                row['beyondIdeal'], row['belowIdeal']))
        lines.append('')
        names = {'botIdentity': 'bot identity pair (per process, 60 s cache)',
                 'extraPreflight': 'successful preflight reads beyond one pass per sent post',
                 'answered429': 'answered 429 by the mock (organic)', 'injectedFailures': 'injected by the scenario',
                 'otherStatus': 'other non-2xx answers', 'extraCreates': 'creates beyond one per sent post',
                 'extraReadbacks': 'read-backs beyond one per verified post', 'otherRoutes': 'other routes'}
        lines.append('| Overhead | Requests | Per verified post | Per sent post |')
        lines.append('|---|---|---|---|')
        for key, count in ledger['overheadBuckets'].items():
            lines.append('| %s | %d | %s | %s |' % (names[key], count, per(count), per_sent(count)))
        lines.append('')
        split, passes = ledger['extraPreflightSplit'], ledger['preflightPassesPerSentPostOnePostWorkspaces']
        lines.append('Preflight reads beyond the ideal, by workspace: %d in repeated passes for posts that were sent, %d '
                     'for posts never sent, %d on routes the mock could not attribute to a workspace (mock older than '
                     'the ledger). Preflight passes per sent post (one-post workspaces, counted by GET /guilds/{id}): '
                     '%s.' % (
                         split['repeatedPassesForSentPosts'], split['forPostsNeverSent'], split['unattributed'],
                         ', '.join('%s pass(es): %d posts' % item for item in passes.items()) or 'none'))
        lines.append('')
    d = result['database']
    lines.append('## Database')
    lines.append('')
    p = d.get('pooler') or {}
    if p:
        wt, ht, et = p.get('waitSeconds') or {}, p.get('transactionHoldSeconds') or {}, p.get('exchangeSeconds') or {}
        lines.append('Pooler (%s, pool %s, %s ms per round trip, connection setup %s extra round trips): peak '
                     'transactions holding a server connection %s, peak demand (holding + waiting) %s = %s of the pool, '
                     'peak clients %s; %s transactions; wait for a server connection p50 %s s, p95 %s s, max %s s; wait '
                     'timeouts %s; longest transaction hold %s s; longest statement exchange %s s; pooler CPU %s s.' % (
                         p.get('mode'), p.get('poolSize'), p.get('latencyMs'), p.get('connectRtts'), p.get('assignedPeak'),
                         p.get('demandPeak'), _fmt(d.get('poolerDemandShare')), p.get('clientPeak'), p.get('transactions'),
                         _fmt(wt.get('p50')), _fmt(wt.get('p95')), _fmt(wt.get('max')), p.get('waitTimeouts'),
                         _fmt(ht.get('max')), _fmt(et.get('max')), _fmt(p.get('cpuSeconds'))))
        lines.append('')
    lines.append('PostgreSQL %s: peak backends sampled each second %s (active %s, waiting on a lock %s); longest running '
                 'statement seen by the sampler %s s; statements over 1 s in the server log %s; server CPU %s s; errors by '
                 'SQLSTATE %s; request admissions by state at the end %s; coordinator holds %s.' % (
                     d.get('serverVersion'), d.get('peakBackendsSampled'), d.get('peakActiveSampled'),
                     d.get('peakLockWaitsSampled'), _fmt(d.get('longestActiveStatementSampledSeconds')),
                     d.get('statementsOverOneSecond'), _fmt(d.get('postgresCpuSeconds')),
                     json.dumps(result['errors'], sort_keys=True), json.dumps(d.get('admissionsByState'), sort_keys=True),
                     json.dumps([h for h in d.get('rateStateHolds') or [] if h['manualHold'] or h['blocked'] or h['circuit']])))
    if d.get('slowestStatements'):
        lines.append('')
        lines.append('| Slowest statements (pg_stat_statements) | calls | mean ms | max ms |')
        lines.append('|---|---|---|---|')
        for row in d['slowestStatements'][:8]:
            lines.append('| `%s` | %s | %.1f | %.1f |' % (' '.join(row['query'].split())[:120].replace('|', '/'),
                                                          row['calls'], row['meanMs'], row['maxMs']))
    lines.append('')
    wk = result['workers']
    lines.append('## Workers (cron invocations, one OS process each)')
    lines.append('')
    lines.append('%d invocations (%d lane, %d minute worker); failed %d; killed at the function limit %d, by the crash '
                 'injector %d, at the end of the run %d; refused egress %d. CPU %.1f s in total, per invocation mean %s s, '
                 'max %s s; largest RSS %s MB. Lane handler time median %s s, max %s s. Start delay after the scheduled '
                 'cron time: median %s s, max %s s.' % (
                     wk['invocations'], wk['laneInvocations'], wk['minuteInvocations'], wk['failedInvocations'],
                     wk['killedAtFunctionLimit'], wk['killedByInjector'], wk['killedAtEnd'], wk['blockedEgress'],
                     wk['cpuSecondsTotal'], _fmt(wk['cpuSecondsPerInvocation']['mean']),
                     _fmt(wk['cpuSecondsPerInvocation']['max']), _fmt(wk['maxRssMb']),
                     _fmt(wk['laneHandlerSeconds']['median']), _fmt(wk['laneHandlerSeconds']['max']),
                     _fmt(wk['startDelaySeconds']['median']), _fmt(wk['startDelaySeconds']['max'])))
    lines.append('')
    lines.append('Lane counters (sum over invocations; the application\'s own claims): ' +
                 json.dumps(wk['laneCounters'], sort_keys=True) + '. Stopped by: ' +
                 json.dumps(wk['laneStoppedBy'], sort_keys=True) + '. Minute worker Discord counters: ' +
                 json.dumps(wk['minuteWorkerDiscordCounters'], sort_keys=True) + '.')
    if wk['failureSamples']:
        lines.append('')
        lines.append('Failed invocation samples: `' + json.dumps(wk['failureSamples'])[:1500] + '`')
    if result.get('cronGap'):
        g = result['cronGap']
        lines.append('')
        lines.append('Cron gap: per shard and %d-second period, no loop of that shard was inside its handler for %.1f s '
                     'on average (max %.1f s, over %d shard periods up to the drain).' % (
                         g['periodSeconds'], g['meanGapSeconds'], g['maxGapSeconds'], g['shardPeriods']))
    if result.get('kills'):
        lines.append('')
        lines.append('Injected kills: `' + json.dumps(result['kills'])[:1500] + '`')
    lines.append('')
    lines.append('Machine: 1-minute load average peaked at %s (start of run: %s; end: %s); mock Discord CPU %s s.' % (
        _fmt(result['machineLoad1Max']), config.get('loadAtStart'), config.get('loadAtEnd'), _fmt(result.get('mockCpuSeconds'))))
    lines.append('')
    lines.append('## Configuration')
    lines.append('')
    lines.append('```json')
    lines.append(json.dumps({k: config[k] for k in sorted(config) if k not in ('environmentNames',)}, indent=1,
                            sort_keys=True, default=str))
    lines.append('```')
    lines.append('')
    return '\n'.join(lines)
