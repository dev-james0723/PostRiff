"""Normalized Universal Library file service."""
import hashlib,json,re,time,uuid
from postriff_alpha.domain import AlphaError
from .permissions import require
from .library_extract import MIMES,MAX_FILE_BYTES,MAX_TEXT,chunks,extract_text,normalize
TOKEN_SECONDS=7200;SWEEP_MARGIN=86400
FILENAME=re.compile(r"^[^/\\\x00-\x1f]{1,255}$");EXT=re.compile(r"^[a-z0-9]{1,12}$");ASSET_ID=re.compile(r"^[0-9a-f]{32}$")
def _member(row):
 from .permissions import Membership
 return Membership.from_row(*row[2:7])
def _type(name,mime):
 if not isinstance(name,str) or not FILENAME.fullmatch(name.strip()) or name.strip() in (".",".."):raise AlphaError("Choose a file with a valid name.")
 name=name.strip();ext=name.rsplit(".",1)[-1].lower() if "." in name else "";mime=str(mime or "").split(";",1)[0].strip().lower()
 if not EXT.fullmatch(ext):raise AlphaError("This file needs a simple extension.")
 allowed=MIMES.get(ext)
 if allowed is None:
  if mime!="application/octet-stream":raise AlphaError("Upload unsupported formats as generic binary files.")
  return name,ext,mime,"file"
 if mime not in allowed:raise AlphaError("The file extension and content type do not match.")
 return name,ext,mime,"document"
