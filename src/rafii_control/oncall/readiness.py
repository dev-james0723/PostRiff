"""The H-07 status computed from its inputs (docs/ops/H07-EVIDENCE.md).

It checks the shape of its inputs, not their truth. The evidence file, the roster and the night-cover answer are handed
to it, so hand-written entries, an invented roster and --night-cover yes print VERIFIED (second review, N-3). A VERIFIED
result counts only after a person has traced every entry to its receipt: the owner's rule is "no paper pass". Design
for inputs that cannot be written by hand (not built): each entry names the oncall_events ids of its real deliveries and
acknowledgement, which this reader looks up and checks, and night cover and the roster come from a committed owner
declaration, not from command-line flags.


- BLOCKED: there is no real 24/7 P0 cover: the owner has not declared that a named Primary and Backup cover nights,
  weekends and holidays, or the roster cannot carry P0 (a gap, a missing Primary or Backup, a person without push,
  e-mail or phone). The result lists the executable alternatives.
- NOT_VERIFIED: cover is declared and the roster is valid, but at least one requirement lacks a passing test on real
  people and real destinations.
- VERIFIED: every requirement has a passing real test. Isolated evidence (fake providers, disposable databases) never
  counts: it proves the logic, not delivery.

    python -m rafii_control.oncall.readiness [--evidence FILE] [--night-cover yes|no] [--roster FILE]
    exit 0 VERIFIED, 1 NOT_VERIFIED, 2 BLOCKED
"""
import argparse
import json
import sys
from pathlib import Path

from .policy import load, roster_problems, validate_roster

DEFAULT_EVIDENCE = Path(__file__).resolve().parents[3] / 'docs' / 'ops' / 'h07-real-evidence.json'
REQUIREMENTS = (
    ('roster', 'A named Primary and Backup cover every minute of the week, and each received a test page'),
    ('routing_p0', 'A real P0 reached the Primary at once by push and e-mail'),
    ('routing_p1', 'A real P1 in duty hours reached the Primary by push and e-mail; outside them, e-mail at once and push at 09:00'),
    ('routing_p2', 'A real P2 reached the Primary by e-mail in duty hours, and nothing else'),
    ('push_delivery', 'A push was received on the phone of each of the Primary and the Backup'),
    ('email_delivery', 'An e-mail was received by each of the Primary and the Backup'),
    ('phone_delivery', 'A phone call rang and was answered by each of the Primary and the Backup'),
    ('acknowledgement', 'An acknowledgement from push, e-mail and phone stopped the chain and was recorded'),
    ('escalation_5min', 'An unacknowledged P0 rang the Primary at 5 minutes (not before)'),
    ('escalation_10min_backup', 'An unacknowledged P0 reached the Backup by push, e-mail and phone at 10 minutes'),
    ('dedupe', 'A repeating alert produced one incident and one notification per step and channel'),
    ('suppression', 'A maintenance window and an inhibited symptom did not page; a security alert in a window did'),
    ('audit_trail', 'The incident timeline shows every step, delivery, acknowledgement and resolution with times'),
    ('end_to_end', 'One night-time P0 drill, announced, from the evaluator to the Backup call and back to resolution'),
)
ALTERNATIVES = (
    'Name a Primary and a Backup for nights, weekends and holidays (for example a Backup in another time zone), give each a '
    'push subscription, an e-mail and a verified phone, declare night cover, then run the real tests in H07-EVIDENCE.md.',
    'Option B: buy a paging service with schedules and phone calls (paid; the owner chooses the vendor) and point the '
    'evaluator at it through the vendor-neutral adapter, plus its heartbeat monitor.',
    'Option D: enable the automatic hold (RAFII_ONCALL_AUTO_HOLD_ENABLED) for the dangerous classes so an unattended P0 '
    'stops Discord sending until a person lifts it. It limits harm; it does not make H-07 VERIFIED.',
    'Open the public launch with a smaller server cap and accept the night risk for a limited audience, or delay the '
    'opening until cover exists. Business decisions for the owner.',
)


def _real_pass(entry):
    return (isinstance(entry, dict) and entry.get('kind') == 'real' and entry.get('result') == 'pass'
            and entry.get('destination') == 'real' and entry.get('people') == 'real' and bool(entry.get('at'))
            and bool(entry.get('reference')))


def status(policy, evidence=(), *, night_cover=None, roster=None):
    roster = validate_roster(roster) if roster is not None else policy['roster']
    problems = roster_problems(policy, roster)
    passed = {entry['requirement'] for entry in evidence if _real_pass(entry) and isinstance(entry.get('requirement'), str)}
    missing = [name for name, _ in REQUIREMENTS if name not in passed]
    isolated = sorted({e.get('requirement') for e in evidence if isinstance(e, dict) and e.get('kind') == 'isolated'})
    reasons = []
    if night_cover is not True:
        reasons.append('night_cover_not_declared' if night_cover is None else 'no_night_cover')
    reasons.extend('roster:' + problem for problem in problems)
    if reasons:
        return {'status': 'BLOCKED', 'reasons': reasons, 'missingRealTests': missing, 'isolatedOnly': isolated,
                'alternatives': list(ALTERNATIVES)}
    if missing:
        return {'status': 'NOT_VERIFIED', 'reasons': ['real_test_missing:' + name for name in missing], 'missingRealTests': missing,
                'isolatedOnly': isolated}
    return {'status': 'VERIFIED', 'reasons': [], 'missingRealTests': [], 'isolatedOnly': isolated}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--evidence', default=str(DEFAULT_EVIDENCE))
    parser.add_argument('--night-cover', choices=('yes', 'no'))
    parser.add_argument('--roster')
    args = parser.parse_args(argv)
    evidence_path = Path(args.evidence)
    evidence = json.loads(evidence_path.read_text()).get('evidence', []) if evidence_path.is_file() else []
    roster = json.loads(Path(args.roster).read_text()) if args.roster else None
    cover = {'yes': True, 'no': False}.get(args.night_cover)
    report = status(load(), evidence, night_cover=cover, roster=roster)
    print(json.dumps(report, indent=2))
    return {'VERIFIED': 0, 'NOT_VERIFIED': 1, 'BLOCKED': 2}[report['status']]


if __name__ == '__main__':
    sys.exit(main())
