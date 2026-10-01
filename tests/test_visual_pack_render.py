"""Visual Pack renderer and checks (PRD R-VIS-01/02 · AC22): six real 1080×1350 PNGs, measured CJK-aware wrapping,
cmap glyph coverage, bounded fitting, safe areas and determinism, over the fixed review set's layout cases."""
import hashlib
import io
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PIL import Image, ImageChops  # noqa: E402

from postriff_phase2.coworker.creative import PLATFORM_SPECS  # noqa: E402
from postriff_phase2.visual_pack import checks, fonts, render, slides  # noqa: E402

CASES = {c["id"]: c for c in json.loads((ROOT / "tests/fixtures/product_growth/review_set_v1.json").read_text())["cases"]}


def pack(texts, lang="en", images=None):
    out = [{"key": f"s{i + 1}", "text": text, "altText": slides.default_alt(i + 1, text, lang=lang), "imageAssetId": None} for i, text in enumerate(texts)]
    for position, asset_id in (images or {}).items():
        out[position - 1]["imageAssetId"] = asset_id
    return out


def filled(case_id, filler):
    """A review-set case as the hook, the rest filled with plain copy so the pack is complete."""
    return [CASES[case_id]["source"]] + [f"{filler} {i}" for i in range(2, 7)]


def ink_box(raw, background):
    """Bounding box of every pixel that differs from the slide background, read back from the PNG itself."""
    with Image.open(io.BytesIO(raw)) as image:
        image.load()
        return ImageChops.difference(image, Image.new("RGB", image.size, checks.rgb(background))).getbbox()


def jpeg(width=1400, height=1000):
    image = Image.new("RGB", (width, height))
    image.putdata([((x * 7) % 256, (y * 5) % 256, 120) for y in range(height) for x in range(width)])
    out = io.BytesIO()
    image.save(out, "JPEG", quality=88)
    return out.getvalue()


class Fonts(unittest.TestCase):
    def test_bundled_fonts_match_their_manifest_and_license(self):
        manifest = fonts.manifest()
        self.assertEqual(manifest["license"]["id"], "OFL-1.1")
        self.assertEqual(hashlib.sha256((fonts.DIRECTORY / "OFL.txt").read_bytes()).hexdigest(), manifest["license"]["sha256"])
        self.assertIn("SIL Open Font License", (fonts.DIRECTORY / "OFL.txt").read_text())
        for entry in manifest["fonts"]:
            data = (fonts.DIRECTORY / entry["file"]).read_bytes()
            self.assertEqual((len(data), hashlib.sha256(data).hexdigest()), (entry["bytes"], entry["sha256"]))
            self.assertEqual(fonts.coverage_count(entry["weight"]), entry["cmapCodePoints"])

    def test_cmap_covers_latin_traditional_chinese_and_punctuation_but_not_emoji(self):
        required = "AZaz09éü&@#%$€£¥—–…“”‘’«»→←·•《》「」『』【】（），。、！？：；～臺灣師範鋼琴即興週六陶藝工作室取件"
        for weight in fonts.WEIGHTS:
            self.assertEqual([c for c in required if not fonts.covers(weight, ord(c))], [], weight)
            for emoji in "💡✅😀‍️":
                self.assertFalse(fonts.covers(weight, ord(emoji)), (weight, emoji))

    def test_safe_area_is_the_strictest_1080x1350_carousel_spec(self):
        carousel = [s["safe"] for (p, f), s in PLATFORM_SPECS.items() if f == "carousel" and s["size"] == [1080, 1350]]
        self.assertEqual((checks.SAFE["top"], checks.SAFE["bottom"], checks.SAFE["sides"]), (81, 135, 65))
        self.assertGreaterEqual(checks.SAFE["top"], max(s["top"] for s in carousel) * 1350)
        self.assertGreaterEqual(checks.SAFE["sides"], max(s["sides"] for s in carousel) * 1080)
        self.assertEqual(checks.SAFE["platforms"], ["Instagram", "LinkedIn", "Threads"])

    def test_palettes_meet_wcag_contrast(self):
        for name, palette in checks.PALETTES.items():
            self.assertGreaterEqual(checks.contrast(palette["text"], palette["background"]), 7, name)
            self.assertGreaterEqual(checks.contrast(palette["muted"], palette["background"]), 4.5, name)
            self.assertGreaterEqual(checks.contrast(palette["accent"], palette["background"]), 3, name)


