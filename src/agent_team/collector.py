"""Bounded local evidence collection. No prompts, transcript/audio uploads or task dispatch."""
from datetime import datetime, timedelta, timezone
import hashlib
import plistlib
from pathlib import Path
from .events import Event, Journal, canonical
from .observers import TypelessConfig, TypelessObserver, LuciObserver, ObservationBatch
from .periods import aware

TYPELESS_DB=Path.home()/'Library/Application Support/Typeless/typeless.db'
LUCI_SHIM=Path.home()/'.luciMicrosoft/bin/luci'
TYPELESS_INFO=Path('/Applications/Typeless.app/Contents/Info.plist')


def from_observation(observation):
    d=observation.cloud_projection();m=d['metadata']
    payload={'kind':d['event_type']}
    # Receipt time is not evidence that the underlying activity was recent.
    if d['updated_at'] or d['occurred_at']:payload['sourceFreshAt']=d['updated_at'] or d['occurred_at']
    if 'text_length' in m:payload['textLength']=m['text_length']
    if 'audio_exists' in m and observation.local_reference.get('audio_path'):payload['audioAvailable']=m['audio_exists']
    if m.get('text_hash'):payload['sha']=m['text_hash']
    if d['source']=='claude':payload['reportedState']='error_observed' if m.get('is_error') else 'message_observed'
    if d['source']=='luci' and 'app_kind' in m and 'context_signal' in m:
        payload.update(app=m['app_kind'], reportedState=m['context_signal'],
                       origin='read_only_luci_capture_context', verified=False)
    return Event(d['source'],d['source_ref'],d['source_version'],d['occurred_at'] or d['updated_at'] or d['observed_at'],d['observed_at'],payload)


def coverage_event(source,batch,observed_at,start_at,end_at):
    """Record scan receipt time separately from a verified scan watermark.

    Only a successful, gap-free finished bounded query gets sourceFreshAt.
    This watermark describes a source scan, including an empty result, not the
    latest activity or daily/whole-mission coverage. Failure or an unfinished
    scan leaves source freshness unknown; observed_at still records the scan.
    """
    gaps=list(batch.gaps)+['bounded_scan_only']
    payload={'kind':'source_coverage','sourceStatus':batch.status,
             'scanComplete':False,'gaps':gaps,'count':batch.scanned}
    if batch.status=='ok' and batch.complete is True and not batch.gaps:
        payload['sourceFreshAt']=observed_at
    else:gaps.append('source_freshness_unknown')
    revision=hashlib.sha256(canonical([source,start_at,end_at,observed_at,payload]).encode()).hexdigest()
    return Event('health',source,revision,observed_at,observed_at,payload)


def collect_once(journal,now=None,*,typeless=True,luci=False,window_seconds=1800,
                 typeless_observer=None,luci_observer=None,max_pages=4):
    now=aware(now or datetime.now(timezone.utc));start=now-timedelta(seconds=window_seconds)
    if not 1<=window_seconds<=3600 or not 1<=max_pages<=4:raise ValueError('collector_bounds')
    start_at,end_at=start.isoformat(),now.isoformat();batches={};added=0
    if typeless:
        if typeless_observer is None:
            with TYPELESS_INFO.open('rb') as f:version=plistlib.load(f)['CFBundleShortVersionString']
            typeless_observer=TypelessObserver(TypelessConfig(TYPELESS_DB,TYPELESS_DB,version))
        cursor=journal.cursor('typeless');items=[];gaps=set();scanned=0;last=None
        # Page continuation uses frozen bounds. An older unfinished cursor must
        # finish in its original bounded window; never silently discard it.
        if cursor and cursor.get('window_start'):
            start_at=cursor['window_start'];end_at=cursor['window_end']
        for _ in range(max_pages):
            last=typeless_observer.poll(start_at=start_at,end_at=end_at,cursor=cursor,limit=50)
            items.extend(last.observations);scanned+=last.scanned;gaps.update(last.gaps)
            added+=journal.ingest([from_observation(x) for x in last.observations],source='typeless',cursor=last.cursor)
            cursor=last.cursor
            if last.complete or last.status not in {'ok','partial'}:break
        successful=last.status in {'ok','partial'}
        complete=successful and last.complete is True
        if complete:gaps.discard('page_remaining')
        status='partial' if successful and (gaps or not complete) else last.status
        batches['typeless']=ObservationBatch(status,tuple(items),cursor,tuple(sorted(gaps)),scanned,complete)
    if luci:
        adapter=luci_observer or LuciObserver(LUCI_SHIM,LUCI_SHIM)
        batch=adapter.poll(start_ms=int(start.timestamp()*1000),end_ms=int(now.timestamp()*1000),limit=20)
        added+=journal.ingest([from_observation(x) for x in batch.observations])
        batches['luci']=batch
    observed_at=datetime.now(timezone.utc).isoformat()
    for source,batch in batches.items():added+=journal.ingest([coverage_event(source,batch,observed_at,start_at,end_at)])
    return {'executionState':'real_local_read_only','observedAt':observed_at,'added':added,
            'sources':{k:{'status':v.status,'observations':len(v.observations),'scanned':v.scanned,
                'gaps':list(v.gaps),'boundedScanComplete':v.complete,'dailyCoverageComplete':False} for k,v in batches.items()},
            'cloudUpload':'not_requested','taskDispatch':'not_requested'}


def coverage_from_journal(events):
    """Recover health metadata; failed legacy receipts cannot claim freshness.

    scannedAt is the health event receipt time. freshAt may be a documented
    bounded-scan watermark, and never establishes activity or daily coverage.
    """
    sources={}
    for e in events:
        if e['source']=='health' and e['payload'].get('kind')=='source_coverage':
            p=e['payload'];status=p['sourceStatus'];gaps=p['gaps']
            successful=status in {'ok','partial'}
            sources[e['source_id']]={'status':status,
                'freshAt':p.get('sourceFreshAt') if successful else None,
                'scannedAt':e['observed_at'],
                'complete':successful and p['scanComplete'] is True and 'bounded_scan_only' not in gaps,
                'gaps':gaps}
    return sources