class UniversalLibrary:
 def __init__(self,service,storage=None,clock=None,bucket="postriff-library"):self.service=service;self.storage=storage;self.clock=clock or time.time;self.bucket=bucket
 def _store(self):
  if self.storage is None:raise AlphaError("File uploads aren't available yet.",503,code="library_storage_not_configured")
  return self.storage
 def _row(self,cur,w,i,lock=False):
  if not isinstance(i,str) or not ASSET_ID.fullmatch(i):raise AlphaError("File unavailable.",404)
  cur.execute("SELECT id::text,created_by::text,original_filename,display_title,title_source,summary,tags,kind,mime,extension,bytes,sha256,bucket,object_name,etag,processing_status,analysis_status,indexing_status,extract(epoch from created_at),provenance FROM public.pr_library_assets WHERE workspace_id=%s AND replace(id::text,'-','')=%s"+(" FOR UPDATE" if lock else ""),(w,i));r=cur.fetchone()
  if not r:raise AlphaError("File unavailable.",404)
  k=("id","createdBy","originalFilename","displayTitle","titleSource","summary","tags","kind","mime","extension","bytes","sha256","bucket","objectName","etag","processingStatus","analysisStatus","indexingStatus","createdAt","provenance");a=dict(zip(k,r));a["id"]=a["id"].replace("-","");a["tags"]=list(a["tags"] or []);a["createdAt"]=float(a["createdAt"]);return a
 def begin(self,w,t,b):
  b=b if isinstance(b,dict) else {};name,ext,mime,kind=_type(b.get("filename"),b.get("mime"));size=b.get("bytes")
  if type(size) is not int or not 0<size<=MAX_FILE_BYTES:raise AlphaError("This file is empty or over 50 MB.")
  i=uuid.uuid4().hex;o=f"{i}.{ext}";s=self._store()
  with self.service.repository.transaction(t,w) as (cur,row,p):
   require(_member(row),"edit");cur.execute("SELECT count(*) FROM public.pr_library_assets WHERE workspace_id=%s AND processing_status='pending'",(w,))
   if int(cur.fetchone()[0])>=8:raise AlphaError("Finish or remove pending file uploads first.",409)
   cur.execute("INSERT INTO public.pr_library_assets(id,workspace_id,created_by,original_filename,display_title,title_source,kind,mime,extension,bytes,bucket,object_name,token_expires_at,provenance) VALUES(%s,%s,%s,%s,%s,'filename',%s,%s,%s,%s,%s,%s,now()+make_interval(secs=>%s),%s::jsonb)",(i,w,p,name,name.rsplit('.',1)[0][:160],kind,mime,ext,size,self.bucket,o,TOKEN_SECONDS,json.dumps({"source":"upload"})))
  return {"upload":{"assetId":i,"url":s.signed_upload_url(w,"file",o),"mime":mime,"bytes":size,"filename":name,"expiresIn":TOKEN_SECONDS}}
 def commit(self,w,t,i):
  s=self._store()
  with self.service.repository.transaction(t,w) as (cur,row,p):
   require(_member(row),"edit");a=self._row(cur,w,i,True)
   if a["processingStatus"] in ("ready","unsupported"):return {"asset":a,"status":a["processingStatus"]}
   if a["processingStatus"]!="pending":raise AlphaError("This upload is not waiting to be finished.",409)
   if a["createdBy"]!=p:raise AlphaError("Only the uploader can finish this file.",403)
   info=s.object_info(w,"file",a["objectName"])
   if info.get("bytes")!=a["bytes"] or info.get("mime")!=a["mime"] or not info.get("etag"):raise AlphaError("The uploaded file does not match its declared identity.",409)
  raw=s.get_bounded(w,"file",a["objectName"],MAX_FILE_BYTES)
  if len(raw)!=a["bytes"]:raise AlphaError("The uploaded file changed before verification.",409)
  digest=hashlib.sha256(raw).hexdigest()
  try:status,text=extract_text(raw,a["extension"]);parts=chunks(text);proc="ready" if status=="ready" else "unsupported";idx="ready" if parts or status=="ready" else "not_applicable";summary=normalize(text)[:360] or None;err=None
  except AlphaError as e:parts=[];proc="failed";idx="failed";summary=None;err=str(e)[:300]
  with self.service.repository.transaction(t,w) as (cur,row,p):
   require(_member(row),"edit");self._row(cur,w,i,True);cur.execute("DELETE FROM public.pr_library_chunks WHERE workspace_id=%s AND asset_id=%s",(w,uuid.UUID(hex=i)))
   for n,x in enumerate(parts):cur.execute("INSERT INTO public.pr_library_chunks(asset_id,workspace_id,ordinal,text) VALUES(%s,%s,%s,%s)",(uuid.UUID(hex=i),w,n,x))
   cur.execute("UPDATE public.pr_library_assets SET sha256=%s,etag=%s,processing_status=%s,analysis_status='not_applicable',indexing_status=%s,summary=%s,extraction_error=%s,token_expires_at=null,updated_at=now() WHERE workspace_id=%s AND id=%s",(digest,info["etag"],proc,idx,summary,err,w,uuid.UUID(hex=i)));a=self._row(cur,w,i)
  return {"asset":a,"status":proc}
 def detail(self,w,t,i):
  with self.service.repository.transaction(t,w) as (cur,row,p):
   require(_member(row),"read");a=self._row(cur,w,i);cur.execute("SELECT ordinal,text FROM public.pr_library_chunks WHERE workspace_id=%s AND asset_id=%s ORDER BY ordinal LIMIT 400",(w,uuid.UUID(hex=i)));parts=[{"ordinal":int(n),"text":x} for n,x in cur.fetchall()]
  return {"asset":a,"chunks":parts,"extractedText":"\n".join(x["text"] for x in parts)[:MAX_TEXT]}
 def rename(self,w,t,i,title):
  if not isinstance(title,str) or not 1<=len(title.strip())<=160:raise AlphaError("Use a title from 1 to 160 characters.")
  with self.service.repository.transaction(t,w) as (cur,row,p):
   require(_member(row),"edit");self._row(cur,w,i,True);cur.execute("UPDATE public.pr_library_assets SET display_title=%s,title_source='user',updated_at=now() WHERE workspace_id=%s AND id=%s",(title.strip(),w,uuid.UUID(hex=i)));return {"asset":self._row(cur,w,i)}
 def url(self,w,t,i):
  with self.service.repository.transaction(t,w) as (cur,row,p):require(_member(row),"read");a=self._row(cur,w,i)
  if a["processingStatus"] not in ("ready","unsupported"):raise AlphaError("This file is not ready.",409)
  return {"url":self._store().signed_url(w,"file",a["objectName"]),"mime":a["mime"],"filename":a["originalFilename"]}
 def delete(self,w,t,i):
  s=self._store()
  with self.service.repository.transaction(t,w) as (cur,row,p):require(_member(row),"edit");a=self._row(cur,w,i,True);cur.execute("UPDATE public.pr_library_assets SET processing_status='deleting' WHERE workspace_id=%s AND id=%s",(w,uuid.UUID(hex=i)))
  s.delete(w,"file",a["objectName"])
  with self.service.repository.transaction(t,w) as (cur,row,p):cur.execute("DELETE FROM public.pr_library_assets WHERE workspace_id=%s AND id=%s",(w,uuid.UUID(hex=i)))
  return {"assetId":i,"status":"deleted"}
 def list(self,w,t,query="",limit=100):
  limit=max(1,min(int(limit or 100),200));query=str(query or "").strip()[:120]
  with self.service.repository.transaction(t,w) as (cur,row,p):
   require(_member(row),"read")
   if query:cur.execute("WITH q AS (SELECT plainto_tsquery('simple',%s) q),h AS (SELECT a.id,max(ts_rank(c.search_vector,q.q)) rank FROM public.pr_library_assets a LEFT JOIN public.pr_library_chunks c ON c.asset_id=a.id AND c.workspace_id=a.workspace_id,q WHERE a.workspace_id=%s AND (c.search_vector@@q.q OR to_tsvector('simple',coalesce(a.display_title,'')||' '||a.original_filename||' '||coalesce(a.summary,''))@@q.q) GROUP BY a.id) SELECT replace(a.id::text,'-',''),a.original_filename,a.display_title,a.title_source,a.summary,a.tags,a.kind,a.mime,a.extension,a.bytes,a.sha256,a.processing_status,a.analysis_status,a.indexing_status,extract(epoch from a.created_at),a.created_by::text FROM h JOIN public.pr_library_assets a ON a.id=h.id ORDER BY h.rank DESC,a.created_at DESC LIMIT %s",(query,w,limit))
   else:cur.execute("SELECT replace(id::text,'-',''),original_filename,display_title,title_source,summary,tags,kind,mime,extension,bytes,sha256,processing_status,analysis_status,indexing_status,extract(epoch from created_at),created_by::text FROM public.pr_library_assets WHERE workspace_id=%s AND processing_status<>'deleting' ORDER BY created_at DESC LIMIT %s",(w,limit))
   rows=cur.fetchall()
  keys=("id","originalFilename","displayTitle","titleSource","summary","tags","kind","mime","extension","bytes","hash","processing","analysisStatus","indexingStatus","createdAt","uploadedBy");assets=[]
  for r in rows:
   a=dict(zip(keys,r));a["tags"]=list(a["tags"] or []);a["createdAt"]=float(a["createdAt"]);a["assetKind"]=a["kind"];a["hash"]=a["hash"] or "";a["deleted"]=False;assets.append(a)
  snap=self.service.repository.get(w,t)
  legacy=[{**a,"assetKind":"video" if str(a.get("mime") or "").startswith("video/") else "image"} for a in snap["state"].get("phase2",{}).get("assets",[]) if not a.get("deleted") and not a.get("deletionPending")]
  return {"assets":legacy+assets,"query":query}
 def sweep(self,connect,limit=100):
  s=self._store()
  with connect() as db,db.cursor() as cur:cur.execute("SELECT workspace_id::text,replace(id::text,'-',''),object_name FROM public.pr_library_assets WHERE (processing_status='pending' AND token_expires_at+make_interval(secs=>%s)<now()) OR processing_status='deleting' ORDER BY token_expires_at NULLS FIRST LIMIT %s FOR UPDATE SKIP LOCKED",(SWEEP_MARGIN,limit));due=cur.fetchall()
  removed=failed=0
  for w,i,o in due:
   try:
    s.delete(w,"file",o)
    with connect() as db,db.cursor() as cur:cur.execute("DELETE FROM public.pr_library_assets WHERE workspace_id=%s AND id=%s",(w,uuid.UUID(hex=i)))
    removed+=1
   except Exception:failed+=1
  return {"removed":removed,"failed":failed}
 def purge_workspace(self,cur,w):
  cur.execute("SELECT object_name FROM public.pr_library_assets WHERE workspace_id=%s",(w,))
  for (o,) in cur.fetchall():self._store().delete(w,"file",o)
  for p in self._store().list_prefix(f"{w}/file",bucket=self.bucket):self._store().delete(w,"file",p.rsplit("/",1)[-1])
  cur.execute("DELETE FROM public.pr_library_assets WHERE workspace_id=%s",(w,))
