"""H-07 on-call policy (src/rafii_control/oncall/policy.py, docs/ops/h07-oncall-policy.json): validation, duty hours in
America/New_York across daylight saving, rosters with overnight shifts, and the rule-to-priority table.

Pure: no database, network, clock or credential.
"""
import copy
import json
import re
import unittest
from datetime import datetime, timezone
from pathlib import Path

from rafii_control.oncall import ENV_AUTO_HOLD, ENV_ENABLED, enabled
from rafii_control.oncall import policy as P

ROOT = Path(__file__).resolve().parents[1]
RAW = json.loads((ROOT / 'docs/ops/h07-oncall-policy.json').read_text())


def utc(text):
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp()


def roster(**people):
    full = {name: {'push': 'ref-%s-push' % name, 'email': 'ref-%s-mail' % name, 'phone': 'ref-%s-phone' % name} for name in ('ana', 'ben', 'cy', 'dee')}
    full.update(people)
    return {'shifts': [{'days': ['mon', 'tue', 'wed', 'thu', 'fri'], 'start': '09:00', 'end': '21:00', 'primary': 'ana', 'backup': 'ben'},
                       {'days': ['sat', 'sun'], 'start': '09:00', 'end': '21:00', 'primary': 'ben', 'backup': 'ana'},
                       {'days': 'daily', 'start': '21:00', 'end': '09:00', 'primary': 'cy', 'backup': 'dee'}],
            'people': full}


class Flags(unittest.TestCase):
    def test_flags_are_off_unless_exactly_true(self):
        for value in (None, '', 'TRUE', 'True', '1', 'yes', ' true'):
            with self.subTest(value=value):
                values = {} if value is None else {ENV_ENABLED: value, ENV_AUTO_HOLD: value}
                self.assertFalse(enabled(values))
                self.assertFalse(enabled(values, ENV_AUTO_HOLD))
        self.assertTrue(enabled({ENV_ENABLED: 'true'}))
        self.assertFalse(enabled({ENV_ENABLED: 'true'}, ENV_AUTO_HOLD))

    def test_nothing_in_the_application_imports_the_engine(self):
        hits = [str(path.relative_to(ROOT)) for path in (ROOT / 'src').rglob('*.py')
                if 'oncall' not in path.parts and re.search(r'\boncall\b', path.read_text(errors='ignore'))]
        self.assertEqual(hits, [])


class Validation(unittest.TestCase):
    def test_the_repository_policy_loads(self):
        policy = P.load()
        self.assertEqual((policy['timeZone'], policy['dutyHours']['start'], policy['dutyHours']['end']), ('America/New_York', 540, 1380))
        self.assertEqual([s['after'] for s in policy['escalation']['P0']], [0, 300, 600])
        self.assertEqual([(s['to'], s['channels']) for s in policy['escalation']['P0']],
                         [('primary', ['push', 'email']), ('primary', ['phone']), ('backup', ['push', 'email', 'phone'])])
        self.assertEqual([(s['after'], s['to'], s['hours']) for s in policy['escalation']['P1']], [(0, 'primary', 'duty'), (900, 'backup', 'duty')])
        self.assertEqual(policy['escalation']['P2'][0]['channels'], ['email'])
        self.assertNotIn('phone', policy['escalation']['P1'][0]['channels'] + policy['escalation']['P2'][0]['channels'])

    def test_the_shipped_roster_is_a_placeholder_that_cannot_carry_p0(self):
        problems = P.roster_problems(P.load())
        self.assertEqual(problems, sorted('%s_without_%s' % (r, c) for r in ('primary', 'backup') for c in ('push', 'email', 'phone')))

    def test_malformed_policies_are_refused(self):
        def broken(mutate):
            raw = copy.deepcopy(RAW)
            mutate(raw)
            return raw
        cases = {
            'version': lambda r: r.update(version=2),
            'zone': lambda r: r.update(timeZone='Mars/Olympus'),
            'empty duty': lambda r: r['dutyHours'].update(start='09:00', end='09:00'),
            'bad time': lambda r: r['dutyHours'].update(start='9:00'),
            'holiday': lambda r: r['dutyHours'].update(holidays=['25/12/2026']),
            'missing chain': lambda r: r['escalation'].pop('P2'),
            'negative after': lambda r: r['escalation']['P0'][0].update(after=-1),
            'order': lambda r: r['escalation']['P0'].reverse(),
            'channel': lambda r: r['escalation']['P0'][0].update(channels=['sms']),
            'target': lambda r: r['escalation']['P0'][0].update(to='everyone'),
            'repeat too short': lambda r: r['repeat']['P0'].update(periodSeconds=600),
            'storm zero': lambda r: r['suppression']['storm']['limits'].update(phone=0),
            'priority': lambda r: r['priorities'].append({'rule': 'X_Y', 'severity': 'page', 'priority': 'P9'}),
            'rule id': lambda r: r['priorities'].append({'rule': 'lower', 'severity': 'page', 'priority': 'P1'}),
            'person channel': lambda r: r['roster']['people']['PRIMARY'].update(sms='x'),
            'empty shift': lambda r: r['roster']['shifts'][0].update(start='08:00', end='08:00'),
            'maintenance': lambda r: r['suppression']['maintenance'].append({'start': 10, 'end': 5}),
            'clear evaluations': lambda r: r['suppression'].update(resolveAfterClearEvaluations=0),
        }
        for name, mutate in cases.items():
            with self.subTest(case=name), self.assertRaises(P.PolicyError):
                P.validate(broken(mutate))