class Wrapping(unittest.TestCase):
    def test_kinsoku_and_latin_words_hold_while_cjk_breaks_between_characters(self):
        font = fonts.font("regular", 60)
        text = "很多人問：「孩子幾歲開始學鋼琴最好？」我的答案是看 Rafii Weekly 的專注力，不是看年齡。"
        for width in range(240, 940, 37):
            lines, broken = checks.wrap(text, font, width)
            self.assertEqual("".join(lines).replace(" ", ""), text.replace(" ", ""), width)
            self.assertEqual(broken, [])
            for line in lines:
                self.assertLessEqual(font.getlength(line), width)
                self.assertNotIn(line[0], checks.NO_START, (width, line))
                self.assertNotIn(line[-1], checks.NO_END, (width, line))
                self.assertFalse(line.endswith("Raf") or line.startswith("ii"), line)

    def test_long_word_breaks_with_a_hyphen_and_is_reported(self):
        lines, broken = checks.wrap(CASES["en-long-word-layout"]["source"], fonts.font("bold", 88), 942)
        self.assertEqual(broken, ["Pneumonoultramicroscopicsilicovolcanoconiosis-"])
        self.assertTrue(lines[0].endswith("-") and not lines[0].endswith("--"))
        self.assertEqual("".join(lines).replace("-", "").replace(" ", ""), CASES["en-long-word-layout"]["source"].replace("-", "").replace(" ", ""))

    def test_dash_runs_stay_with_the_preceding_character(self):
        lines, _ = checks.wrap("育推廣中心》秋季班——「從零開始的鋼琴即興」", fonts.font("bold", 88), 860)
        self.assertFalse(any(line.startswith("—") for line in lines), lines)

    def test_overflow_reports_measured_excess_and_never_goes_below_the_minimum(self):
        result = checks.fit("太長的句子，" * 120, "hook", "bold", 942, 400)
        self.assertFalse(result["fits"])
        self.assertEqual(result["size"], checks.TYPE["hook"]["min"])
        finding = result["finding"]
        self.assertEqual(finding["code"], "needs_shorter_copy")
        self.assertGreater(finding["excessPx"], 0)
        self.assertGreater(finding["excessLines"], 0)
        self.assertLess(finding["suggestedMaxChars"], 720)
        fits = checks.fit("短句。", "hook", "bold", 942, 400)
        self.assertEqual((fits["fits"], fits["size"]), (True, checks.TYPE["hook"]["size"]))

    def test_text_normalization_drops_controls_and_keeps_markup_as_text(self):
        self.assertEqual(checks.normalize_text("a\r\n\x07b\t c\n\n\n\nd", 100), "a\nb  c\n\nd")
        with self.assertRaises(ValueError):
            checks.normalize_text("x" * 11, 10)
        html = CASES["adversarial-html-script"]["source"]
        lines, _ = checks.wrap(html, fonts.font("regular", 60), 942)
        self.assertTrue("".join(lines).startswith("<script>fetch("))


