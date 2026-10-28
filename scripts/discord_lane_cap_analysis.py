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
import re
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


def _spread(values):
    """Nearest-rank percentiles of a list of seconds, or None when it is empty."""
    if not values:
        return None
    ordered = sorted(values)
    return {'n': len(ordered), 'min': ordered[0], 'p10': quantile(ordered, .1), 'p50': quantile(ordered, .5), 'p90': quantile(ordered, .9),
            'p99': quantile(ordered, .99), 'p999': quantile(ordered, .999), 'max': ordered[-1]}


def _answered(record):
    status = record.get('status')
    return isinstance(status, int) and 200 <= status < 300 and not record.get('injected')


def witness_age(window, posts):
    """Per create: how old the permission witness was when the create reached the mock. A create's pass is the run of
    its workspace's requests since that workspace's previous create or read-back: the person's grant check
    (`GET /oauth2/@me`, when the mock could attribute it to the workspace), the server read, the two member reads and
    the channel list. The oldest witness is the grant check, else the server read; the newest is the channel list.
    Ages are arrival at the mock to the create's arrival, in seconds; percentiles p50 / p90 / p99 / max."""
    by_tenant = defaultdict(list)
    for record in window:
        tenant = tenant_of(record)
        if tenant is not None:
            by_tenant[tenant].append(record)
    oldest, newest, from_grant, without = [], [], 0, 0
    for tenant, records in by_tenant.items():
        records.sort(key=lambda r: r['arrived'])
        for position, record in enumerate(records):
            if not record.get('created'):
                continue
            guild_at = grant_at = channels_at = None
            for earlier in reversed(records[max(0, position - 12):position]):
                route = earlier.get('route')
                if route in (CREATE, READBACK):
                    break  # the previous job of this workspace: its requests are not this create's witness
                if not _answered(earlier):
                    continue
                if route == 'GET /guilds/{id}/channels' and channels_at is None:
                    channels_at = earlier['arrived']
                elif route == 'GET /guilds/{id}' and guild_at is None:
                    guild_at = earlier['arrived']
                elif route == 'GET /oauth2/@me' and guild_at is not None:
                    grant_at = earlier['arrived']
                    break
            first = grant_at if grant_at is not None else guild_at
            if first is None or record['arrived'] - first >= 120:
                without += 1
                continue
            from_grant += grant_at is not None
            oldest.append(record['arrived'] - first)
            if channels_at is not None and record['arrived'] - channels_at < 120:
                newest.append(record['arrived'] - channels_at)
    if not oldest:
        return None
    return {'creates': len(oldest), 'withoutWitness': without, 'oldestFromGrantCheck': from_grant,
            'oldest': _spread(oldest), 'newest': _spread(newest)}


def pair_admissions(window, admissions, max_gap=30.0, with_rows=False):
    """Join each admission that was sent to the mock's arrival of that request. Exactly by the coordinator's permit id where
    the mock logged it (the invocation wrapper stamps it on the request, harness commits after the attempt log), and for the
    rest by path digest and order: an arrival no earlier than 5 ms before the admission's send time and within `max_gap`
    seconds after it. Returns (pairs [(send time, record, is publish)], sends without an arrival, every send time sorted);
    with `with_rows` each pair also carries the admission row as a fourth element."""
    sends, every, pairs = defaultdict(list), [], []
    by_id = {row[11]: row for row in admissions if len(row) > 11 and row[11]}
    matched, rest = set(), []
    for record in window:
        row = by_id.get(record.get('permit')) if record.get('permit') else None
        if row is not None and row[2] is not None and id(row) not in matched:
            matched.add(id(row))
            publish = bool(row[8]) if len(row) > 8 else False
            pairs.append((row[2], record, publish, row) if with_rows else (row[2], record, publish))
        else:
            rest.append(record)
    for row in admissions:
        sent, key = row[2], row[7]
        if sent is None:
            continue  # reserved or blocked without ever being sent
        every.append(sent)
        if id(row) not in matched:
            sends[key].append((sent, bool(row[8]) if len(row) > 8 else False, row))
    arrivals = defaultdict(list)
    for record in rest:
        if record.get('pathKey'):
            arrivals[record['pathKey']].append(record)
    unpaired = 0
    for key, items in sends.items():
        items.sort(key=lambda item: item[0])
        hits = sorted(arrivals.get(key, ()), key=lambda r: r['arrived'])
        cursor = 0
        for at, publish, row in items:
            while cursor < len(hits) and hits[cursor]['arrived'] < at - 0.005:
                cursor += 1  # an arrival from before this send belongs to no send of this path
            if cursor < len(hits) and hits[cursor]['arrived'] - at <= max_gap:
                pairs.append((at, hits[cursor], publish, row) if with_rows else (at, hits[cursor], publish))
                cursor += 1
            else:
                unpaired += 1
    every.sort()
    return pairs, unpaired, every


def guard_sizing(pairs, ceiling=25, at_the_ceiling=0.25):
    """What guard between the (ceiling+1)-th send and the first would keep the mock at `ceiling` in a closed second.

    Take every request i in send order and the request `ceiling` places after it. The coordinator keeps them at least
    1 + G apart by send time (G is its guard), and the two arrive (s_j - s_i) + (d_j - d_i) apart, where d is a request's
    delay from send to arrival. The mock counts more than `ceiling` in a trailing second exactly when that is under
    one second, that is when d_i - d_j exceeds the slack s_j - s_i - 1. Only windows at the ceiling (slack up to
    `at_the_ceiling` seconds) are used; a quiet stretch puts no pressure on it. Returns the number of such windows, the
    smallest slack, how many had the 26th arrival less than a second after the first, and the percentiles of
    d_i - d_j: a guard of that size would have held that share of the windows (inference, from this run's delays)."""
    ordered = sorted(pairs, key=lambda item: item[0])
    sends = [item[0] for item in ordered]
    arrivals = [item[1]['arrived'] for item in ordered]
    differences, slacks, violations = [], [], 0
    for i in range(len(ordered) - ceiling):
        j = i + ceiling
        slack = sends[j] - sends[i] - 1.0
        if slack > at_the_ceiling:
            continue
        slacks.append(slack)
        differences.append((arrivals[i] - sends[i]) - (arrivals[j] - sends[j]))
        violations += (arrivals[j] - arrivals[i]) < 1.0
    if not differences:
        return None
    ordered_differences = sorted(differences)
    pick = lambda q: ordered_differences[min(len(ordered_differences) - 1, int(q * len(ordered_differences)))]
    return {'ceiling': ceiling, 'windows': len(differences), 'minSlack': min(slacks), 'violations': violations,
            'violationShare': violations / len(differences),
            'delayDifference': {'p50': pick(.5), 'p90': pick(.9), 'p99': pick(.99), 'p999': pick(.999),
                                'p9999': pick(.9999), 'max': ordered_differences[-1]}}


def wire_jitter(window, admissions, ceiling=25):
    """Admission-to-wire spread, per request, and what it does to the ceiling.

    Each admission's send time (the coordinator's `sent_at`, database clock) is joined to the mock's arrival of that
    request. Where the invocation wrapper stamped the call (`callAt`, the last thing before the HTTP call), the delay is
    split into admission to call (inside the application) and call to arrival (loopback, and the mock's accept and
    thread start on the same loaded machine). The requests the mock counted above `ceiling` in their trailing second
    are then attributed: the coordinator had already sent more than `ceiling` in the trailing second of their send time
    ('coordinator'), or not, but more than `ceiling` had arrived in the trailing second of their arrival ('wire'), or
    neither, and only the mock's own processing order (it counts up to half a latency after arrival) put them over
    ('mock'). Returns None when the run has no admissions export or the mock logged no path digests."""
    if not admissions or not any(r.get('pathKey') for r in window[:200]):
        return None
    import bisect
    pairs, unpaired, every = pair_admissions(window, admissions)
    keyed = sum(1 for r in window if r.get('pathKey'))
    if not pairs:
        return None
    total = [r['arrived'] - at for at, r, _ in pairs]
    app_side = [r['callAt'] - at for at, r, _ in pairs if 'callAt' in r]
    wire_side = [r['arrived'] - r['callAt'] for _, r, _ in pairs if 'callAt' in r]
    creates = [r['arrived'] - at for at, r, publish in pairs if publish]
    reads = [r['arrived'] - at for at, r, publish in pairs if not publish]
    arrivals = sorted(r['arrived'] for r in window)
    send_of = {id(r): at for at, r, _ in pairs}
    causes = Counter()
    for record in window:
        if (record.get('trailingAll') or 0) <= ceiling:
            continue
        at = send_of.get(id(record))
        if at is None:
            causes['unpaired'] += 1
            continue
        sent_in_second = bisect.bisect_right(every, at) - bisect.bisect_right(every, at - 1.0)
        arrived_in_second = (bisect.bisect_right(arrivals, record['arrived'])
                             - bisect.bisect_right(arrivals, record['arrived'] - 1.0))
        causes['coordinator' if sent_in_second > ceiling else 'wire' if arrived_in_second > ceiling else 'mock'] += 1
    all_total = _spread(total)
    guard = guard_sizing(pairs, ceiling)
    return {'paired': len(pairs), 'admissionsSent': len(every), 'admissionsWithoutArrival': unpaired, 'guard': guard,
            'arrivalsWithoutAdmission': keyed - len(pairs),
            'admissionToArrival': all_total, 'admissionToCall': _spread(app_side), 'callToArrival': _spread(wire_side),
            'creates': _spread(creates), 'reads': _spread(reads),
            'spreadAboveMedianP999': (all_total['p999'] - all_total['p50']) if all_total else None,
            'sendPeakTrailingSecond': peak_trailing(every, 1.0), 'sendPeakCalendarSecond': peak_calendar_second(every),
            'arrivalPeakTrailingSecond': peak_trailing(arrivals, 1.0), 'arrivalPeakCalendarSecond': peak_calendar_second(arrivals),
            'aboveCeilingAtMock': sum(causes.values()), 'aboveCeilingBy': dict(causes), 'ceiling': ceiling}


_WITNESS = {'GET /oauth2/@me': 'grant', 'GET /guilds/{id}': 'guild', 'GET /guilds/{id}/members/{id}': 'member',
            'GET /guilds/{id}/channels': 'channels'}


def workspace_passes(window):
    """Each workspace's preflight passes in the mock log. A pass starts at the person's grant check (`GET /oauth2/@me`)
    and holds the witness reads that follow; it ends 'created' at the workspace's create, or 'released' when the next
    grant check or a read-back of the same workspace shows the lane let it go before the create (the lane keeps no
    memory of a released pass: the next claim of that post starts again at the grant check)."""
    by_tenant = defaultdict(list)
    for record in window:
        tenant = tenant_of(record)
        if tenant is not None and (record.get('route') in _WITNESS or record.get('route') in (CREATE, READBACK)):
            by_tenant[tenant].append(record)
    result = {}
    for tenant, records in by_tenant.items():
        records.sort(key=lambda r: r['arrived'])
        passes, current = [], None
        for record in records:
            route = record['route']
            if route == 'GET /oauth2/@me':
                if current is not None:
                    current['end'] = 'released'
                    passes.append(current)
                current = {'start': record['arrived'], 'requests': [record], 'end': None}
            elif route == CREATE:
                if current is None:
                    current = {'start': record['arrived'], 'requests': [], 'end': None}
                current['requests'].append(record)
                current['end'] = 'created'
                passes.append(current)
                current = None
            elif route == READBACK:
                if current is not None:
                    current['end'] = 'released'
                    passes.append(current)
                    current = None
            elif current is not None:
                current['requests'].append(record)
        if current is not None:
            current['end'] = 'open at end'
            passes.append(current)
        result[tenant] = passes
    return result


