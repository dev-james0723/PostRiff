"""Bounded, non-executing document text extraction for Universal Library."""
import csv,html,io,json,re,zipfile
from html.parser import HTMLParser
from pathlib import PurePosixPath
from xml.etree import ElementTree as ET
from postriff_alpha.domain import AlphaError
MAX_FILE_BYTES=50*1024*1024
MAX_TEXT=2_000_000
CHUNK=6000
MIMES={"txt":{"text/plain"},"md":{"text/markdown","text/plain"},"markdown":{"text/markdown","text/plain"},"html":{"text/html"},"htm":{"text/html"},"json":{"application/json","text/json"},"csv":{"text/csv","application/csv","text/plain"},"pdf":{"application/pdf"},"docx":{"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},"xlsx":{"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},"pptx":{"application/vnd.openxmlformats-officedocument.presentationml.presentation"}}
LEGACY = {'doc','xls','ppt','odt','ods','odp','rtf'}
MIMES.update({
 'doc': {'application/msword','application/vnd.ms-word'},
 'xls': {'application/vnd.ms-excel'},
 'ppt': {'application/vnd.ms-powerpoint'},
 'odt': {'application/vnd.oasis.opendocument.text'},
 'ods': {'application/vnd.oasis.opendocument.spreadsheet'},
 'odp': {'application/vnd.oasis.opendocument.presentation'},
 'rtf': {'application/rtf','text/rtf'},
})
# OS MIME registries often omit these legacy types. The isolated converter still
# validates actual source content; preserve the original stored MIME identity.
for extension in LEGACY:MIMES[extension].add('application/octet-stream')
def normalize(x):
 x=html.unescape(str(x or "")).replace("\x00","");x=re.sub(r"\r\n?","\n",x);x=re.sub(r"[ \t\f\v]+"," ",x);return re.sub(r"\n{3,}","\n\n",x).strip()[:MAX_TEXT]
def chunks(x):
 x=normalize(x);return [x[i:i+CHUNK] for i in range(0,len(x),CHUNK)] if x else []
class _HTML(HTMLParser):
 def __init__(self):super().__init__(convert_charrefs=True);self.skip=0;self.out=[]
 def handle_starttag(self,t,a):
  t=t.lower()
  if t in ("script","style","noscript","template"):self.skip+=1
  elif not self.skip and t in ("p","br","div","li","h1","h2","h3","tr"):self.out.append("\n")
 def handle_endtag(self,t):
  if t.lower() in ("script","style","noscript","template") and self.skip:self.skip-=1
 def handle_data(self,d):
  if not self.skip:self.out.append(d)
def _office(raw,ext):
 try:z=zipfile.ZipFile(io.BytesIO(raw))
 except (zipfile.BadZipFile,OSError):raise AlphaError("This Office document is damaged or unsupported.") from None
 infos=z.infolist()
 if len(infos)>2000:z.close();raise AlphaError("This Office document contains too many parts.")
 total=0
 for i in infos:
  p=PurePosixPath(i.filename);total+=i.file_size
  if p.is_absolute() or ".." in p.parts or "\\" in i.filename:z.close();raise AlphaError("This Office document contains an unsafe path.")
  if total>100*1024*1024 or (i.file_size>1024*1024 and i.file_size>max(1,i.compress_size)*100):z.close();raise AlphaError("This Office document expands beyond the safe limit.")
  if i.filename.lower().endswith(("vbaproject.bin",".exe",".js",".vbs")):z.close();raise AlphaError("Macro or executable Office content is not accepted.")
 names=[i.filename for i in infos]
 if ext=="docx":names=[n for n in names if n=="word/document.xml" or n.startswith("word/header") or n.startswith("word/footer")]
 elif ext=="xlsx":names=[n for n in names if n=="xl/sharedStrings.xml" or (n.startswith("xl/worksheets/sheet") and n.endswith(".xml"))]
 else:names=[n for n in names if n.startswith("ppt/slides/slide") and n.endswith(".xml")]
 out=[];size=0
 try:
  for n in names:
   try:root=ET.fromstring(z.read(n))
   except (KeyError,ET.ParseError):continue
   for node in root.iter():
    if node.tag.rsplit("}",1)[-1] in ("t","v") and node.text:
     out.append(node.text);size+=len(node.text)
     if size>=MAX_TEXT:return normalize("\n".join(out))
  return normalize("\n".join(out))
 finally:z.close()