class DefaultCopy(unittest.TestCase):
    def test_copy_follows_the_creative_plan_and_drops_or_invents_nothing(self):
        for case_id in ("en-factual-workshop", "zh-hant-factual-studio", "mixed-script-product-names", "zh-hant-series-question",
                        "zh-hant-long-names-punctuation", "en-long-word-layout", "emoji-and-symbols"):
            source = CASES[case_id]["source"]
            prepared = slides.from_draft({"brandHub": {}}, {"text": source, "platform": "Instagram", "language": CASES[case_id]["language"]})
            self.assertEqual([s["plannedRole"] for s in prepared["slides"]], ["hook", "point 1", "point 2", "point 3", "point 4", "close"])
            self.assertEqual([s["key"] for s in prepared["slides"]], list(slides.KEYS))
            joined = "".join(s["text"] for s in prepared["slides"])
            self.assertEqual(joined.replace(" ", ""), source.replace(" ", ""), case_id)
            self.assertEqual(prepared["caption"], source)
            for position, slide in enumerate(prepared["slides"], start=1):
                if slide["text"]:
                    self.assertIn(" ".join(slide["text"].split()), slide["altText"])
        self.assertEqual(slides.from_draft({}, {"text": CASES["zh-hant-factual-studio"]["source"], "language": "zh-Hant"})["language"], "zh-Hant")

    def test_sentence_rules_keep_numbers_domains_and_urls_whole(self):
        self.assertEqual(slides.sentences("Price is US$9.50 at rafii.app today. Book now! https://x.test/?c=1 ok"),
                         ["Price is US$9.50 at rafii.app today.", "Book now!", "https://x.test/?c=1 ok"])
        self.assertEqual(slides.sentences("「真的嗎？」他問。好！"), ["「真的嗎？」", "他問。", "好！"])

    def test_alt_text_describes_only_what_is_visible(self):
        self.assertEqual(slides.default_alt(2, "Book now", None), "Slide 2 of 6. Text: Book now")
        photo = {"alt": "Studio with six wheels", "lineage": None}
        self.assertEqual(slides.default_alt(1, "Hi", photo), "Slide 1 of 6. Text: Hi Image: Studio with six wheels.")
        self.assertIn("AI-generated image: no description saved.", slides.default_alt(1, "Hi", {"lineage": {"operation": "generated"}}))
        self.assertEqual(slides.default_alt(3, "週六", None, lang="zh-Hant"), "第 3 張，共 6 張。文字：週六")