def last_answer(record):
    return record.get('answered') or record['processed']


def preflight_passes(window, admissions, span=1.1, ceiling=25):
    """How often the whole witness pass repeats and why it is let go (from the mock log and the admissions export).

    Per created post: the number of passes it took. Per released pass: what it had completed (so which request was refused
    next), how long until the same workspace's next pass (the re-claim), when in the minute it happened, and whether the
    application window held `ceiling` sends within `span` seconds at five instants over the second after the pass's last
    answer (the provider waits at most one second for a read). Per witness step: the wait between the previous request's
    answer being observed and this request's admission, which holds every refused attempt, every sleep and the
    reservation's own lock wait. Refused reservations leave no row, so their count and quoted waits are not here."""
    import bisect
    by_tenant = workspace_passes(window)
    passes = [p for items in by_tenant.values() for p in items]
    if not passes:
        return None
    per_post, reclaim, released = Counter(), [], []
    for items in by_tenant.values():
        count = 0
        for number, item in enumerate(items):
            count += 1
            if item['end'] == 'created':
                per_post[count] += 1
                count = 0
            elif item['end'] == 'released':
                released.append(item)
                if number + 1 < len(items):
                    reclaim.append(items[number + 1]['start'] - last_answer(item['requests'][-1]))
    posts = sum(per_post.values())
    sends = sorted(row[2] for row in admissions if row[2] is not None)
    occupied = lambda t: bisect.bisect_right(sends, t) - bisect.bisect_right(sends, t - span)
    stages, window_state, by_stage_window, minute_bins, per_minute = Counter(), Counter(), defaultdict(Counter), Counter(), Counter()
    for item in released:
        stage = '+'.join(_WITNESS[r['route']] for r in item['requests'] if r['route'] in _WITNESS) or 'none'
        t = last_answer(item['requests'][-1])
        counts = [occupied(t + dt) for dt in (0.0, 0.25, 0.5, 0.75, 1.0)]
        state = 'full throughout' if min(counts) >= ceiling else 'full at some instant' if max(counts) >= ceiling else 'never full'
        stages[stage] += 1
        window_state[state] += 1
        by_stage_window[stage][state] += 1
        minute_bins[int(t % 60) // 5 * 5] += 1
    steps = {}
    if admissions and any(len(row) > 8 for row in admissions):
        pairs, _unpaired, _every = pair_admissions(window, admissions, with_rows=True)
        row_of = {id(record): row for _at, record, _publish, row in pairs}
        gaps = defaultdict(list)
        for item in passes:
            previous = None
            for record in item['requests']:
                row, last = row_of.get(id(record)), row_of.get(id(previous)) if previous is not None else None
                if previous is not None and row is not None and last is not None and last[3] is not None:
                    route = record['route']
                    label = ('guild read' if route == 'GET /guilds/{id}' else
                             'channel list' if route == 'GET /guilds/{id}/channels' else
                             'create permit' if route == CREATE else
                             ('first member read' if previous['route'] == 'GET /guilds/{id}' else 'second member read'))
                    gaps[label].append(row[0] - last[3])
                previous = record
        steps = {label: dict(_spread(values) or {}, over100ms=sum(1 for v in values if v > .1) / len(values),
                             over1s=sum(1 for v in values if v > 1.0) / len(values)) for label, values in gaps.items()}
    return {'passes': len(passes), 'createdPosts': posts, 'released': len(released),
            'openAtEnd': sum(1 for p in passes if p['end'] == 'open at end'),
            'passesPerPost': {str(k): v for k, v in sorted(per_post.items())},
            'meanPassesPerPost': (sum(k * v for k, v in per_post.items()) / posts) if posts else None,
            'releasedAfter': dict(stages.most_common()), 'reclaimDelay': _spread(reclaim),
            'reclaimWithinTwoSeconds': (sum(1 for d in reclaim if d <= 2.0) / len(reclaim)) if reclaim else None,
            'releasesBySecondOfMinute': {str(k): v for k, v in sorted(minute_bins.items())},
            'applicationWindow': dict(window_state), 'applicationWindowByStage': {k: dict(v) for k, v in by_stage_window.items()},
            'span': span, 'ceiling': ceiling, 'stepWait': steps}


_KINDS = {'GET /oauth2/@me': 'grant check', 'GET /guilds/{id}': 'server read', 'GET /guilds/{id}/members/{id}': 'member read',
          'GET /guilds/{id}/channels': 'channel list', 'POST /channels/{id}/messages': 'create',
          'GET /channels/{id}/messages/{id}': 'read-back', 'GET /users/@me': 'bot identity',
          'GET /oauth2/applications/@me': 'bot identity'}


BOOKED_MIN = 0.005  # a room under 5 ms is not booked (SharedPostgresBudget._book_ahead); a read stored 5 ms or less after its reservation is not told from timer noise


def _booking_columns(row):
    """(seconds the coordinator booked for the call, seconds the call spent waiting for its slot, the room the caller allowed
    to be booked or None) of an attempt row; zeros and None for the 13-column rows of a log written before booking."""
    if len(row) >= 16:
        return (row[13] or 0.0), (row[14] or 0.0), row[15]
    return 0.0, 0.0, None


def attempt_statistics(attempts, created_posts=None, restart_gap=3.0):
    """Every reservation attempt of the shared coordinator, from the invocation wrapper's attempt log: outcomes and the wait
    quoted to each refused attempt, by credential class and request kind; how many attempts a read step needed; per
    created post. Rows are [time, seconds the call took, operation (read, reserve, consume), method, route, credential kind,
    workspace, outcome (A admitted, R refused, E error), quoted wait, scope, cause, permit id, cron source, seconds booked,
    seconds slept, book-ahead room allowed]; the last three only in logs of a harness with booking.

    With booking an admitted call is a slot reached: a reserve or reserve_read that found the window full booked the next
    free slot and slept in the call until it came (up to a second), so the seconds an admitted call took are split into
    calls that did not book and calls that did, and the booked wait is reported on its own.

    A read step is a run of attempts at the same route by the same cron process and workspace: refusals until an admission
    (or the last refusal, when the provider gives up and the lane releases the post), restarted after `restart_gap` seconds."""
    attempts = [r for r in attempts or [] if r[2] in ('read', 'reserve', 'consume')]  # the calls after a request are in coordinator_failures
    if not attempts:
        return None
    groups = defaultdict(list)
    for row in attempts:
        route = _KINDS.get('%s %s' % (row[3], row[4]), 'other')
        groups[(row[5], route, row[2])].append(row)
    by_kind = {}
    for (credential, route, operation), rows in groups.items():
        refused = [r for r in rows if r[7] == 'R']
        admitted = [r for r in rows if r[7] == 'A']
        booked = [r for r in admitted if _booking_columns(r)[0] > 0]
        unbooked = [r for r in admitted if not _booking_columns(r)[0] > 0]
        by_kind['%s / %s / %s' % (credential, route, operation)] = {
            'credential': credential, 'kind': route, 'operation': operation, 'attempts': len(rows), 'admitted': len(admitted),
            'refused': len(refused), 'errors': sum(1 for r in rows if r[7] == 'E'),
            'quotedWait': _spread([r[8] for r in refused if r[8] is not None]),
            'scopes': dict(Counter('%s/%s' % (r[9], r[10]) for r in refused).most_common()),
            'callSecondsAdmitted': _spread([r[1] for r in admitted]), 'callSecondsRefused': _spread([r[1] for r in refused]),
            'booked': len(booked), 'bookedPlanned': _spread([_booking_columns(r)[0] for r in booked]),
            'bookedSlept': _spread([_booking_columns(r)[1] for r in booked]),
            'callSecondsAdmittedUnbooked': _spread([r[1] for r in unbooked]),
            'callSecondsAdmittedBooked': _spread([r[1] for r in booked]),
            'refusedWithRoomToBook': sum(1 for r in refused if (_booking_columns(r)[2] or 0) >= BOOKED_MIN)}
    steps = defaultdict(Counter)
    runs = defaultdict(list)
    for row in sorted(attempts, key=lambda r: r[0]):
        if row[2] != 'read':
            continue
        key = (row[12], row[3] + ' ' + row[4], row[6])
        run = runs[key]
        if run and (run[-1][7] == 'A' or row[0] - run[-1][0] > restart_gap):
            kind = _KINDS.get(run[0][3] + ' ' + run[0][4], 'other')
            steps[kind]['%d attempt(s), %s' % (len(run), 'admitted' if run[-1][7] == 'A' else 'gave up')] += 1
            run.clear()
        run.append(row)
    for key, run in runs.items():
        if run:
            kind = _KINDS.get(run[0][3] + ' ' + run[0][4], 'other')
            steps[kind]['%d attempt(s), %s' % (len(run), 'admitted' if run[-1][7] == 'A' else 'gave up')] += 1
    totals = Counter(r[7] for r in attempts)
    booked_rows = [r for r in attempts if r[7] == 'A' and _booking_columns(r)[0] > 0]
    return {'attempts': len(attempts), 'admitted': totals['A'], 'refused': totals['R'], 'errors': totals['E'],
            'withBookingColumns': sum(1 for r in attempts if len(r) >= 16),
            'errorsByCause': dict(Counter('%s %s' % (r[2], r[10]) for r in attempts if r[7] == 'E').most_common()),
            'booked': len(booked_rows), 'bookedByOperation': dict(Counter(r[2] for r in booked_rows)),
            'bookedPlannedSeconds': sum(_booking_columns(r)[0] for r in booked_rows),
            'bookedSleptSeconds': sum(_booking_columns(r)[1] for r in booked_rows),
            'bookedPlanned': _spread([_booking_columns(r)[0] for r in booked_rows]),
            'bookedSlept': _spread([_booking_columns(r)[1] for r in booked_rows]),
            'refusedWithRoomToBook': sum(1 for r in attempts if r[7] == 'R' and (_booking_columns(r)[2] or 0) >= BOOKED_MIN),
            'refusedPerAdmitted': totals['R'] / totals['A'] if totals['A'] else None,
            'attemptsPerCreatedPost': (len(attempts) / created_posts) if created_posts else None,
            'refusedPerCreatedPost': (totals['R'] / created_posts) if created_posts else None,
            'byKind': by_kind, 'readSteps': {k: dict(v) for k, v in steps.items()},
            'refusalsByScopeAndCause': dict(Counter('%s/%s' % (r[9], r[10]) for r in attempts if r[7] == 'R').most_common())}


def attempt_lines(stats):
    """Markdown lines for the receipt (the table of reservation attempts)."""
    if not stats:
        return []
    booking = stats.get('withBookingColumns')
    lines = ['## Reservation attempts (the coordinator attempt log)', '',
             '%s attempts of the shared coordinator: %s admitted, %s refused with a quoted wait (%s per admission), %s errors; %s attempts '
             'and %s refusals per created post. A refused attempt leaves no row in the database; this log is its only record.%s' % (
                 _count(stats['attempts']), _count(stats['admitted']), _count(stats['refused']), _fmt(stats['refusedPerAdmitted']),
                 _count(stats['errors']), _fmt(stats['attemptsPerCreatedPost']), _fmt(stats['refusedPerCreatedPost']),
                 (' With booking an admitted call is a slot reached: %s admitted calls booked a slot and slept in the call '
                  '(planned wait p50 / p90 / max %s s, slept %s s; %s refusals still had room to book, so the horizon was '
                  'full or the caller\'s deadline too near).' % (
                      _count(stats.get('booked')), ' / '.join(_fmt((stats.get('bookedPlanned') or {}).get(k)) for k in ('p50', 'p90', 'max')),
                      ' / '.join(_fmt((stats.get('bookedSlept') or {}).get(k)) for k in ('p50', 'p90', 'max')),
                      _count(stats.get('refusedWithRoomToBook')))) if booking else
                 ' (This log has no booking columns: written by a harness without booking.)'), '',
             '| Credential / request / operation | Attempts | Admitted | Booked (planned wait p50 / p90 / max, s) | Refused | Quoted wait of a refusal, p10 / p50 / p90 / p99 / max (s) | Refused by scope / cause | Call took p50 (ms): admitted unbooked / admitted booked / refused |',
             '|---|---|---|---|---|---|---|---|']
    for label, row in sorted(stats['byKind'].items()):
        wait = row['quotedWait']
        planned = row.get('bookedPlanned') or {}
        lines.append('| %s | %s | %s | %s | %s (%.1f%%) | %s | %s | %s / %s / %s |' % (
            label, _count(row['attempts']), _count(row['admitted']),
            ('%s (%s / %s / %s)' % (_count(row.get('booked')), *(_fmt(planned.get(k)) for k in ('p50', 'p90', 'max')))
             if row.get('booked') else '0'),
            _count(row['refused']),
            100 * row['refused'] / row['attempts'] if row['attempts'] else 0,
            ' / '.join(_fmt(wait.get(k)) for k in ('p10', 'p50', 'p90', 'p99', 'max')) if wait else 'n/a',
            json.dumps(row['scopes']) if row['scopes'] else 'none',
            _ms((row.get('callSecondsAdmittedUnbooked') or {}).get('p50')),
            _ms((row.get('callSecondsAdmittedBooked') or {}).get('p50')),
            _ms((row['callSecondsRefused'] or {}).get('p50'))))
    if stats.get('errorsByCause'):
        lines.append('')
        lines.append('Errors (a failure that is not a refusal with a wait; the coordinator hides the cause of a failed transaction, '
                     'so these are the class and SQLSTATE of the failure it hid), by operation and cause: %s.' % json.dumps(stats['errorsByCause']))
    lines.append('')
    lines.append('Attempts a read step needed (a run of attempts at one route by one process until it was admitted or the provider gave up): '
                 + '; '.join('%s: %s' % (kind, ', '.join('%s %s' % (k, _count(v)) for k, v in sorted(counts.items())))
                             for kind, counts in sorted(stats['readSteps'].items())) + '.')
    lines.append('')
    return lines


LOCK_TIMEOUT, STATEMENT_TIMEOUT, DEADLOCK = '55P03', '57014', '40P01'
RESERVE_OPS = ('read', 'reserve')


def coordinator_failures(rows, stopped=None, due=None, creates_per_minute=None):
    """Every coordinator failure of the run, counted: the database-latency cliff of the scope-B review (a lock timeout becomes
    RateCoordinatorUnavailable, the lane releases the post for 300 s, and one failed observe() sets rate_coordinator_degraded
    in that process for good). `rows` is the whole attempt log, calls and events: calls are [time, seconds, operation, method,
    route, credential, workspace, outcome A / R / E, quoted wait, scope, cause, permit, source, ...] where an error (E) holds the
    error class in `scope` and the class and SQLSTATE of the failure the coordinator hid in `cause`; events are rows with
    operation `event`: ['release', reason, seconds released for, rate scope, rate cause] and ['degraded', where, ..., the failed
    call before it]. Always returns a summary (zeros are the answer of a clean run); None only without any row."""
    if not rows:
        return None
    calls = [r for r in rows if r[2] != 'event']
    events = [r for r in rows if r[2] == 'event']
    by_op = {}
    for op in ('read', 'reserve', 'consume', 'observe', 'note_failure', 'abandon'):
        mine = [r for r in calls if r[2] == op]
        errors = [r for r in mine if r[7] == 'E']
        by_op[op] = {'calls': len(mine), 'errors': len(errors),
                     'unavailable': sum(1 for r in errors if r[9] == 'RateCoordinatorUnavailable'),
                     'lockTimeouts': sum(1 for r in errors if LOCK_TIMEOUT in str(r[10])),
                     'statementTimeouts': sum(1 for r in errors if STATEMENT_TIMEOUT in str(r[10])),
                     'deadlocks': sum(1 for r in errors if DEADLOCK in str(r[10])),
                     'otherErrors': sum(1 for r in errors if not any(code in str(r[10]) for code in (LOCK_TIMEOUT, STATEMENT_TIMEOUT, DEADLOCK))),
                     'seconds': _spread([r[1] for r in mine])}
    errors = [r for r in calls if r[7] == 'E']
    reserve = [by_op[op] for op in RESERVE_OPS]
    totals = {'errors': len(errors), 'unavailable': sum(1 for r in errors if r[9] == 'RateCoordinatorUnavailable'),
              'lockTimeoutsInReserve': sum(b['lockTimeouts'] for b in reserve),
              'lockTimeoutsInConsume': by_op['consume']['lockTimeouts'],
              'lockTimeoutsInObserve': by_op['observe']['lockTimeouts'] + by_op['note_failure']['lockTimeouts'] + by_op['abandon']['lockTimeouts'],
              'causes': dict(Counter('%s %s' % (r[2], r[10]) for r in errors).most_common())}
    releases = [r for r in events if r[3] == 'release']
    unavailable_wait = [r for r in releases if isinstance(r[8], (int, float)) and abs(r[8] - 300.0) < 1.0]
    quoted = [r for r in releases if isinstance(r[8], (int, float)) and abs(r[8] - 300.0) >= 1.0]
    degraded = [r for r in events if r[3] == 'degraded']
    summary = {'byOperation': by_op, 'totals': totals,
               'releases': {'total': len(releases), 'about300Seconds': len(unavailable_wait), 'quotedWait': len(quoted),
                            'noWaitGiven': len(releases) - len(unavailable_wait) - len(quoted),
                            'byReasonAndCause': dict(Counter('%s / %s / %s' % (r[4], r[9], r[10]) for r in releases).most_common()),
                            'quotedWaitSeconds': _spread([r[8] for r in quoted])},
               'degraded': {'processes': len({r[12] for r in degraded}), 'events': len(degraded),
                            'firstAfterDue': (min(r[0] for r in degraded) - due) if degraded and due else None,
                            'lastAfterDue': (max(r[0] for r in degraded) - due) if degraded and due else None,
                            'where': dict(Counter(re.sub(r':[0-9]+', '', r[4]) for r in degraded).most_common(6)),
                            'afterFailedCall': dict(Counter('%s %s' % (r[9], r[10]) for r in degraded).most_common(6))},
               'laneStopped': {k: v for k, v in (stopped or {}).items() if k in ('coordinator_degraded', 'coordinator_unavailable')},
               'createsPerMinute': None}
    if creates_per_minute:
        counts = [v for k, v in sorted(((int(k), v) for k, v in creates_per_minute.items())) if v >= 1]
        full = [v for v in counts if v >= 0.2 * max(counts)]
        summary['createsPerMinute'] = {'minutes': len(counts), 'median': statistics_median(full), 'min': min(full), 'max': max(counts),
                                       'best5': max((sum(counts[i:i + 5]) / 5 for i in range(max(1, len(counts) - 4))), default=None)}
    return summary


def statistics_median(values):
    ordered = sorted(values)
    n = len(ordered)
    return None if not n else (ordered[n // 2] if n % 2 else (ordered[n // 2 - 1] + ordered[n // 2]) / 2)


def coordinator_failure_lines(summary):
    """Markdown lines for the receipt: the counts the scope-B review asked for, printed even when they are zero."""
    if not summary:
        return ['## Coordinator failures (the database-latency cliff)', '',
                'No attempt log in this directory (a harness before the attempt log, or the wrapper could not be installed): '
                'lock timeouts, RateCoordinatorUnavailable errors, 300 s releases and the degraded flag are NOT MEASURED.', '']
    t, r, d = summary['totals'], summary['releases'], summary['degraded']
    o = summary['byOperation']
    lines = ['## Coordinator failures (the database-latency cliff)', '']
    lines.append('Counted from the attempt log (every coordinator call of every process, including the observation after each answer and the '
                 'releases of posts; zeros are the answer of a clean run). A lock timeout is SQLSTATE 55P03 (the coordinator sets a 2 s '
                 '`lock_timeout`), a statement timeout 57014, a deadlock 40P01.')
    lines.append('')
    lines.append('| Operation | Calls | Errors | RateCoordinatorUnavailable | Lock timeouts | Statement timeouts | Deadlocks | Other | Call took p50 / p99 / max (ms) |')
    lines.append('|---|---|---|---|---|---|---|---|---|')
    names = {'read': 'reserve_read (a read)', 'reserve': 'reserve (a create permit)', 'consume': 'consume', 'observe': 'observe (the answer)',
             'note_failure': 'note_transport_failure', 'abandon': 'abandon_unsent'}
    for op in ('read', 'reserve', 'consume', 'observe', 'note_failure', 'abandon'):
        b = o[op]
        s = b.get('seconds') or {}
        lines.append('| %s | %s | %s | %s | %s | %s | %s | %s | %s |' % (
            names[op], _count(b['calls']), _count(b['errors']), _count(b['unavailable']), _count(b['lockTimeouts']),
            _count(b['statementTimeouts']), _count(b['deadlocks']), _count(b['otherErrors']), _ms_list(s, ('p50', 'p99', 'max'))))
    lines.append('')
    lines.append('- **Lock timeouts: %s in reserve (reads and create permits), %s in consume (the create leaving), %s in observe (the answer recorded, '
                 'and the notes of a request that failed or was dropped).** RateCoordinatorUnavailable errors in all: %s of %s errors.' % (
                     _count(t['lockTimeoutsInReserve']), _count(t['lockTimeoutsInConsume']), _count(t['lockTimeoutsInObserve']),
                     _count(t['unavailable']), _count(t['errors'])))
    by_cause = r['byReasonAndCause']
    lines.append('- **Releases of a post** (the worker gives it back unsent): %s; about 300 s (what a coordinator that is unavailable releases for; a '
                 'quote of exactly 300 s would count too): **%s**; with a quoted wait: %s%s; without a wait given: %s. By reason / rate scope / rate cause: %s.' % (
                     _count(r['total']), _count(r['about300Seconds']), _count(r['quotedWait']),
                     (' (p50 / p90 / max %s s)' % ' / '.join(_fmt((r.get('quotedWaitSeconds') or {}).get(k)) for k in ('p50', 'p90', 'max'))) if r['quotedWait'] else '',
                     _count(r['noWaitGiven']), json.dumps(by_cause) if by_cause else 'none'))
    if d['events']:
        lines.append('- **`rate_coordinator_degraded` was set in %d process(es) (%d events)**, first %s after T, last %s after T; set from %s, right after the failed call %s. '
                     'In a process where it is set every later request is refused before transport; the lane there stops as `coordinator_degraded`.' % (
                         d['processes'], d['events'], _minutes(d['firstAfterDue']), _minutes(d['lastAfterDue']),
                         json.dumps(d['where']), json.dumps(d['afterFailedCall'])))
    else:
        lines.append('- **`rate_coordinator_degraded` was never set** in any process of the run.')
    stopped = summary['laneStopped']
    lines.append('- Lane invocations that stopped as `coordinator_degraded`: %s; as `coordinator_unavailable`: %s.' % (
        _count(stopped.get('coordinator_degraded', 0)), _count(stopped.get('coordinator_unavailable', 0))))
    c = summary.get('createsPerMinute')
    if c:
        lines.append('- **Posts created a minute** (not only lateness): median %s over the %d minutes that count (at least a fifth of the busiest), '
                     'least %s, most %s, best five minutes in a row %s a minute.' % (_fmt(c['median']), c['minutes'], _fmt(c['min']), _fmt(c['max']), _fmt(c['best5'])))
    lines.append('')
    return lines


def _samples_of(values):
    return _spread([v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)])


def health_summary(samples):
    """The health payload (`GET /api/ops/discord/health`, the route an operator reads) as the harness sampled it during the
    run, one reduced reading a minute (health-samples.jsonl). From each reading: coordinator.booking (status, bookAheadSeconds,
    aheadNow, horizonSeconds, bookedReads60s, bookedReadWaitSeconds60s, meanBookedReadWaitSeconds60s,
    maxBookedReadWaitSeconds60s), coordinator.guards.policy (the application row: remaining, limit, remainingRatio,
    resetSeconds; with booking `remaining` is the number of slots bookings may still fill and `resetSeconds` when a booking is
    possible again, not "the window is nearly spent") and coordinator.traffic.admissions60s.

    The spreads are taken over the busy readings only, so the idle ends of a run (and the seeding minute before it, whose
    admissions are still in the first reading's 60 seconds under a policy of 20,000 a second) do not dilute them: a reading is
    busy when the lane had work due (queue.dueWorkspaces > 0; every reading, when the payload has no queue section) and its
    admissions60s is at least half of the largest of those; every reading is counted in 'readings'. A tree without the route
    answers 404: said so."""
    if not samples:
        return None
    statuses = Counter(str(s.get('status')) if s.get('status') is not None else 'exception' for s in samples)
    usable = [s for s in samples if s.get('status') == 200 and isinstance(s.get('coordinator'), dict)]
    out = {'readings': len(samples), 'statuses': dict(statuses), 'usable': len(usable),
           'exceptions': [str(s['exception'])[:160] for s in samples if s.get('exception')][:3],
           'sectionErrors': dict(Counter(e.get('section') for s in samples for e in (s.get('errors') or []) if isinstance(e, dict))),
           'wallSeconds': _spread([s['wallSeconds'] for s in samples if isinstance(s.get('wallSeconds'), (int, float))]),
           'elapsedMs': _samples_of([s.get('elapsedMs') for s in usable])}
    if not usable:
        return out
    traffic = lambda s: ((s.get('coordinator') or {}).get('traffic') or {})
    due = lambda s: (s.get('queue') or {}).get('dueWorkspaces')
    with_work = [s for s in usable if not isinstance(due(s), (int, float)) or due(s) > 0]
    admitted = [traffic(s).get('admissions60s') for s in with_work if isinstance(traffic(s).get('admissions60s'), (int, float))]
    peak = max(admitted, default=0)
    busy = [s for s in with_work if peak and isinstance(traffic(s).get('admissions60s'), (int, float))
            and traffic(s)['admissions60s'] >= 0.5 * peak] or usable
    booking = lambda s: ((s.get('coordinator') or {}).get('booking') or {})
    policy = lambda s: (((s.get('coordinator') or {}).get('guards') or {}).get('policy') or {})
    observed = [s for s in busy if booking(s).get('status') == 'observed']
    ahead = next((booking(s).get('bookAheadSeconds') for s in observed), None)
    out.update(
        busyReadings=len(busy), peakAdmissions60s=peak,
        admissions60s=_samples_of([traffic(s).get('admissions60s') for s in busy]),
        bookingStatuses=dict(Counter(booking(s).get('status', 'missing') for s in usable)),
        bookAheadSeconds=ahead, bookingReadings=len(observed),
        aheadNow=_samples_of([booking(s).get('aheadNow') for s in observed]),
        horizonSeconds=_samples_of([booking(s).get('horizonSeconds') for s in observed]),
        horizonFullReadings=sum(1 for s in observed if ahead and isinstance(booking(s).get('horizonSeconds'), (int, float))
                                and booking(s)['horizonSeconds'] >= ahead - 0.1),
        bookedReads60s=_samples_of([booking(s).get('bookedReads60s') for s in observed]),
        bookedReadWaitSeconds60s=_samples_of([booking(s).get('bookedReadWaitSeconds60s') for s in observed]),
        meanBookedReadWaitSeconds60s=_samples_of([booking(s).get('meanBookedReadWaitSeconds60s') for s in observed]),
        maxBookedReadWaitSeconds60s=_samples_of([booking(s).get('maxBookedReadWaitSeconds60s') for s in observed]),
        policyRemaining=_samples_of([policy(s).get('remaining') for s in busy]),
        policyLimit=next((policy(s).get('limit') for s in busy if policy(s).get('limit') is not None), None),
        policyRemainingRatio=_samples_of([policy(s).get('remainingRatio') for s in busy]),
        policyResetSeconds=_samples_of([policy(s).get('resetSeconds') for s in busy]),
        policyRemainingZeroReadings=sum(1 for s in busy if policy(s).get('remaining') == 0),
        policyRemainingZeroShallowHorizon=sum(1 for s in busy if policy(s).get('remaining') == 0 and ahead
                                              and isinstance(booking(s).get('horizonSeconds'), (int, float))
                                              and booking(s)['horizonSeconds'] < 0.5 * ahead),
        policyHoldOrEmbargo=sum(1 for s in usable if policy(s).get('hold') or policy(s).get('blocked') or policy(s).get('circuit')),
        responses429=_samples_of([traffic(s).get('responses429') for s in busy]),
        lastReading={k: v for k, v in (usable[-1].get('coordinator') or {}).items() if k in ('booking', 'traffic')})
    return out


def reads_ahead(admissions):
    """How many reads lay ahead of the clock (a wire time not yet reached) when each read was reserved: the booked horizon
    as the reads themselves saw it, not sampled once a minute like the health payload. Reads only: a booked create permit is
    stored with its slot as its reservation time, so its true reservation instant is not in the table. Returns the spread of
    the counts, or None without reads."""
    import heapq
    reads = sorted((r[0], r[2]) for r in admissions or [] if len(r) > 8 and not r[8] and r[0] is not None and r[2] is not None)
    if not reads:
        return None
    heap, ahead = [], []
    for reserved, wire in reads:
        while heap and heap[0] <= reserved:
            heapq.heappop(heap)
        ahead.append(len(heap))
        heapq.heappush(heap, wire)
    return _spread(ahead)


def booking_summary(lane_counters, created_posts, admissions, attempts, health):
    """Booking (rate_limits.booking: a lane caller that finds the application window full books the next free slot and sleeps
    in the call until it comes) from four independent sources, so each can be checked against the others:
    the lane's own counters (bookedWaits, bookedSeconds), the coordinator's admissions (a read stored `sent` at a wire time later
    than its reservation was booked; the difference is its wait; a create's booked wait is not stored, its reserved_at is its
    slot), the attempt log (booked and slept seconds per call) and the health payload. Returns None when nothing shows booking."""
    counters = lane_counters or {}
    booked_waits, booked_seconds = counters.get('bookedWaits'), counters.get('bookedSeconds')
    reads = [r for r in admissions or [] if len(r) > 8 and not r[8] and r[2] is not None and r[0] is not None]
    waits = [r[2] - r[0] for r in reads if r[2] - r[0] > BOOKED_MIN]
    if booked_waits is None and not waits and not (attempts or {}).get('booked') and not health:
        return None
    created = created_posts or 0
    out = {'laneBookedWaits': booked_waits, 'laneBookedSeconds': booked_seconds,
           'laneMeanBookedSeconds': (booked_seconds / booked_waits) if booked_waits else None,
           'laneBookedWaitsPerCreatedPost': (booked_waits / created) if booked_waits is not None and created else None,
           'laneBookedSecondsPerCreatedPost': (booked_seconds / created) if booked_seconds is not None and created else None,
           'laneCounters': {k: counters.get(k) for k in ('rateDelayed', 'permitWaits', 'rateWaits', 'steps', 'positionsKept',
                                                          'claimed', 'posted', 'verified') if k in counters},
           'admittedReads': len(reads), 'bookedReads': len(waits),
           'bookedReadShare': (len(waits) / len(reads)) if reads else None, 'bookedReadWait': _spread(waits),
           'bookedReadSeconds': sum(waits), 'readsAhead': reads_ahead(admissions),
           'attempts': {k: (attempts or {}).get(k) for k in ('withBookingColumns', 'booked', 'bookedByOperation',
                                                              'bookedPlannedSeconds', 'bookedSleptSeconds', 'bookedPlanned',
                                                              'bookedSlept', 'refusedWithRoomToBook')} if attempts else None,
           'health': health}
    return out


def booking_lines(result):
    """Markdown lines for the receipt: the booking figures and the health payload's reading of them."""
    b = result.get('booking')
    if not b:
        return []
    lines = ['## Booking (the limiter\'s "book the next free slot")', '']
    c = b.get('laneCounters') or {}
    lines.append('- **Lane counters** (sum over the lane invocations; the application\'s own claims): bookedWaits %s (%s per created '
                 'post), bookedSeconds %s (mean %s s a booking, %s s per created post); rateDelayed (releases) %s, permitWaits %s, '
                 'rateWaits %s, steps %s, positionsKept %s.' % (
                     _count(b.get('laneBookedWaits')), _fmt(b.get('laneBookedWaitsPerCreatedPost')), _fmt(b.get('laneBookedSeconds')),
                     _fmt(b.get('laneMeanBookedSeconds')), _fmt(b.get('laneBookedSecondsPerCreatedPost')), _count(c.get('rateDelayed')),
                     _count(c.get('permitWaits')), _count(c.get('rateWaits')), _count(c.get('steps')), _count(c.get('positionsKept'))))
    w = b.get('bookedReadWait')
    lines.append('- **Reads booked, from the coordinator\'s admissions** (a read stored `sent` at a wire time more than 5 ms after its '
                 'reservation): %s of %s admitted reads (%.1f%%); the wait p50 / p90 / p99 / max %s s; %s s in all. Creates are not '
                 'in this count: a booked create permit is stored reserved at its slot.' % (
                     _count(b.get('bookedReads')), _count(b.get('admittedReads')), 100 * (b.get('bookedReadShare') or 0),
                     ' / '.join(_fmt((w or {}).get(k)) for k in ('p50', 'p90', 'p99', 'max')), _fmt(b.get('bookedReadSeconds'))))
    ra = b.get('readsAhead')
    if ra:
        lines.append('- **Booked horizon as the reads saw it:** the number of reads lying ahead of the clock (a wire time not yet reached) '
                     'when a read was reserved, p50 / p90 / p99 / max %s (n = %s reads; with the reviewed 25 a second and a 0.1 s guard a '
                     'full horizon holds about 21).' % (
                         ' / '.join(_fmt(ra.get(k)) for k in ('p50', 'p90', 'p99', 'max')), _count(ra.get('n'))))
    a = b.get('attempts')
    if a and a.get('withBookingColumns'):
        lines.append('- **Booked calls, from the attempt log:** %s (by operation %s); planned wait p50 / p90 / max %s s, seconds '
                     'slept in the call (the wait for the slot and the gate after it) p50 / p90 / max %s s; %s planned and %s slept '
                     'in all. A refused call that still had room to book: %s (the booked horizon was full, or the caller\'s own '
                     'deadline too near).' % (
                         _count(a.get('booked')), json.dumps(a.get('bookedByOperation') or {}, sort_keys=True),
                         ' / '.join(_fmt((a.get('bookedPlanned') or {}).get(k)) for k in ('p50', 'p90', 'max')),
                         ' / '.join(_fmt((a.get('bookedSlept') or {}).get(k)) for k in ('p50', 'p90', 'max')),
                         _fmt(a.get('bookedPlannedSeconds')), _fmt(a.get('bookedSleptSeconds')), _count(a.get('refusedWithRoomToBook'))))
    h = b.get('health')
    if not h:
        lines.append('- Health payload: not sampled in this directory (no health-samples.jsonl).')
    elif not h.get('usable'):
        lines.append('- **Health payload** (`GET /api/ops/discord/health`): %s readings, none usable (statuses %s%s); a tree without the '
                     'route answers 404, which says nothing about its limiter.' % (
                         h['readings'], json.dumps(h['statuses'], sort_keys=True),
                         ('; ' + '; '.join(h['exceptions'])) if h.get('exceptions') else ''))
    else:
        sp = lambda key, keys=('p50', 'p90', 'max'), digits=2: ' / '.join(
            ('n/a' if (h.get(key) or {}).get(k) is None else ('%.*f' % (digits, h[key][k]))) for k in keys)
        lines.append(
            '- **Health payload** (`GET /api/ops/discord/health`, %s readings a minute apart, %s usable, %s of them busy: '
            'admissions60s at least half of the largest, %s; section errors %s). Spreads p50 / p90 / max over the busy readings. '
            '`coordinator.booking` (status %s; bookAheadSeconds %s): aheadNow %s; horizonSeconds %s (at or within 0.1 s of '
            'bookAheadSeconds in %s of %s readings); bookedReads60s %s; bookedReadWaitSeconds60s %s; meanBookedReadWaitSeconds60s '
            '%s; maxBookedReadWaitSeconds60s %s.' % (
                h['readings'], h['usable'], h['busyReadings'], _fmt(h['peakAdmissions60s']),
                json.dumps(h['sectionErrors'], sort_keys=True) or '{}', json.dumps(h['bookingStatuses'], sort_keys=True),
                _fmt(h['bookAheadSeconds']), sp('aheadNow', digits=0), sp('horizonSeconds', digits=3), h['horizonFullReadings'],
                h['bookingReadings'], sp('bookedReads60s', digits=0), sp('bookedReadWaitSeconds60s', digits=1),
                sp('meanBookedReadWaitSeconds60s', digits=3), sp('maxBookedReadWaitSeconds60s', digits=3)))
        lines.append(
            '- **Application row, `coordinator.guards.policy`** (limit %s): `remaining` %s, `remainingRatio` %s, `resetSeconds` %s. Its '
            'meaning changed with booking (and was changed again by the limiter), so it is printed next to the horizon to be checked '
            'against it: `remaining` was 0 in %s of the %s busy readings, and in %s of those the booked horizon was under half of '
            '`bookAheadSeconds` (a 0 with a shallow horizon is not a refusal in sight; the meaning per head is in docs/w02/CAPACITY-RUN.md). '
            '`coordinator.traffic.admissions60s` %s (a minute at the 22.7 a second the guard allows is 1,362; the most a saturated lane '
            'sends is 21.8 a second = 1,308); holds, embargoes or open circuits on the policy row in %s readings; 429 responses in the '
            'last minute %s. Reading took %s ms (server), %s s (process, cold).' % (
                _fmt(h.get('policyLimit')), sp('policyRemaining', digits=0), sp('policyRemainingRatio', digits=2),
                sp('policyResetSeconds', digits=1), h['policyRemainingZeroReadings'], h['busyReadings'],
                h['policyRemainingZeroShallowHorizon'],
                sp('admissions60s', digits=0), h['policyHoldOrEmbargo'], sp('responses429', digits=0),
                ' / '.join(_fmt((h.get('elapsedMs') or {}).get(k)) for k in ('p50', 'max')),
                ' / '.join(_fmt((h.get('wallSeconds') or {}).get(k)) for k in ('p50', 'max'))))
    lines.append('')
    return lines


def permit_stats(admissions):
    """The run's create permits (publish admissions): how each ended, and how long the seal and the send took against
    the permit's lifetime. A permit that died unused is one that expired still reserved (before the seal) or was
    sealed and then blocked (after it). Rows are those of admissions.jsonl."""
    rows = [r for r in admissions if len(r) > 8 and r[8]]
    if not rows:
        return None
    states = Counter()
    for r in rows:
        sealed = r[1] is not None
        key = r[5] if r[5] in ('observed', 'sent', 'uncertain', 'reserved', 'sealed') else (
            'blocked after the seal' if sealed else 'blocked before the seal')
        states[key] += 1
    return {'permits': len(rows), 'used': states['observed'], 'diedBeforeSeal': states['reserved'],
            'diedAfterSeal': states['blocked after the seal'] + states['sealed'],
            'stoppedBeforeSeal': states['blocked before the seal'], 'leftOpen': states['sent'] + states['uncertain'],
            'byState': dict(states),
            'lifetime': _spread([r[4] - r[0] for r in rows if r[4] is not None]),
            'sealLatency': _spread([r[1] - r[0] for r in rows if r[1] is not None]),
            'consumeLatency': _spread([r[2] - r[1] for r in rows if r[1] is not None and r[2] is not None])}


def hot_channel(posts, window, due):
    """The largest workspace's creates while it still had due posts, against the physical one create per second per
    channel (the mock's bucket is five per five seconds). Rates: from T to its last create (to the end of the log if
    some were never sent), and between its first and last create; its creates per minute after T."""
    by_index = defaultdict(list)
    for p in posts.values():
        by_index[p['index']].append(p)
    if not by_index:
        return None
    index = max(by_index, key=lambda i: len(by_index[i]))
    hot = by_index[index]
    if len(hot) < 50:
        return None
    created = sorted(p['createdAt'] for p in hot if p['createdAt'] is not None)
    all_sent = len(created) == len(hot)
    end = created[-1] if all_sent else (max(r['processed'] for r in window) if window else due)
    seconds = max(1.0, end - due)
    steady = ((len(created) - 1) / (created[-1] - created[0])) if len(created) > 1 and created[-1] > created[0] else None
    per_minute = Counter(int((t - due) // 60) for t in created)
    return {'workspace': index, 'posts': len(hot), 'sent': len(created), 'notSent': len(hot) - len(created),
            'firstCreateAfterDue': (created[0] - due) if created else None,
            'lastCreateAfterDue': (created[-1] - due) if created else None,
            'createsPerSecondWhileDue': len(created) / seconds, 'shareOfOnePerSecond': len(created) / seconds,
            'steadyCreatesPerSecond': steady, 'windowSeconds': seconds, 'allSent': all_sent,
            'postsPerMinute': {str(k): v for k, v in sorted(per_minute.items())}}


def grant_custody(ledger):
    """What the mock saw of the person's grant check: the real path asks GET /oauth2/@me once per sent post."""
    row = next((r for r in ledger['rows'] if (r['route'], r['credential']) == ('GET /oauth2/@me', 'user')), None)
    seen = row['answered2xx'] if row else 0
    sent = ledger['sentPosts']
    if not sent:
        return {'state': 'not measured', 'identityChecks': seen, 'sentPosts': sent}
    return {'state': 'real path' if seen >= sent else 'below one per sent post', 'identityChecks': seen,
            'sentPosts': sent}


def pacing(window, posts, due, *, active_threshold=5, ceiling=25.0):
    """How the lane used its request budget while it was creating posts.

    Busy period: first to last create at the mock. A second of it is active when the mock processed at least
    `active_threshold` requests in it (stragglers of a stopping loop excluded). Duty cycle: active seconds over all
    seconds of the busy period. Active rate: requests per active second, also as a share of the ceiling. Plateau: from
    the due time to the first read-back the mock answered (read-backs are served behind creates), or to the last create
    if no read-back came first; requests per created post in it. Profile: mean requests per second of the minute over
    the plateau, and the first and last second of the minute averaging at least `active_threshold`."""
    creates = sorted(p['createdAt'] for p in posts.values() if p['createdAt'] is not None)
    if len(creates) < 2:
        return None
    start, end = creates[0], creates[-1]
    per_second = Counter(int(math.floor(r['processed'])) for r in window if start <= r['processed'] <= end)
    seconds = list(range(int(math.floor(start)), int(math.floor(end)) + 1))
    active = [s for s in seconds if per_second.get(s, 0) >= active_threshold]
    readbacks = sorted(r['processed'] for r in window if r.get('readback') and r.get('status') == 200)
    plateau_end = readbacks[0] if readbacks and start < readbacks[0] < end else end
    in_plateau = [r for r in window if due <= r['processed'] < plateau_end]
    created_in_plateau = sum(1 for t in creates if due <= t < plateau_end)
    minutes = max(1e-9, (plateau_end - due) / 60.0)
    profile = Counter(int(math.floor(r['processed'])) % 60 for r in in_plateau)
    mean_by_second = {s: profile.get(s, 0) / minutes for s in range(60)}
    busy_slots = [s for s in range(60) if mean_by_second[s] >= active_threshold]
    active_rate = (sum(per_second[s] for s in active) / len(active)) if active else None
    # The same two figures for the plateau alone (the phase that decides the median).
    plateau_seconds = [s for s in seconds if s < plateau_end]
    plateau_active = [s for s in plateau_seconds if per_second.get(s, 0) >= active_threshold]
    plateau_duty = (len(plateau_active) / len(plateau_seconds)) if plateau_seconds else None
    plateau_rate = (sum(per_second[s] for s in plateau_active) / len(plateau_active)) if plateau_active else None
    result = {
        'busyStartAfterDue': start - due, 'busyEndAfterDue': end - due, 'busySeconds': len(seconds),
        'activeSeconds': len(active), 'dutyCycle': len(active) / len(seconds) if seconds else None,
        'activeRatePerSecond': active_rate, 'activeRateShareOfCeiling': (active_rate / ceiling) if active_rate else None,
        'busyRatePerSecond': sum(per_second.values()) / len(seconds) if seconds else None,
        'plateauEndAfterDue': plateau_end - due, 'plateauRequests': len(in_plateau), 'plateauCreates': created_in_plateau,
        'plateauRequestsPerCreatedPost': (len(in_plateau) / created_in_plateau) if created_in_plateau else None,
        'secondOfMinuteActive': [min(busy_slots), max(busy_slots)] if busy_slots else None,
        'secondOfMinuteMeanRate': {str(s): round(v, 2) for s, v in mean_by_second.items()},
        'plateauDutyCycle': plateau_duty, 'plateauActiveRatePerSecond': plateau_rate,
        'plateauActiveRateShareOfCeiling': (plateau_rate / ceiling) if plateau_rate else None}
    # The lateness this pacing implies for the middle post (inference, not a measurement).
    if plateau_duty and plateau_rate and result['plateauRequestsPerCreatedPost']:
        effective = plateau_duty * plateau_rate
        result['effectiveRatePerSecond'] = effective
        result['impliedMedianLatenessMinutes'] = (start - due + 0.5 * len(posts) * result['plateauRequestsPerCreatedPost']
                                                  / effective) / 60.0
    return result


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
    # A downloaded artifact may hold invocations.jsonl but not the per-invocation results: the worker figures are then
    # empty (the receipt says so), everything measured at the mock is unchanged.
    for name in (sorted(os.listdir(folder)) if os.path.isdir(folder) else []):
        if name.endswith('.json'):
            try:
                invocations.append(load_json(os.path.join(folder, name)))
            except ValueError:
                invocations.append({'path': name, 'exception': 'unreadable result'})
    summary_path = os.path.join(run_dir, 'invocations-summary.json')
    if not invocations and os.path.exists(summary_path):
        invocations = load_json(summary_path)  # the results without their log lines, kept as an artifact
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
    paced = pacing(window, posts, T)
    admissions = load_jsonl(os.path.join(run_dir, 'admissions.jsonl'))
    witness = witness_age(window, posts)
    jitter = wire_jitter(window, admissions)
    permits = permit_stats(admissions)
    passes_summary = preflight_passes(window, admissions)
    created_count = sum(1 for p in posts.values() if p['createdAt'] is not None)
    attempt_rows = load_jsonl(os.path.join(run_dir, 'attempts.jsonl'))
    attempts_summary = attempt_statistics(attempt_rows, created_count)
    health = health_summary(load_jsonl(os.path.join(run_dir, 'health-samples.jsonl')))
    hot = hot_channel(posts, window, T) if config.get('hotPosts') else None
    channel_items = max((r.get('items') or 0 for r in window), default=0) or None
    refreshes = sum(1 for r in window if r.get('route') == 'POST /oauth2/token')
    # Traffic from invocations that are not lane shards: from the source tag the invocation wrapper puts on every request
    # (visible in a downloaded artifact), else from the per-invocation results when they are present.
    tagged = [r for r in window if r.get('src')]
    if tagged:
        by_source = Counter('lane' if r['src'].startswith('lane') else r['src'] for r in tagged)
        non_lane = {'requests': sum(n for k, n in by_source.items() if k != 'lane'), 'bySource': dict(by_source),
                    'untagged': len(window) - len(tagged)}
    elif invocations:
        non_lane = sum(int(i.get('discordRequests') or 0) for i in invocations
                       if not i.get('path', '').startswith('/api/cron/discord-worker/'))
    else:
        non_lane = None
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
        small_lateness = [(p['createdAt'] - p['due']) if p['createdAt'] is not None else math.inf
                          for index, items in by_workspace.items() if index != hot_index and len(items) <= 5 for p in items]
        fairness = {'hotWorkspace': hot_index, 'hotPosts': len(hot_posts), 'hotSent': len(hot_created),
                    'hotLastCreateAfterT': (max(hot_created) - T) if hot_created else None,
                    'hotLateness': describe(hot_lateness), 'smallWorkspaces': len(completions),
                    'smallCompletionAfterT': describe(completions), 'smallLateness': describe(small_lateness),
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
    waited = Counter()
    for item in lane:
        for key, value in (((item.get('body') or {}).get('waitedSeconds')) or {}).items():
            if isinstance(value, (int, float)):
                waited[key] += value
    step_timing = None
    if lane_counters.get('steps') and handler_seconds:
        steps = lane_counters['steps']
        totals = extra.get('statementTotals')
        latency = (config.get('settings') or {}).get('db_latency_ms')
        # A booked wait sleeps inside the coordinator's reserve (lane counter bookedSeconds): waiting, not busy.
        busy = max(0.0, sum(handler_seconds) - waited['rate'] - waited['idle'] - (lane_counters.get('bookedSeconds') or 0.0))
        server_ms = 1000 * totals['execSeconds'] / steps if totals else None
        trip_ms = (totals['calls'] * latency / steps) if totals and latency is not None else None
        step_timing = {'steps': steps, 'loopSeconds': sum(handler_seconds), 'waitedRateSeconds': waited['rate'],
                       'waitedIdleSeconds': waited['idle'], 'waitedBookedSeconds': lane_counters.get('bookedSeconds') or 0.0,
                       'busySecondsPerStep': busy / steps,
                       'statementsPerStep': (totals['calls'] / steps) if totals else None, 'serverMsPerStep': server_ms,
                       'dbLatencyMs': latency, 'roundTripMsPerStep': trip_ms,
                       'otherMsPerStep': (1000 * busy / steps - server_ms - trip_ms) if server_ms is not None and trip_ms is not None else None}
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
        'version': 2, 'scenario': config['scenario'], 'judgeAs': (config.get('settings') or {}).get('judge_as') or config['scenario'],
        'label': config['label'], 'sourceTree': config['sourceTree'],
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
        'ledger': ledger, 'grantCustody': custody, 'pacing': paced, 'witnessAge': witness, 'wireJitter': jitter,
        'permits': permits, 'preflightPasses': passes_summary, 'attempts': attempts_summary,
        'booking': booking_summary(dict(lane_counters), created_count, admissions, attempts_summary, health),
        'coordinatorFailures': coordinator_failures(attempt_rows, dict(stopped), T, {str(k): v for k, v in per_minute.items()}),
        'health': health, 'stepTiming': step_timing, 'hotChannel': hot, 'largestChannelList': channel_items,
        'tokenRefreshRequests': refreshes, 'nonLaneDiscordRequests': non_lane,
        'invocationResultsPresent': os.path.isdir(folder) or bool(invocations),
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
    result['launchGates'] = launch_gates(result)
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
        scenario = result.get('judgeAs') or result['scenario']  # an S1 variant is judged as S1
        if (applies and scenario not in applies) or scenario in excluded:
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
        planned_random = len(config['settings'].get('kills') or [])
        planned_at_create = int(config['settings'].get('kill_at_create') or 0)
        _line(rows, 'fcrash_kills', 'The planned SIGKILLs were delivered', len(done) >= planned,
              'planned %d (%d random, %d during a create); delivered %d (%d random, %d during a create); missed %d (%d random, %d during a create)' % (
                  planned, planned_random, planned_at_create, len(done), sum(1 for k in done if k['kind'] == 'random'),
                  sum(1 for k in done if k['kind'] == 'at_create'),
                  sum(1 for k in kills if k.get('kind') in ('at_create_missed', 'random_missed')),
                  sum(1 for k in kills if k.get('kind') == 'random_missed'),
                  sum(1 for k in kills if k.get('kind') == 'at_create_missed')),
              'delivered = planned, missed 0')
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


def _ms(value):
    return 'n/a' if value is None else '%.1f ms' % (1000 * value)


def _ms_list(spread, keys=('p50', 'p90', 'p99', 'p999', 'max')):
    return ' / '.join(_ms(spread.get(k)) for k in keys) if spread else 'n/a'


def _count(value):
    return 'n/a' if value is None else '{:,}'.format(int(value))


def _open_text(rows):
    parts = []
    for r in rows:
        what = '%s %s%s' % (r['state'], 'create' if r['publish'] else 'read',
                            '' if r.get('unexpired') is None else (' unexpired' if r['unexpired'] else ' expired'))
        old = r.get('olderThan60Seconds')
        parts.append('%s %s: %d (oldest %s s%s)' % (r.get('kind') or '?', what, r['count'], _fmt(r.get('oldestAgeSeconds')),
                                                    (', %d older than 60 s' % old) if old else ''))
    return '; '.join(parts) or 'none'


def _unanswered(rows):
    """The open admissions that count against a window today: sent and uncertain ones (an answer may never come) and
    reserved or sealed ones whose permit has not expired."""
    return [r for r in rows or () if r['state'] in ('sent', 'uncertain') or (r['state'] in ('reserved', 'sealed') and r.get('unexpired'))]


def launch_gates(result):
    """Gates that are reported, never raised: they sit beside the scenario's expected behaviour and do not change its
    tally. Each says PASS, FAIL or NOT MEASURED in its own row."""
    d = result.get('database') or {}
    rows = []
    opened = d.get('openAdmissions')
    if opened is None:
        _line(rows, 'open_admissions', 'Admissions left without an observed answer at the end of the run', None,
              'not collected by this harness version', '0')
    else:
        held = _unanswered(opened)
        _line(rows, 'open_admissions', 'Admissions left without an observed answer at the end of the run (by state)',
              not held, ('%d: %s' % (sum(r['count'] for r in held), _open_text(held))) if held else 'none', '0')
    probes = d.get('budgetProbes')
    good = [p for p in probes or [] if not p.get('error') and p.get('admitted') is not None]
    if not good:
        _line(rows, 'budget_restored', 'The application budget is whole again once unanswered requests have aged out', None,
              'no probe ran (%s)' % (('probe failed: ' + str(probes[-1].get('error'))[:200]) if probes else
                                     'no delayed probe in this scenario, or the tree has no coordinator'), 'full capacity')
    else:
        last = good[-1]
        capacity = last.get('capacity')
        waited = last.get('waited') or 0
        text = '; '.join('after %s s: %s of %s admitted%s' % (_fmt(p.get('waited')), p.get('admitted'), p.get('capacity'),
                                                               ' (window rolled during the probe)' if p.get('windowRolled') else '')
                         for p in good)
        name = ('The application budget is whole again once unanswered requests have aged out (probe %s s after the end)' % _fmt(waited)
                if waited >= 60 else 'The application budget right after the run (no delayed probe in this scenario)')
        _line(rows, 'budget_restored', name, last.get('admitted') == capacity if capacity else None, text,
              '%s of %s' % (capacity, capacity))
    # Owner reply 16 (D-16): what the coordinator let leave must stay at or under the ceiling; the count of requests above it
    # as the mock sees them arrive is REPORTED, not a failure. Both are printed, the second never softened.
    admissions = (result.get('ceiling') or {}).get('coordinatorAdmissions') or {}
    jitter = result.get('wireJitter') or {}
    wire = admissions.get('wire') or {}
    stamped = wire.get('peakTrailingSecond') if wire.get('peakTrailingSecond') is not None else jitter.get('sendPeakTrailingSecond')
    stamped_calendar = wire.get('peakCalendarSecond') if wire.get('peakCalendarSecond') is not None else jitter.get('sendPeakCalendarSecond')
    ceiling = (result.get('ceiling') or {}).get('policyCeiling') or 25
    _line(rows, 'coordinator_stamped_ceiling',
          'Coordinator-stamped sends (sent_at, the instant the coordinator let a request leave) in any trailing second (owner reply 16, D-16)',
          None if stamped is None else stamped <= ceiling,
          'not measurable here (no admissions export)' if stamped is None else 'most in a trailing second %s, in a calendar second %s' % (
              stamped, stamped_calendar), '<= %s' % ceiling)
    above = (result.get('ceiling') or {}).get('aboveTwentyFiveAll')
    if above is not None:
        by = jitter.get('aboveCeilingBy') or {}
        rows.append({'id': 'arrival_above_ceiling',
                     'name': 'Requests above %s in a trailing second as they arrive at the mock (owner reply 16, D-16: REPORTED, not a failure)' % ceiling,
                     'expected': 'report',
                     'measured': '%s requests (peak in a trailing second %s)%s' % (
                         _count(above), (result.get('ceiling') or {}).get('peakTrailingSecondAll'),
                         ('; by cause: the coordinator had sent more than %s %s, wire jitter %s, the mock\'s processing order %s, not paired %s' % (
                             ceiling, by.get('coordinator', 0), by.get('wire', 0), by.get('mock', 0), by.get('unpaired', 0))) if by or jitter else ''),
                     'verdict': 'REPORTED'})
    permits = result.get('permits')
    if permits is None:
        _line(rows, 'permits_unused', 'Create permits that died unused', None, 'no create permit in the admissions export', '0')
    else:
        retries = d.get('jobRetries') or {}
        dead = permits['diedBeforeSeal'] + permits['diedAfterSeal']
        _line(rows, 'permits_unused', 'Create permits that died unused (expired before the seal, or sealed and then blocked)',
              dead == 0, '%d of %d permits: %d before the seal, %d after it; ratePermitRetries %s (largest in one job %s)' % (
                  dead, permits['permits'], permits['diedBeforeSeal'], permits['diedAfterSeal'],
                  retries.get('ratePermitRetries'), retries.get('ratePermitRetriesMaxPerJob')), '0')
    return rows


def evidence_lines(result):
    """Wire timing, witness age, permits, per-step database time, the hot workspace, identities and other traffic."""
    d = result.get('database') or {}
    lines = ['## Wire timing, witness age, permits and the database per step', '']
    j = result.get('wireJitter')
    if j:
        t = j['admissionToArrival']
        lines.append(
            '- **Admission-to-wire spread** (%s of %s sent admissions paired with their arrival at the mock; %s admissions '
            'without an arrival, %s arrivals without an admission). Admission (`sent_at`, database clock) to arrival at the '
            'mock, p50 / p90 / p99 / p99.9 / max: %s (n = %s%s). **p99.9 %s; spread above the median at p99.9 %s** (a guard has '
            'to cover the spread, not the delay itself: inference). Creates %s, reads %s (same percentiles).' % (
                _count(j['paired']), _count(j['admissionsSent']), _count(j['admissionsWithoutArrival']),
                _count(j['arrivalsWithoutAdmission']), _ms_list(t), _count(t['n']),
                '; fewer than 1,000, so p99.9 is the maximum' if t['n'] < 1000 else '', _ms(t['p999']),
                _ms(j['spreadAboveMedianP999']), _ms_list(j['creates']), _ms_list(j['reads'])))
        if j.get('admissionToCall'):
            lines.append(
                '  - Split where the call was stamped: admission to the HTTP call (inside the application) %s; call to arrival '
                '(loopback, and the mock\'s accept and thread start on the same loaded machine) %s. In production the second '
                'part is real network time, which this run does not model.' % (_ms_list(j['admissionToCall']),
                                                                              _ms_list(j['callToArrival'])))
        g = j.get('guard')
        if g:
            dd = g['delayDifference']
            lines.append(
                '- **Guard sizing** (windows at the ceiling: a request and the %dth after it sent within %.2f s of one second '
                'apart; %s such windows, smallest slack %s): the later one arrived less than 1 s after the first in %s windows '
                '(%.3f%%). Delay of the first minus delay of the later one, p50 / p90 / p99 / p99.9 / p99.99 / max: %s. A guard '
                'of the p99 / p99.9 / p99.99 value would hold the ceiling in all but 1%% / 0.1%% / 0.01%% of such windows '
                '(inference from this run\'s delays; the guard in force is the smallest slack).' % (
                    g['ceiling'] + 1, 0.25, _count(g['windows']), _ms(g['minSlack']), _count(g['violations']),
                    100 * g['violationShare'], ' / '.join(_ms(dd[k]) for k in ('p50', 'p90', 'p99', 'p999', 'p9999', 'max'))))
        by = j['aboveCeilingBy']
        lines.append(
            '- **Requests the mock counted above %d in their trailing second: %s**, by cause: the coordinator had already sent '
            'more than %d in the trailing second of the request\'s send time %s; wire jitter (%d or fewer sent, more arrived in '
            'the trailing second of the arrival) %s; the mock\'s processing order only (%d or fewer arrived; the mock counts '
            'up to half a latency after arrival) %s; request not paired %s. Most requests in any trailing second: by send time '
            '%s, by arrival %s, as the mock counted %s; in any calendar second: by send time %s, by arrival %s.' % (
                j['ceiling'], _count(j['aboveCeilingAtMock']), j['ceiling'], _count(by.get('coordinator', 0)), j['ceiling'],
                _count(by.get('wire', 0)), j['ceiling'], _count(by.get('mock', 0)), _count(by.get('unpaired', 0)),
                j['sendPeakTrailingSecond'], j['arrivalPeakTrailingSecond'],
                (result.get('ceiling') or {}).get('peakTrailingSecondAll'), j['sendPeakCalendarSecond'],
                j['arrivalPeakCalendarSecond']))
    else:
        lines.append('- Admission-to-wire spread: not measurable in this directory (needs admissions.jsonl and a mock that '
                     'records path digests, harness commit with the wire timing).')
    pp = result.get('preflightPasses')
    if pp:
        rc, win = pp.get('reclaimDelay') or {}, pp['applicationWindow']
        lines.append(
            '- **Preflight passes** (%s passes for %s created posts = %s per post; %s were released before the create, %s '
            'still open at the end): posts by number of passes %s. A released pass had completed: %s (so the next request '
            'was the one refused). Re-claim of the same post after a release, p10 / p50 / p90 / p99 / max: %s s (%.0f%% within '
            '2 s). Application window (%d sends within %.1f s) at five instants over the second after a release: full '
            'throughout %s, full at some instant %s, never full %s. Wait from the previous answer being observed to the '
            'next admission, per step, p50 / p90 / p99 and the share over 100 ms / over 1 s: %s.' % (
                _count(pp['passes']), _count(pp['createdPosts']), _fmt(pp['meanPassesPerPost']), _count(pp['released']),
                pp['openAtEnd'], json.dumps(pp['passesPerPost']), json.dumps(pp['releasedAfter']),
                ' / '.join(_fmt(rc.get(k)) for k in ('p10', 'p50', 'p90', 'p99', 'max')),
                100 * (pp.get('reclaimWithinTwoSeconds') or 0), pp['ceiling'], pp['span'], win.get('full throughout', 0),
                win.get('full at some instant', 0), win.get('never full', 0),
                '; '.join('%s %s / %s / %s ms, %.0f%% / %.1f%%' % (label, *(_fmt(1000 * v[k]) for k in ('p50', 'p90', 'p99')),
                                                                  100 * v['over100ms'], 100 * v['over1s'])
                          for label, v in sorted(pp['stepWait'].items())) or 'n/a'))
    w = result.get('witnessAge')
    if w:
        lines.append('- **Witness age at the create** (%d creates; %d with no witness found; the grant check was the oldest '
                     'witness for %d): oldest witness request of the create\'s pass to the create reaching the mock, p50 / p90 / '
                     'p99 / max: %s; newest (the channel list): %s.' % (
                         w['creates'], w['withoutWitness'], w['oldestFromGrantCheck'],
                         _ms_list(w['oldest'], ('p50', 'p90', 'p99', 'max')), _ms_list(w['newest'], ('p50', 'p90', 'p99', 'max'))))
    else:
        lines.append('- Witness age: no create with an attributed witness pass in the mock log.')
    pm = result.get('permits')
    if pm:
        retries = d.get('jobRetries') or {}
        lines.append('- **Create permits** (%d): used %d; died before the seal (expired while reserved) %d; died after the seal '
                     '(sealed, then blocked or never used) %d; stopped before the seal (blocked, never sealed) %d; left open '
                     '(sent or uncertain) %d. Counters in the jobs: ratePermitRetries %s (largest in one job %s), '
                     'rateReadRetries %s, unsentFailures %s. Permit lifetime min / p50 / max %s / %s / %s; seal after '
                     'reservation p50 / p99 / max %s; send after seal p50 / p99 / max %s.' % (
                         pm['permits'], pm['used'], pm['diedBeforeSeal'], pm['diedAfterSeal'], pm['stoppedBeforeSeal'],
                         pm['leftOpen'], retries.get('ratePermitRetries'), retries.get('ratePermitRetriesMaxPerJob'),
                         retries.get('rateReadRetries'), retries.get('unsentFailures'),
                         *(_ms((pm['lifetime'] or {}).get(k)) for k in ('min', 'p50', 'max')),
                         _ms_list(pm['sealLatency'], ('p50', 'p99', 'max')), _ms_list(pm['consumeLatency'], ('p50', 'p99', 'max'))))
    st = result.get('stepTiming')
    if st:
        lines.append(
            '- **Per lane step** (%s steps over %s loop-seconds, of which %s s waiting for the budget, %s s idle and %s s asleep in '
            'booked waits inside the coordinator): busy time '
            '%s per step. Database (every statement after seeding, the minute worker\'s included): %s statements per step, '
            'each a round trip; server execution %s per step; emulated network %s per step (%s statements x %s ms); the '
            'remaining %s per step is Python, the HTTP call to the mock, lock and pool waits (inference).' % (
                _count(st['steps']), _count(st['loopSeconds']), _count(st['waitedRateSeconds']), _count(st['waitedIdleSeconds']),
                _count(st.get('waitedBookedSeconds')),
                _ms(st['busySecondsPerStep']), _fmt(st['statementsPerStep']), _ms(None if st['serverMsPerStep'] is None else st['serverMsPerStep'] / 1000),
                _ms(None if st['roundTripMsPerStep'] is None else st['roundTripMsPerStep'] / 1000), _fmt(st['statementsPerStep']),
                _fmt(st['dbLatencyMs']),
                _ms(None if st['otherMsPerStep'] is None else st['otherMsPerStep'] / 1000)))
    locks = d.get('lockStatements')
    if locks:
        created = (result.get('outcomes') or {}).get('sentAtMock') or None
        per = lambda calls: _fmt(calls / created) if created else 'n/a'
        ex, sh, sd = locks.get('exclusive') or {}, locks.get('shared') or {}, locks.get('seed') or {}
        lines.append(
            '- **Reservation lock statements** (pg_stat_statements; the coordinator\'s `_locked`, which every reservation attempt '
            'runs and an observation runs only when it cannot share the lock). Exclusive form (`FOR UPDATE` on the scope rows): %s '
            'calls = **%s per created post**, mean %s ms, max %s ms. Shared form (`FOR SHARE` guards, a GET observation that can '
            'share): %s calls = %s per created post, mean %s ms, max %s ms. Seeding statement (`scope_seed`): %s calls, mean %s ms. '
            'The mean is the time the statement ran, a wait for the row locks included.' % (
                _count(ex.get('calls')), per(ex.get('calls') or 0), _fmt(ex.get('meanMs')), _fmt(ex.get('maxMs')),
                _count(sh.get('calls')), per(sh.get('calls') or 0), _fmt(sh.get('meanMs')), _fmt(sh.get('maxMs')),
                _count(sd.get('calls')), _fmt(sd.get('meanMs'))))
    heavy = d.get('heaviestStatements')
    if heavy:
        total = (d.get('statementTotals') or {}).get('execSeconds') or sum(h['totalSeconds'] for h in heavy) or 1.0
        lines.append('- Heaviest statements by total server time (share of all): ' + '; '.join(
            '`%s` %s s (%.0f%%), %s calls, mean %.1f ms, max %.1f ms' % (' '.join(h['query'].split())[:70].replace('|', '/'),
                                                                          _fmt(h['totalSeconds']), 100 * h['totalSeconds'] / total,
                                                                          h['calls'], h['meanMs'], h['maxMs']) for h in heavy[:5]) + '.')
    hot, seeded, ended = result.get('hotChannel'), d.get('documentAtSeed'), d.get('largestDocument')
    if hot:
        writes = d.get('workspaceWrites') or []
        lines.append(
            '- **Hot workspace (index %s, %d posts)** - document as seeded: %s; at the end of the run: %s. A transaction on '
            'it rewrites the whole document, so one step costs at least one read-modify-write. The application\'s '
            'UPDATE of a workspace document, over the run: %s.' % (
                hot['workspace'], hot['posts'], _document_text(seeded), _document_text(ended),
                '; '.join('mean %.1f ms, max %.1f ms over %s calls' % (w_['meanMs'], w_['maxMs'], w_['calls']) for w_ in writes[:1])
                or 'not collected'))
        lines.append(
            '- **Hot workspace\'s create rate while it had due posts (REPORTED, proposed measure; the proposed target of at least '
            '0.8 per second is not applied here):** %s creates per second from T to its %s (%.0f%% of the physical one per '
            'second per channel); steady rate between its first and last create %s per second; %d of %d sent, %d never sent; '
            'first create %s after T, last %s. Posts per minute after T: %s.' % (
                _fmt(hot['createsPerSecondWhileDue']),
                'last create' if hot['allSent'] else 'end of the run (not all were sent)', 100 * hot['shareOfOnePerSecond'],
                _fmt(hot['steadyCreatesPerSecond']), hot['sent'], hot['posts'], hot['notSent'],
                _minutes(hot['firstCreateAfterDue']), _minutes(hot['lastCreateAfterDue']),
                ', '.join('%s: %d' % item for item in hot['postsPerMinute'].items()) or 'none'))
    elif seeded or (ended and ended.get('jobs', 0) >= 50):
        lines.append('- Largest workspace document: as seeded %s; at the end %s.' % (_document_text(seeded), _document_text(ended)))
    else:
        lines.append('- Largest workspace document at the end: %s.' % _document_text(ended))
    expiry = d.get('identityExpiryAtDue')
    shortest = d.get('identityShortestHours')
    lines.append('- **Identity tokens at T** (time left until the person\'s Discord token expires): %s; the shortest %s hours. '
                 'Token refreshes at the mock during the run (`POST /oauth2/token`): %s. The harness gives every identity a '
                 '7-day token, so none expires during a run; a refresh storm is not modelled. Largest channel list answered: %s '
                 '(the mock serves one text channel per server).' % (
                     json.dumps(expiry, sort_keys=True) if expiry is not None else 'not collected',
                     _fmt(shortest), result.get('tokenRefreshRequests'), result.get('largestChannelList')))
    nl = result.get('nonLaneDiscordRequests')
    if isinstance(nl, dict):
        lines.append('- **Discord requests from invocations other than the lane shards** (the minute worker and others), as '
                     'tagged by the invocation wrapper: %d of %d tagged requests; by source %s; untagged requests %d.' % (
                         nl['requests'], sum(nl['bySource'].values()), json.dumps(nl['bySource'], sort_keys=True), nl['untagged']))
    elif nl is not None:
        lines.append('- **Discord requests from invocations other than the lane shards:** %d (from the invocation results).' % nl)
    else:
        lines.append('- Discord requests from invocations other than the lane shards: not visible in this directory.')
    opened = d.get('openAdmissions')
    if opened is not None:
        unused = sum(r['count'] for r in opened if r['state'] in ('reserved', 'sealed') and not r.get('unexpired'))
        lines.append('- **Admissions left without an observed answer at the end of the run (sent or uncertain, or a permit still '
                     'alive):** %s. A tree without an age bound counts every one of them against every window, for good. '
                     'Permits that expired unused, reserved or sealed, sent nothing and are counted with the create permits '
                     'above: %d.' % (_open_text(_unanswered(opened)), unused))
    after = d.get('openAdmissionsAfterWait')
    if after is not None:
        lines.append('- Still without an answer after the wait below: %s.' % _open_text(_unanswered(after)))
    probes = d.get('budgetProbes')
    if probes:
        parts = []
        for probe in probes:
            if probe.get('error'):
                parts.append('probe failed: %s' % str(probe['error'])[:200])
            else:
                parts.append('after %s s: %s of %s admitted%s (refused by %s)' % (
                    _fmt(probe.get('waited')), probe.get('admitted'), probe.get('capacity'),
                    ', window rolled during the probe' if probe.get('windowRolled') else '',
                    (probe.get('refused') or {}).get('scope')))
        lines.append("- **Application budget after the run** (a fresh window, probed with synthetic reads through the tree's "
                     'own coordinator, nothing sent anywhere): ' + '; '.join(parts) + '.')
    lines.append('')
    return lines


def _document_text(doc):
    if not doc:
        return 'n/a'
    if doc.get('error'):
        return 'error: %s' % str(doc['error'])[:120]
    timings = doc.get('readModifyWriteSeconds') or []
    return '%d jobs, %s bytes of JSON text (%s stored), one read-modify-write %s s (%s)' % (
        doc['jobs'], _count(doc['textBytes']), _count(doc['storedBytes']),
        ' / '.join(str(t) for t in timings), doc.get('note', 'timed, rolled back'))


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
    gates = result.get('launchGates')
    if gates:
        lines.append('## Launch gates (reported: they do not change the verdicts above)')
        lines.append('')
        lines.append('| Gate | Expected | Measured | Verdict |')
        lines.append('|---|---|---|---|')
        for g in gates:
            lines.append('| %s | %s | %s | **%s** |' % (g['name'], g['expected'], g['measured'], g['verdict']))
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
        sl = f.get('smallLateness')
        if sl:
            lines.append('')
            lines.append('Lateness of the small workspaces\' posts alone (REPORTED; the proposed scope of the lateness lines '
                         'for a scenario with a hot workspace): %d posts, median %s, p95 %s, max %s.' % (
                             sl['count'], *(_minutes(sl[k]) for k in ('median', 'p95', 'max'))))
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
                      'credential %s): most in any trailing second %s, in any calendar second %s, counted by RESERVATION instant.%s%s' % (
                          admissions.get('count'), json.dumps(admissions.get('byCredential'), sort_keys=True),
                          admissions.get('peakTrailingSecond'), admissions.get('peakCalendarSecond'),
                          ((' By WIRE time (`sent_at`, the instant a request may leave: with booking a booked read is stored at its '
                            'slot, after its reservation; %s requests stored with a wire time): most in any trailing second %s, in '
                            'any calendar second %s. This is the series the ceiling is kept on.' % (
                                admissions['wire']['count'], admissions['wire']['peakTrailingSecond'],
                                admissions['wire']['peakCalendarSecond'])) if admissions.get('wire') else ''),
                          (' Wire time (or reservation, where none) to observation (d): mean %s s, median %s s, p95 %s s; an admission still in '
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
    pc = result.get('pacing')
    if pc:
        active_slots = pc.get('secondOfMinuteActive') or ['n/a', 'n/a']
        lines.append('')
        lines.append('Pacing while creating (busy period: first to last create, %s to %s after T):' % (
            _minutes(pc['busyStartAfterDue']), _minutes(pc['busyEndAfterDue'])))
        lines.append('')
        lines.append('- **Busy-period duty cycle %.0f%%:** %d of %d seconds had at least 5 requests (plateau: %.0f%%). In '
                     'the plateau the lane is active from second %s to second %s of each minute.' % (
                         100 * (pc['dutyCycle'] or 0), pc['activeSeconds'], pc['busySeconds'],
                         100 * (pc.get('plateauDutyCycle') or 0), active_slots[0], active_slots[1]))
        lines.append('- **Active-window rate %s requests/s, %.0f%% of the 25/s ceiling** (plateau: %s requests/s, '
                     '%.0f%%). The busy-period average is %s requests/s.' % (
                         _fmt(pc['activeRatePerSecond']), 100 * (pc['activeRateShareOfCeiling'] or 0),
                         _fmt(pc.get('plateauActiveRatePerSecond')), 100 * (pc.get('plateauActiveRateShareOfCeiling') or 0),
                         _fmt(pc['busyRatePerSecond'])))
        lines.append('- **Plateau requests per created post %s:** %d requests and %d creates, from T to %s after T (the '
                     'first read-back).' % (_fmt(pc['plateauRequestsPerCreatedPost']), pc['plateauRequests'],
                                            pc['plateauCreates'], _minutes(pc['plateauEndAfterDue'])))
        lines.append('- Implied median lateness (inference): first create + (posts / 2) x plateau requests per created '
                     'post / (plateau duty cycle x plateau active rate) = %s.' % _fmt(
                         pc.get('impliedMedianLatenessMinutes'), 'min'))
    if not result.get('invocationResultsPresent', True):
        lines.append('')
        lines.append('The per-invocation results (`invocations/`) are not in this directory, which is downloaded from '
                     'an artifact. The worker figures below are empty for that reason; the mock\'s figures are complete.')
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
    lines.extend(evidence_lines(result))
    lines.extend(attempt_lines(result.get('attempts')))
    lines.extend(booking_lines(result))
    lines.extend(coordinator_failure_lines(result.get('coordinatorFailures')))
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
