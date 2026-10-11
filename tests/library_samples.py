"""Small valid files with non-sensitive acceptance text; no external downloads."""
import io
import json
import wave
import zipfile

TEXT = 'Rafii archive acceptance. Brahms rehearsal on Wednesday.\nPrivate practice notes.'


def pdf():
    stream = b'BT /F1 12 Tf 40 750 Td (Rafii archive acceptance Brahms rehearsal) Tj ET'
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
               b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'\nendstream']
    out=b'%PDF-1.4\n';offsets=[0]
    for n,obj in enumerate(objects,1):
        offsets.append(len(out));out+=str(n).encode()+b' 0 obj\n'+obj+b'\nendobj\n'
    xref=len(out);out+=b'xref\n0 6\n0000000000 65535 f \n'
    for offset in offsets[1:]:out+=f'{offset:010} 00000 n \n'.encode()
    return out+f'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode()


def viewer_pdf():
    """Two real PDF pages with distinct text and artwork for reader acceptance."""
    streams = [b'1 0 0 rg 40 600 200 100 re f 0 0 0 rg BT /F1 18 Tf 40 750 Td (Viewer first page Brahms) Tj ET',
               b'0 0 1 rg 40 600 200 100 re f 0 0 0 rg BT /F1 18 Tf 40 750 Td (Viewer second page Mozart) Tj ET']
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Kids [3 0 R 6 0 R] /Count 2 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
               b'<< /Length '+str(len(streams[0])).encode()+b' >>\nstream\n'+streams[0]+b'\nendstream',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 7 0 R >>',
               b'<< /Length '+str(len(streams[1])).encode()+b' >>\nstream\n'+streams[1]+b'\nendstream']
    out=b'%PDF-1.4\n'; offsets=[0]
    for n,obj in enumerate(objects,1):
        offsets.append(len(out));out+=str(n).encode()+b' 0 obj\n'+obj+b'\nendobj\n'
    xref=len(out);out+=b'xref\n0 8\n0000000000 65535 f \n'
    for offset in offsets[1:]: out+=f'{offset:010} 00000 n \n'.encode()
    return out+f'trailer\n<< /Size 8 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode()


def office(ext):
    main={
        'docx':('word/document.xml','application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>'+TEXT+'</w:t></w:r></w:p><w:sectPr/></w:body></w:document>'),
        'xlsx':('xl/workbook.xml','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml','<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Notes" sheetId="1" r:id="rId1"/></sheets></workbook>'),
        'pptx':('ppt/presentation.xml','application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml','<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><p:sldIdLst><p:sldId id="256" r:id="rId1"/></p:sldIdLst><p:sldSz cx="9144000" cy="6858000"/></p:presentation>')}
    name,mime,xml=main[ext]
    files={name:xml,'_rels/.rels':f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="{name}"/></Relationships>'}
    extras=[]
    if ext=='xlsx':
        files['xl/_rels/workbook.xml.rels']='<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>'
        files['xl/worksheets/sheet1.xml']='<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>'+TEXT+'</t></is></c></row></sheetData></worksheet>'
        extras=[('/xl/worksheets/sheet1.xml','application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml')]
    if ext=='pptx':
        files['ppt/_rels/presentation.xml.rels']='<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide1.xml"/></Relationships>'
        files['ppt/slides/slide1.xml']='<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><p:spTree><p:sp><p:nvSpPr><p:cNvPr id="2" name="Rehearsal notes"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr><p:spPr><a:xfrm><a:off x="500000" y="500000"/><a:ext cx="8000000" cy="5000000"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr sz="2400"><a:solidFill><a:srgbClr val="000000"/></a:solidFill></a:rPr><a:t>'+TEXT+'</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>'
        extras=[('/ppt/slides/slide1.xml','application/vnd.openxmlformats-officedocument.presentationml.slide+xml')]
    files['[Content_Types].xml']='<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'+''.join(f'<Override PartName="{n}" ContentType="{m}"/>' for n,m in [('/'+name,mime),*extras])+'</Types>'
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        for name,xml in files.items():z.writestr(name,xml)
    return out.getvalue()


def samples():
    out={ext:TEXT.encode() for ext in ('txt','md','markdown')}
    out.update(pdf=pdf(),json=json.dumps({'notes':TEXT}).encode(),csv=('notes\n"'+TEXT+'"').encode(),html=('<p>'+TEXT+'</p><script>SHOULD_NOT_EXECUTE</script>').encode())
    out['htm']=out['html']
    for ext in ('docx','xlsx','pptx'):out[ext]=office(ext)
    audio=io.BytesIO()
    with wave.open(audio,'wb') as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(8000);w.writeframes(b'\0\0'*8000)
    out['wav']=audio.getvalue();out['bin']=b'\x01\x02Rafii acceptance binary'
    return out


if __name__=='__main__':
    import sys
    from pathlib import Path
    dest=Path(sys.argv[1]);dest.mkdir(parents=True,exist_ok=True)
    for ext,raw in samples().items():(dest/('archive-acceptance.'+ext)).write_bytes(raw)
    (dest/'archive-viewer.pdf').write_bytes(viewer_pdf())