class DutyHours(unittest.TestCase):
    policy = P.load()

    def test_duty_starts_at_nine_new_york_time_on_both_sides_of_spring_forward(self):
        # 2026-03-08 02:00 EST becomes 03:00 EDT: nine o'clock is 14:00Z the day before and 13:00Z that day.
        self.assertTrue(P.in_duty(utc('2026-03-07T14:00:00'), self.policy))
        self.assertFalse(P.in_duty(utc('2026-03-07T13:59:59'), self.policy))
        self.assertTrue(P.in_duty(utc('2026-03-08T13:00:00'), self.policy))
        self.assertFalse(P.in_duty(utc('2026-03-08T12:59:59'), self.policy))

    def test_duty_starts_at_nine_new_york_time_on_both_sides_of_fall_back(self):
        # 2026-11-01 02:00 EDT becomes 01:00 EST: nine o'clock is 13:00Z on Oct 31 and 14:00Z on Nov 1.
        self.assertTrue(P.in_duty(utc('2026-10-31T13:00:00'), self.policy))
        self.assertFalse(P.in_duty(utc('2026-11-01T13:30:00'), self.policy))
        self.assertTrue(P.in_duty(utc('2026-11-01T14:00:00'), self.policy))

    def test_duty_ends_at_twenty_three_hundred(self):
        self.assertTrue(P.in_duty(utc('2026-07-02T02:59:59'), self.policy))   # 22:59:59 EDT
        self.assertFalse(P.in_duty(utc('2026-07-02T03:00:00'), self.policy))  # 23:00 EDT
        self.assertTrue(P.in_duty(utc('2026-12-02T03:59:59'), self.policy))   # 22:59:59 EST
        self.assertFalse(P.in_duty(utc('2026-12-02T04:00:00'), self.policy))

    def test_weekends_are_duty_days_and_holidays_are_not(self):
        self.assertTrue(P.in_duty(utc('2026-10-24T15:00:00'), self.policy))   # Saturday 11:00 EDT
        raw = copy.deepcopy(RAW)
        raw['dutyHours']['holidays'] = ['2026-12-25']
        policy = P.validate(raw)
        self.assertFalse(P.in_duty(utc('2026-12-25T15:00:00'), policy))
        self.assertEqual(P.next_duty_start(utc('2026-12-25T15:00:00'), policy), utc('2026-12-26T14:00:00'))

    def test_next_duty_start_across_the_transitions(self):
        self.assertEqual(P.next_duty_start(utc('2026-03-08T05:00:00'), self.policy), utc('2026-03-08T13:00:00'))
        self.assertEqual(P.next_duty_start(utc('2026-11-01T05:00:00'), self.policy), utc('2026-11-01T14:00:00'))
        self.assertEqual(P.next_duty_start(utc('2026-07-02T03:30:00'), self.policy), utc('2026-07-02T13:00:00'))
        inside = utc('2026-07-01T15:00:00')
        self.assertEqual(P.next_duty_start(inside, self.policy), inside)

    def test_duty_seconds_count_only_wall_clock_duty_time(self):
        # 22:00 EST Mar 7 to 10:00 EDT Mar 8: one hour before 23:00 and one after 09:00, across the lost hour.
        self.assertEqual(P.duty_seconds(utc('2026-03-08T03:00:00'), utc('2026-03-08T14:00:00'), self.policy), 7200)
        # 22:00 EDT Oct 31 to 10:00 EST Nov 1, across the repeated hour.
        self.assertEqual(P.duty_seconds(utc('2026-11-01T02:00:00'), utc('2026-11-01T15:00:00'), self.policy), 7200)
        self.assertEqual(P.duty_seconds(utc('2026-07-01T14:00:00'), utc('2026-07-01T13:00:00'), self.policy), 0)
        self.assertEqual(P.duty_seconds(utc('2026-07-01T13:00:00'), utc('2026-07-02T13:00:00'), self.policy), 14 * 3600)

    def test_a_wrapping_duty_window(self):
        raw = copy.deepcopy(RAW)
        raw['dutyHours'].update(start='20:00', end='02:00')
        policy = P.validate(raw)
        self.assertTrue(P.in_duty(utc('2026-07-02T05:30:00'), policy))    # 01:30 EDT, window that began the evening before
        self.assertFalse(P.in_duty(utc('2026-07-02T06:00:00'), policy))   # 02:00 EDT
        self.assertEqual(P.duty_seconds(utc('2026-07-01T00:00:00'), utc('2026-07-02T00:00:00'), policy), 6 * 3600)


