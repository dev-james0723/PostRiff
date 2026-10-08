"""Real source-page rasterization. No summaries, icons or generated cover art.

Office source bytes -> LibreOffice first-page PDF -> PDFium JPEG.
PDF source bytes -> PDFium first-page JPEG. Text/Markdown/HTML source bytes are
typeset from the original content, then follow the same first-page raster path.
The child has no credentials, no Internet sockets, bounded CPU/memory/output,
an isolated disposable Office profile, disabled macros and disabled link updates.
"""
import io
import json
import logging
import re
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

VERSION = 'source-page-v1'
SUPPORTED = {'pdf', 'docx', 'xlsx', 'pptx', 'doc', 'xls', 'ppt', 'odt', 'ods', 'odp', 'rtf', 'txt', 'md', 'markdown', 'html', 'htm', 'csv', 'json'}
ROOT = Path(__file__).resolve().parents[2] / '.document-runtime'

def _deny_internet():
    import ctypes
    import ctypes.util
    # Fail closed: sandbox absence never quietly permits document link fetching.
    lib = ctypes.CDLL(str(ROOT / 'lib/libseccomp.so.2') if (ROOT / 'lib/libseccomp.so.2').exists() else ctypes.util.find_library('seccomp'))
    class Compare(ctypes.Structure):
        _fields_ = [('arg', ctypes.c_uint), ('op', ctypes.c_uint), ('a', ctypes.c_uint64), ('b', ctypes.c_uint64)]
    lib.seccomp_init.restype = ctypes.c_void_p
    lib.seccomp_rule_add_array.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint, ctypes.POINTER(Compare)]
    lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    lib.seccomp_load.argtypes = [ctypes.c_void_p]
    lib.seccomp_release.argtypes = [ctypes.c_void_p]
    ctx = lib.seccomp_init(0x7fff0000)
    if not ctx:
        raise RuntimeError('Preview sandbox unavailable')
    try:
        syscall = lib.seccomp_syscall_resolve_name(b'socket')
        for family in (2, 10, 17):  # IPv4, IPv6, packet sockets; local Office IPC allowed.
            cmp = Compare(0, 4, family, 0)  # SCMP_CMP_EQ
            if lib.seccomp_rule_add_array(ctx, 0x00050001, syscall, 1, ctypes.byref(cmp)) != 0:
                raise RuntimeError('Preview sandbox unavailable')
        if lib.seccomp_load(ctx) != 0:
            raise RuntimeError('Preview sandbox unavailable')
    finally:
        lib.seccomp_release(ctx)

def _safe_html(source):
    from html import escape
    from html.parser import HTMLParser
    class Clean(HTMLParser):
        allowed = {'p','br','div','span','h1','h2','h3','h4','h5','h6','strong','b','em','i','u','pre','code','blockquote','ul','ol','li','table','thead','tbody','tr','td','th','hr'}
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.out = []; self.skip = 0
        def handle_starttag(self, tag, attrs):
            if tag in {'script','style','iframe','object','embed','template'}: self.skip += 1
            elif not self.skip and tag in self.allowed: self.out.append('<'+tag+'>')
        def handle_endtag(self, tag):
            if tag in {'script','style','iframe','object','embed','template'} and self.skip: self.skip -= 1
            elif not self.skip and tag in self.allowed: self.out.append('</'+tag+'>')
        def handle_data(self, text):
            if not self.skip: self.out.append(escape(text))
    parser = Clean(); parser.feed(source)
    return '<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>'+''.join(parser.out)+'</body></html>'

