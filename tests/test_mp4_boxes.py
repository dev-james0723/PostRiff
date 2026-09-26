"""mp4_boxes: brand check, bounded top-level walk and moov parsing, on MP4/MOV bytes built in the test (SPEC §7.3)."""
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from postriff_phase2 import mp4_boxes as mb  # noqa: E402


def box(kind, payload=b""):
    return struct.pack(">I4s", 8 + len(payload), kind) + payload


def large_box(kind, payload):
    return struct.pack(">I4sQ", 1, kind, 16 + len(payload)) + payload


def ftyp(major=b"isom", compatible=(b"isom", b"mp41")):
    return box(b"ftyp", major + b"\x00\x00\x02\x00" + b"".join(compatible))


def mvhd(timescale, duration, version=0):
    if version == 1:
        body = b"\x01\x00\x00\x00" + struct.pack(">QQIQ", 0, 0, timescale, duration)
    else:
        body = b"\x00\x00\x00\x00" + struct.pack(">IIII", 0, 0, timescale, duration)
    return box(b"mvhd", body + b"\x00" * 80)


def tkhd(width, height, version=0):
    times = struct.pack(">QQIIQ", 0, 0, 1, 0, 0) if version == 1 else struct.pack(">IIIII", 0, 0, 1, 0, 0)
    body = bytes([version, 0, 0, 7]) + times + b"\x00" * 8 + b"\x00" * 8 + b"\x00" * 36 + struct.pack(">II", int(width * 65536), int(height * 65536))
    return box(b"tkhd", body)


def trak(width, height, version=0):
    return box(b"trak", tkhd(width, height, version) + box(b"mdia", box(b"mdhd", b"\x00" * 24)))


def qt_string(kind, text):
    return box(kind, struct.pack(">HH", len(text), 0x15C7) + text)


def meta(entries):
    keys = b"".join(struct.pack(">I4s", 8 + len(k), b"mdta") + k for k, _ in entries)
    items = b"".join(box(struct.pack(">I", i + 1), box(b"data", b"\x00\x00\x00\x01\x00\x00\x00\x00" + v)) for i, (_, v) in enumerate(entries))
    return box(b"meta", box(b"hdlr", b"\x00" * 24 + b"mdta") + box(b"keys", b"\x00\x00\x00\x00" + struct.pack(">I", len(entries)) + keys) + box(b"ilst", items))


def moov(*children):
    return box(b"moov", b"".join(children))


ISO = b"com.apple.quicktime.location.ISO6709"
MAKE = b"com.apple.quicktime.make"


class BrandTests(unittest.TestCase):
    def test_allowed(self):
        for major in (b"isom", b"iso2", b"iso4", b"iso5", b"iso6", b"mp41", b"mp42", b"avc1", b"M4V ", b"qt  "):
            with self.subTest(major=major):
                self.assertEqual(mb.brand(ftyp(major, ())), major.decode())

    def test_compatible_brand(self):
        self.assertEqual(mb.brand(ftyp(b"dash", (b"iso6",))), "iso6")

    def test_refused(self):
        self.assertIsNone(mb.brand(ftyp(b"heic", (b"mif1",))))
        self.assertIsNone(mb.brand(b"\x1aE\xdf\xa3" + b"\x00" * 20))   # WebM
        self.assertIsNone(mb.brand(b"short"))
        self.assertIsNone(mb.brand(None))


class WalkTests(unittest.TestCase):
    def walk(self, data, **kw):
        reads = []

        def read_at(offset, length):
            reads.append(offset)
            return data[offset:offset + length]
        return mb.walk(read_at, len(data), **kw), reads

    def test_moov_before_mdat(self):
        data = ftyp() + moov(mvhd(1000, 5000)) + box(b"mdat", b"\x00" * 5000)
        result, reads = self.walk(data)
        self.assertEqual(result["moov"], (len(ftyp()), len(moov(mvhd(1000, 5000)))))
        self.assertEqual(len(reads), 2)

    def test_moov_after_large_mdat(self):
        mdat = large_box(b"mdat", b"\x00" * 3000)
        data = ftyp() + box(b"free", b"x" * 10) + mdat + moov(mvhd(600, 1200))
        result, _ = self.walk(data)
        self.assertEqual([b[0] for b in result["boxes"]], ["ftyp", "free", "mdat", "moov"])
        self.assertEqual(result["moov"][0], len(data) - len(moov(mvhd(600, 1200))))

    def test_budget(self):
        data = ftyp() + b"".join(box(b"free", b"x") for _ in range(10)) + moov(mvhd(1, 1))
        result, reads = self.walk(data, max_header_reads=8)
        self.assertEqual((result["moov"], result["complete"], len(reads)), (None, False, 8))

    def test_no_moov(self):
        result, _ = self.walk(ftyp() + box(b"mdat", b"abc"))
        self.assertEqual((result["moov"], result["complete"]), (None, True))

    def test_size_zero_runs_to_end(self):
        data = ftyp() + struct.pack(">I4s", 0, b"mdat") + b"\x00" * 50
        result, _ = self.walk(data)
        self.assertEqual(result["boxes"][-1], ("mdat", len(ftyp()), 58))

    def test_bad_input_is_typed(self):
        for data in (ftyp() + struct.pack(">I4s", 4, b"free"), ftyp() + struct.pack(">I4s", 999, b"mdat"), b"\x00" * 4):
            with self.subTest(data=data[-8:]), self.assertRaises(mb.BoxError):
                self.walk(data)


