"""Media/extraction fixtures for Library intelligence T03, generated in code (no downloads, no real people).

Everything here is synthetic: PDF pages built object by object, Office packages built with zipfile, WAV with the
`wave` module and ISO-BMFF boxes with struct. `ramp.flac` beside this file is the single committed binary; it was
converted once with ffmpeg from `ramp_wav()` (mono, 8 kHz, 0.5 s, 440 Hz sine with a 0→0.9 amplitude ramp).
"""
from __future__ import annotations

import io
import math
import struct
import wave
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

HERE = Path(__file__).resolve().parent
RAMP_FLAC = HERE / "ramp.flac"


# --- PDF -----------------------------------------------------------------------------------------------------------
def pdf(pages, outline=None) -> bytes:
    """pages: list of (content_stream_bytes, uses_image). Optional outline: [(title, page_index)]."""
    objects = [None, None, None]  # 1 catalog, 2 pages
    font_id = len(objects)
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    img = bytes((x * 16 + y) % 256 for y in range(16) for x in range(16))
    img_id = len(objects)
    objects.append(b"<< /Type /XObject /Subtype /Image /Width 16 /Height 16 /ColorSpace /DeviceGray /BitsPerComponent 8 /Length "
                   + str(len(img)).encode() + b" >>\nstream\n" + img + b"\nendstream")
    kids = []
    for content, use_img in pages:
        cid = len(objects)
        objects.append(b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream")
        res = b"<< /Font << /F1 " + str(font_id).encode() + b" 0 R >>" + ((b" /XObject << /Im1 " + str(img_id).encode() + b" 0 R >>") if use_img else b"") + b" >>"
        pid = len(objects)
        objects.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources " + res + b" /Contents " + str(cid).encode() + b" 0 R >>")
        kids.append(pid)
    catalog = b"<< /Type /Catalog /Pages 2 0 R"
    if outline:
        outlines_id = len(objects)
        objects.append(None)
        item_ids = []
        for title, index in outline:
            item_ids.append(len(objects))
            objects.append(None)
        for n, (title, index) in enumerate(outline):
            parts = [b"/Title (" + title.encode("latin-1") + b")", b"/Parent " + str(outlines_id).encode() + b" 0 R",
                     b"/Dest [" + str(kids[index]).encode() + b" 0 R /Fit]"]
            if n > 0:
                parts.append(b"/Prev " + str(item_ids[n - 1]).encode() + b" 0 R")
            if n + 1 < len(item_ids):
                parts.append(b"/Next " + str(item_ids[n + 1]).encode() + b" 0 R")
            objects[item_ids[n]] = b"<< " + b" ".join(parts) + b" >>"
        objects[outlines_id] = (b"<< /Type /Outlines /First " + str(item_ids[0]).encode() + b" 0 R /Last " + str(item_ids[-1]).encode()
                                + b" 0 R /Count " + str(len(item_ids)).encode() + b" >>")
        catalog += b" /Outlines " + str(outlines_id).encode() + b" 0 R"
    objects[1] = catalog + b" >>"
    objects[2] = b"<< /Type /Pages /Kids [" + b" ".join(str(k).encode() + b" 0 R" for k in kids) + b"] /Count " + str(len(kids)).encode() + b" >>"
    out, offsets = b"%PDF-1.4\n", []
    for i in range(1, len(objects)):
        offsets.append(len(out))
        out += str(i).encode() + b" 0 obj\n" + objects[i] + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 " + str(len(objects)).encode() + b"\n0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010} 00000 n \n".encode()
    return out + f"trailer\n<< /Size {len(objects)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()


def text_page(text: str) -> tuple[bytes, bool]:
    return (b"BT /F1 12 Tf 40 750 Td (" + text.encode("latin-1") + b") Tj ET", False)


IMAGE_ONLY_PAGE = (b"q 612 0 0 792 0 0 cm /Im1 Do Q", True)
# Glyph codes with no usable text mapping: pypdf returns control characters, which must never pass as clean text.
GARBLED_PAGE = (b"BT /F1 12 Tf 40 750 Td <0102030405060708090a0b0c0e0f1011121314> Tj ET", False)


