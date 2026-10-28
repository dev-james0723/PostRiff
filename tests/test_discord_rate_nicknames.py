"""What the nickname route (the sender-name feature) relies on from the shared request coordinator, pinned.

One Discord write is made by that feature: PATCH /guilds/{id}/members/@me, the shared bot's nickname. It is admitted by
reserve(), recorded as a claim by write_admitted(permit), consumed, sent, and observed; an answer that never comes leaves
the admission `uncertain` for the claim path to retire later with a fresh read (reconcile_nickname, or by id when the token
changed). These tests keep that contract while the coordinator's ceiling, ageing and permit lifetimes change around it.

Storage is the shared MemoryLedger double (fake database clock). The real-PostgreSQL side is in
test_discord_rate_ceiling_postgres.py. No network, no credentials.
"""
import json
import os
import unittest
from dataclasses import replace
from unittest.mock import patch

from postriff_alpha.domain import AlphaError
from postriff_phase2.discord.rate_limits import (
    NICKNAME_ENV, Permit, RateCoordinatorUnavailable, RateDelayed, RequestIdentity, SharedPostgresBudget, _digest, route_identity)
from postriff_phase2.social_connectors import DiscordProvider
from test_discord_rate_limits import A, APP, B, MemoryLedger, synthetic_policy

GUILD = '333333333333333333'
OK = {'status': 200, 'headers': {}}
MARGIN = SharedPostgresBudget.UNOBSERVED_MARGIN_SECONDS


def path_of(guild=GUILD):
    return '/guilds/%s/members/@me' % guild


class Gate(unittest.TestCase):
    def test_the_nickname_route_is_admitted_only_while_its_capability_is_exactly_true(self):
        for value in (None, '', 'false', '0', '1', 'True', 'TRUE', ' true', 'true ', 'yes', 'on'):
            environment = {key: v for key, v in os.environ.items() if key != NICKNAME_ENV}
            if value is not None:
                environment[NICKNAME_ENV] = value
            with self.subTest(value=value), patch.dict(os.environ, environment, clear=True), self.assertRaises(RateCoordinatorUnavailable):
                route_identity('PATCH', path_of())
        with patch.dict(os.environ, {NICKNAME_ENV: 'true'}):
            self.assertEqual(route_identity('PATCH', path_of())[0], 'PATCH:/guilds/{id}/members/@me')
            route_identity('GET', '/guilds/%s/members/%s' % (GUILD, A))
        ledger = MemoryLedger(now=1000)
        budget = SharedPostgresBudget(ledger.connection, APP, policy=synthetic_policy())
        identity = RequestIdentity.make(APP, 'bot', 'gate-bot-token')
        with patch.dict(os.environ, {k: v for k, v in os.environ.items() if k != NICKNAME_ENV}, clear=True):
            with self.assertRaises(RateCoordinatorUnavailable):
                budget.reserve('PATCH', path_of(), identity=identity)
        self.assertEqual((ledger.admissions, ledger.states), ({}, {}), 'a refused reserve leaves no admission and no state')
        with patch.dict(os.environ, {NICKNAME_ENV: 'false'}):   # no other route depends on it
            route_identity('GET', '/guilds/%s/members/%s' % (GUILD, A))
            route_identity('POST', '/channels/%s/messages' % A)
            with self.assertRaises(RateCoordinatorUnavailable):
                route_identity('PATCH', '/guilds/%s/members/%s' % (GUILD, A))   # and the allowlist is exact: only `@me`


