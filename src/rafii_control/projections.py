"""Opt-in analytical event projection. Not mounted in Control HTTP or the copilot registry.

Sources invoke this only after their existing signature/auth/receipt checks. No provider
dispatch, polling, notification or financial mutation is performed here.
"""
import hashlib
from datetime import timedelta
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from .auth import ControlError
from .intelligence import canonical
from .metrics import validate_event, timestamp


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
                self._materialize(con, event)
                # Historical replay deliberately cannot publish alerts or mutate canonical domain sources.
                return True

    def _materialize(self, con, event):
        # The only currently qualified adapter is local synthetic check metadata.
        # Hosted/proposed financial policies are never activated by fixture ingestion.
        if self.environment != 'local' or not event['fixture'] or event['eventType'] != 'control.engineering.check_completed': return
        receipt_id = event['payload']['receiptId']
        from .intelligence import identifier, Catalog
        identifier(receipt_id)
        if event['sourceEventId'] != receipt_id or event['subject'] != {'type':'engineering_job','id':receipt_id}: raise ControlError('VALIDATION_FAILED',400)
        receipt = con.execute("SELECT id,kind,exact_sha,conclusion,failure_class,attested,observed_at FROM rafii_control.engineering_evidence WHERE id=%s AND environment=%s",(receipt_id,self.environment)).fetchone()
        if not receipt or receipt['kind'] != 'check' or not receipt['attested'] or receipt['exact_sha'] != event['payload']['exactSha']:
            raise ControlError('SOURCE_UNAVAILABLE',503)
        # Align the event with the actual source receipt, preventing invented timestamps.
        if timestamp(event['eventTime']) != receipt['observed_at'] or len(event['source']) > 160: raise ControlError('VALIDATION_FAILED',400)
        existing = con.execute("SELECT dimensions FROM rafii_control.metric_rollups WHERE environment='local' AND fixture AND metric_id='check_failures' AND source_receipt_ids=ARRAY[%s]::uuid[]",(receipt_id,)).fetchone()
        if existing: raise ControlError('IDEMPOTENCY_CONFLICT',409)
        metric = Catalog().metrics['check_failures']
        complete = receipt['conclusion'] in ('success','failure')
        dimensions = {'suite':event['source'],'failure_class':receipt['failure_class'] or 'unknown'}
        dimension_digest = hashlib.sha256(canonical(dimensions).encode()).hexdigest()
        inserted = con.execute("INSERT INTO rafii_control.metric_rollups(environment,metric_id,definition_version,interval_start,interval_end,grain,dimension_digest,dimensions,value,currency,sample_count,source_watermark,source_receipt_ids,policy_approval_ref,data_state,fixture) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,NULL,%s,%s,%s,NULL,%s,true) ON CONFLICT DO NOTHING RETURNING metric_id",
            (self.environment,metric['id'],metric['version'],receipt['observed_at'],receipt['observed_at']+timedelta(microseconds=1),metric['grain'],dimension_digest,Jsonb(dimensions),int(receipt['conclusion']=='failure') if complete else None,int(complete),receipt['observed_at'],[receipt_id],'measured' if complete else 'partial')).fetchone()
        if not inserted: raise ControlError('IDEMPOTENCY_CONFLICT',409)
