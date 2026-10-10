"""Real disposable PostgreSQL and file parsers; storage/identity are synthetic."""
import runpy
from pathlib import Path
base=runpy.run_path(str(Path(__file__).with_name('postgres_library.py')))
globals().update({k:v for k,v in base.items() if not k.startswith('__')})
from library_samples import samples, viewer_pdf
from postriff_phase2.library_extract import MIMES,AUDIO_MIMES
from postriff_phase2.site_agent.tools import Context
from postriff_phase2.site_agent.library_reads import library_read,library_search
from postriff_phase2.permissions import Membership

ids={}
for ext,raw in samples().items():
    mime=sorted((MIMES.get(ext) or AUDIO_MIMES.get(ext) or {'application/octet-stream'}))[0]
    item=library.begin(wid,'one',{'filename':'sample.'+ext,'mime':mime,'bytes':len(raw)})['upload'];i=item['assetId'];ids[ext]=i
    storage.put(wid,i+'.'+ext,raw,mime)
    result=library.commit(wid,'one',i)
    if result['status']=='queued':library.process(connection,wid,i)
    detail=library.detail(wid,'one',i)
    expected='unsupported' if ext in ('bin','wav') else 'ready'
    check(ext+': real parser status',detail['asset']['processing']==expected or detail['asset']['processing']=='duplicate',detail)
    if ext not in ('bin','wav') and detail['asset']['processing']!='duplicate':
        check(ext+': extracted acceptance text','Brahms' in detail['extractedText'],detail)
    check(ext+': signed private original',library.url(wid,'one',i,True)['url'].startswith('https://') if detail['asset']['processing']!='duplicate' else True)

# Previously stored legacy documents retain their exact storage identity and gain
# an explicit indexing action after the renderer upgrade; no bulk data migration.
legacy=b'{\\rtf1\\ansi Legacy archive Brahms upgrade marker.}'
legacy_upload=library.begin(wid,'one',{'filename':'historical.rtf','mime':'application/rtf','bytes':len(legacy)})['upload'];legacy_id=legacy_upload['assetId']
storage.put(wid,legacy_id+'.rtf',legacy,'application/octet-stream')
with connection() as db:
    db.execute("UPDATE public.pr_library_assets SET kind='file',mime='application/octet-stream',processing_status='unsupported',indexing_status='not_applicable',etag=%s WHERE id=%s",(storage.object_info(wid,'file',legacy_id+'.rtf')['etag'],legacy_id))
check('historical legacy offers scoped indexing',library.detail(wid,'one',legacy_id)['asset']['canRetryProcessing'])
check('historical legacy indexing completes',library.retry(wid,'one',legacy_id)['status']=='ready')
legacy_detail=library.detail(wid,'one',legacy_id)
check('historical storage identity preserved',legacy_detail['asset']['assetKind']=='file' and legacy_detail['asset']['mime']=='application/octet-stream')
check('historical legacy source content searchable',any(x['id']==legacy_id for x in library.list(wid,'one','upgrade marker')['assets']))
for unchanged in (ids['bin'],ids['wav']):
    check('unsupported generic/audio cannot reindex automatically',not library.detail(wid,'one',unchanged)['asset']['canRetryProcessing'])
    try:library.retry(wid,'one',unchanged);raise AssertionError('Unsupported content retry escaped')
    except AlphaError as e:check('unsupported retry denied',e.status==409)

# Explicit retry processes only this bounded source, even without a cron scheduler.
reader=viewer_pdf()
reader_upload=library.begin(wid,'one',{'filename':'reader.pdf','mime':'application/pdf','bytes':len(reader)})['upload'];reader_id=reader_upload['assetId']
storage.put(wid,reader_id+'.pdf',reader,'application/pdf')
check('small document is read during its own upload',library.commit(wid,'one',reader_id)['status']=='ready')
with connection() as db:
    db.execute("UPDATE public.pr_library_assets SET processing_status='failed',indexing_status='failed',extraction_error='Earlier read failed.' WHERE id=%s",(reader_id,))
