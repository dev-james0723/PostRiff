"""The rate-policy tool only emits and accepts values the coordinator itself accepts (synthetic; no network)."""
import importlib.util
import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from postriff_phase2.discord.rate_limits import RateCoordinatorUnavailable, SafetyPolicy

spec = importlib.util.spec_from_file_location('discord_rate_policy', ROOT / 'scripts/discord_rate_policy.py')
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)

NOW = 1792700000  # a fixed instant; the tool is never given the wall clock in these tests
DAY = 86400


def levels(findings):
    return {code: level for level, code, _ in findings}


class Generated(unittest.TestCase):
    def test_the_default_policy_is_accepted_by_the_coordinator_parser(self):
        policy = tool.build(NOW)
        parsed = SafetyPolicy.parse(json.dumps(policy, separators=(',', ':')))
        self.assertEqual(parsed.app_capacity, 25)
        self.assertEqual(parsed.revision, policy['revision'])

    def test_it_fits_the_environment_variable_limit_and_has_no_extra_keys(self):
        text = json.dumps(tool.build(NOW), separators=(',', ':'))
        self.assertLessEqual(len(text), 4096)
        self.assertEqual(set(json.loads(text)), set(SafetyPolicy.__dataclass_fields__) | {'version'})

    def test_it_starts_a_little_before_now_and_never_exceeds_the_validity_limit(self):
        policy = tool.build(NOW, days=31)
        self.assertLess(policy['issued_at'], NOW)
        self.assertLessEqual(policy['expires_at'] - policy['issued_at'], 31 * DAY)
        SafetyPolicy.parse(policy)

    def test_a_longer_validity_is_refused_before_a_value_exists(self):
        for days in (0, -1, 32):
            with self.assertRaises(ValueError, msg=days):
                tool.build(NOW, days=days)

    def test_an_unknown_setting_is_refused(self):
        with self.assertRaises(ValueError):
            tool.build(NOW, burst_capacity=5)

    def test_the_defaults_stay_inside_both_documented_ceilings_even_back_to_back(self):
        summary, findings = tool.judge(tool.build(NOW), NOW)
        self.assertEqual(findings, [])
        self.assertLessEqual(summary['appRequestsPerSecond'] * 2, tool.DISCORD_GLOBAL_PER_SECOND)
        self.assertLessEqual(summary['invalidRequestsPer10Minutes'] * 2, tool.DISCORD_INVALID_PER_10_MINUTES)

    def test_the_renewal_date_is_seven_days_before_expiry(self):
        policy = tool.build(NOW)
        summary, _ = tool.judge(policy, NOW)
        self.assertEqual(summary['renewBy'], tool.iso(policy['expires_at'] - 7 * DAY))


