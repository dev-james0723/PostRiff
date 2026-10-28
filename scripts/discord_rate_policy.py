#!/usr/bin/env python3
"""Generate and check the reviewed Discord rate policy (POSTRIFF_DISCORD_RATE_POLICY).

The policy is operator-reviewed JSON, not a secret. This tool reads no environment variable, no deployment and no
database: it prints a candidate and judges a candidate with the coordinator's own SafetyPolicy.parse, so a value that
passes here is a value the coordinator accepts. Once a policy expires every Discord request fails closed, so a policy
has a renewal date and applying one needs a new deployment (environment changes reach new deployments only).
"""
import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from postriff_phase2.discord.rate_limits import RateCoordinatorUnavailable, SafetyPolicy  # noqa: E402

# Figures published in Discord's rate-limit documentation; re-read them whenever a policy is renewed.
DISCORD_GLOBAL_PER_SECOND = 50
DISCORD_INVALID_PER_10_MINUTES = 10000
APP_SHARE_CEILING = 0.8
INVALID_SHARE_CEILING = 0.5
RENEW_LEAD_DAYS = 7
# The lane (discord/lane.py SHARDS, pinned by a test) runs this many loops, and its requests are booked a place in line, which
# holds about (budget - 1) / 1.1 of them. Measured with 12 loops: booking makes 34 to 66 percent more posts than polling from a
# budget of 12 a second up and fewer below it (docs/w02/OPEN-QUESTIONS.md, Q19). Under 1.5 a shard is a warning.
LANE_SHARDS = 12
LANE_MIN_RATE = 1.5 * LANE_SHARDS
MAX_VALIDITY_DAYS = 31
CLOCK_SKEW_SECONDS = 60

# Fixed windows can admit two adjacent windows back to back, so the defaults keep 2x inside the documented figures.
DEFAULTS = {
    'egress_scope': 'vercel-shared-egress',
    'app_capacity': 25, 'app_window_seconds': 1, 'unknown_window_seconds': 1,
    'invalid_capacity': 2000, 'invalid_window_seconds': 600,
    'failure_threshold': 3, 'circuit_seconds': 30, 'permit_ttl_seconds': 5, 'read_attempts': 3,
}


KINDS = {'egress_scope': str, 'app_capacity': int, 'invalid_capacity': int, 'failure_threshold': int, 'read_attempts': int}


def number(text):
    value = float(text)
    return int(value) if value.is_integer() else value


def parse_time(value):
    if value is None or value == 'now':
        return datetime.now(timezone.utc).timestamp()
    try:
        return float(value)
    except ValueError:
        moment = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return (moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)).timestamp()


def iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def build(now, *, days=30, revision=None, **overrides):
    """Candidate policy valid from just before `now` for `days` days (the coordinator accepts at most 31)."""
    if not 0 < days <= MAX_VALIDITY_DAYS:
        raise ValueError('days must be between 0 and %d' % MAX_VALIDITY_DAYS)
    unknown = set(overrides) - set(DEFAULTS)
    if unknown:
        raise ValueError('unknown setting: ' + ', '.join(sorted(unknown)))
    issued = int(now) - CLOCK_SKEW_SECONDS
    values = {**DEFAULTS, **overrides}
    return {'version': 1, 'revision': revision or 'rafii-w1-' + datetime.fromtimestamp(now, timezone.utc).strftime('%Y%m%d'),
            'issued_at': issued, 'expires_at': issued + int(days * 86400), **values}


