"""Immutable private short report audio in the existing database.

Authentication belongs to the ingress. This store accepts only bytes bound to an
already persisted, due whole-day report; it has no TTS, provider or send path.
Metadata receipts never contain report text, narration text or encoded audio.
"""
from __future__ import annotations

import base64
import binascii
from datetime import datetime, timedelta, timezone
import hashlib
import re
import time

from agent_team.periods import TZ, aware, period
from agent_team.acceptance import AcceptancePeriod, acceptance_key, document_period
from postriff_alpha.domain import AlphaError

MAX_AUDIO_BYTES = 2 * 1024 * 1024
MAX_ENCODED_BYTES = 4 * ((MAX_AUDIO_BYTES + 2) // 3)
PRODUCER = 'macos_say_sinji'
MIME = 'audio/wav'
UPLOAD_FIELDS = {'reportKey', 'fingerprint', 'version', 'summaryHash', 'narrationHash', 'excerpt',
                 'sha256', 'mime', 'producer', 'observedAt', 'data'}
METADATA_COLUMNS = ('report_key', 'fingerprint', 'report_version', 'summary_hash', 'narration_hash', 'excerpt',
                    'sha256', 'mime', 'producer', 'observed_at', 'byte_count', 'duration_ms', 'created_at')
SELECT_METADATA = ','.join(METADATA_COLUMNS)


def invalid(message='Invalid report audio upload.', status=400, code='agent_team_audio_invalid'):
    return AlphaError(message, status, code=code)


def identity(report_key, fingerprint):
    accepted = acceptance_key(report_key)
    if accepted and isinstance(fingerprint, str) and re.fullmatch(r'[0-9a-f]{64}', fingerprint):
        p = period(accepted[0], 'half_day')
        return AcceptancePeriod(p.workday, p.kind, p.start, p.cutoff, accepted[1])
    match = re.fullmatch(r'agent-team:v1:(20\d{2}-\d{2}-\d{2}):whole_day', report_key or '') if isinstance(report_key, str) else None
    if not match or not isinstance(fingerprint, str) or not re.fullmatch(r'[0-9a-f]{64}', fingerprint):
        raise invalid()
    try:
        return period(match[1], 'whole_day')
    except (TypeError, ValueError):
        raise invalid() from None


def text_hash(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def metadata(row, *, created=False):
    value = dict(zip(METADATA_COLUMNS, row))
    return {'state': 'stored', 'audioState': 'ready', 'deliveryState': 'not_proven', 'created': bool(created),
            'verificationState': 'report_hash_and_wav_format_validated',
            'reportKey': value['report_key'], 'fingerprint': value['fingerprint'], 'version': value['report_version'],
            'summaryHash': value['summary_hash'], 'narrationHash': value['narration_hash'], 'excerpt': value['excerpt'],
            'sha256': value['sha256'], 'mime': value['mime'], 'producer': value['producer'],
            'observedAt': aware(value['observed_at']).isoformat(), 'createdAt': aware(value['created_at']).isoformat(),
            'byteCount': value['byte_count'], 'durationSeconds': value['duration_ms'] / 1000,
            'sampleRate': 16000, 'channels': 1, 'sampleWidth': 2,
            'voiceIdentity': 'local_macos_sinji_zh_HK', 'clonedVoice': False}


class TeamAudioStore:
    def __init__(self, connection_factory, *, clock=time.time, validator=None, narrator=None):
        self.connection_factory, self.clock = connection_factory, clock
        self.validator, self.narrator = validator, narrator

    def _helpers(self):
        if self.validator is not None and self.narrator is not None:
            return self.validator, self.narrator
        from agent_team.audio import narration_for_report, validate_wav
        return self.validator or validate_wav, self.narrator or narration_for_report

    def _report(self, cur, report_key, fingerprint, now):
        p = identity(report_key, fingerprint)
        if not isinstance(p, AcceptancePeriod) and p.cutoff > now:
            raise invalid('This whole-day report is not due.', 409, 'agent_team_audio_not_due')
        cur.execute('SELECT document FROM public.pr_agent_team_reports WHERE report_key=%s AND fingerprint=%s',
                    (report_key, fingerprint))
        row = cur.fetchone()
        if not row:
            raise invalid('The immutable report is unavailable.', 404, 'agent_team_audio_report_missing')
        doc = row[0]
        try:
            if isinstance(p, AcceptancePeriod):
                p = document_period(doc)
                if p.key != report_key: raise ValueError('acceptance_key_mismatch')
            if (not isinstance(doc, dict) or doc.get('executionState') != 'generated'
                    or doc.get('fingerprint') != fingerprint or doc.get('period') != p.as_dict()
                    or type(doc.get('version')) is not int or not 1 <= doc['version'] <= 9_999
                    or not isinstance(doc.get('summary'), str) or not doc['summary'].strip()
                    or not p.cutoff <= aware(doc['generatedAt']) <= now):
                raise ValueError('report_not_generated')
            _, narrator = self._helpers()
            narration = narrator(doc)
            if not isinstance(narration, str) or not narration.strip():
                raise ValueError('narration_unavailable')
            summary_hash, narration_hash = text_hash(doc['summary']), text_hash(narration)
        except (KeyError, TypeError, ValueError, UnicodeError, AttributeError):
            raise invalid('Report audio contract could not be verified.', 409, 'agent_team_audio_report_invalid') from None
        return doc, summary_hash, narration_hash, narration != doc['summary']

    def _stored(self, cur, report_key, fingerprint, *, data=False):
        cur.execute(f'SELECT {SELECT_METADATA}' + (',wav_data' if data else '') +
                    ' FROM public.pr_agent_team_audio_assets WHERE report_key=%s AND fingerprint=%s',
                    (report_key, fingerprint))
        return cur.fetchone()

    def put(self, payload):
        if not isinstance(payload, dict) or set(payload) != UPLOAD_FIELDS:
            raise invalid()
        p = identity(payload['reportKey'], payload['fingerprint'])
        if (type(payload['version']) is not int or not 1 <= payload['version'] <= 9_999
                or type(payload['excerpt']) is not bool or payload['mime'] != MIME or payload['producer'] != PRODUCER
                or any(not isinstance(payload[key], str) or not re.fullmatch(r'[0-9a-f]{64}', payload[key])
                       for key in ('summaryHash', 'narrationHash', 'sha256'))):
            raise invalid()
        now = datetime.fromtimestamp(self.clock(), timezone.utc)
        if isinstance(p, AcceptancePeriod):
            with self.connection_factory() as db, db.cursor() as cur:
                document, _, _, _ = self._report(cur, p.key, payload['fingerprint'], now)
            p = document_period(document)
        try:
            observed = aware(payload['observedAt'])
        except (TypeError, ValueError, AttributeError):
            raise invalid() from None
        if observed > now or p.cutoff > observed:
            raise invalid('Audio observation is outside the due report window.', 409, 'agent_team_audio_not_due')
        encoded = payload['data']
        if not isinstance(encoded, str) or not encoded or len(encoded) > MAX_ENCODED_BYTES:
            raise invalid('Report audio exceeds the body limit.', 413, 'agent_team_audio_size')
        try:
            raw = base64.b64decode(encoded, validate=True)
            if base64.b64encode(raw).decode('ascii') != encoded:
                raise ValueError('noncanonical_base64')
        except (ValueError, binascii.Error, UnicodeError):
            raise invalid() from None
        if not raw or len(raw) > MAX_AUDIO_BYTES:
            raise invalid('Report audio exceeds the byte limit.', 413, 'agent_team_audio_size')
        if hashlib.sha256(raw).hexdigest() != payload['sha256']:
            raise invalid('Audio digest does not match.', 409, 'agent_team_audio_digest')
        validator, _ = self._helpers()
        try:
            parsed = validator(raw)
            frames = parsed['frames']
            if (parsed['sampleRate'] != 16000 or parsed['channels'] != 1 or parsed['sampleWidth'] != 2
                    or type(frames) is not int or not 1 <= frames <= 16000 * 45
                    or parsed['byteCount'] != len(raw) or parsed['sha256'] != payload['sha256']
                    or parsed['durationSeconds'] != frames / 16000):
                raise ValueError('invalid_wav_receipt')
            duration_ms = (frames * 1000 + 15999) // 16000
        except (TypeError, ValueError, KeyError, AttributeError):
            raise invalid('Audio must be nonempty PCM16 mono 16kHz WAV within 45 seconds.') from None
        with self.connection_factory() as db, db.cursor() as cur:
            cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',
                        ('agent-team-audio:' + p.key + ':' + payload['fingerprint'],))
            doc, summary_hash, narration_hash, excerpt = self._report(cur, p.key, payload['fingerprint'], now)
            if (payload['version'] != doc['version'] or payload['summaryHash'] != summary_hash
                    or payload['narrationHash'] != narration_hash or payload['excerpt'] != excerpt
                    or observed < aware(doc['generatedAt'])):
                raise invalid('Audio does not match the immutable report narration.', 409, 'agent_team_audio_report_mismatch')
            old = self._stored(cur, p.key, payload['fingerprint'])
            if old:
                if old[6] != payload['sha256'] or old[2] != payload['version'] or old[3] != summary_hash or old[4] != narration_hash or old[5] != excerpt:
                    raise invalid('This report already has another immutable audio asset.', 409, 'agent_team_audio_conflict')
                result = metadata(old)
            else:
                cur.execute('INSERT INTO public.pr_agent_team_audio_assets(report_key,fingerprint,report_version,summary_hash,narration_hash,excerpt,'
                            'sha256,mime,producer,observed_at,byte_count,duration_ms,wav_data) '
                            f'VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING {SELECT_METADATA}',
                            (p.key, payload['fingerprint'], doc['version'], summary_hash, narration_hash, excerpt,
                             payload['sha256'], MIME, PRODUCER, observed, len(raw), duration_ms, raw))
                result = metadata(cur.fetchone(), created=True)
            db.commit()
        return result

    def get(self, reportKey, fingerprint):
        """Internal stream result: metadata plus bytes. The route must authenticate."""
        identity(reportKey, fingerprint)
        with self.connection_factory() as db, db.cursor() as cur:
            row = self._stored(cur, reportKey, fingerprint, data=True)
        return (metadata(row[:-1]), bytes(row[-1])) if row else None

    def get_metadata(self, reportKey, fingerprint):
        """Stored asset receipt only; never load audio bytes for a delivery read."""
        identity(reportKey, fingerprint)
        with self.connection_factory() as db, db.cursor() as cur:
            row = self._stored(cur, reportKey, fingerprint)
        return metadata(row) if row else None

    def work(self, now):
        """One latest-due whole-day version, without an asset; no historical fanout."""
        try:
            now = aware(now)
        except (ValueError, TypeError, AttributeError):
            raise invalid() from None
        local = now.astimezone(TZ)
        workday = (local.date() - timedelta(days=1 if local.hour >= 1 else 2)).isoformat()
        p = period(workday, 'whole_day')
        with self.connection_factory() as db, db.cursor() as cur:
            cur.execute("SELECT document FROM public.pr_agent_team_reports WHERE report_key=%s "
                        "ORDER BY coalesce((document->>'version')::integer,1) DESC,generated_at DESC LIMIT 1", (p.key,))
            row = cur.fetchone()
            if not row:
                return {'state': 'no_due_report', 'audioState': 'unavailable'}
            doc = row[0]
            doc, summary_hash, narration_hash, excerpt = self._report(cur, p.key, doc.get('fingerprint'), now)
            existing = self._stored(cur, p.key, doc['fingerprint'])
        if existing:
            return {'state': 'already_stored', 'asset': metadata(existing)}
        return {'state': 'pending', 'audioState': 'audio_required', 'reportKey': p.key, 'fingerprint': doc['fingerprint'],
                'version': doc['version'], 'workday': p.workday, 'kind': p.kind,
                'summaryHash': summary_hash, 'narrationHash': narration_hash, 'excerpt': excerpt,
                'mime': MIME, 'producer': PRODUCER, 'maxSeconds': 45, 'maxBytes': MAX_AUDIO_BYTES,
                'sampleRate': 16000, 'channels': 1, 'sampleWidth': 2}

    def work_for_report(self, document, now):
        """One explicitly selected immutable acceptance; never historical fanout."""
        try:
            p = document_period(document)
            if not isinstance(p, AcceptancePeriod): raise ValueError()
        except (ValueError, TypeError, KeyError):
            raise invalid() from None
        with self.connection_factory() as db, db.cursor() as cur:
            doc, summary_hash, narration_hash, excerpt = self._report(cur, p.key, document['fingerprint'], aware(now))
            existing = self._stored(cur, p.key, doc['fingerprint'])
        if existing:
            return {'state': 'already_stored', 'asset': metadata(existing)}
        return {'state': 'pending', 'audioState': 'audio_required', 'reportKey': p.key, 'fingerprint': doc['fingerprint'],
                'version': doc['version'], 'workday': p.workday, 'kind': p.kind,
                'summaryHash': summary_hash, 'narrationHash': narration_hash, 'excerpt': excerpt,
                'mime': MIME, 'producer': PRODUCER, 'maxSeconds': 45, 'maxBytes': MAX_AUDIO_BYTES,
                'sampleRate': 16000, 'channels': 1, 'sampleWidth': 2}