class Rendering(unittest.TestCase):
    def test_ac22_six_ordered_1080x1350_pngs_with_hashes_no_clipping_and_deterministic_bytes(self):
        texts = filled("zh-hant-long-names-punctuation", "Mixed 混合 copy")
        images = {"a" * 32: {"id": "a" * 32, "alt": "A photo"}, "b" * 32: {"id": "b" * 32, "lineage": {"operation": "generated"}}}
        payload = pack(texts, "zh-Hant", {2: "a" * 32, 4: "b" * 32})
        first = render.render(payload, {"palette": "rafii_violet", "weight": "bold"}, images, {"a" * 32: jpeg(), "b" * 32: jpeg(900, 1300)}, "zh-Hant")
        fonts.font.cache_clear()
        second = render.render(payload, {"palette": "rafii_violet", "weight": "bold"}, images, {"a" * 32: jpeg(), "b" * 32: jpeg(900, 1300)}, "zh-Hant")
        self.assertEqual([f["position"] for f in first["files"]], [1, 2, 3, 4, 5, 6])
        self.assertEqual([f["key"] for f in first["files"]], [s["key"] for s in payload])
        self.assertTrue(first["checks"]["ok"])
        background = checks.PALETTES["rafii_violet"]["background"]
        for a, b in zip(first["files"], second["files"]):
            self.assertEqual(a["png"], b["png"])                       # deterministic bytes
            self.assertEqual((a["sha256"], a["pixelSha256"]), (b["sha256"], b["pixelSha256"]))
            self.assertEqual(hashlib.sha256(a["png"]).hexdigest(), a["sha256"])
            with Image.open(io.BytesIO(a["png"])) as image:            # a real, complete PNG
                image.load()
                self.assertEqual((image.format, image.size, image.mode), ("PNG", (1080, 1350), "RGB"))
            self.assertTrue(checks.inside_safe_area(ink_box(a["png"], background)), a["position"])
        self.assertEqual(first["files"][3]["label"], "AI 生成圖像")
        self.assertEqual(first["renderer"]["layout"], "basic")
        self.assertEqual(first["renderer"]["fonts"]["bold"], fonts.sha256("bold"))

    def test_english_and_mixed_scripts_render_inside_the_safe_area(self):
        for case_id, lang in (("en-factual-workshop", "en"), ("mixed-script-product-names", "zh-Hant"), ("en-long-word-layout", "en")):
            prepared = slides.from_draft({}, {"text": CASES[case_id]["source"], "language": lang})
            texts = [s["text"] or "Written by the person." for s in prepared["slides"]]
            result = render.render(pack(texts, lang), {"palette": "rafii_light", "weight": "regular"}, {}, {}, lang)
            for item in result["files"]:
                self.assertTrue(checks.inside_safe_area(ink_box(item["png"], checks.PALETTES["rafii_light"]["background"])), (case_id, item["position"]))
            if case_id == "en-long-word-layout":
                self.assertIn("long_word_broken", [f["code"] for f in result["checks"]["slides"][0]["findings"]])

    def test_missing_glyphs_are_reported_per_slide_and_never_drawn(self):
        texts = ["Hook", CASES["emoji-and-symbols"]["source"], "Point", "Point", "Point", "Close ✅"]
        measured = render.public_checks(render.layout(pack(texts), {}, {}))
        self.assertFalse(measured["ok"])
        by_slide = {s["position"]: s for s in measured["slides"]}
        glyphs = next(f for f in by_slide[2]["findings"] if f["code"] == "missing_glyphs")["glyphs"]
        self.assertEqual([g["codePoint"] for g in glyphs], ["U+1F4A1", "U+2705"])
        self.assertEqual(next(f for f in by_slide[6]["findings"] if f["code"] == "missing_glyphs")["glyphs"][0]["char"], "✅")
        self.assertTrue(by_slide[1]["ok"] and by_slide[3]["ok"])
        with self.assertRaises(render.RenderError):
            render.render(pack(texts), {}, {}, {})

    def test_missing_image_empty_slide_and_overflow_block_rendering(self):
        texts = ["Hook", "", "Point", "Point " * 400, "Point", "Close"]
        measured = render.public_checks(render.layout(pack(texts, images={3: "c" * 32}), {}, {}))
        codes = {s["position"]: [f["code"] for f in s["findings"]] for s in measured["slides"]}
        self.assertIn("empty_slide", codes[2])
        self.assertIn("missing_image", codes[3])
        self.assertIn("needs_shorter_copy", codes[4])
        self.assertEqual(measured["blocking"], 3)

    def test_points_share_one_size_and_six_distinct_slides_are_required(self):
        texts = ["Hook", "Short", "A much longer point that needs more room than the others so it sets the size for all " * 3, "Short", "Short", "Close"]
        measured = render.public_checks(render.layout(pack(texts), {}, {}))
        sizes = {s["typography"]["size"] for s in measured["slides"] if s["role"] == "point"}
        self.assertEqual(len(sizes), 1)
        with self.assertRaises(render.RenderError):
            render.layout(pack(texts)[:5], {}, {})
        duplicate = pack(texts)
        duplicate[1]["key"] = "s1"
        with self.assertRaises(render.RenderError):
            render.layout(duplicate, {}, {})

    def test_verify_png_rejects_truncated_or_wrong_files(self):
        good = render.render(pack(["One", "Two", "Three", "Four", "Five", "Six"]), {}, {}, {})["files"][0]["png"]
        self.assertEqual(checks.verify_png(good)["bytes"], len(good))
        for bad in (good[:-20], good[:100], b"GIF89a" + good[6:]):
            with self.assertRaises(ValueError):
                checks.verify_png(bad)
        small = io.BytesIO()
        Image.new("RGB", (1080, 1080)).save(small, "PNG")
        with self.assertRaises(ValueError):
            checks.verify_png(small.getvalue())


if __name__ == "__main__":
    unittest.main()
