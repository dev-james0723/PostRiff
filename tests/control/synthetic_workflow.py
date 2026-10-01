"""Synthetic source receipts only; never copied to a deployable Control artifact."""
from datetime import datetime, timezone, timedelta
import uuid
import psycopg
from rafii_control.projections import Projector
from rafii_control.store import connection_factory


def seed(dsn, prefix):
    now = datetime.now(timezone.utc)
    projector = Projector(connection_factory(dsn,'rafii_control_ingest','local'),'local')
    events = []
    with psycopg.connect(dsn,autocommit=True) as owner:
        for name,conclusion,age in [('zero','success',10),('one','failure',10),('partial','skipped',10),('stale','failure',7200)]:
            receipt = str(uuid.uuid4())
            stamp = now-timedelta(seconds=age)
            suite = prefix+'-'+name
            owner.execute("INSERT INTO rafii_control.engineering_evidence(id,environment,kind,provider,external_id,exact_sha,state,conclusion,failure_class,attested,required,observed_at) VALUES(%s,'local','check','local',%s,%s,'reproduced',%s,'test',true,true,%s)",(receipt,receipt,'a'*40,conclusion,stamp))
            event = dict(schemaVersion=1,eventId=str(uuid.uuid4()),eventType='control.engineering.check_completed',source=suite,sourceEventId=receipt,environment='local',eventTime=stamp.isoformat(),receivedAt=(stamp+timedelta(seconds=1)).isoformat(),subject={'type':'engineering_job','id':receipt},classification='internal_metadata',dedupeKey='synthetic:check:'+receipt,payload={'receiptId':receipt,'exactSha':'a'*40},fixture=True)
            projector.ingest(event)
            events.append(event)
    query = dict(metricIds=['check_failures'],interval={'start':(now-timedelta(days=28)).isoformat(),'end':(now+timedelta(seconds=5)).isoformat(),'timeZone':'UTC'},groupBy=['suite','failure_class'],filters=[{'dimension':'suite','operator':'in','values':[event['source'] for event in events]}],comparison='none',limit=100)
    return events,query
