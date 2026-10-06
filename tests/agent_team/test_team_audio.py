"""Private audio storage with synthetic WAV and fake transactions; no synthesis."""
import base64
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import io
import struct
import unittest
import wave

from agent_team.periods import period
from agent_team.reports import report
from postriff_alpha.domain import AlphaError
from postriff_phase2.agent_team_audio import TeamAudioStore, METADATA_COLUMNS, PRODUCER, MIME, MAX_ENCODED_BYTES
from postriff_phase2.james_agent_team import content_fingerprint


def summary_hash(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def whole_report(version=1, summary='一份完整的合成測試摘要。', workday='2026-10-05'):
    p = period(workday, 'whole_day')
    doc = report(p, [], p.cutoff + timedelta(minutes=1))
    doc.update(version=version, summary=summary)
    doc['fingerprint'] = content_fingerprint(doc)
    return doc


def synthetic_wav(frames=1600, channels=1, rate=16000, width=2, signal=True):
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(width)
        writer.setframerate(rate)
        writer.writeframes((struct.pack('<h', 1200 if signal else 0) if width == 2 else b'\x20') * frames * channels)
    return stream.getvalue()


class FakeDB:
    def __init__(self, now):
        self.reports = {}
        self.assets = {}
        self.now = now
        self.history = []
        self.commits = 0
        self.rollbacks = 0

    def seed(self, doc):
        self.reports[(doc['period']['key'], doc['fingerprint'])] = copy.deepcopy(doc)

    def __call__(self):
        return Connection(self)


class Connection:
    def __init__(self, db):
        self.db = db
        self.assets = copy.deepcopy(db.assets)
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, kind, _value, _trace):
        if kind or not self.committed:
            self.db.rollbacks += 1

    def cursor(self):
        return Cursor(self)

    def commit(self):
        self.db.assets = copy.deepcopy(self.assets)
        self.db.commits += 1
        self.committed = True


class Cursor:
    def __init__(self, connection):
        self.connection = connection
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def execute(self, sql, values):
        self.connection.db.history.append((sql, tuple(values)))
        self.rows = []
        if sql.startswith('SELECT pg_advisory_xact_lock'):
            self.rows = [(None,)]
        elif sql.startswith('SELECT document FROM public.pr_agent_team_reports'):
            if len(values) == 2:
                doc = self.connection.db.reports.get(tuple(values))
            else:
                matches = [doc for (key, _fingerprint), doc in self.connection.db.reports.items() if key == values[0]]
                doc = max(matches, key=lambda d: d['version']) if matches else None
            self.rows = [(doc,)] if doc else []
        elif sql.startswith('SELECT report_key,fingerprint,report_version'):
            asset = self.connection.assets.get(tuple(values))
            if asset:
                row = tuple(asset[key] for key in METADATA_COLUMNS)
                self.rows = [row + (asset['wav_data'],)] if ',wav_data FROM' in sql else [row]
        elif sql.startswith('INSERT INTO public.pr_agent_team_audio_assets'):
            fields = ('report_key', 'fingerprint', 'report_version', 'summary_hash', 'narration_hash', 'excerpt',
                      'sha256', 'mime', 'producer', 'observed_at', 'byte_count', 'duration_ms', 'wav_data')
            asset = {**dict(zip(fields, values)), 'created_at': self.connection.db.now}
            key = (asset['report_key'], asset['fingerprint'])
            if key in self.connection.assets:
                raise AssertionError('Duplicate immutable asset insertion')
            if key not in self.connection.db.reports:
                raise AssertionError('Missing report FK')
            self.connection.assets[key] = asset
            self.rows = [tuple(asset[field] for field in METADATA_COLUMNS)]
        else:
            raise AssertionError('Unexpected SQL: ' + sql)

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None