def render(raw, extension, page_number=1, metadata=False):
    import pypdfium2 as pdfium
    if extension not in SUPPORTED or not raw or len(raw) > 50 * 1024 * 1024:
        raise ValueError('No first-page renderer for this file')
    if extension == 'pdf':
        pdf = raw
    else:
        with tempfile.TemporaryDirectory(prefix='rafii-page-') as temp:
            work = Path(temp)
            profile = work / 'profile/user'
            profile.mkdir(parents=True)
            (profile / 'registrymodifications.xcu').write_text('''<?xml version="1.0"?><oor:items xmlns:oor="http://openoffice.org/2001/registry"><item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop></item><item oor:path="/org.openoffice.Office.Writer/Content/Update"><prop oor:name="Link" oor:op="fuse"><value>2</value></prop></item></oor:items>''')
            ext = extension
            if ext in {'md', 'markdown', 'html', 'htm'}:
                source = raw.decode('utf-8-sig')
                if ext in {'md', 'markdown'}:
                    import markdown
                    source = markdown.markdown(source, extensions=['tables','fenced_code'])
                raw = _safe_html(source).encode(); ext = 'html'
            source = work / ('source.'+ext)
            source.write_bytes(raw)
            # Run the headless ELF directly: Vercel does not guarantee the shell
            # wrapper's dirname/grep/uname utilities or its oosplash loader.
            executable = ROOT / 'office/program/soffice.bin'
            command = str(executable) if executable.exists() else shutil.which('libreoffice')
            if not command:
                raise RuntimeError('Document renderer unavailable')
            env = {'PATH':'/usr/bin:/bin', 'LANG':'C.UTF-8', 'SAL_USE_VCLPLUGIN':'svp', 'TMPDIR':str(work)}
            if ROOT.exists():
                env['LD_LIBRARY_PATH'] = str(ROOT / 'lib')+':'+str(ROOT / 'office/program')
                fonts = work / 'fonts.conf'
                fonts.write_text('<fontconfig><dir>'+str(ROOT / 'fonts')+'</dir><cachedir>'+str(work / 'font-cache')+'</cachedir></fontconfig>')
                env['FONTCONFIG_FILE'] = str(fonts)
            result = subprocess.run([command, '-env:UserInstallation='+ (work / 'profile').as_uri(), '--headless','--invisible','--nodefault','--nolockcheck','--nologo','--norestore','--convert-to','pdf','--outdir',str(work),str(source)], env=env, cwd=work, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=45, check=False)
            output = work / 'source.pdf'
            if result.returncode or not output.exists() or output.stat().st_size > 32*1024*1024:
                missing = re.findall(rb'([A-Za-z0-9_.+-]+\.so(?:\.[0-9]+)*): cannot open shared object file', result.stderr)
                logging.warning('Office renderer failed: exit=%s pdf_present=%s missing_libraries=%s', result.returncode, output.exists(), [name.decode('ascii') for name in missing])
                raise ValueError('Document could not be rendered')
            pdf = output.read_bytes()
    with pdfium.PdfDocument(pdf) as doc:
        if not len(doc):
            raise ValueError('Document has no pages')
        page_count = len(doc)
        if type(page_number) is not int or not 1 <= page_number <= page_count:
            raise ValueError("Page outside document")
        page = doc[page_number-1]
        try:
            width, height = page.get_size()
            if not 0 < width <= 20000 or not 0 < height <= 20000:
                raise ValueError('Document page is too large')
            bitmap = page.render(scale=min(1000/width, 1400/height), may_draw_forms=False)
            try:
                image = bitmap.to_pil().convert('RGB')
                output = io.BytesIO(); image.save(output, 'JPEG', quality=85)
                jpeg = output.getvalue()
                if metadata:
                    import base64
                    text_page = page.get_textpage()
                    try: text = text_page.get_text_range()[:50000]
                    finally: text_page.close()
                    return {'image':base64.b64encode(jpeg).decode(), 'pageCount':page_count, 'page':page_number, 'width':image.width, 'height':image.height, 'text':text}
                return jpeg
            finally:
                bitmap.close()
        finally:
            page.close()

def render_isolated(raw, extension, page_number=None):
    env = {'PATH':os.environ.get('PATH','/usr/bin:/bin'), 'PYTHONPATH':os.pathsep.join(dict.fromkeys([str(Path(__file__).resolve().parents[1]),*sys.path])), 'PYTHONDONTWRITEBYTECODE':'1'}
    command = [sys.executable, '-m', 'postriff_phase2.library_preview', extension]
    if page_number is not None: command.append(str(page_number))
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, start_new_session=True)
    try:
        result, error_output = process.communicate(raw, timeout=60)
        if process.returncode or len(result)>3*1024*1024 or (page_number is None and not result.startswith(b'\xff\xd8')):
            # Report only controlled process diagnostics, never document text or paths.
            exceptions = re.findall(rb'^([A-Za-z]+(?:Error|Exception)):', error_output, re.MULTILINE)
            codes = re.findall(rb'\[Errno ([0-9]+)\]', error_output)
            office = re.findall(rb'Office renderer failed: exit=(-?[0-9]+) pdf_present=(True|False) missing_libraries=(\[[A-Za-z0-9_.+, \'-]*\])', error_output)
            logging.warning('Library renderer failed: exit=%s exceptions=%s errno=%s office=%s', process.returncode, [v.decode('ascii') for v in exceptions], [v.decode('ascii') for v in codes], [[v.decode('ascii') for v in row] for row in office])
            raise ValueError('First-page preview unavailable (renderer exit '+str(process.returncode)+')')
        if page_number is not None:
            import json, base64
            data = json.loads(result)
            data['image'] = base64.b64decode(data['image'], validate=True)
            if not data['image'].startswith(b'\xff\xd8') or len(data['image'])>2*1024*1024:
                raise ValueError('Invalid page raster')
            return data
        return result
    except BaseException:
        import signal
        try: os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError: pass
        process.wait()
        raise

if __name__ == '__main__':
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (40,40))
    resource.setrlimit(resource.RLIMIT_AS, (1536*1024*1024,1536*1024*1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (32*1024*1024,32*1024*1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (512,512))
    _deny_internet()
    raw = sys.stdin.buffer.read(50*1024*1024+1)
    if len(sys.argv)>2:
        import json
        sys.stdout.write(json.dumps(render(raw,sys.argv[1],int(sys.argv[2]),True)))
    else:
        sys.stdout.buffer.write(render(raw,sys.argv[1]))
