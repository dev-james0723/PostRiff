"""Actual source-byte rendering checks; no mocked renderer or synthetic covers."""
import io
import unittest
from PIL import Image
from library_samples import samples, pdf, viewer_pdf
from postriff_phase2.library_preview import render_isolated

class FirstPageRendering(unittest.TestCase):
    def image(self, raw, ext):
        try:
            rendered = render_isolated(raw, ext)
        except ValueError:
            import subprocess,sys,os
            diagnostic=subprocess.run([sys.executable,'-m','postriff_phase2.library_preview',ext],input=raw,capture_output=True,env={'PATH':os.environ['PATH'],'PYTHONPATH':os.pathsep.join(sys.path)},timeout=60)
            self.fail('Sample renderer failed: '+diagnostic.stderr.decode(errors='replace')[-3000:])
        image = Image.open(io.BytesIO(rendered))
        self.assertEqual(image.format, 'JPEG')
        self.assertGreater(image.width, 500)
        self.assertGreater(image.height, 500)
        # Text/graphics must be visibly rasterized, not an empty white page.
        self.assertLess(min(image.convert('L').getdata()), 180)
        return image

    def test_actual_two_page_reader_navigation_and_text(self):
        first=render_isolated(viewer_pdf(),'pdf',1)
        second=render_isolated(viewer_pdf(),'pdf',2)
        self.assertEqual(first['pageCount'],2)
        self.assertEqual(second['page'],2)
        self.assertIn('Viewer first page Brahms',first['text'])
        self.assertIn('Viewer second page Mozart',second['text'])
        self.assertNotEqual(first['image'],second['image'])
        with self.assertRaises(ValueError):render_isolated(viewer_pdf(),'pdf',3)

    def test_full_document_text_reads_both_pages_without_rasterization(self):
        from postriff_phase2.library_preview import extract_text_isolated
        text = extract_text_isolated(viewer_pdf(),'pdf')
        self.assertIn('Viewer first page Brahms',text)
        self.assertIn('Viewer second page Mozart',text)

    def test_full_document_text_rejects_over_300_pages(self):
        import re
        from postriff_phase2.library_preview import extract_text_isolated
        # A valid 301-page PDF; verify page rendering before testing the text cap.
        objects = re.findall(rb'[0-9]+ 0 obj\n(.*?)\nendobj',pdf(),re.DOTALL)
        objects.extend([objects[2]] * 300)
        kids = [3,*range(6,306)]
        objects[1] = b'<< /Type /Pages /Kids ['+b' '.join(f'{number} 0 R'.encode() for number in kids)+b'] /Count 301 >>'
        raw = b'%PDF-1.4\n'; offsets = []
        for number, obj in enumerate(objects,1):
            offsets.append(len(raw)); raw += str(number).encode()+b' 0 obj\n'+obj+b'\nendobj\n'
        count = len(objects)+1
        xref = len(raw); raw += f'xref\n0 {count}\n0000000000 65535 f \n'.encode()
        for offset in offsets: raw += f'{offset:010} 00000 n \n'.encode()
        raw += f'trailer\n<< /Size {count} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode()
        self.assertEqual(render_isolated(raw,'pdf',1)['pageCount'],301)
        with self.assertRaises(ValueError):extract_text_isolated(raw,'pdf')

    def test_actual_supported_source_bytes(self):
        for ext,raw in samples().items():
            if ext not in {'pdf','docx','xlsx','pptx','txt','md','markdown','csv','json','html','htm'}: continue
            with self.subTest(format=ext): self.image(raw, ext)

    def test_pdf_uses_graphics_from_source_page(self):
        original=pdf()
        # Keep the PDF byte offsets stable: replace a content text token with a
        # vector red rectangle plus padding, proving that graphics survive.
        old=b'BT /F1 12 Tf 40 750 Td (Rafii archive acceptance Brahms rehearsal) Tj ET'
        drawing=b'1 0 0 rg 40 600 200 100 re f'
        raw=original.replace(old,drawing+b' '*(len(old)-len(drawing)))
        image=self.image(raw,'pdf')
        reds=sum(1 for r,g,b in image.getdata() if r>180 and g<80 and b<80)
        self.assertGreater(reds,10000,'Thumbnail must contain actual PDF artwork')

    def test_markdown_is_typeset_from_original_not_summary(self):
        first=render_isolated(b'# Red rehearsal\n\n**Brahms** rehearsal notes.','md')
        second=render_isolated(b'# A different page\n\nA completely different source.','md')
        self.assertNotEqual(first,second)
        self.image(b'# Red rehearsal\n\n**Brahms** rehearsal notes.','md')

    def test_office_first_page_preserves_source_colour_and_omits_page_two(self):
        import zipfile
        from library_samples import office
        source=io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(office('docx'))) as original, zipfile.ZipFile(source,'w') as target:
            for name in original.namelist():
                data=original.read(name)
                if name=='word/document.xml':
                    data=data.replace(b'<w:r><w:t>',b'<w:r><w:rPr><w:color w:val="FF0000"/><w:sz w:val="72"/></w:rPr><w:t>')
                    data=data.replace(b'<w:sectPr/>',b'<w:p><w:r><w:br w:type="page"/></w:r></w:p><w:p><w:r><w:rPr><w:color w:val="0000FF"/><w:sz w:val="96"/></w:rPr><w:t>SECOND PAGE MUST NOT APPEAR</w:t></w:r></w:p><w:sectPr/>')
                target.writestr(name,data)
        image=self.image(source.getvalue(),'docx')
        red=sum(1 for r,g,b in image.getdata() if r>150 and g<100 and b<100)
        blue=sum(1 for r,g,b in image.getdata() if b>150 and r<100 and g<100)
        self.assertGreater(red,200,'Actual first-page source formatting must survive')
        self.assertEqual(blue,0,'Second page must not appear in thumbnail')

    def test_legacy_office_formats_use_real_document_pages(self):
        import subprocess,tempfile,shutil
        from pathlib import Path
        from library_samples import office
        from postriff_phase2.library_preview import ROOT, _run_office
        executable=ROOT/'office/program/soffice.bin'
        command=str(executable) if executable.exists() else shutil.which('libreoffice')
        for source_ext,targets in [('docx',['doc','odt','rtf']),('xlsx',['xls','ods']),('pptx',['ppt','odp'])]:
            for target in targets:
                with self.subTest(format=target), tempfile.TemporaryDirectory() as temp:
                    work=Path(temp);source=work/('fixture.'+source_ext);source.write_bytes(office(source_ext))
                    env = None
                    if ROOT.exists():
                        import os
                        env = {**os.environ,'LD_LIBRARY_PATH':str(ROOT/'lib')+':'+str(ROOT/'office/program')}
                    result=_run_office([command,'-env:UserInstallation='+(work/'profile').as_uri(),'--headless','--convert-to',target,'--outdir',temp,str(source)],cwd=work,env=env)
                    converted=work/('fixture.'+target)
                    self.assertTrue(converted.exists(),result.stdout.decode()+result.stderr.decode())
                    self.image(converted.read_bytes(),target)
                    from postriff_phase2.library_extract import extract_isolated, MIMES, LEGACY
                    self.assertIn(target, LEGACY)
                    self.assertIn(target, MIMES)
                    status, text = extract_isolated(converted.read_bytes(),target)
                    self.assertEqual(status,'ready')
                    searchable = ' '.join(text.split())
                    self.assertIn('Brahms rehearsal on Wednesday',searchable)
                    self.assertIn('Private practice notes',searchable)

    def test_network_is_denied_in_render_child(self):
        import subprocess,sys,os
        code='from postriff_phase2.library_preview import _deny_internet; _deny_internet(); import socket; socket.socket(socket.AF_INET,socket.SOCK_STREAM)'
        result=subprocess.run([sys.executable,'-c',code],capture_output=True,env={**os.environ,'PYTHONPATH':'src'})
        self.assertNotEqual(result.returncode,0)
        self.assertIn(b'Operation not permitted',result.stderr)

    def test_invalid_source_has_no_fabricated_thumbnail(self):
        with self.assertRaises(ValueError): render_isolated(b'not a PDF','pdf')

if __name__=='__main__': unittest.main()
