"""H-07 cross-tenant denial signal, offline: the membership gate's one log line, its cap, its fields, its silence on success.

The gate is the real PostgresWorkspaceRepository.transaction over an in-memory connection; the signal's own tables run
on an injected clock. The real-PostgreSQL drill (two tenants, the real query) is in test_discord_ops_drills_postgres.py.
"""
import json
import logging
import re
import unittest
from unittest.mock import patch

from postriff_alpha.domain import AlphaError
from postriff_phase2 import security_signals
from postriff_phase2.hosted import PostgresWorkspaceRepository

MEMBER = '5a9e1c3b-7d2f-4e6a-8b0c-1d2e3f4a5b6c'
FOREIGN = '0f1e2d3c-4b5a-4968-8776-655443322110'


class Captured:
    def __init__(self):
        self.lines = []
        self.handler = logging.Handler()
        self.handler.emit = lambda record: self.lines.append((record.levelno, record.getMessage()))

    def __enter__(self):
        logging.getLogger('postriff.request').addHandler(self.handler)
        return self

    def __exit__(self, *exc):
        logging.getLogger('postriff.request').removeHandler(self.handler)

    def events(self):
        return [json.loads(message) for _level, message in self.lines if security_signals.EVENT in message]


class Memory:
    """One connection: the membership SELECT answers `row`."""
    def __init__(self, row):
        self.row, self.executed = row, []

    def __call__(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return self

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        return self.row


def repository(row, member=MEMBER):
    return PostgresWorkspaceRepository(Memory(row), verify_session=lambda token: member)


class Clock:
    def __init__(self, at=1_800_000_000.0):
        self.at = at

    def __call__(self):
        return self.at


class TheGate(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.signal = security_signals.DenialSignal(clock=self.clock)
        patcher = patch.object(security_signals, 'SIGNAL', self.signal)
        patcher.start()
        self.addCleanup(patcher.stop)

    def deny(self, repo=None):
        with self.assertRaises(AlphaError) as raised:
            with (repo or repository(None)).transaction('synthetic-session', FOREIGN):
                self.fail('a foreign workspace must not be entered')
        return raised.exception

    def test_a_denial_logs_one_line_and_the_403_is_unchanged(self):
        with Captured() as captured:
            error = self.deny()
        self.assertEqual((error.status, str(error), error.code), (403, 'Workspace unavailable.', 'permission_denied'))
        events = captured.events()
        self.assertEqual(len(events), 1)
        self.assertEqual(set(events[0]), {'event', 'routeFamily', 'status', 'actorKey', 'suppressed'})
        self.assertEqual(events[0]['status'], 403)
        self.assertEqual(events[0]['suppressed'], 0)
        self.assertRegex(events[0]['actorKey'], r'^[0-9a-f]{10}$')
        self.assertEqual(events[0]['actorKey'], security_signals.actor_key(MEMBER))
        self.assertEqual([level for level, message in captured.lines if security_signals.EVENT in message], [logging.WARNING])

    def test_no_id_body_or_path_reaches_the_line(self):
        with Captured() as captured:
            self.deny()
        text = ' '.join(message for _level, message in captured.lines)
        for value in (MEMBER, FOREIGN, MEMBER.replace('-', ''), 'synthetic-session', '/api/'):
            self.assertNotIn(value, text)
        self.assertIsNone(re.search(r'[0-9a-f]{8}-[0-9a-f]{4}', text))
        self.assertFalse(MEMBER.replace('-', '').startswith(security_signals.actor_key(MEMBER)))

    def test_a_member_entering_their_own_workspace_logs_nothing(self):
        row = (3, {'phase2': {}}, 'owner', True, True, True, True)
        with Captured() as captured, patch('postriff_phase2.agent_runtime_v2.authz.recheck_transaction'):
            with repository(row).transaction('synthetic-session', FOREIGN) as (_cur, found, principal):
                self.assertEqual((found[0], principal), (3, MEMBER))
        self.assertEqual(captured.events(), [])
        self.assertEqual(self.signal.summary()['deniedTotal'], 0)

    def test_one_line_per_actor_and_family_a_minute_with_the_rest_counted(self):
        with Captured() as captured:
            for _ in range(5):
                self.deny()
            self.assertEqual(len(captured.events()), 1)
            self.clock.at += 60
            self.deny()
        events = captured.events()
        self.assertEqual([e['suppressed'] for e in events], [0, 4])
        other = repository(None, member='9b8a7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d')
        with Captured() as captured:
            self.deny(other)
        self.assertEqual(len(captured.events()), 1, 'another member has their own line')
        self.assertEqual(self.signal.summary()['deniedTotal'], 7)

    def test_the_signal_never_raises_and_never_changes_the_denial(self):
        with patch.object(self.signal, 'denied', side_effect=RuntimeError('logging broke')):
            error = self.deny()
            self.assertFalse(security_signals.cross_tenant_denied(MEMBER))
        self.assertEqual(error.status, 403)
        with patch.object(security_signals, 'caller_family', side_effect=ValueError('no frames')):
            self.assertEqual(self.deny().status, 403)

    def test_the_route_family_is_the_calling_subsystem(self):
        repo = repository(None)
        for module, family in (('postriff_phase2.discord.oauth', 'discord'), ('postriff_phase2.oauth', 'connections'),
                               ('postriff_phase2.hosted_app', 'workspace'), ('postriff_phase2.ideas', 'workspace'),
                               ('some_test_module', 'other')):
            with self.subTest(module=module), Captured() as captured:
                namespace = {'__name__': module, 'repo': repo, 'FOREIGN': FOREIGN}
                exec('def enter():\n    with repo.transaction("synthetic-session", FOREIGN):\n        pass\n', namespace)
                with self.assertRaises(AlphaError):
                    namespace['enter']()
                self.assertEqual([e['routeFamily'] for e in captured.events()], [family])
            self.clock.at += 60

    def test_a_discord_context_manager_around_the_gate_is_still_discord(self):
        """DiscordConnections.local wraps repository.transaction in its own context manager."""
        repo = repository(None)
        namespace = {'__name__': 'postriff_phase2.discord.oauth', 'repo': repo, 'FOREIGN': FOREIGN}
        exec('from contextlib import contextmanager\n'
             '@contextmanager\n'
             'def local():\n    with repo.transaction("synthetic-session", FOREIGN) as entered:\n        yield entered\n'
             'def guilds():\n    with local():\n        pass\n', namespace)
        caller = {'__name__': 'postriff_phase2.hosted_app', 'guilds': namespace['guilds']}
        exec('def route():\n    guilds()\n', caller)
        with Captured() as captured, self.assertRaises(AlphaError):
            caller['route']()
        self.assertEqual([e['routeFamily'] for e in captured.events()], ['discord'])


class Bounds(unittest.TestCase):
    def test_many_actors_in_one_minute_fold_into_one_overflow_line_per_family(self):
        clock = Clock()
        signal = security_signals.DenialSignal(clock=clock)
        with Captured() as captured:
            for number in range(security_signals.MAX_KEYS + 50):
                signal.denied('member-%d' % number, 'workspace')
        events = captured.events()
        self.assertEqual(len(events), security_signals.MAX_KEYS + 1)
        self.assertEqual(events[-1]['actorKey'], security_signals.OVERFLOW)
        self.assertEqual(len(signal.minutes[int(clock.at // 60)]), security_signals.MAX_KEYS + 1)

    def test_old_minutes_are_dropped_and_the_summary_windows_hold(self):
        clock = Clock(1_800_000_000.0 - 1_800_000_000.0 % 60)
        signal = security_signals.DenialSignal(clock=clock, logger=logging.getLogger('security-signals-quiet'))
        logging.getLogger('security-signals-quiet').propagate = False
        signal.denied(MEMBER, 'discord')            # minute 0
        clock.at += 9 * 60
        signal.denied(MEMBER, 'workspace')          # minute 9
        signal.denied('another', 'workspace')
        summary = signal.summary()
        self.assertEqual(summary['denied'], {'discord': 1, 'connections': 0, 'workspace': 2, 'other': 0})
        self.assertEqual((summary['actors10m'], summary['topActorDenials10m']), (2, 2))
        clock.at += 60                              # minute 10: minute 0 leaves the 10-minute window, not the 15
        summary = signal.summary()
        self.assertEqual((summary['deniedTotal'], summary['topActorDenials10m']), (3, 1))
        clock.at += 5 * 60                          # minute 15: minute 0 leaves the 15-minute window
        self.assertEqual(signal.summary()['denied']['discord'], 0)
        clock.at += 20 * 60
        signal.denied(MEMBER, 'workspace')
        self.assertEqual(sorted(signal.minutes), [int(clock.at // 60)])
        self.assertEqual(set(signal.logged), {(security_signals.actor_key(MEMBER), 'workspace')})

    def test_an_unknown_family_is_other(self):
        signal = security_signals.DenialSignal(clock=Clock(), logger=logging.getLogger('security-signals-quiet'))
        signal.denied(MEMBER, 'invented')
        self.assertEqual(signal.summary()['denied']['other'], 1)


if __name__ == '__main__':
    unittest.main()