def extract_text(raw,ext):
 if not isinstance(raw,bytes) or not raw or len(raw)>MAX_FILE_BYTES:raise AlphaError("The file is empty or too large.")
 ext=str(ext or "").lower()
 if ext not in MIMES:return "unsupported",""
 if ext in LEGACY:return extract_isolated(raw,ext)
 if ext in ("txt","md","markdown"):
  try:return "ready",normalize(raw.decode())
  except UnicodeDecodeError:raise AlphaError("This text file must be UTF-8.") from None
 if ext in ("html","htm"):
  try:p=_HTML();p.feed(raw.decode());return "ready",normalize("".join(p.out))
  except (UnicodeDecodeError,ValueError):raise AlphaError("This HTML file must be valid UTF-8.") from None
 if ext=="json":
  try:v=json.loads(raw.decode())
  except (UnicodeDecodeError,ValueError,RecursionError):raise AlphaError("This JSON file is invalid.") from None
  return "ready",normalize(json.dumps(v,ensure_ascii=False,indent=2))
 if ext=="csv":
  try:s=raw.decode("utf-8-sig")
  except UnicodeDecodeError:raise AlphaError("This CSV file must be UTF-8.") from None
  rows=[]
  try:
   for i,row in enumerate(csv.reader(io.StringIO(s))):
    if i>=10000:break
    rows.append(" | ".join(cell[:2000] for cell in row[:200]))
  except csv.Error:raise AlphaError("This CSV file is invalid.") from None
  return "ready",normalize("\n".join(rows))
 if ext=="pdf":
  # Real-world PDFs (exported slides, scanned scores) often carry small structural faults that a strict parser rejects
  # outright. Read leniently, still failing closed on files that are not PDFs, and lose only the text of a page that
  # cannot be decoded: an image-only page or an odd font must not make the whole file unusable.
  try:
   from pypdf import PdfReader
   r=PdfReader(io.BytesIO(raw),strict=False)
   if r.is_encrypted:raise AlphaError("Password-protected PDFs are not supported.")
   pages=r.pages
   if len(pages)>300:raise AlphaError("This PDF has too many pages.")
  except AlphaError:raise
  except MemoryError:raise
  except Exception:raise AlphaError("This PDF could not be read safely.") from None
  out=[];size=0
  for page in pages:
   try:x=page.extract_text() or ""
   except MemoryError:raise
   except Exception:x=""
   out.append(x);size+=len(x)
   if size>=MAX_TEXT:break
  return "ready",normalize("\n\n".join(out))
 return "ready",_office(raw,ext)

AUDIO_MIMES = {
    'wav': {'audio/wav','audio/x-wav'}, 'mp3': {'audio/mpeg','audio/mp3'},
    'm4a': {'audio/mp4','audio/x-m4a'}, 'ogg': {'audio/ogg'}, 'oga': {'audio/ogg'},
    'flac': {'audio/flac','audio/x-flac'}, 'aac': {'audio/aac'}, 'webm': {'audio/webm'},
}


def validate_audio(raw, ext):
    """Container identity only. Playback codec availability remains browser-specific."""
    valid = {
        'wav': raw[:4] == b'RIFF' and raw[8:12] == b'WAVE',
        'mp3': raw[:3] == b'ID3' or (len(raw)>1 and raw[0]==255 and raw[1]&224==224),
        'm4a': raw[4:8] == b'ftyp', 'ogg': raw[:4] == b'OggS', 'oga': raw[:4] == b'OggS',
        'flac': raw[:4] == b'fLaC', 'aac': len(raw)>1 and raw[0]==255 and raw[1]&246==240,
        'webm': raw[:4] == b'\x1aE\xdf\xa3',
    }
    if not valid.get(ext):
        raise AlphaError('This audio file does not match its declared container.',422)