class TeamAudioTests(unittest.TestCase):
    def setup_audio(self, doc=None):
        from agent_team.audio import narration_for_report
        doc = doc or whole_report()
        now = datetime.fromisoformat(doc['generatedAt']) + timedelta(minutes=1)
        db = FakeDB(now)
        db.seed(doc)
        raw = synthetic_wav()
        narration = narration_for_report(doc)
        payload = {'reportKey': doc['period']['key'], 'fingerprint': doc['fingerprint'], 'version': doc['version'],
                   'summaryHash': summary_hash(doc['summary']), 'narrationHash': summary_hash(narration),
                   'excerpt': narration != doc['summary'], 'sha256': hashlib.sha256(raw).hexdigest(),
                   'mime': MIME, 'producer': PRODUCER, 'observedAt': now.isoformat(),
                   'data': base64.b64encode(raw).decode('ascii')}
        store = TeamAudioStore(db, clock=lambda: now.timestamp())
        return doc, raw, payload, db, store

    def changed_bytes(self, payload, raw):
        return {**payload, 'sha256': hashlib.sha256(raw).hexdigest(), 'data': base64.b64encode(raw).decode('ascii')}

    def test_valid_audio_commits_metadata_and_binary_under_report_fk(self):
        doc, raw, payload, db, store = self.setup_audio()
        receipt = store.put(payload)
        self.assertEqual((receipt['state'], receipt['audioState'], receipt['deliveryState']), ('stored', 'ready', 'not_proven'))
        self.assertTrue(receipt['created'])
        self.assertEqual(receipt['durationSeconds'], .1)
        self.assertEqual(receipt['byteCount'], len(raw))
        self.assertEqual((receipt['sampleRate'], receipt['channels'], receipt['sampleWidth']), (16000, 1, 2))
        self.assertNotIn('data', receipt)
        self.assertNotIn('summary', receipt)
        self.assertNotIn('narration', receipt)
        self.assertFalse(receipt['clonedVoice'])
        self.assertEqual(db.commits, 1)
        metadata, streamed = store.get(doc['period']['key'], doc['fingerprint'])
        self.assertEqual(streamed, raw)
        self.assertEqual(metadata['sha256'], payload['sha256'])

    def test_identical_retry_preserves_first_observation_without_second_asset(self):
        _doc, _raw, payload, db, store = self.setup_audio()
        first = store.put(payload)
        second = store.put({**payload, 'observedAt': (db.now - timedelta(seconds=1)).isoformat()})
        self.assertTrue(first['created'])
        self.assertFalse(second['created'])
        self.assertEqual(first['observedAt'], second['observedAt'])
        self.assertEqual(len(db.assets), 1)

    def test_delivery_metadata_read_does_not_load_wav_or_claim_playback(self):
        doc, _raw, payload, db, store = self.setup_audio()
        self.assertIsNone(store.get_metadata(doc['period']['key'], doc['fingerprint']))
        store.put(payload)
        start = len(db.history)
        receipt = store.get_metadata(doc['period']['key'], doc['fingerprint'])
        self.assertEqual(receipt['sha256'], payload['sha256'])
        self.assertEqual(receipt['deliveryState'], 'not_proven')
        self.assertNotIn('data', receipt)
        self.assertNotIn('wav_data', receipt)
        self.assertTrue(all('wav_data' not in sql for sql, _ in db.history[start:]))

    def test_different_sha_for_same_report_conflicts_and_preserves_original(self):
        _doc, raw, payload, db, store = self.setup_audio()
        store.put(payload)
        with self.assertRaises(AlphaError) as raised:
            store.put(self.changed_bytes(payload, synthetic_wav(frames=1700)))
        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(next(iter(db.assets.values()))['wav_data'], raw)

    def test_wrong_version_summary_narration_or_excerpt_never_inserts(self):
        for key, value in (('version', 2), ('summaryHash', 'f' * 64), ('narrationHash', 'f' * 64), ('excerpt', True)):
            _doc, _raw, payload, db, store = self.setup_audio()
            with self.assertRaises(AlphaError) as raised:
                store.put({**payload, key: value})
            self.assertEqual(raised.exception.status, 409)
            self.assertEqual(db.assets, {})
            self.assertEqual(db.commits, 0)

    def test_missing_report_and_preview_are_not_audio_authority(self):
        _doc, _raw, payload, db, store = self.setup_audio()
        db.reports.clear()
        with self.assertRaises(AlphaError) as raised:
            store.put(payload)
        self.assertEqual(raised.exception.status, 404)
        doc, _raw, payload, db, store = self.setup_audio()
        db.reports[(doc['period']['key'], doc['fingerprint'])]['executionState'] = 'preview'
        with self.assertRaises(AlphaError):
            store.put(payload)
        self.assertEqual(db.assets, {})

    def test_half_day_future_naive_timestamp_and_contract_extras_reject_before_db(self):
        _doc, _raw, payload, db, store = self.setup_audio()
        cases = [dict(payload, reportKey=payload['reportKey'].replace('whole_day', 'half_day')),
                 dict(payload, observedAt=(db.now + timedelta(seconds=1)).isoformat()),
                 dict(payload, observedAt='2026-10-06T05:03:00'), dict(payload, durationSeconds=.1),
                 dict(payload, mime='audio/mpeg'), dict(payload, producer='cloud_tts'), dict(payload, version=True)]
        for bad in cases:
            with self.assertRaises(AlphaError):
                store.put(bad)
        self.assertEqual(db.history, [])

    def test_parser_bytes_control_format_and_duration_without_declared_hint(self):
        for raw in (b'not wav', synthetic_wav(channels=2), synthetic_wav(rate=8000),
                    synthetic_wav(width=1), synthetic_wav(frames=16000 * 45 + 1), synthetic_wav(signal=False)):
            _doc, _original, payload, db, store = self.setup_audio()
            with self.assertRaises(AlphaError):
                store.put(self.changed_bytes(payload, raw))
            self.assertEqual(db.history, [])
            self.assertEqual(db.assets, {})

    def test_base64_and_digest_limits_fail_before_report_lookup(self):
        _doc, _raw, payload, db, store = self.setup_audio()
        for bad in (dict(payload, data='!invalid'), dict(payload, sha256='f' * 64),
                    dict(payload, data='A' * (MAX_ENCODED_BYTES + 1))):
            with self.assertRaises(AlphaError):
                store.put(bad)
        self.assertEqual(db.history, [])

    def test_excerpt_is_verified_and_labelled_without_claiming_full_summary_audio(self):
        doc = whole_report(summary='第一句摘要。' + '其餘來源及驗收仍待核對。' * 30)
        _doc, _raw, payload, _db, store = self.setup_audio(doc)
        self.assertTrue(payload['excerpt'])
        receipt = store.put(payload)
        self.assertTrue(receipt['excerpt'])
        self.assertNotEqual(receipt['summaryHash'], receipt['narrationHash'])

    def test_work_only_returns_latest_due_whole_day_without_private_text(self):
        doc, _raw, payload, db, store = self.setup_audio()
        descriptor = store.work(db.now)
        self.assertEqual(descriptor['state'], 'pending')
        self.assertEqual(descriptor['fingerprint'], doc['fingerprint'])
        self.assertNotIn('summary', descriptor)
        self.assertNotIn('data', descriptor)
        store.put(payload)
        self.assertEqual(store.work(db.now)['state'], 'already_stored')
        second = whole_report(version=2, summary='更新的合成摘要。')
        db.seed(second)
        updated = store.work(db.now)
        self.assertEqual((updated['version'], updated['state']), (2, 'pending'))
        self.assertEqual(updated['fingerprint'], second['fingerprint'])

    def test_work_does_not_fall_back_to_old_missing_assets_or_create_future_work(self):
        doc, _raw, _payload, db, store = self.setup_audio()
        old = whole_report(workday='2026-10-04')
        db.seed(old)
        del db.reports[(doc['period']['key'], doc['fingerprint'])]
        self.assertEqual(store.work(db.now)['state'], 'no_due_report')
        before_cutoff = period('2026-10-05', 'whole_day').cutoff - timedelta(seconds=1)
        self.assertEqual(store.work(before_cutoff)['fingerprint'], old['fingerprint'])

    def test_future_report_generation_and_predating_observation_reject(self):
        doc, _raw, payload, db, store = self.setup_audio()
        db.reports[(doc['period']['key'], doc['fingerprint'])]['generatedAt'] = (db.now + timedelta(seconds=1)).isoformat()
        with self.assertRaises(AlphaError):
            store.put(payload)
        doc, _raw, payload, db, store = self.setup_audio()
        bad = dict(payload, observedAt=(datetime.fromisoformat(doc['generatedAt']) - timedelta(seconds=1)).isoformat())
        with self.assertRaises(AlphaError):
            store.put(bad)
        self.assertEqual(db.assets, {})


if __name__ == '__main__':
    unittest.main()