def mixed_pdf() -> bytes:
    """Page 1 digital text, page 2 a scanned (image-only) page, page 3 a garbled text layer, page 4 digital text."""
    return pdf([text_page("Rafii digital page one Brahms rehearsal"), IMAGE_ONLY_PAGE, GARBLED_PAGE,
                text_page("Page four lists the concert hall booking")],
               outline=[("Introduction", 0), ("Programme", 3)])


# --- Office (OOXML) -------------------------------------------------------------------------------------------------
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"


def _zip(files: dict, *, compression=zipfile.ZIP_DEFLATED) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return out.getvalue()


def _types(overrides, extra_defaults=""):
    return ('<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>' + extra_defaults
            + "".join(f'<Override PartName="{n}" ContentType="{m}"/>' for n, m in overrides) + "</Types>")


DOCX_PARAGRAPHS = ["Spring recital plan", "", "Rehearse the Brahms sonata on Wednesday.", "我哋喺大會堂綵排。"]
DOCX_TABLE = [["Item", "Owner"], ["Hall booking", "James"]]


def docx(paragraphs=DOCX_PARAGRAPHS, table=DOCX_TABLE, *, extra_files=None, content_types_extra="") -> bytes:
    body = []
    for n, text in enumerate(paragraphs):
        style = '<w:pPr><w:pStyle w:val="Heading1"/></w:pPr>' if n == 0 else ""
        # Word's own rendered-page hint must never become a page number.
        hint = "<w:lastRenderedPageBreak/>" if n == 2 else ""
        body.append(f"<w:p>{style}<w:r>{hint}<w:t xml:space=\"preserve\">{escape(text)}</w:t></w:r></w:p>")
    if table:
        rows = "".join("<w:tr>" + "".join(f"<w:tc><w:p><w:r><w:t>{escape(cell)}</w:t></w:r></w:p></w:tc>" for cell in row) + "</w:tr>" for row in table)
        body.append(f"<w:tbl>{rows}</w:tbl>")
    document = f'<w:document xmlns:w="{W}"><w:body>{"".join(body)}<w:sectPr/></w:body></w:document>'
    files = {"[Content_Types].xml": _types([("/word/document.xml", "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml")], content_types_extra),
             "_rels/.rels": f'<Relationships xmlns="{PKG}"><Relationship Id="rId1" Type="{R}/officeDocument" Target="word/document.xml"/></Relationships>',
             "word/document.xml": document}
    files.update(extra_files or {})
    return _zip(files)