class Admissions(unittest.TestCase):
    def setUp(self):
        patcher = patch.dict(os.environ, {NICKNAME_ENV: 'true'})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.db = MemoryLedger(now=1000)
        self.identity = RequestIdentity.make(APP, 'bot', 'nickname-bot-token')
        self.guilds = {}
        self.make(10)

    def make(self, capacity):
        self.s = SharedPostgresBudget(self.db.connection, APP, policy={**synthetic_policy(), 'app_capacity': capacity, 'app_window_seconds': 1})

    def admit(self, *, guild=None, consume=True, identity=None):
        """One PATCH admission. Each one gets a guild of its own unless named: a second request to a server whose route
        nobody has learned yet waits for the first one's answer (the cold probe), which is not what is tested here."""
        self.serial = getattr(self, 'serial', 0) + 1
        guild = guild or '3333333333%08d' % self.serial
        permit = self.s.reserve('PATCH', path_of(guild), identity=identity or self.identity)
        self.guilds[permit.id] = guild
        if consume:
            self.s.consume(permit, 'PATCH', path_of(guild))
        return permit

    def g(self, permit):
        return self.guilds[permit.id]

    def lost(self, **kwargs):
        permit = self.admit(**kwargs)
        self.s.note_transport_failure(permit)       # the response never came: a write's outcome is unknown
        return permit

    def state(self, permit):
        return self.db.admissions[permit.id]['state']

    def age(self, seconds):
        self.db.now += seconds

    def free_slots(self):
        import copy
        snapshot = copy.deepcopy((self.db.states, self.db.maps, self.db.admissions))
        granted = 0
        try:
            while granted < 100:
                self.s.reserve_read('GET', '/guilds/%d' % (760000000000000000 + granted), identity=self.identity)
                granted += 1
        except RateDelayed:
            pass
        finally:
            self.db.states, self.db.maps, self.db.admissions = snapshot
        return granted

    # --- abandon_unsent_nickname ------------------------------------------------------------------------------------

    def test_abandon_retires_only_a_sent_unbound_bot_patch_on_the_nickname_route(self):
        sent = self.admit()
        for forged in (replace(sent, method='GET'), replace(sent, method='POST'), replace(sent, binding_hash='a' * 64),
                       replace(sent, identity=RequestIdentity.make(APP, 'user', 'someone', '810000000000000001')), 'not a permit'):
            with self.subTest(forged=str(forged)[:40]), self.assertRaises(RateCoordinatorUnavailable):
                self.s.abandon_unsent_nickname(forged)
        self.assertEqual(self.state(sent), 'sent')
        read = self.s.reserve_read('GET', '/guilds/%s' % A, identity=self.identity)
        with self.assertRaises(RateCoordinatorUnavailable):          # another route's admission under a forged method
            self.s.abandon_unsent_nickname(replace(read, method='PATCH', path_key=_digest(path_of(A))))
        self.s.abandon_unsent_nickname(sent)
        self.assertEqual(self.state(sent), 'blocked')

    def test_abandon_is_silent_for_every_settled_state_and_refuses_what_may_have_been_sent(self):
        settled = self.admit()
        self.s.abandon_unsent_nickname(settled)
        self.s.abandon_unsent_nickname(settled)                      # blocked: silent
        answered = self.admit()
        self.s.observe(answered, OK)
        self.s.abandon_unsent_nickname(answered)                     # observed: silent
        self.assertEqual((self.state(settled), self.state(answered)), ('blocked', 'observed'))
        for permit in (self.lost(), self.admit(consume=False)):       # uncertain, reserved: never retired as unsent
            with self.subTest(state=self.state(permit)), self.assertRaises(RateCoordinatorUnavailable):
                self.s.abandon_unsent_nickname(permit)

    def test_abandon_is_still_idempotent_after_the_unanswered_row_aged_out_of_every_count(self):
        permit = self.admit()                                         # sent, never answered
        self.age(1 + MARGIN + 1)
        self.assertEqual(self.free_slots(), 10, 'it no longer counts')
        self.s.abandon_unsent_nickname(permit)                        # but the denied writer may still arrive late
        self.s.abandon_unsent_nickname(permit)
        self.assertEqual(self.state(permit), 'blocked')

    # --- reconcile_nickname and reconcile_nickname_by_id ------------------------------------------------------------

    def test_a_settled_admission_is_silent_to_both_reconcilers_however_young_it_is(self):
        blocked, answered = self.admit(), self.admit()
        self.s.abandon_unsent_nickname(blocked)
        self.s.observe(answered, OK)
        for permit in (blocked, answered):
            with self.subTest(state=self.state(permit)):
                self.s.reconcile_nickname(self.db, permit, self.g(permit))        # age 0: the 120 s rule does not apply
                self.s.reconcile_nickname_by_id(self.db, permit.id, self.g(permit))
                self.assertIn(self.state(permit), ('blocked', 'observed'))
        self.assertEqual(self.db.admissions[answered.id]['status'], 200, 'a settled row is not touched')

    def test_a_live_admission_is_retired_only_by_an_exact_aged_reading_and_keeps_no_invented_status(self):
        permit = self.lost(guild=GUILD)
        for seconds in (0, 60, 119):
            self.db.now = 1000 + seconds
            with self.subTest(seconds=seconds):
                for how in (lambda: self.s.reconcile_nickname(self.db, permit, GUILD),
                            lambda: self.s.reconcile_nickname_by_id(self.db, permit.id, GUILD)):
                    with self.assertRaises(RateCoordinatorUnavailable):
                        how()
        self.db.now = 1000 + 121
        for guild in ('9999999', B):
            with self.assertRaises(RateCoordinatorUnavailable):
                self.s.reconcile_nickname(self.db, permit, guild)
            with self.assertRaises(RateCoordinatorUnavailable):
                self.s.reconcile_nickname_by_id(self.db, permit.id, guild)
        self.assertEqual(self.state(permit), 'uncertain')
        self.s.reconcile_nickname_by_id(self.db, permit.id, GUILD)
        row = self.db.admissions[permit.id]
        self.assertEqual((row['state'], row['status'], row['scope']), ('observed', None, 'unknown'))
        self.s.reconcile_nickname(self.db, permit, GUILD)                         # settled twice: silent
        self.s.reconcile_nickname_by_id(self.db, permit.id, GUILD)

    def test_by_id_refuses_everything_that_is_not_a_bot_nickname_patch_of_this_application(self):
        permit = self.lost(guild=GUILD)
        self.db.now += 200
        for bad in (None, 7, '', 'not-a-uuid', '00000000-0000-0000-0000-000000000000', permit.id + 'x'):
            with self.subTest(admission=bad), self.assertRaises(RateCoordinatorUnavailable):
                self.s.reconcile_nickname_by_id(self.db, bad, GUILD)
        for guild in (None, 5, '', 'x', GUILD + 'x'):
            with self.subTest(guild=guild), self.assertRaises(RateCoordinatorUnavailable):
                self.s.reconcile_nickname_by_id(self.db, permit.id, guild)
        read = self.s.reserve_read('GET', '/guilds/%s' % A, identity=self.identity)
        row = self.db.admissions[permit.id]
        for name, change in (('a read', lambda: self.db.admissions[read.id].update(route=row['route'], path=row['path'])),
                             ('a publish', lambda: row.update(publish=True)),
                             ('a binding', lambda: row.update(binding='b' * 64)),
                             ('an intent', lambda: row.update(intent='an-intent')),
                             ('a user credential', lambda: row.update(kind='user')),
                             ('another application', lambda: row.update(application='f' * 64))):
            with self.subTest(refused=name):
                saved = dict(row)
                change()
                with self.assertRaises(RateCoordinatorUnavailable):
                    self.s.reconcile_nickname_by_id(self.db, read.id if name == 'a read' else permit.id, GUILD)
                row.clear()
                row.update(saved)
        self.assertEqual(self.state(permit), 'uncertain')
        self.s.reconcile_nickname_by_id(self.db, permit.id, GUILD)
        self.assertEqual(self.state(permit), 'observed')

    def test_a_rotated_bot_token_cannot_stop_an_aged_admission_from_being_retired(self):
        permit = self.lost(guild=GUILD)
        self.db.now += 200
        rotated = replace(permit, identity=RequestIdentity.make(APP, 'bot', 'the-rotated-bot-token'))
        with self.assertRaises(RateCoordinatorUnavailable):
            self.s.reconcile_nickname(self.db, rotated, GUILD)                    # the credential digest differs: for ever
        self.s.reconcile_nickname_by_id(self.db, permit.id, GUILD)
        self.assertEqual(self.state(permit), 'observed')

    def test_the_permit_the_claim_rebuilds_from_its_stored_id_and_float_expiry_is_accepted_and_nothing_looser(self):
        permit = self.lost(guild=GUILD)
        self.db.now += 200
        stored = json.loads(json.dumps({'id': permit.id, 'expires': permit.expires_at}))   # the claim persists these two
        rebuilt = Permit(stored['id'], self.s.application_key, 'PATCH', _digest(path_of()), self.identity, None, stored['expires'])
        self.assertEqual(rebuilt, permit)
        for off in (replace(rebuilt, expires_at=rebuilt.expires_at + 5e-6), replace(rebuilt, expires_at=rebuilt.expires_at - 5e-6),
                    replace(rebuilt, id='7' * 8 + permit.id[8:]), replace(rebuilt, path_key=_digest(path_of(B)))):
            with self.subTest(off=str(off)[-60:]), self.assertRaises(RateCoordinatorUnavailable):
                self.s.reconcile_nickname(self.db, off, GUILD)
        self.s.reconcile_nickname(self.db, replace(rebuilt, expires_at=rebuilt.expires_at + 1.5e-6), GUILD)   # inside 2e-6
        self.assertEqual(self.state(permit), 'observed')

    # --- the ceiling and the ageing, seen from the nickname route -----------------------------------------------------

    def test_spent_nickname_admissions_keep_their_slots_for_their_span_without_refund(self):
        self.make(3)
        unsent = self.admit()
        self.s.abandon_unsent_nickname(unsent)       # blocked: never sent, and not refunded
        answered = self.admit(guild=B)
        self.s.observe(answered, OK)
        orphan = self.lost(guild=A)                  # uncertain
        self.age(.5)
        self.assertEqual(self.free_slots(), 0)
        self.age(.7)                                 # past the span: blocked and answered free their slots, the orphan keeps its own
        self.assertEqual(self.free_slots(), 2)
        self.age(MARGIN)                             # and the orphan stops counting after the margin, still `uncertain`
        self.assertEqual(self.free_slots(), 3)
        self.assertEqual([self.state(p) for p in (unsent, answered, orphan)], ['blocked', 'observed', 'uncertain'])

    def test_ageing_changes_no_row_so_the_claim_path_can_still_retire_an_orphan_after_the_bound(self):
        orphan, sent = self.lost(guild=GUILD), self.admit(guild=B)
        before = {key: dict(self.db.admissions[key]) for key in (orphan.id, sent.id)}
        self.age(1 + MARGIN + 5)
        for number in range(5):                                # the coordinator keeps working, reserving and observing
            self.s.observe(self.s.reserve_read('GET', '/guilds/%d' % (770000000000000000 + number), identity=self.identity), OK)
        self.assertEqual({key: self.db.admissions[key] for key in before}, before, 'nothing re-aged or rewritten them')
        self.age(200)
        self.s.reconcile_nickname(self.db, orphan, GUILD)
        self.s.reconcile_nickname_by_id(self.db, sent.id, B)
        self.assertEqual([self.state(orphan), self.state(sent)], ['observed', 'observed'])


    def test_turning_the_capability_off_strands_no_admission_that_exists(self):
        orphan, sent = self.lost(guild=GUILD), self.admit(guild=B)
        self.age(200)
        with patch.dict(os.environ, {NICKNAME_ENV: 'false'}):
            with self.assertRaises(RateCoordinatorUnavailable):
                self.s.reserve('PATCH', path_of(), identity=self.identity)          # no new admission
            self.s.observe(sent, OK)                                                # but the existing ones settle
            self.s.reconcile_nickname(self.db, orphan, GUILD)
            self.s.reconcile_nickname_by_id(self.db, orphan.id, GUILD)
            self.s.abandon_unsent_nickname(sent)
        self.assertEqual([self.state(orphan), self.state(sent)], ['observed', 'observed'])