check('explicit small-document retry completes extraction',library.retry(wid,'one',reader_id)['status']=='ready')
reader_first=library.viewer_page(wid,'one',reader_id,1);reader_second=library.viewer_page(wid,'one',reader_id,2)
check('private viewer retrieves two actual distinct pages',reader_first['pageCount']==2 and 'Brahms' in reader_first['text'] and 'Mozart' in reader_second['text'] and reader_first['url']!=reader_second['url'])
reader_thumbs=[library._preview_object({'id':reader_id,'sha256':hashlib.sha256(reader).hexdigest()},n) for n in (1,2)]
library.delete(wid,'one',reader_id)
check('deletion removes every rendered page',all((wid,name) not in storage.objects for name in reader_thumbs))

# Search has no dependence on title and supports CJK substrings.
text=b'Unique lifecycle search marker.\nSecond fact for permission test.'
item=library.begin(wid,'one',{'filename':'context.txt','mime':'text/plain','bytes':len(text)})['upload'];i=item['assetId']
storage.put(wid,i+'.txt',text,'text/plain');library.commit(wid,'one',i)
preview=library.preview(wid,'one',i)
check('actual JPEG page preview',preview['mime']=='image/jpeg' and preview['page']==1)
thumb=library.detail(wid,'one',i)['asset']['provenance']['thumbnail']['objectName']
check('preview stores actual raster bytes',storage.objects[(wid,thumb)][0].startswith(b'\xff\xd8'))
check('preview cache reuses immutable object',library.preview(wid,'one',i)==preview)
page=library.viewer_page(wid,'one',i,1)
check('viewer returns actual page text and dimensions',page['pageCount']==1 and page['page']==1 and page['width']>500 and 'Unique lifecycle' in page['text'])
try:library.viewer_page(wid,'one',i,2);raise AssertionError('Invalid viewer page escaped')
except AlphaError as e:check('viewer page bounds',e.status==422)
used=library.list(wid,'one')['storage']['usedBytes']
check('rendered page bytes count toward workspace storage',used>=len(text)+len(storage.objects[(wid,thumb)][0]))
try: library.preview(viewer_workspace,'viewer',i); raise AssertionError('Cross-workspace preview escaped')
except AlphaError as e: check('preview workspace isolation',e.status in (403,404))
check('full text search',any(x['id']==i for x in library.list(wid,'one','lifecycle search')['assets']))
collection=library.collections(wid,'one',{'name':'Rehearsal'})['collections'][0]['id']
library.metadata(wid,'one',i,{'title':'Session notes','tags':['practice','Brahms'],'collections':[collection]})
check('organization filters',len(library.list(wid,'one',tag='practice',collection=collection)['assets'])==1)
check('pagination',library.list(wid,'one',limit=1)['nextOffset']==1)
check('kind filter',all(x['assetKind']=='audio' for x in library.list(wid,'one',kind='audio')['assets']))
before=service.get(wid,'one')['revision'];imported=library.as_source(wid,'one',i,{'expectedRevision':before});source_id=imported['sourceId']

def read_tool():
    with service.repository.transaction('one',wid) as (cur,row,p):
        return library_read(Context(state=library.service.ideas._state(row),membership=Membership.from_row(*row[2:7]),principal=p,workspace_id=wid,cur=cur,service=service),i)
try:read_tool();raise AssertionError('Unapproved private facts escaped')
except AlphaError as e:check('AI denies unreviewed or unshared source',e.status==404)
def approve(state,actor):
    source=next(s for s in state['sources'] if s['id']==source_id)
    source['facts'][0]['approved']=True;source['egressConsent']=['local','cloud']
    return state
