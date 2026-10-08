import io,json,unittest,zipfile
from postriff_alpha.domain import AlphaError
from postriff_phase2.library_extract import MAX_TEXT,chunks,extract_text

def archive(files):
 out=io.BytesIO()
 with zipfile.ZipFile(out,"w",zipfile.ZIP_DEFLATED) as z:
  for name,data in files.items():z.writestr(name,data)
 return out.getvalue()

class LibraryExtractTests(unittest.TestCase):
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
if __name__=="__main__":unittest.main()