def judge(raw, at, require_days=14):
    """Return (policy summary, findings). A FAIL means the policy must not be applied."""
    findings = []
    text = raw if isinstance(raw, str) else json.dumps(raw)
    try:
        SafetyPolicy.parse(text)
    except RateCoordinatorUnavailable:
        return {}, [('FAIL', 'rejected', 'SafetyPolicy.parse rejects this value; the coordinator would fail closed')]
    policy = json.loads(text)
    app_rate = policy['app_capacity'] / policy['app_window_seconds']
    invalid_rate = policy['invalid_capacity'] / policy['invalid_window_seconds']
    app_ceiling = DISCORD_GLOBAL_PER_SECOND * APP_SHARE_CEILING
    invalid_ceiling = DISCORD_INVALID_PER_10_MINUTES * INVALID_SHARE_CEILING
    if app_rate > app_ceiling or policy['app_capacity'] > app_ceiling:
        findings.append(('FAIL', 'app_ceiling', 'app budget %.1f/s exceeds %.0f%% of the %d/s bot limit'
                         % (app_rate, APP_SHARE_CEILING * 100, DISCORD_GLOBAL_PER_SECOND)))
    elif policy['app_capacity'] * 2 > DISCORD_GLOBAL_PER_SECOND:
        findings.append(('WARN', 'app_straddle', 'two adjacent windows can briefly admit twice the app budget, above the bot limit'))
    if app_rate < LANE_MIN_RATE:
        findings.append(('WARN', 'lane_booking', 'app budget %.1f/s is under %.0f/s (1.5 for each of the lane\'s %d shards): the lane\'s '
                         'requests are booked a place in line, which holds about (budget - 1) / 1.1 loops; with fewer, loops are '
                         'refused at the booked horizon and the lane makes fewer posts than polling would (OPEN-QUESTIONS Q19)'
                         % (app_rate, LANE_MIN_RATE, LANE_SHARDS)))
    if invalid_rate * 600 > invalid_ceiling or policy['invalid_capacity'] > invalid_ceiling:
        findings.append(('FAIL', 'invalid_ceiling', 'invalid budget exceeds %.0f%% of %d per 10 minutes'
                         % (INVALID_SHARE_CEILING * 100, DISCORD_INVALID_PER_10_MINUTES)))
    remaining = (policy['expires_at'] - at) / 86400
    if at < policy['issued_at']:
        findings.append(('FAIL', 'not_yet_valid', 'policy starts at %s' % iso(policy['issued_at'])))
    elif at >= policy['expires_at']:
        findings.append(('FAIL', 'expired', 'policy expired at %s; Discord requests fail closed' % iso(policy['expires_at'])))
    elif remaining < require_days:
        findings.append(('FAIL', 'too_short', '%.1f days left, %.0f required' % (remaining, require_days)))
    summary = {
        'revision': policy['revision'], 'egressScope': policy['egress_scope'],
        'issuedAt': iso(policy['issued_at']), 'expiresAt': iso(policy['expires_at']),
        'renewBy': iso(policy['expires_at'] - RENEW_LEAD_DAYS * 86400), 'daysRemaining': round(remaining, 1),
        'appRequestsPerSecond': round(app_rate, 2), 'invalidRequestsPer10Minutes': round(invalid_rate * 600),
    }
    return summary, findings


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest='command', required=True)
    make = commands.add_parser('generate', help='print a candidate policy as one line of JSON')
    make.add_argument('--now', help='epoch seconds or ISO time (default: the current time)')
    make.add_argument('--days', type=float, default=30)
    make.add_argument('--revision')
    for name, default in DEFAULTS.items():
        make.add_argument('--' + name.replace('_', '-'), type=KINDS.get(name, number), default=default)
    check = commands.add_parser('check', help='judge a policy given as a file or - for standard input')
    check.add_argument('source')
    check.add_argument('--at', help='epoch seconds or ISO time the policy must be valid at (default: the current time)')
    check.add_argument('--require-days', type=float, default=14, help='minimum validity left at --at')
    args = parser.parse_args(argv)
    if args.command == 'generate':
        now = parse_time(args.now)
        overrides = {name: getattr(args, name) for name in DEFAULTS}
        policy = build(now, days=args.days, revision=args.revision, **overrides)
        summary, findings = judge(policy, now, require_days=0)
        if not any(level == 'FAIL' for level, _, _ in findings):
            print(json.dumps(policy, separators=(',', ':')))
    else:
        raw = sys.stdin.read() if args.source == '-' else Path(args.source).read_text()
        summary, findings = judge(raw.strip(), parse_time(args.at), require_days=args.require_days)
    report = {'summary': summary, 'findings': [{'level': a, 'code': b, 'detail': c} for a, b, c in findings]}
    print(json.dumps(report, indent=2), file=sys.stderr if args.command == 'generate' else sys.stdout)
    return 1 if any(level == 'FAIL' for level, _, _ in findings) else 0


if __name__ == '__main__':
    sys.exit(main())