def xlsx() -> bytes:
    """Two sheets with real names; shared strings, inline strings, numbers and a formula with a cached value."""
    shared = ["Item", "Cost", "Hall hire", "Piano tuning", "練習室"]
    sst = f'<sst xmlns="{S}" count="{len(shared)}" uniqueCount="{len(shared)}">' + "".join(f"<si><t>{escape(s)}</t></si>" for s in shared) + "</sst>"
    sheet1 = (f'<worksheet xmlns="{S}"><sheetData>'
              '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
              '<row r="4"><c r="A4" t="s"><v>2</v></c><c r="B4"><v>1200</v></c><c r="C4" t="inlineStr"><is><t>Deposit paid</t></is></c></row>'
              '<row r="5"><c r="A5" t="s"><v>3</v></c><c r="B5"><f>B4/4</f><v>300</v></c></row>'
              "</sheetData></worksheet>")
    sheet2 = (f'<worksheet xmlns="{S}"><sheetData>'
              '<row r="2"><c r="B2" t="s"><v>4</v></c><c r="C2" t="str"><f>CONCAT("Room ",3)</f><v>Room 3</v></c></row>'
              "</sheetData></worksheet>")
    workbook = (f'<workbook xmlns="{S}" xmlns:r="{R}"><sheets><sheet name="Budget" sheetId="1" r:id="rId1"/>'
                f'<sheet name="練習 Notes" sheetId="2" r:id="rId2"/></sheets></workbook>')
    rels = (f'<Relationships xmlns="{PKG}"><Relationship Id="rId1" Type="{R}/worksheet" Target="worksheets/sheet1.xml"/>'
            f'<Relationship Id="rId2" Type="{R}/worksheet" Target="/xl/worksheets/sheet2.xml"/>'
            f'<Relationship Id="rId3" Type="{R}/sharedStrings" Target="sharedStrings.xml"/></Relationships>')
    return _zip({"[Content_Types].xml": _types([("/xl/workbook.xml", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml")]),
                 "_rels/.rels": f'<Relationships xmlns="{PKG}"><Relationship Id="rId1" Type="{R}/officeDocument" Target="xl/workbook.xml"/></Relationships>',
                 "xl/workbook.xml": workbook, "xl/_rels/workbook.xml.rels": rels, "xl/sharedStrings.xml": sst,
                 "xl/worksheets/sheet1.xml": sheet1, "xl/worksheets/sheet2.xml": sheet2})


def pptx() -> bytes:
    """Presentation order is slide3.xml, slide1.xml, slide2.xml — file names must not decide slide numbers."""
    def slide(lines):
        paras = "".join(f"<a:p><a:r><a:t>{escape(line)}</a:t></a:r></a:p>" for line in lines)
        return f'<p:sld xmlns:p="{P}" xmlns:a="{A}"><p:cSld><p:spTree><p:sp><p:txBody><a:bodyPr/>{paras}</p:txBody></p:sp></p:spTree></p:cSld></p:sld>'
    presentation = (f'<p:presentation xmlns:p="{P}" xmlns:r="{R}"><p:sldIdLst><p:sldId id="256" r:id="rId3"/><p:sldId id="257" r:id="rId1"/>'
                    f'<p:sldId id="258" r:id="rId2"/></p:sldIdLst></p:presentation>')
    rels = (f'<Relationships xmlns="{PKG}">' + "".join(f'<Relationship Id="rId{n}" Type="{R}/slide" Target="slides/slide{n}.xml"/>' for n in (1, 2, 3))
            + "</Relationships>")
    return _zip({"[Content_Types].xml": _types([("/ppt/presentation.xml", "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml")]),
                 "_rels/.rels": f'<Relationships xmlns="{PKG}"><Relationship Id="rId1" Type="{R}/officeDocument" Target="ppt/presentation.xml"/></Relationships>',
                 "ppt/presentation.xml": presentation, "ppt/_rels/presentation.xml.rels": rels,
                 "ppt/slides/slide1.xml": slide(["Programme", "Brahms Op. 120"]), "ppt/slides/slide2.xml": slide(["Thank you"]),
                 "ppt/slides/slide3.xml": slide(["Spring recital", "Opening slide"])})


def macro_docx() -> bytes:
    return docx(extra_files={"word/vbaProject.bin": b"\xd0\xcf\x11\xe0 fake macro project"})


def macro_content_type_docx() -> bytes:
    return docx(content_types_extra='<Default Extension="bin" ContentType="application/vnd.ms-office.vbaProject"/>')


def traversal_docx() -> bytes:
    return docx(extra_files={"../../evil.xml": "<x/>"})


def zip_bomb_docx() -> bytes:
    """One part that inflates 60 MB of zeros from a few kilobytes."""
    return docx(extra_files={"word/media/zeros.xml": b"\0" * (60 * 1024 * 1024)})


def entity_bomb_docx() -> bytes:
    bomb = ('<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">'
            '<!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">]>'
            f'<w:document xmlns:w="{W}"><w:body><w:p><w:r><w:t>&lol3;</w:t></w:r></w:p></w:body></w:document>')
    files = {"[Content_Types].xml": _types([]), "word/document.xml": bomb}
    return _zip(files)


HOSTILE_HTML = (b"<html><head><script>fetch('http://169.254.169.254/latest/meta-data/')</script>"
                b"<link rel=stylesheet href=http://127.0.0.1:9/x.css><style>body{background:url(http://10.0.0.1/a)}</style></head>"
                b"<body><p>Visible programme note</p><iframe src=\"http://localhost/admin\"></iframe><img src=x onerror=alert(1)>"
                b"<p>Second paragraph</p></body></html>")


# --- audio / video ----------------------------------------------------------------------------------------------------
def wav(samples, *, rate=8000, width=2, channels=1) -> bytes:
    """samples: floats in [-1, 1] (interleaved when channels > 1)."""
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        if width == 1:
            data = bytes(int(round(128 + 127 * s)) for s in samples)
        elif width == 2:
            data = b"".join(struct.pack("<h", int(round(32767 * s))) for s in samples)
        elif width == 3:
            data = b"".join(struct.pack("<i", int(round(8388607 * s)))[:3] for s in samples)
        else:
            data = b"".join(struct.pack("<i", int(round(2147483647 * s))) for s in samples)
        w.writeframes(data)
    return out.getvalue()


def ramp_samples(rate=8000, seconds=0.5, *, down=False):
    n = int(rate * seconds)
    out = []
    for i in range(n):
        env = 0.9 * (i / n)
        if down:
            env = 0.9 - env
        out.append(env * math.sin(2 * math.pi * 440 * i / rate))
    return out


def ramp_wav() -> bytes:
    """Same generator as the committed FLAC: int(32767 * 0.9 * i/n * sin(...)) at 8 kHz."""
    rate, n = 8000, 4000
    frames = b"".join(struct.pack("<h", int(32767 * 0.9 * (i / n) * math.sin(2 * math.pi * 440 * i / rate))) for i in range(n))
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(frames)
    return out.getvalue()


def _box(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I4s", 8 + len(payload), kind) + payload


def mp4(*, duration_ms=5000, width=1920, height=1080, timescale=1000) -> bytes:
    """A minimal ftyp + moov (mvhd + trak/tkhd) + empty mdat. Enough for real header parsing; not playable."""
    ftyp = _box(b"ftyp", b"isom" + struct.pack(">I", 512) + b"isomiso2mp41")
    mvhd = _box(b"mvhd", b"\0\0\0\0" + struct.pack(">IIII", 0, 0, timescale, duration_ms * timescale // 1000) + b"\0" * 80)
    tkhd_body = b"\0\0\0\x07" + struct.pack(">IIIII", 0, 0, 1, 0, duration_ms) + b"\0" * 8 + b"\0" * 8 + b"\0" * 36 + struct.pack(">II", width << 16, height << 16)
    trak = _box(b"trak", _box(b"tkhd", tkhd_body))
    return ftyp + _box(b"moov", mvhd + trak) + _box(b"mdat", b"")


def flac_header(*, rate=44100, channels=2, bits=16, total_samples=441000) -> bytes:
    """fLaC + a STREAMINFO block only (no audio frames)."""
    packed = (rate << 44) | ((channels - 1) << 41) | ((bits - 1) << 36) | total_samples
    streaminfo = struct.pack(">HH", 4096, 4096) + b"\0\0\0" + b"\0\0\0" + packed.to_bytes(8, "big") + b"\0" * 16
    return b"fLaC" + bytes([0x80]) + len(streaminfo).to_bytes(3, "big") + streaminfo


def ogg_opus(*, seconds=3.0, pre_skip=312) -> bytes:
    """Two Ogg pages: OpusHead, then a last page whose granule position marks the end at 48 kHz."""
    def page(granule, payload, flags):
        header = b"OggS" + bytes([0, flags]) + struct.pack("<qIIIB", granule, 1, 0, 0, 1) + bytes([len(payload)])
        return header + payload
    head = b"OpusHead" + bytes([1, 2]) + struct.pack("<HIhB", pre_skip, 48000, 0, 0)
    return page(0, head, 2) + page(int(seconds * 48000) + pre_skip, b"\0" * 10, 4)
