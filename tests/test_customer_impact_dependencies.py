"""Customer impact of the candidate's Python dependency moves on the unchanged paths every customer uses.

The candidate moves Pillow 12.3.0 -> 13.0.0 and pypdf 6.19.0 -> 6.21.1 (requirements.txt); media.py,
account_pictures.py and library_extract.py are byte-identical in both trees. These tests feed the same inputs to the
same code under different library versions in separate interpreters and require identical results:

  Pillow   an uploaded image (media._decode_pillow) and a connected account's picture (account_pictures.square_jpeg),
           15 images: JPEG baseline/progressive/EXIF-rotated/CMYK/grey, PNG RGBA/palette+transparency/16-bit/LA,
           animated GIF, WebP, too small, truncated, large, too wide. Bytes of every rendition must match.
  pypdf    a Universal Library PDF upload (library_extract.extract_text): one page, three pages, WinAnsi accents,
           a broken xref, a truncated file and an encrypted file.

Interpreters: this one (the project venv) and IMPACT_OLD_PILLOW_PYTHON (default /usr/bin/python3) for Pillow, which
must carry the live pin; for pypdf every interpreter in IMPACT_PYPDF_PYTHONS (os.pathsep separated, default this one
and /usr/bin/python3). A test skips when it cannot find two different versions to compare.
"""
import io
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIVE_REV = os.environ.get('IMPACT_LIVE_REV', 'c5fc1fd10350f3142ec6f34b2c373139e85abb39')


def pin(rev, package):
    text = subprocess.run(['git', '-C', str(ROOT), 'show', '%s:requirements.txt' % rev], capture_output=True, text=True).stdout
    match = re.search(r'^%s==([0-9.]+)\s*$' % re.escape(package), text, re.M | re.I)
    return match.group(1) if match else None