class MoovTests(unittest.TestCase):
    def test_v0_duration_and_size(self):
        out = mb.parse_moov(moov(mvhd(600, 25416), trak(0, 0), trak(1080, 1920)))
        self.assertEqual(out, {"duration": 42.36, "width": 1080, "height": 1920, "location_present": False})

    def test_v1_and_payload_without_header(self):
        data = moov(mvhd(90000, 90000 * 30, version=1), trak(1920, 1080, version=1))
        self.assertEqual(mb.parse_moov(data)["duration"], 30.0)
        self.assertEqual(mb.parse_moov(data[8:])["width"], 1920)

    def test_fragmented_falls_back_to_mehd(self):
        mehd = box(b"mehd", b"\x00\x00\x00\x00" + struct.pack(">I", 12000))
        out = mb.parse_moov(moov(mvhd(1000, 0), box(b"mvex", mehd)))
        self.assertEqual(out["duration"], 12.0)
        mehd1 = box(b"mehd", b"\x01\x00\x00\x00" + struct.pack(">Q", 3000))
        self.assertEqual(mb.parse_moov(moov(mvhd(1000, 0xFFFFFFFF), box(b"mvex", mehd1)))["duration"], 3.0)

    def test_location_atoms(self):
        tagged = moov(mvhd(1, 1), box(b"udta", qt_string(b"\xa9xyz", b"+22.2783+114.1747/")))
        self.assertTrue(mb.parse_moov(tagged)["location_present"])
        blanked = moov(mvhd(1, 1), box(b"udta", qt_string(b"\xa9xyz", b" " * 18)))
        self.assertFalse(mb.parse_moov(blanked)["location_present"])
        zeroed = moov(mvhd(1, 1), box(b"udta", box(b"loci", b"\x00" * 30)))
        self.assertFalse(mb.parse_moov(zeroed)["location_present"])
        loci = moov(mvhd(1, 1), box(b"udta", box(b"loci", b"\x00\x00\x00\x00" + b"\x15\xc7Home\x00")))
        self.assertTrue(mb.parse_moov(loci)["location_present"])
        device_only = moov(mvhd(1, 1), box(b"udta", qt_string(b"\xa9mak", b"Apple")))
        self.assertFalse(mb.parse_moov(device_only)["location_present"])

    def test_iso6709_key(self):
        self.assertTrue(mb.parse_moov(moov(mvhd(1, 1), meta([(MAKE, b"Apple"), (ISO, b"+22.27+114.17/")])))["location_present"])
        self.assertFalse(mb.parse_moov(moov(mvhd(1, 1), meta([(MAKE, b"Apple"), (ISO, b"   ")])))["location_present"])
        self.assertFalse(mb.parse_moov(moov(mvhd(1, 1), meta([(MAKE, b"Apple")])))["location_present"])
        in_udta = moov(mvhd(1, 1), box(b"udta", meta([(ISO, b"+1+2/")])))
        self.assertTrue(mb.parse_moov(in_udta)["location_present"])

    def test_truncated_and_odd(self):
        full = moov(mvhd(600, 1200), trak(640, 480))
        for data in (full[:20], full[:-10], b"", b"\x00" * 3, box(b"moov", struct.pack(">I4s", 3, b"mvhd"))):
            with self.subTest(n=len(data)):
                out = mb.parse_moov(data)
                self.assertEqual(set(out), {"duration", "width", "height", "location_present"})
        self.assertEqual(mb.parse_moov(full[:-10])["duration"], 2.0)   # what was read before the damage is kept

    def test_budget(self):
        with self.assertRaises(mb.BoxError):
            mb.parse_moov(b"\x00" * (mb.MOOV_MAX + 1))


if __name__ == "__main__":
    unittest.main()
