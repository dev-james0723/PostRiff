"""Opt-in analytical event projection. Not mounted in Control HTTP or the copilot registry.

Sources invoke this only after their existing signature/auth/receipt checks. No provider
dispatch, polling, notification or financial mutation is performed here.
"""
import hashlib
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from .auth import ControlError
from .intelligence import canonical
from .metrics import validate_event


class Projector:
    def __init__(self, factory, environment):
        self.factory,self.environment=factory,environment

    def ingest(self, event):
        validate_event(event,self.environment)
        lineage={key:event[key] for key in ('source','sourceEventId','environment','eventType','eventTime','subject','classification','dedupeKey','payload','fixture')}
        digest=hashlib.sha256(canonical(lineage).encode()).hexdigest()
        with self.factory() as con:
            con.row_factory=dict_row
            with con.transaction():
                role=con.execute('SELECT current_user AS name,rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user').fetchone()
                if role['name']!='rafii_control_ingest' or role['rolsuper'] or role['rolbypassrls']:raise ControlError('SCOPE_DENIED')
                con.execute("SET LOCAL statement_timeout='5s'")
                con.execute("SELECT set_config('rafii_control.environment',%s,true)",(self.environment,))
                row=con.execute('INSERT INTO rafii_control.normalized_events(event_id,environment,source,source_event_id,event_type,dedupe_key,event_time,received_at,subject_type,subject_id,classification,payload,payload_digest,fixture) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING event_id',
                                (event['eventId'],self.environment,event['source'],event['sourceEventId'],event['eventType'],event['dedupeKey'],event['eventTime'],event['receivedAt'],event['subject']['type'],event['subject']['id'],event['classification'],Jsonb(event['payload']),digest,event['fixture'])).fetchone()
                if not row:
                    previous=con.execute('SELECT payload_digest FROM rafii_control.normalized_events WHERE source=%s AND source_event_id=%s OR dedupe_key=%s OR event_id=%s',(event['source'],event['sourceEventId'],event['dedupeKey'],event['eventId'])).fetchall()
                    if not previous or any(item['payload_digest']!=digest for item in previous):raise ControlError('IDEMPOTENCY_CONFLICT',409)
                    return False
                con.execute('INSERT INTO rafii_control.ingestion_cursors(environment,source,received_watermark) VALUES(%s,%s,%s) ON CONFLICT(environment,source) DO UPDATE SET received_watermark=greatest(ingestion_cursors.received_watermark,excluded.received_watermark),projected_at=now()', (self.environment,event['source'],event['receivedAt']))
                # Historical replay deliberately cannot publish alerts or mutate canonical domain sources.
                return True