def extract_isolated(raw, ext):
    """Complex formats get a killable process with CPU/address-space/output bounds."""
    import os
    import subprocess
    import sys
    if ext in LEGACY or ext == 'pdf':
        # The existing Office boundary has a credential-free environment,
        # denied network sockets, a process-group deadline, and enough bounded
        # memory/CPU for one conversion. Do not nest it in the smaller XML parser.
        # PDFs use the same child: its pdfium text reader is the engine that already renders their page previews, and
        # it reads real-world files (scans, exported slides) that trip pure-Python parsers. pypdf below is the fallback,
        # which also gives password-protected files their specific message.
        from .library_preview import extract_text_isolated
        try:
            return 'ready', normalize(extract_text_isolated(raw, ext))
        except (ValueError, OSError, subprocess.TimeoutExpired) as error:
            if ext != 'pdf':
                raise AlphaError('This document exceeded safe extraction limits or could not be read.',422) from None
            _failed(ext, 'pdfium_' + type(error).__name__)
    # Vercel installs vendored dependencies through site.addsitedir; these are
    # present in sys.path but absent from a fresh subprocess's default path.
    paths = [str(__import__('pathlib').Path(__file__).resolve().parents[1]), *sys.path]
    env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'LANG': 'C.UTF-8',
           'PYTHONPATH': os.pathsep.join(dict.fromkeys(paths)), 'PYTHONDONTWRITEBYTECODE': '1'}
    try:
        result = subprocess.run([sys.executable,'-m','postriff_phase2.library_extract',ext],input=raw,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=_budget(ext)[2],env=env,check=False)
        if result.returncode != 0 or len(result.stdout)>12*MAX_TEXT:
            _failed(ext, 'exit_%d' % result.returncode)
            raise AlphaError('This document exceeded safe extraction limits or could not be read.',422)
        data=json.loads(result.stdout)
        if data.get('error'):
            _failed(ext, data.get('errorClass') or 'AlphaError')
            raise AlphaError(data['error'],422)
        return data['status'],data['text'][:MAX_TEXT]
    except subprocess.TimeoutExpired:
        _failed(ext, 'timeout')
        raise AlphaError('This document exceeded safe extraction limits or could not be read.',422) from None
    except (ValueError,KeyError):
        _failed(ext, 'malformed_output')
        raise AlphaError('This document exceeded safe extraction limits or could not be read.',422) from None


def _budget(ext):
    """(CPU seconds, address space MiB, wall seconds) for one isolated extraction. Multi-page PDFs need more room than
    the small XML formats; legacy Office conversion has its own larger boundary."""
    if ext in LEGACY:
        return 40, 1536, 60
    if ext == 'pdf':
        return 20, 1024, 30
    return 10, 384, 20


def _failed(ext, error_class):
    """Content-free diagnostics: the format and the failure class, never file names or text."""
    print(json.dumps({'event': 'library.extract_failed', 'ext': str(ext)[:12], 'errorClass': str(error_class)[:60]}), flush=True)


if __name__ == '__main__':
    import sys
    try:
        import resource
        budget = _budget(sys.argv[1])
        resource.setrlimit(resource.RLIMIT_CPU,(budget[0],budget[0]))
        try:
            resource.setrlimit(resource.RLIMIT_AS,(budget[1]*1024*1024,budget[1]*1024*1024))
        except (ValueError,OSError):
            pass  # macOS rejects RLIMIT_AS; Linux (production, CI) enforces it. CPU and output bounds still apply.
        raw=sys.stdin.buffer.read(MAX_FILE_BYTES+1)
        status,text=extract_text(raw,sys.argv[1])
        print(json.dumps({'status':status,'text':text}))
    except AlphaError as e:
        print(json.dumps({'error':str(e)[:300],'errorClass':'AlphaError'}))
    except MemoryError:
        print(json.dumps({'error':'This document needs more memory than safe extraction allows.','errorClass':'MemoryError'}))
    except Exception as e:
        print(json.dumps({'error':'This document could not be read safely.','errorClass':type(e).__name__[:60]}))
