"""Run the code every workspace read and command goes through, from one source tree, on one stored state; print JSON.

Used by tests/test_customer_impact_shared_paths.py: the same stored state (an ordinary workspace with a LinkedIn
channel, an approved post and no Discord data) is given to the live tree and to the candidate tree, and the outputs are
compared. No database, provider or network is involved.

  present      HostedPhase2Commands.present(state, revision), what GET /api/workspaces/<id> returns
  invalidate   whether Phase2Store.invalidate, which ends every hosted command and every worker claim, changes the state
  current      Phase2Store.current for every stored review and job
  channelState Phase2Store.channel_state for every channel
  approvals    a fresh review and approval of the same draft on a LinkedIn and on a Facebook Page channel
"""
import copy
import json
import os
import sys
from datetime import datetime, timezone

tree, path = sys.argv[1], sys.argv[2]
sys.path.insert(0, os.path.join(tree, 'src'))
from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2.hosted import HostedPhase2Commands  # noqa: E402

with open(path) as handle:
    stored = json.load(handle)
state, revision, principal = stored['state'], stored['revision'], stored['principal']
now = max(j['manifest']['timing']['timestamp'] for j in state['phase2']['jobs']) - 120
commands = HostedPhase2Commands(clock=lambda: now)
engine = commands.engine
out = {}

out['present'] = commands.present(copy.deepcopy(state), revision)
before = json.dumps(state, sort_keys=True)
work = copy.deepcopy(state)
engine.invalidate(work)
out['invalidateChanged'] = json.dumps(work, sort_keys=True) != before
out['jobStatesAfterInvalidate'] = [j['state'] for j in work['phase2']['jobs']]
out['current'] = {'reviews': [engine.current(state, r['manifest']) for r in state['phase2']['reviews']],
                  'jobs': [engine.current(state, j['manifest']) for j in state['phase2']['jobs']]}
out['channelState'] = {c['platform']: engine.channel_state(c) for c in state['phase2']['channels']}


def approve(platform):
    """Prepare and approve the same reviewed draft for one server-verified channel of this platform."""
    work = copy.deepcopy(state)
    for variant in work['variants']:
        variant['platform'] = platform
    channel = {'id': platform.lower() + '-impact-2', 'platform': platform, 'account': 'Impact Page', 'accountType': 'page' if platform == 'Facebook' else 'member',
               'scopes': ['pages_show_list', 'pages_manage_posts'] if platform == 'Facebook' else ['openid', 'profile', 'w_member_social'],
               'verifiedAt': now, 'expiresAt': now + 86400 * 30, 'capabilityVersion': 1, 'providerAccountId': 'impact-2', 'language': 'English'}
    result = {}
    try:
        commands.upsert_verified_channel(work, principal, channel)
        variant = work['variants'][-1]
        local = datetime.fromtimestamp((now // 60 + 10) * 60, timezone.utc).strftime('%Y-%m-%dT%H:%M')
        commands(work, principal, 'p2_review', {'variantId': variant['id'], 'channelId': channel['id'], 'localTime': local,
                                                'timeZone': 'UTC', 'acknowledgedWarnings': variant['warnings']})
        review = work['phase2']['reviews'][-1]
        result['review'] = review['status']
        result['reviewCurrent'] = engine.current(work, review['manifest'])
        commands(work, principal, 'p2_approve', {'reviewId': review['id'], 'digest': review['digest'], 'confirmed': True})
        job = work['phase2']['jobs'][-1]
        result.update(job=job['state'], jobCurrent=engine.current(work, job['manifest']))
    except AlphaError as error:
        result['refused'] = str(error)
        if 'review' in result:
            # A post approved on the other build: the same manifest, as a scheduled job, then one ordinary invalidate().
            review = work['phase2']['reviews'][-1]
            work['phase2']['jobs'].append({'id': 'job-approved-elsewhere', 'manifest': copy.deepcopy(review['manifest']),
                                           'approvalDigest': review['digest'], 'approvedAt': now, 'approvedBy': principal,
                                           'state': 'scheduled', 'events': [], 'attempts': [], 'checks': 0, 'leaseOwner': None,
                                           'leaseUntil': 0, 'nextAt': now + 600, 'cancelRequested': False})
    mine = [job for job in work['phase2']['jobs'] if job['manifest']['platform'] == platform and job['manifest']['channelId'] == channel['id']]
    if mine:
        engine.invalidate(work)
        result['jobAfterInvalidate'] = mine[-1]['state']
    return result


out['approvals'] = {platform: approve(platform) for platform in ('LinkedIn', 'Facebook')}
print(json.dumps(out, sort_keys=True, default=str))