class Judged(unittest.TestCase):
    def test_an_app_budget_above_eighty_percent_of_the_bot_limit_fails(self):
        _, findings = tool.judge(tool.build(NOW, app_capacity=41), NOW)
        self.assertEqual(levels(findings).get('app_ceiling'), 'FAIL')

    def test_a_long_window_cannot_hide_a_large_burst(self):
        _, findings = tool.judge(tool.build(NOW, app_capacity=400, app_window_seconds=10), NOW)
        self.assertEqual(levels(findings).get('app_ceiling'), 'FAIL')

    def test_an_invalid_budget_above_half_the_threshold_fails(self):
        _, findings = tool.judge(tool.build(NOW, invalid_capacity=5001), NOW)
        self.assertEqual(levels(findings).get('invalid_ceiling'), 'FAIL')
        _, findings = tool.judge(tool.build(NOW, invalid_capacity=3000, invalid_window_seconds=300), NOW)
        self.assertEqual(levels(findings).get('invalid_ceiling'), 'FAIL')

    def test_an_app_budget_at_the_ceiling_passes_with_a_warning_about_back_to_back_windows(self):
        _, findings = tool.judge(tool.build(NOW, app_capacity=40, invalid_capacity=5000), NOW)
        self.assertNotIn('FAIL', levels(findings).values())
        self.assertEqual(levels(findings).get('app_straddle'), 'WARN')

    def test_a_budget_too_small_for_the_lane_s_shards_warns_and_the_reviewed_one_does_not(self):
        from postriff_phase2.discord import lane
        self.assertEqual(tool.LANE_SHARDS, lane.SHARDS)
        for capacity, warned in ((10, True), (17, True), (18, False), (25, False)):
            _, findings = tool.judge(tool.build(NOW, app_capacity=capacity), NOW)
            self.assertEqual(levels(findings).get('lane_booking') == 'WARN', warned, capacity)
            self.assertNotIn('FAIL', levels(findings).values(), capacity)
        _, findings = tool.judge(tool.build(NOW, app_capacity=120, app_window_seconds=10), NOW)   # 12 a second: by the rate, not the count
        self.assertEqual(levels(findings).get('lane_booking'), 'WARN')

    def test_the_parser_rejection_wins_over_every_other_finding(self):
        bad = tool.build(NOW)
        bad['permit_ttl_seconds'] = 11
        with self.assertRaises(RateCoordinatorUnavailable):
            SafetyPolicy.parse(bad)
        _, findings = tool.judge(bad, NOW)
        self.assertEqual(levels(findings), {'rejected': 'FAIL'})

    def test_text_that_is_not_json_is_rejected_not_crashed_on(self):
        for raw in ('', 'not json', '[]', '{"version":1}', 'x' * 5000):
            _, findings = tool.judge(raw, NOW)
            self.assertEqual(levels(findings), {'rejected': 'FAIL'}, raw[:20])

    def test_an_expired_policy_fails_and_names_the_consequence(self):
        policy = tool.build(NOW, days=2)
        _, findings = tool.judge(policy, policy['expires_at'] + 1, require_days=0)
        self.assertEqual(levels(findings), {'expired': 'FAIL'})
        self.assertIn('fail closed', findings[0][2])

    def test_a_policy_that_has_not_started_fails(self):
        policy = tool.build(NOW)
        _, findings = tool.judge(policy, policy['issued_at'] - 1)
        self.assertEqual(levels(findings), {'not_yet_valid': 'FAIL'})

    def test_the_launch_needs_at_least_two_weeks_left_at_the_promotion_time(self):
        policy = tool.build(NOW, days=20)
        self.assertEqual(tool.judge(policy, NOW + 5 * DAY)[1], [])
        _, findings = tool.judge(policy, NOW + 7 * DAY)
        self.assertEqual(levels(findings), {'too_short': 'FAIL'})


class CommandLine(unittest.TestCase):
    def run_tool(self, *argv, stdin=''):
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err), patch('sys.stdin', StringIO(stdin)):
            code = tool.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_generate_prints_one_line_of_json_and_keeps_the_report_off_stdout(self):
        code, out, err = self.run_tool('generate', '--now', str(NOW))
        self.assertEqual(code, 0)
        self.assertEqual(len(out.strip().splitlines()), 1)
        SafetyPolicy.parse(out.strip())
        self.assertIn('renewBy', err)

    def test_generate_prints_no_value_when_a_ceiling_is_exceeded(self):
        code, out, err = self.run_tool('generate', '--now', str(NOW), '--app-capacity', '45')
        self.assertEqual(code, 1)
        self.assertEqual(out, '')
        self.assertIn('app_ceiling', err)

    def test_check_accepts_what_generate_prints_from_standard_input(self):
        _, line, _ = self.run_tool('generate', '--now', str(NOW))
        code, out, _ = self.run_tool('check', '-', '--at', str(NOW), stdin=line)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)['findings'], [])

    def test_check_exits_nonzero_for_an_expired_policy(self):
        _, line, _ = self.run_tool('generate', '--now', str(NOW), '--days', '3')
        code, out, _ = self.run_tool('check', '-', '--at', str(NOW + 4 * DAY), '--require-days', '0', stdin=line)
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)['findings'][0]['code'], 'expired')

    def test_iso_and_epoch_times_mean_the_same_instant(self):
        self.assertEqual(tool.parse_time('2026-10-22T20:00:00Z'), tool.parse_time('2026-10-22T20:00:00+00:00'))
        self.assertEqual(tool.parse_time('1792699200'), 1792699200.0)

    def test_the_tool_never_reads_the_environment(self):
        source = (ROOT / 'scripts/discord_rate_policy.py').read_text()
        for needle in ('os.environ', 'getenv', 'urlopen', 'socket', 'import requests', 'subprocess'):
            self.assertNotIn(needle, source, needle)


if __name__ == '__main__':
    unittest.main()
