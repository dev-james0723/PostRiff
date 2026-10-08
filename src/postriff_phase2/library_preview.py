"""Real source-page rasterization. No summaries, icons or generated cover art.

Office source bytes -> LibreOffice first-page PDF -> PDFium JPEG.
PDF source bytes -> PDFium first-page JPEG. Text/Markdown/HTML source bytes are
typeset from the original content, then follow the same first-page raster path.
The child has no credentials, no Internet sockets, bounded CPU/memory/output,
an isolated disposable Office profile, disabled macros and disabled link updates.
"""
import io
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

def render(raw, extension):
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
            executable = ROOT / 'office/program/soffice'
            command = str(executable) if executable.exists() else shutil.which('libreoffice')
            if not command:
                raise RuntimeError('Document renderer unavailable')
            env = {'PATH':'/usr/bin:/bin', 'LANG':'C.UTF-8', 'SAL_USE_VCLPLUGIN':'svp', 'TMPDIR':str(work)}
            if ROOT.exists():
                env['LD_LIBRARY_PATH'] = str(ROOT / 'lib')+':'+str(ROOT / 'office/program')
                fonts = work / 'fonts.conf'
                fonts.write_text('<fontconfig><dir>'+str(ROOT / 'fonts')+'</dir><cachedir>'+str(work / 'font-cache')+'</cachedir></fontconfig>')
                env['FONTCONFIG_FILE'] = str(fonts)
            result = subprocess.run([command, '-env:UserInstallation='+ (work / 'profile').as_uri(), '--headless','--invisible','--nodefault','--nolockcheck','--nologo','--norestore','--convert-to','pdf','--outdir',str(work),str(source)], env=env, cwd=work, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=45, check=False)
            output = work / 'source.pdf'
            if result.returncode or not output.exists() or output.stat().st_size > 32*1024*1024:
                raise ValueError('Document could not be rendered')
            pdf = output.read_bytes()
    with pdfium.PdfDocument(pdf) as doc:
        if not len(doc):
            raise ValueError('Document has no pages')
        page = doc[0]
        try:
            width, height = page.get_size()
            if not 0 < width <= 20000 or not 0 < height <= 20000:
                raise ValueError('Document page is too large')
            bitmap = page.render(scale=min(1000/width, 1400/height), may_draw_forms=False)
            try:
                image = bitmap.to_pil().convert('RGB')
                output = io.BytesIO(); image.save(output, 'JPEG', quality=85)
                return output.getvalue()
            finally:
                bitmap.close()
        finally:
            page.close()

def render_isolated(raw, extension):
    env = {'PATH':os.environ.get('PATH','/usr/bin:/bin'), 'PYTHONPATH':os.pathsep.join(dict.fromkeys([str(Path(__file__).resolve().parents[1]),*sys.path])), 'PYTHONDONTWRITEBYTECODE':'1'}
    process = subprocess.Popen([sys.executable, '-m', 'postriff_phase2.library_preview', extension], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, start_new_session=True)
    try:
        result, error_output = process.communicate(raw, timeout=60)
        if process.returncode or not result.startswith(b'\xff\xd8') or len(result)>2*1024*1024:
            raise ValueError('First-page preview unavailable (renderer exit '+str(process.returncode)+')')
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
    sys.stdout.buffer.write(render(sys.stdin.buffer.read(50*1024*1024+1), sys.argv[1]))