service.repository.command(wid,'one',service.get(wid,'one')['revision'],approve)
result=read_tool()
check('AI retrieval keeps provenance',result['data']['sourceId']==source_id and result['data']['sha256']==hashlib.sha256(text).hexdigest(),result)
check('AI retrieval approved facts only',len(result['data']['facts'])==1,result)
library.delete(wid,'one',i)
check('delete removes page preview',(wid,thumb) not in storage.objects)
try: library.preview(wid,'one',i); raise AssertionError('Deleted preview escaped')
except AlphaError as e: check('deleted preview unavailable',e.status==404)
source=next(s for s in service.get(wid,'one')['state']['sources'] if s['id']==source_id)
check('deletion retracts AI source',not source['active'] and not source['facts'])

audio=ids['wav'];library.transcript(wid,'one',audio,'Transcribed cello bowing acceptance marker.')
check('audio transcript indexed',any(x['id']==audio for x in library.list(wid,'one','bowing acceptance')['assets']))
source_id2=library.as_source(wid,'one',audio,{'expectedRevision':service.get(wid,'one')['revision']})['sourceId']
library.transcript(wid,'one',audio,'Replacement transcript. Old words must disappear.')
check('transcript replacement withdraws old source',not next(s for s in service.get(wid,'one')['state']['sources'] if s['id']==source_id2)['active'])
check('old transcript no longer searchable',not library.list(wid,'one','bowing acceptance')['assets'])
# Free on-device recognition never replaces a person's transcript, and only it may report "no speech".
library.transcript(wid,'one',audio,'Automatic words that must not win.',source='browser_whisper')
check('automatic transcript keeps the person\'s own',library.detail(wid,'one',audio)['asset']['transcriptSource']=='user_supplied' and not library.list(wid,'one','must not win')['assets'])
try: library.transcript(wid,'one',audio,None,speech='none'); check('no-speech needs an automatic source',False)
except AlphaError as e: check('no-speech needs an automatic source',e.status==400)
try: library.transcript(wid,'one',audio,'x',source='paid_cloud'); check('unknown transcript source rejected',False)
except AlphaError as e: check('unknown transcript source rejected',e.status==400)

# Storage failure retries, immutable identity, crashed worker lease, dedup and account freeze.
raw=b'Background queue recovery marker'
item=library.begin(wid,'one',{'filename':'queued.txt','mime':'text/plain','bytes':len(raw)})['upload'];j=item['assetId'];storage.put(wid,j+'.txt',raw,'text/plain')
with connection() as db:db.execute("UPDATE public.pr_library_assets SET processing_status='queued',etag=%s WHERE id=%s",(storage.object_info(wid,'file',j+'.txt')['etag'],j))
original=storage.get_bounded
storage.get_bounded=lambda *args: (_ for _ in ()).throw(AlphaError('Temporary storage failure',503))
check('transient extraction queues retry',library.process(connection,wid,j)=='retrying')
storage.get_bounded=original
with connection() as db:db.execute("UPDATE public.pr_library_assets SET next_attempt_at=now()-interval '1 second' WHERE id=%s",(j,))
check('retry recovers',library.process(connection,wid,j)=='ready')
old_limit=library.storage_limit;library.storage_limit=1
try:library.begin(wid,'one',{'filename':'cap.txt','mime':'text/plain','bytes':1});raise AssertionError('capacity bypass')
except AlphaError as e:check('workspace storage limit',e.status==413)
library.storage_limit=old_limit
for table in ('pr_library_labels','pr_library_collections','pr_library_collection_items'):
    with connection() as db:
        db.execute('SET ROLE authenticated')
        try:db.execute('SELECT * FROM public.'+table);raise AssertionError('browser read '+table)
        except psycopg.errors.InsufficientPrivilege:db.rollback()
    check(table+': browser denied',True)
print(json.dumps({'status':'pass','execution':'cloud disposable PostgreSQL; real sample bytes/parsers; synthetic storage/identity','checks':checks},indent=2))
