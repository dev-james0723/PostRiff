"""Founder follow-ups: validation, idempotent creation, derived `due`, revision-checked updates and the SQL shape.

No PostgreSQL: `MemoryFollowUpStore` mirrors the FollowUpSQL method surface, and `RecordingStore` captures the statements
FollowUpSQL issues so the operator GUC and the environment/operator predicates are proven without a database.
"""
import copy
import unittest
import uuid
from contextlib import contextmanager

from rafii_control import founder_follow_ups
from rafii_control.auth import ControlError
from rafii_control.founder_cron import PostgresFounderStore
from rafii_control.founder_follow_ups import EVIDENCE_BYTES, MAX_OPEN, FollowUpSQL, create, list_follow_ups, stamp, update

OPERATOR = '00000000-0000-0000-0000-00000000f00d'
OTHER = '00000000-0000-0000-0000-0000000000b2'
T0 = 1790000000.0  # 2026-09-21 14:13:20 UTC
PRINCIPAL = {'operator': {'user_id': OPERATOR, 'capabilities': ['control.read', 'followups.write']}, 'session': {'id': 'sess', 'environment': 'local'}}
STRANGER = {'operator': {'user_id': OTHER, 'capabilities': ['control.read', 'followups.write']}, 'session': {'id': 'sess2', 'environment': 'local'}}


class MemoryFollowUpStore:
    """Same method surface as FollowUpSQL, including the per-operator visibility the 054 policy enforces."""

    def __init__(self, environment='local'):
        self.environment, self.rows = environment, {}

    def follow_ups(self, operator_id, *, limit=100):
        rows = sorted((r for r in self.rows.values() if r['operator_id'] == operator_id), key=lambda r: (-r['created_at'], r['id']))
        return [copy.deepcopy(r) for r in rows[:limit]]

    def follow_up(self, operator_id, follow_up_id):
        row = self.rows.get(follow_up_id)
        return copy.deepcopy(row) if row and row['operator_id'] == operator_id else None

    def insert_follow_up(self, row):
        key = (row['operator_id'], row['environment'], row['source_type'], row['source_id'])
        existing = next((r for r in self.rows.values() if (r['operator_id'], r['environment'], r['source_type'], r['source_id']) == key), None)
        if existing:
            return copy.deepcopy(existing)
        self.rows[row['id']] = copy.deepcopy(row)
        return copy.deepcopy(row)

    def update_follow_up(self, operator_id, follow_up_id, *, expected_revision, **fields):
        if set(fields) - founder_follow_ups._FOLLOW_UP_FIELDS:
            raise ValueError('unknown follow-up field')
        row = self.rows.get(follow_up_id)
        if row is None or row['operator_id'] != operator_id or row['revision'] != expected_revision:
            return None
        row.update(fields)
        row['revision'] += 1
        return copy.deepcopy(row)


class FollowUpWriteTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryFollowUpStore()

    def test_create_validates_and_stamps_iso_times(self):
        created = create(self.store, PRINCIPAL, {'title': ' Call Ada about the failed invoice ', 'dueAt': '2026-09-22T13:00:00Z', 'timeZone': 'Asia/Hong_Kong',
                                                 'sourceType': 'incident', 'sourceId': 'inc-1', 'evidence': {'receiptIds': ['r-1']}}, now=T0)
        item = created['followUp']
        self.assertTrue(created['created'])
        self.assertEqual((item['title'], item['state'], item['dueAt'], item['timeZone'], item['sourceType'], item['sourceId'], item['revision']),
                         ('Call Ada about the failed invoice', 'scheduled', '2026-09-22T13:00:00Z', 'Asia/Hong_Kong', 'incident', 'inc-1', 1))
        self.assertEqual((item['createdAt'], item['updatedAt'], item['evidence'], item['href']), (stamp(T0), stamp(T0), {'receiptIds': ['r-1']}, '/founder?tab=follow-ups'))
        str(uuid.UUID(item['id']))
        draft = create(self.store, PRINCIPAL, {'title': 'Think about pricing'}, now=T0)['followUp']
        self.assertEqual((draft['state'], draft['dueAt'], draft['sourceType'], draft['sourceId'], draft['timeZone']),
                         ('draft', None, 'manual', draft['id'], founder_follow_ups.DEFAULT_TIME_ZONE))
        for body in [{}, {'title': ''}, {'title': 'x' * 201}, {'title': 'ok', 'extra': 1}, {'title': 'ok', 'dueAt': '2026-09-22T13:00:00'},
                     {'title': 'ok', 'dueAt': 'tomorrow'}, {'title': 'ok', 'dueAt': 12}, {'title': 'ok', 'timeZone': 'Mars/Olympus'},
                     {'title': 'ok', 'state': 'scheduled'}, {'title': 'ok', 'state': 'completed'}, {'title': 'ok', 'sourceType': 'Bad Type'},
                     {'title': 'ok', 'sourceId': 'has space'}, {'title': 'ok', 'evidence': ['list']}, {'title': 'ok', 'evidence': {'big': 'x' * EVIDENCE_BYTES}},
                     {'title': 'ok', 'dueAt': '2020-01-01T00:00:00Z'}, {'title': 'ok', 'dueAt': '2030-01-01T00:00:00Z'}, 'not a dict']:
            with self.subTest(body=body), self.assertRaises(ControlError) as caught:
                create(self.store, PRINCIPAL, body, now=T0)
            self.assertEqual((caught.exception.code, caught.exception.status), ('VALIDATION_FAILED', 400))
        self.assertEqual(len(self.store.rows), 2)

    def test_create_replays_on_the_same_source_and_caps_open_rows(self):
        first = create(self.store, PRINCIPAL, {'title': 'Call Ada', 'sourceType': 'incident', 'sourceId': 'inc-1', 'dueAt': '2026-09-22T13:00:00Z'}, now=T0)
        again = create(self.store, PRINCIPAL, {'title': 'Call Ada (edited)', 'sourceType': 'incident', 'sourceId': 'inc-1'}, now=T0 + 5)
        self.assertEqual((again['created'], again['followUp']), (False, first['followUp']))
        other = create(self.store, STRANGER, {'title': 'Mine', 'sourceType': 'incident', 'sourceId': 'inc-1'}, now=T0)
        self.assertTrue(other['created'])
        self.assertNotEqual(other['followUp']['id'], first['followUp']['id'])
        for index in range(MAX_OPEN - 1):
            create(self.store, PRINCIPAL, {'title': f'Item {index}', 'sourceId': f'src-{index}'}, now=T0)
        with self.assertRaises(ControlError) as caught:
            create(self.store, PRINCIPAL, {'title': 'One too many'}, now=T0)
        self.assertEqual((caught.exception.code, caught.exception.status), ('BUDGET_EXCEEDED', 409))
        self.assertEqual(list_follow_ups(self.store, STRANGER, now=T0)['open'], 1)   # the cap is per operator

    def test_list_orders_open_first_and_derives_due_without_persisting(self):
        soon = create(self.store, PRINCIPAL, {'title': 'Soon', 'dueAt': stamp(T0 + 3600)}, now=T0)['followUp']
        later = create(self.store, PRINCIPAL, {'title': 'Later', 'dueAt': stamp(T0 + 7200)}, now=T0 + 1)['followUp']
        undated = create(self.store, PRINCIPAL, {'title': 'Undated'}, now=T0 + 2)['followUp']
        done = create(self.store, PRINCIPAL, {'title': 'Done', 'dueAt': stamp(T0 + 60)}, now=T0 + 3)['followUp']
        update(self.store, PRINCIPAL, done['id'], {'state': 'completed'}, now=T0 + 4)
        listed = list_follow_ups(self.store, PRINCIPAL, now=T0 + 3601)
        self.assertEqual([item['title'] for item in listed['followUps']], ['Soon', 'Later', 'Undated', 'Done'])
        self.assertEqual([item['state'] for item in listed['followUps']], ['due', 'scheduled', 'draft', 'completed'])
        self.assertEqual(listed['open'], 3)
        self.assertEqual(self.store.rows[soon['id']]['state'], 'scheduled')   # derived in the view only
        self.assertEqual(list_follow_ups(self.store, STRANGER, now=T0)['followUps'], [])
        self.assertEqual(update(self.store, PRINCIPAL, later['id'], {'title': 'Later still'}, now=T0 + 5)['followUp']['revision'], 2)
        self.assertEqual(undated['state'], 'draft')

    def test_update_is_revision_checked_and_follows_the_transition_table(self):
        item = create(self.store, PRINCIPAL, {'title': 'Call Ada', 'dueAt': stamp(T0 + 3600)}, now=T0)['followUp']
        with self.assertRaises(ControlError) as caught:
            update(self.store, PRINCIPAL, item['id'], {'state': 'completed', 'revision': 7}, now=T0 + 1)
        self.assertEqual((caught.exception.code, caught.exception.status), ('STALE_PREVIEW', 409))
        moved = update(self.store, PRINCIPAL, item['id'], {'dueAt': stamp(T0 + 86400), 'revision': 1}, now=T0 + 2)['followUp']
        self.assertEqual((moved['revision'], moved['dueAt'], moved['updatedAt'], moved['state']), (2, stamp(T0 + 86400), stamp(T0 + 2), 'scheduled'))
        done = update(self.store, PRINCIPAL, item['id'], {'state': 'completed', 'revision': 2}, now=T0 + 3)['followUp']
        self.assertEqual((done['state'], done['revision']), ('completed', 3))
        for body, code, status in [({'state': 'scheduled'}, 'VALIDATION_FAILED', 400), ({}, 'VALIDATION_FAILED', 400), ({'revision': 0}, 'VALIDATION_FAILED', 400),
                                   ({'state': 'archived'}, 'VALIDATION_FAILED', 400), ({'title': 'x', 'nope': 1}, 'VALIDATION_FAILED', 400)]:
            with self.subTest(body=body), self.assertRaises(ControlError) as caught:
                update(self.store, PRINCIPAL, item['id'], body, now=T0 + 4)
            self.assertEqual((caught.exception.code, caught.exception.status), (code, status))
        with self.assertRaises(ControlError) as caught:
            update(self.store, STRANGER, item['id'], {'title': 'Not yours'}, now=T0 + 4)
        self.assertEqual((caught.exception.code, caught.exception.status), ('VALIDATION_FAILED', 404))
        with self.assertRaises(ControlError) as caught:
            update(self.store, PRINCIPAL, 'not-a-uuid', {'title': 'x'}, now=T0 + 4)
        self.assertEqual(caught.exception.status, 400)
        draft = create(self.store, PRINCIPAL, {'title': 'Draft'}, now=T0)['followUp']
        with self.assertRaises(ControlError):
            update(self.store, PRINCIPAL, draft['id'], {'state': 'scheduled'}, now=T0 + 5)   # scheduling needs a time
        scheduled = update(self.store, PRINCIPAL, draft['id'], {'state': 'scheduled', 'dueAt': stamp(T0 + 600)}, now=T0 + 5)['followUp']
        missed = update(self.store, PRINCIPAL, draft['id'], {'state': 'missed'}, now=T0 + 7)['followUp']
        again = update(self.store, PRINCIPAL, draft['id'], {'state': 'scheduled', 'dueAt': stamp(T0 + 9000)}, now=T0 + 8)['followUp']
        self.assertEqual([scheduled['state'], missed['state'], again['state'], again['revision']], ['scheduled', 'missed', 'scheduled', 4])

    def test_concurrent_writer_is_reported_as_stale(self):
        item = create(self.store, PRINCIPAL, {'title': 'Call Ada', 'dueAt': stamp(T0 + 3600)}, now=T0)['followUp']
        original = self.store.update_follow_up

        def racing(operator_id, follow_up_id, *, expected_revision, **fields):
            original(operator_id, follow_up_id, expected_revision=expected_revision, title='someone else')
            return original(operator_id, follow_up_id, expected_revision=expected_revision, **fields)
        self.store.update_follow_up = racing
        with self.assertRaises(ControlError) as caught:
            update(self.store, PRINCIPAL, item['id'], {'state': 'completed'}, now=T0 + 1)
        self.assertEqual((caught.exception.code, caught.exception.status), ('STALE_PREVIEW', 409))


