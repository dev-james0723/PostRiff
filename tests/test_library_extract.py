import io,json,unittest,zipfile
from postriff_alpha.domain import AlphaError
from postriff_phase2.library_extract import MAX_TEXT,chunks,extract_text,extract_isolated

def archive(files):
 out=io.BytesIO()
 with zipfile.ZipFile(out,"w",zipfile.ZIP_DEFLATED) as z:
  for name,data in files.items():z.writestr(name,data)
 return out.getvalue()

class LibraryExtractTests(unittest.TestCase):
 def test_isolated_pdf_reads_actual_source_with_runtime_dependency_paths(self):
  from library_samples import pdf
  status,text=extract_isolated(pdf(),"pdf")
  self.assertEqual(status,"ready")
  self.assertIn("Brahms rehearsal",text)
 def test_text_markdown_json_csv(self):
  self.assertEqual(extract_text(b"hello\nworld","txt")[1],"hello\nworld")
  self.assertIn('"a": 1',extract_text(json.dumps({"a":1}).encode(),"json")[1])
  self.assertEqual(extract_text(b"a,b\n1,2","csv")[1],"a | b\n1 | 2")
 def test_html_drops_script_and_style(self):
  text=extract_text(b"<p>Hello</p><script>steal()</script><style>x</style><div>World</div>","html")[1]
  self.assertIn("Hello",text);self.assertIn("World",text);self.assertNotIn("steal",text)
 def test_generic_binary_is_metadata_only(self):
  self.assertEqual(extract_text(b"\x01\x02","bin"),("unsupported",""))
 def test_ooxml_text_without_formula_execution(self):
  raw=archive({"word/document.xml":'<w:document xmlns:w="x"><w:p><w:r><w:t>Hello</w:t></w:r></w:p></w:document>'})
  self.assertEqual(extract_text(raw,"docx")[1],"Hello")
  xlsx=archive({"xl/worksheets/sheet1.xml":'<worksheet><sheetData><row><c><f>EXEC()</f><v>42</v></c></row></sheetData></worksheet>'})
  text=extract_text(xlsx,"xlsx")[1];self.assertIn("42",text);self.assertNotIn("EXEC",text)
 def test_zip_path_traversal_and_macro_rejected(self):
  for raw in (archive({"../evil.xml":"x"}),archive({"word/vbaProject.bin":"x"})):
   with self.assertRaises(AlphaError):extract_text(raw,"docx")
 def test_chunks_are_bounded(self):
  result=chunks("x"*(MAX_TEXT+1000));self.assertLessEqual(sum(map(len,result)),MAX_TEXT);self.assertTrue(all(len(x)<=6000 for x in result))
 def test_invalid_utf8_and_encrypted_or_invalid_pdf_fail_closed(self):
  with self.assertRaises(AlphaError):extract_text(b"\xff","txt")
  with self.assertRaises(AlphaError):extract_text(b"not a pdf","pdf")
class RealWorldPdfTests(unittest.TestCase):
 """Uploaded slide decks and scores: multi-page, embedded fonts, imperfect structure (2026-10-09 regression: both
 real PDFs on the release preview ended as 'This PDF could not be read safely.')."""
 FIXTURE=__import__("pathlib").Path(__file__).parent/"fixtures"/"library"/"real-world-slides.pdf"
 def test_multi_page_pdf_with_embedded_fonts_extracts_inside_the_linux_sandbox(self):
  import subprocess,sys
  raw=self.FIXTURE.read_bytes()
  # Same isolated child the upload path uses, with its CPU/address-space limits (enforced on Linux CI and Vercel).
  child=subprocess.run([sys.executable,"-m","postriff_phase2.library_extract","pdf"],input=raw,capture_output=True,timeout=60)
  self.assertEqual(child.returncode,0,child.stderr.decode(errors="replace")[-400:])
  data=json.loads(child.stdout)
  self.assertNotIn("error",data,data)
  status,text=extract_isolated(raw,"pdf")
  self.assertEqual(status,"ready")
  self.assertIn("Hear the pull toward tonic",text)
  self.assertIn("SLIDE 18",text)
  self.assertGreater(len(text),30000)
 @unittest.skipUnless(__import__("sys").platform.startswith("linux"),"the renderer child enforces Linux address-space limits")
 def test_pdf_text_comes_from_the_pdfium_renderer_child(self):
  # The engine that renders page previews on Vercel also reads the text (2026-10-09: pypdf failed every real PDF there).
  from postriff_phase2.library_preview import extract_text_isolated
  text=extract_text_isolated(self.FIXTURE.read_bytes(),"pdf")
  self.assertIn("Hear the pull toward tonic",text)
  self.assertIn("SLIDE 18",text)
 def test_stale_xref_offsets_are_read_leniently(self):
  import re
  from library_samples import pdf
  stale=re.sub(rb"(\d{10}) 00000 n",lambda m:f"{int(m.group(1))+7:010} 00000 n".encode(),pdf())
  status,text=extract_text(stale,"pdf")
  self.assertEqual(status,"ready");self.assertIn("Brahms rehearsal",text)
 def test_a_page_that_cannot_be_decoded_loses_only_its_own_text(self):
  from unittest import mock
  from pypdf._page import PageObject
  real=PageObject.extract_text
  calls={"n":0}
  def flaky(page,*args,**kwargs):
   calls["n"]+=1
   if calls["n"]==1:raise ValueError("undecodable font")
   return real(page,*args,**kwargs)
  with mock.patch.object(PageObject,"extract_text",flaky):
   status,text=extract_text(self.FIXTURE.read_bytes(),"pdf")
  self.assertEqual(status,"ready")
  self.assertNotIn("SLIDE 01 /",text)
  self.assertIn("SLIDE 02 /",text)
 def test_unreadable_files_still_fail_closed(self):
  from library_samples import pdf
  for raw in (b"not a pdf",pdf()[:120]):
   with self.assertRaises(AlphaError):extract_text(raw,"pdf")
if __name__=="__main__":unittest.main()