class Provider(unittest.TestCase):
    def setUp(self):
        patcher = patch.dict(os.environ, {NICKNAME_ENV: 'true'})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.db = MemoryLedger(now=1000)
        self.calls = []

        def transport(method, url, **kwargs):
            self.assertEqual(self.db.active, 0, 'provider I/O under a SQL transaction')
            self.calls.append((method, url))
            return {'status': 200, 'headers': {}, 'body': {'nick': 'x'}}
        self.p = DiscordProvider(APP, 'synthetic-secret', 'synthetic-bot', 'https://rafii.invalid', transport=transport)
        self.p.rate_v1_enabled = True
        self.p.rate_limiter = SharedPostgresBudget(self.db.connection, APP, policy=synthetic_policy())

    def test_write_admitted_runs_between_reserve_and_consume_outside_every_rate_lock(self):
        seen = []

        def admitted(permit):
            seen.append((self.db.active, self.db.admissions[permit.id]['state'], len(self.calls), permit.id))
        self.p._bot('PATCH', path_of(), body={'nick': 'Synthetic'}, write_authorize=lambda: True, write_admitted=admitted)
        (active, state, sent_calls, admission), = seen
        self.assertEqual((active, state, sent_calls), (0, 'reserved', 0), 'no coordinator transaction open, not consumed, not sent')
        self.assertEqual(self.db.admissions[admission]['state'], 'observed')
        self.assertEqual(len(self.calls), 1)

    def test_a_claim_that_cannot_be_written_stops_the_request_before_it_is_consumed_or_sent(self):
        def refuse(permit):
            raise AlphaError('Synthetic custody failure.', 409)
        with self.assertRaises(AlphaError):
            self.p._bot('PATCH', path_of(), body={'nick': 'Synthetic'}, write_authorize=lambda: True, write_admitted=refuse)
        self.assertEqual(self.calls, [])
        (row,) = self.db.admissions.values()
        self.assertEqual(row['state'], 'reserved')


class Double(unittest.TestCase):
    def test_the_storage_double_refuses_sql_it_does_not_know(self):
        with self.assertRaisesRegex(AssertionError, 'Unrecognized synthetic SQL contract'):
            MemoryLedger().execute('SELECT 1 FROM public.pr_discord_something_new WHERE id=%s', ('x',))


if __name__ == '__main__':
    unittest.main()