def version(python, module):
    try:
        done = subprocess.run([python, '-I', '-c', 'import %s;print(%s.__version__)' % (module, module)], capture_output=True, text=True, timeout=60)
    except OSError:
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def probe(python, script, inputs):
    done = subprocess.run([python, '-I', str(ROOT / 'tests' / script), str(ROOT), inputs], capture_output=True, text=True, timeout=300,
                          env={'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'PYTHONDONTWRITEBYTECODE': '1'})
    if done.returncode:
        raise AssertionError('%s failed under %s: %s' % (script, python, done.stderr[-1500:]))
    return json.loads(done.stdout)


def images(directory):
    from PIL import Image, ImageDraw

    def art(mode, size):
        img = Image.new('RGB', size)
        draw = ImageDraw.Draw(img)
        for x in range(0, size[0], 7):
            draw.line([(x, 0), (size[0] - x, size[1])], fill=((x * 3) % 256, (x * 7) % 256, (x * 11) % 256), width=3)
        draw.ellipse([size[0] // 4, size[1] // 4, size[0] * 3 // 4, size[1] * 3 // 4], fill=(240, 200, 40))
        return img if mode == 'RGB' else img.convert(mode)
    d = Path(directory)
    art('RGB', (640, 480)).save(d / '01-rgb.jpg', quality=90)
    art('RGB', (1200, 800)).save(d / '02-progressive.jpg', quality=85, progressive=True)
    rotated = art('RGB', (800, 600))
    exif = rotated.getexif()
    exif[0x0112] = 6
    rotated.save(d / '03-exif-rotated.jpg', exif=exif)
    art('CMYK', (500, 500)).save(d / '04-cmyk.jpg')
    art('L', (400, 400)).save(d / '05-gray.jpg')
    rgba = art('RGB', (512, 512)).convert('RGBA')
    rgba.putalpha(Image.linear_gradient('L').resize((512, 512)))
    rgba.save(d / '06-rgba.png')
    art('RGB', (400, 400)).convert('P', palette=Image.Palette.ADAPTIVE, colors=64).save(d / '07-palette-transparent.png', transparency=0)
    Image.linear_gradient('L').resize((400, 400)).convert('I;16').save(d / '08-gray16.png')
    art('LA', (400, 400)).save(d / '09-la.png')
    frames = [art('RGB', (400, 400)), art('RGB', (400, 400)).rotate(90)]
    frames[0].save(d / '10-animated.gif', save_all=True, append_images=frames[1:])
    art('RGB', (512, 512)).save(d / '11-image.webp', quality=80)
    art('RGB', (100, 100)).save(d / '12-tiny.png')
    raw = (d / '01-rgb.jpg').read_bytes()
    (d / '13-truncated.jpg').write_bytes(raw[: len(raw) // 2])
    art('RGB', (3000, 2000)).save(d / '14-large.jpg', quality=80)
    art('RGB', (5000, 400)).save(d / '15-too-wide.png')


def pdf(pages, encoding=False):
    font = '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica' + (' /Encoding /WinAnsiEncoding' if encoding else '') + ' >>'
    body, kids, n = {1: '<< /Type /Catalog /Pages 2 0 R >>', 3: font}, [], 4
    for text in pages:
        stream = ('BT /F1 18 Tf 72 720 Td (%s) Tj ET' % text).encode('latin-1')
        body[n] = '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>' % (n + 1)
        body[n + 1] = ('<< /Length %d >>\nstream\n' % len(stream)).encode('latin-1') + stream + b'\nendstream'
        kids.append('%d 0 R' % n)
        n += 2
    body[2] = '<< /Type /Pages /Kids [%s] /Count %d >>' % (' '.join(kids), len(kids))
    out, offsets = io.BytesIO(), {}
    out.write(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n')
    for i in sorted(body):
        offsets[i] = out.tell()
        part = body[i] if isinstance(body[i], bytes) else body[i].encode('latin-1')
        out.write(b'%d 0 obj\n' % i + part + b'\nendobj\n')
    xref = out.tell()
    out.write(b'xref\n0 %d\n0000000000 65535 f \n' % (len(body) + 1))
    for i in sorted(body):
        out.write(b'%010d 00000 n \n' % offsets[i])
    out.write(b'trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n' % (len(body) + 1, xref))
    return out.getvalue()


def pdfs(directory):
    from pypdf import PdfReader, PdfWriter
    d = Path(directory)
    (d / '01-one-page.pdf').write_bytes(pdf(['Hello Rafii customers']))
    (d / '02-three-pages.pdf').write_bytes(pdf(['First page of the brief', 'Second page: details', 'Third page: summary']))
    (d / '03-accents.pdf').write_bytes(pdf(['Caf\xe9 cr\xe8me br\xfbl\xe9e \xfcber'], encoding=True))
    good = pdf(['Offsets are wrong here'])
    (d / '04-bad-xref.pdf').write_bytes(good.replace(b'0000000009 00000 n', b'0000000999 00000 n', 1))
    (d / '05-truncated.pdf').write_bytes(good[: len(good) // 2])
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(pdf(['Secret text']))))
    # Generated (rule P2-SEC-CI-04); the readers open it with the empty user password.
    writer.encrypt(user_password='', owner_password='synthetic-' + secrets.token_hex(12), algorithm='RC4-128')
    buffer = io.BytesIO()
    writer.write(buffer)
    (d / '06-encrypted.pdf').write_bytes(buffer.getvalue())


class DependencyMoves(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_pillow_13_renders_customer_images_exactly_as_the_live_pin(self):
        live_pin, rc_pin = pin(LIVE_REV, 'Pillow'), pin('HEAD', 'Pillow')
        old = os.environ.get('IMPACT_OLD_PILLOW_PYTHON', '/usr/bin/python3')
        if version(sys.executable, 'PIL') != rc_pin or version(old, 'PIL') != live_pin or live_pin == rc_pin:
            self.skipTest('needs this interpreter on Pillow %s and %s on Pillow %s' % (rc_pin, old, live_pin))
        images(self.tmp)
        before, after = probe(old, 'impact_pillow_probe.py', self.tmp), probe(sys.executable, 'impact_pillow_probe.py', self.tmp)
        self.assertEqual((before['pillow'], after['pillow']), (live_pin, rc_pin))
        self.assertEqual(len(after['images']), 15)
        self.assertEqual(before['images'], after['images'], 'same accept/refuse decision, rendition bytes and pixels')
        accepted = sum(entry['upload']['ok'] for entry in after['images'].values())
        self.assertEqual(accepted, 10, 'ten of the fifteen inputs are valid uploads (the rest are refused on both)')

    def test_pypdf_reads_customer_pdfs_alike_across_the_pinned_versions(self):
        candidates = os.environ.get('IMPACT_PYPDF_PYTHONS', os.pathsep.join([sys.executable, '/usr/bin/python3'])).split(os.pathsep)
        pythons = {}
        for python in candidates:
            found = version(python, 'pypdf')
            if found and found not in pythons:
                pythons[found] = python
        if len(pythons) < 2:
            self.skipTest('needs two interpreters with different pypdf versions (IMPACT_PYPDF_PYTHONS)')
        pdfs(self.tmp)
        runs = {found: probe(python, 'impact_pypdf_probe.py', self.tmp) for found, python in pythons.items()}
        baseline = next(iter(runs.values()))['files']
        self.assertEqual(len(baseline), 6)
        for found, run in runs.items():
            self.assertEqual(run['files'], baseline, 'pypdf %s reads the same text and refuses the same files' % found)
        self.assertEqual([baseline[name]['ok'] for name in sorted(baseline)], [True, True, True, True, False, False])


if __name__ == '__main__':
    unittest.main()