# --- SQL shape -------------------------------------------------------------------------------------------------------------
class RecordingConnection:
    def __init__(self, answers):
        self.statements, self.answers = [], answers

    def execute(self, sql, params=None):
        self.statements.append((sql, tuple(params or ())))
        return self

    def fetchone(self):
        return self.answers.get('one')

    def fetchall(self):
        return self.answers.get('all', [])


class RecordingStore:
    def __init__(self, answers):
        self.environment, self.connection = 'staging', RecordingConnection(answers)

    @contextmanager
    def transaction(self, read=False):
        assert not read, 'follow-ups are written and read through the session role'
        yield self.connection


ROW = {'id': 'f-1', 'operator_id': OPERATOR, 'environment': 'staging', 'source_type': 'manual', 'source_id': 'f-1', 'title': 'Call Ada', 'due_at': T0 + 60,
       'time_zone': 'UTC', 'state': 'scheduled', 'evidence': {}, 'revision': 1, 'created_at': T0, 'updated_at': T0}


class FollowUpSQLTests(unittest.TestCase):
    def statements(self, work, answers=None):
        store = RecordingStore(answers or {'one': dict(ROW), 'all': [dict(ROW)]})
        fstore = PostgresFounderStore(store)
        self.assertIsInstance(fstore, FollowUpSQL)
        work(fstore)
        return store.connection.statements

    def assertShape(self, statements):
        self.assertEqual(statements[0], ("SELECT set_config('rafii_control.operator',%s,true)", (OPERATOR,)))
        for sql, params in statements[1:]:
            with self.subTest(sql=sql):
                self.assertEqual(sql.count('%s'), len(params), 'every placeholder is a bound parameter')
                self.assertIn('rafii_control.founder_follow_ups', sql)
                if sql.startswith('UPDATE') or sql.startswith('SELECT'):
                    self.assertIn('environment=%s', sql)
                    self.assertIn('staging', params)

    def test_read_statements_bind_operator_and_environment(self):
        listed = self.statements(lambda f: f.follow_ups(OPERATOR, limit=5000))
        self.assertShape(listed)
        self.assertIn('operator_id=%s AND environment=%s ORDER BY created_at DESC,id LIMIT %s', listed[1][0])
        self.assertEqual(listed[1][1], (OPERATOR, 'staging', founder_follow_ups.MAX_LIST))
        one = self.statements(lambda f: f.follow_up(OPERATOR, 'f-1'))
        self.assertShape(one)
        self.assertEqual(one[1][1], ('f-1', OPERATOR, 'staging'))

    def test_insert_is_idempotent_on_the_source_key_and_update_is_a_compare_and_set(self):
        inserted = self.statements(lambda f: f.insert_follow_up(dict(ROW)))
        self.assertShape(inserted)
        self.assertIn('ON CONFLICT(operator_id,environment,source_type,source_id) DO NOTHING', inserted[1][0])
        self.assertEqual(inserted[1][1][:5], ('f-1', OPERATOR, 'staging', 'manual', 'f-1'))
        self.assertEqual(inserted[2][1], (OPERATOR, 'staging', 'manual', 'f-1'))
        updated = self.statements(lambda f: f.update_follow_up(OPERATOR, 'f-1', expected_revision=3, state='completed', evidence={'receiptIds': ['r']}, updated_at=T0 + 1))
        self.assertShape(updated)
        sql, params = updated[1]
        self.assertTrue(sql.startswith('UPDATE rafii_control.founder_follow_ups SET revision=revision+1,state=%s,evidence=%s,updated_at=to_timestamp(%s) WHERE id=%s AND operator_id=%s AND environment=%s AND revision=%s'), sql)
        self.assertEqual((params[0], params[1].obj, params[2:]), ('completed', {'receiptIds': ['r']}, (T0 + 1, 'f-1', OPERATOR, 'staging', 3)))
        self.assertEqual(updated[2][1], ('f-1', 'staging'))
        with self.assertRaises(ValueError):
            PostgresFounderStore(RecordingStore({})).update_follow_up(OPERATOR, 'f-1', expected_revision=1, source_id='moved')
        self.assertIsNone(PostgresFounderStore(RecordingStore({'one': None})).update_follow_up(OPERATOR, 'f-1', expected_revision=1, title='x'))
        rows = PostgresFounderStore(RecordingStore({'all': [dict(ROW, due_at=None, evidence=None)]})).follow_ups(OPERATOR)
        self.assertEqual((rows[0]['due_at'], rows[0]['evidence'], rows[0]['created_at']), (None, {}, T0))


if __name__ == '__main__':
    unittest.main()