class Roster(unittest.TestCase):
    policy = P.load()

    def test_overnight_and_weekend_shifts(self):
        named = P.validate_roster(roster())
        cases = [('2026-10-26T13:00:00', ('ana', 'ben')),    # Monday 09:00 EDT
                 ('2026-10-26T12:59:00', ('cy', 'dee')),     # Monday 08:59: Sunday night's shift, wrapping
                 ('2026-10-27T01:00:00', ('cy', 'dee')),     # Monday 21:00
                 ('2026-10-24T16:00:00', ('ben', 'ana')),    # Saturday noon
                 ('2026-11-01T06:30:00', ('cy', 'dee')),     # Sunday 01:30 EST, the repeated hour
                 ('2026-03-08T07:30:00', ('cy', 'dee'))]     # Sunday 03:30 EDT, after the lost hour
        for moment, expected in cases:
            with self.subTest(moment=moment):
                self.assertEqual(P.on_call(utc(moment), self.policy, named), expected)
        self.assertEqual(P.roster_problems(self.policy, named), [])

    def test_roster_problems_name_every_gap(self):
        gap = roster()
        gap['shifts'] = gap['shifts'][:2]
        self.assertIn('coverage_gap', P.roster_problems(self.policy, P.validate_roster(gap)))
        weekday_only = roster()
        weekday_only['shifts'][1]['backup'] = None
        self.assertEqual(P.roster_problems(self.policy, P.validate_roster(weekday_only)), ['no_backup'])
        same = roster()
        same['shifts'][2]['backup'] = 'cy'
        self.assertEqual(P.roster_problems(self.policy, P.validate_roster(same)), ['primary_is_backup'])
        unknown = roster()
        unknown['shifts'][0]['primary'] = 'zed'
        self.assertEqual(P.roster_problems(self.policy, P.validate_roster(unknown)), ['unknown_person'])
        no_phone = roster(dee={'push': 'ref-d-push', 'email': 'ref-d-mail'})
        self.assertEqual(P.roster_problems(self.policy, P.validate_roster(no_phone)), ['backup_without_phone'])


class Priorities(unittest.TestCase):
    policy = P.load()

    def test_every_evaluator_rule_and_severity_has_a_row(self):
        source = (ROOT / 'scripts/discord_ops_check.py').read_text()
        calls = re.findall(r"_alert\('([A-Z0-9_]+)', '[A-Z_]+', ([^,]+(?:,|$))", source)
        emitted = {}
        for rule, severity in calls:
            literal = re.fullmatch(r"'(page|warn|info)',", severity.strip())
            emitted.setdefault(rule, set()).update({literal.group(1)} if literal else {'page', 'warn'})
        for rule in re.findall(r"'([A-Z][A-Z0-9_]+_GROWTH)'", source):    # raised in a loop, always 'warn'
            emitted.setdefault(rule, set()).add('warn')
        self.assertEqual(len(emitted), 40)
        rows = {(row['rule'], row['severity']) for row in self.policy['priorities']}
        missing = sorted((rule, severity) for rule, severities in emitted.items() for severity in severities if (rule, severity) not in rows)
        self.assertEqual(missing, [])

    def test_the_mapping_examples(self):
        def alert(rule, severity, **evidence):
            return {'id': rule, 'severity': severity, 'evidence': evidence}
        cases = [(alert('CROSS_TENANT_PROBE_FAILED', 'page', failed=1), 'P0'),
                 (alert('CROSS_TENANT_PROBING', 'warn'), 'P1'),
                 (alert('SILENT_HALT_NO_PROGRESS', 'page'), 'P0'),
                 (alert('SILENT_HALT_NO_PROGRESS', 'warn', operatorHold=True), 'P2'),
                 (alert('CONFIG_GATE', 'page', mode='open', workspaces=0), 'P0'),
                 (alert('CONFIG_GATE', 'page', mode='list', workspaces=9), 'P1'),
                 (alert('BACKLOG_LAG', 'warn'), 'P2'),
                 (alert('SOMETHING_NEW', 'page'), 'P1'),
                 (alert('SOMETHING_NEW', 'warn'), 'P2'),
                 (alert('SOMETHING_NEW', 'info'), None),
                 (alert('ONCALL_DELIVERY_FAILED', 'page'), 'P0'),
                 (alert('ONCALL_ENGINE_GAP', 'warn'), 'P1')]
        for given, expected in cases:
            with self.subTest(rule=given['id'], severity=given['severity']):
                self.assertEqual(P.priority_for(given, self.policy), expected)

    def test_the_policy_map_and_the_json_agree_on_p0(self):
        text = (ROOT / 'docs/ops/H07-POLICY-MAP.md').read_text()
        section = text.split('## 6.')[1]
        page_p0 = {m.group(1) for m in re.finditer(r'^\| ([A-Z_0-9]+) \|[^|]*\| \*\*P0\*\* \|', section, re.M)}
        json_p0 = {row['rule'] for row in self.policy['priorities'] if row['priority'] == 'P0' and row['severity'] == 'page'
                   and not row['evidence'] and not row['rule'].startswith('ONCALL_')}
        self.assertEqual(page_p0, json_p0)
        self.assertIn('CONFIG_GATE', {row['rule'] for row in self.policy['priorities'] if row['priority'] == 'P0'})


if __name__ == '__main__':
    unittest.main()
