"""Actual source-byte rendering checks; no mocked renderer or synthetic covers."""
import io
import unittest
from PIL import Image
from library_samples import samples, pdf
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
        from postriff_phase2.library_preview import ROOT
        executable=ROOT/'office/program/soffice'
        command=str(executable) if executable.exists() else shutil.which('libreoffice')
        for source_ext,targets in [('docx',['doc','odt','rtf']),('xlsx',['xls','ods']),('pptx',['ppt','odp'])]:
            for target in targets:
                with self.subTest(format=target), tempfile.TemporaryDirectory() as temp:
                    work=Path(temp);source=work/('fixture.'+source_ext);source.write_bytes(office(source_ext))
                    env = None
                    if ROOT.exists():
                        import os
                        env = {**os.environ,'LD_LIBRARY_PATH':str(ROOT/'lib')+':'+str(ROOT/'office/program')}
                    result=subprocess.run([command,'-env:UserInstallation='+(work/'profile').as_uri(),'--headless','--convert-to',target,'--outdir',temp,str(source)],capture_output=True,timeout=45,env=env)
                    converted=work/('fixture.'+target)
                    self.assertTrue(converted.exists(),result.stdout.decode()+result.stderr.decode())
                    self.image(converted.read_bytes(),target)

    def test_network_is_denied_in_render_child(self):
        import subprocess,sys,os
        code='from postriff_phase2.library_preview import _deny_internet; _deny_internet(); import socket; socket.socket(socket.AF_INET,socket.SOCK_STREAM)'
        result=subprocess.run([sys.executable,'-c',code],capture_output=True,env={**os.environ,'PYTHONPATH':'src'})
        self.assertNotEqual(result.returncode,0)
        self.assertIn(b'Operation not permitted',result.stderr)

    def test_invalid_source_has_no_fabricated_thumbnail(self):
        with self.assertRaises(ValueError): render_isolated(b'not a PDF','pdf')

if __name__=='__main__': unittest.main()
