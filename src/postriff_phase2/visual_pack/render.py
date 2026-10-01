"""Deterministic six-slide 1080×1350 PNG renderer (PRD R-VIS-01/02, decision D-013).

`layout()` measures every slide and reports findings without drawing anything; `render()` draws only a pack whose
layout has no blocking finding, re-opens every file it produced and proves the ink of every text block stays inside its
box (and so inside the strictest platform safe area). Same inputs, fonts and Pillow build → same bytes.
"""
from __future__ import annotations

import io

from . import checks, fonts, slides as slide_copy

BLOCKING = ("empty_slide", "missing_glyphs", "needs_shorter_copy", "missing_image", "alt_text_missing")
X0, Y0, X1, Y1 = checks.SAFE_BOX
ACCENT = (X0, Y0 + 60, X0 + 72, Y0 + 68)
CONTENT_TOP = Y0 + 108
IMAGE_HEIGHT = 540
GAP = 48
PAD = 4                     # measured text keeps this distance from its box, so side bearings can never touch it
RADIUS = 28
LABEL_SIZE = 26


class RenderError(ValueError):
    """A pack that must not be drawn (blocking findings) or a drawn file that failed its own verification."""


def boxes(has_image: bool) -> dict:
    if not has_image:
        return {"image": None, "text": (X0, CONTENT_TOP, X1, Y1)}
    image = (X0, CONTENT_TOP, X1, CONTENT_TOP + IMAGE_HEIGHT)
    return {"image": image, "text": (X0, image[3] + GAP, X1, Y1)}


def _weight(role: str, settings: dict) -> str:
    return "bold" if role in ("hook", "close") else settings["weight"]


def _fit(text, role, weight, box, max_size=None):
    width, height = box[2] - box[0] - 2 * PAD, box[3] - box[1] - 2 * PAD
    return checks.fit(text, role, weight, width, height, max_size=max_size)


def layout(pack_slides: list[dict], settings: dict, images: dict, lang: str = "en") -> dict:
    """Findings and measured typography for all six slides. `images` maps asset id → the workspace asset record, or
    None when it is missing, deleted or not a usable image. Nothing is drawn."""
    if len(pack_slides) != checks.SLIDES or len({s["key"] for s in pack_slides}) != checks.SLIDES:
        raise RenderError("a pack has exactly six distinct slides")
    settings = checks.settings(settings)
    out = []
    for position, slide in enumerate(pack_slides, start=1):
        role = checks.ROLES[position - 1]
        weight = _weight(role, settings)
        asset_id = slide.get("imageAssetId")
        asset = images.get(asset_id) if asset_id else None
        box = boxes(bool(asset_id))
        text = slide.get("text") or ""
        findings = []
        if not text.strip():
            findings.append({"code": "empty_slide", "severity": "blocking"})
        missing = checks.missing_glyphs(text, weight)
        label = slide_copy.generated_label(asset, lang) if asset else None
        missing += [g for g in checks.missing_glyphs(label or "", "bold") if g not in missing]
        if missing:
            findings.append({"code": "missing_glyphs", "severity": "blocking", "glyphs": missing})
        if asset_id and asset is None:
            findings.append({"code": "missing_image", "severity": "blocking", "assetId": asset_id})
        if not (slide.get("altText") or "").strip():
            findings.append({"code": "alt_text_missing", "severity": "blocking"})
        elif text.strip() and " ".join(text.split()) not in " ".join(slide["altText"].split()):
            findings.append({"code": "alt_text_differs", "severity": "warning"})
        if label:
            findings.append({"code": "generated_image_labelled", "severity": "info", "label": label})
        fitted = _fit(text, role, weight, box["text"]) if text.strip() else None
        out.append({"position": position, "key": slide["key"], "role": role, "weight": weight, "box": box, "fit": fitted,
                    "findings": findings, "label": label, "assetId": asset_id})
    # The four points share one size (the largest every fitting point allows), so the carousel reads as one piece.
    points = [s for s in out if s["role"] == "point" and s["fit"] and s["fit"]["fits"]]
    shared = min((s["fit"]["size"] for s in points), default=None)
    for item in points:
        if item["fit"]["size"] != shared:
            item["fit"] = _fit(pack_slides[item["position"] - 1]["text"], "point", item["weight"], item["box"]["text"], max_size=shared)
    for item in out:
        fitted = item["fit"]
        if fitted and not fitted["fits"]:
            item["findings"].append({"severity": "blocking", **fitted["finding"]})
        if fitted and fitted["broken"]:
            item["findings"].append({"code": "long_word_broken", "severity": "warning", "words": fitted["broken"][:5]})
    blocking = sum(1 for item in out for f in item["findings"] if f["severity"] == "blocking")
    return {"ok": blocking == 0, "blocking": blocking, "warnings": sum(1 for item in out for f in item["findings"] if f["severity"] == "warning"),
            "settings": settings, "slides": out}


def public_checks(result: dict) -> dict:
    """The stored/served form of a layout: findings and typography, no geometry internals."""
    return {"definition": "rafii.visual-pack-checks.v1", "ok": result["ok"], "blocking": result["blocking"], "warnings": result["warnings"],
            "safeArea": {k: checks.SAFE[k] for k in ("top", "bottom", "sides")},
            "slides": [{"position": s["position"], "key": s["key"], "role": s["role"], "ok": not any(f["severity"] == "blocking" for f in s["findings"]),
                        "findings": s["findings"], "typography": ({"weight": s["weight"], "size": s["fit"]["size"], "lines": len(s["fit"]["lines"])}
                                                                    if s["fit"] else None)} for s in result["slides"]]}


def _fitted_image(raw: bytes, size: tuple[int, int]):
    from PIL import Image, ImageOps
    with Image.open(io.BytesIO(raw)) as source:
        if source.format not in ("JPEG", "PNG"):
            raise RenderError("an approved image must be a JPEG or PNG rendition")
        source.load()
        image = source.convert("RGB")
    return ImageOps.fit(image, size, method=Image.Resampling.LANCZOS, bleed=0.0, centering=(0.5, 0.5))


def _draw_slide(item: dict, settings: dict, image_bytes: bytes | None) -> bytes:
    from PIL import Image, ImageDraw
    palette = checks.PALETTES[settings["palette"]]
    canvas = Image.new("RGB", (checks.WIDTH, checks.HEIGHT), checks.rgb(palette["background"]))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((ACCENT[0], ACCENT[1], ACCENT[2] - 1, ACCENT[3] - 1), fill=checks.rgb(palette["accent"]))
    muted = Image.new("L", canvas.size, 0)
    ImageDraw.Draw(muted).text((X0, Y0), f"{item['position']}/{checks.SLIDES}", font=fonts.font("regular", checks.COUNTER_SIZE), fill=255, anchor="la")
    image_box = item["box"]["image"]
    if image_box is not None:
        if image_bytes is None:
            raise RenderError("an approved image is missing")
        size = (image_box[2] - image_box[0], image_box[3] - image_box[1])
        rounded = Image.new("L", size, 0)
        ImageDraw.Draw(rounded).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=RADIUS, fill=255)
        canvas.paste(_fitted_image(image_bytes, size), image_box[:2], rounded)
        if item["label"]:
            label_font = fonts.font("bold", LABEL_SIZE)
            ascent, descent = label_font.getmetrics()
            width = int(round(label_font.getlength(item["label"]))) + 28
            pill = (image_box[0] + 20, image_box[3] - 20 - (ascent + descent + 16), image_box[0] + 20 + width, image_box[3] - 20)
            draw.rounded_rectangle(pill, radius=(pill[3] - pill[1]) // 2, fill=checks.rgb(palette["background"]))
            label_mask = Image.new("L", canvas.size, 0)
            ImageDraw.Draw(label_mask).text((pill[0] + 14, pill[1] + 8), item["label"], font=label_font, fill=255, anchor="la")
            _inside(label_mask.getbbox(), pill, "image label")
            canvas.paste(checks.rgb(palette["text"]), (0, 0, *canvas.size), label_mask)
    fitted = item["fit"]
    box = item["box"]["text"]
    font = fonts.font(item["weight"], fitted["size"])
    step = checks.line_step(font, fitted["leading"])
    top = box[1] + PAD
    if item["box"]["image"] is None:   # text alone is centred; under an image it starts right below it
        top += (box[3] - box[1] - 2 * PAD - fitted["height"]) // 2
    body = Image.new("L", canvas.size, 0)
    pen = ImageDraw.Draw(body)
    for index, line in enumerate(fitted["lines"]):
        if line:
            pen.text((box[0] + PAD, top + index * step), line, font=font, fill=255, anchor="la")
    _inside(body.getbbox(), box, "text")
    _inside(muted.getbbox(), checks.SAFE_BOX, "slide number")
    canvas.paste(checks.rgb(palette["text"]), (0, 0, *canvas.size), body)
    canvas.paste(checks.rgb(palette["muted"]), (0, 0, *canvas.size), muted)
    out = io.BytesIO()
    canvas.save(out, format="PNG", compress_level=6, optimize=False)
    return out.getvalue()


def _inside(ink, box, what):
    if ink is not None and not (ink[0] >= box[0] and ink[1] >= box[1] and ink[2] <= box[2] and ink[3] <= box[3]):
        raise RenderError(f"{what} would be clipped")
    if ink is not None and not checks.inside_safe_area(ink):
        raise RenderError(f"{what} would leave the safe area")


def render(pack_slides: list[dict], settings: dict, images: dict, image_bytes: dict, lang: str = "en") -> dict:
    """Six verified PNGs for a pack without blocking findings. `image_bytes` maps asset id → the stored rendition."""
    measured = layout(pack_slides, settings, images, lang)
    if not measured["ok"]:
        raise RenderError("fix the blocking findings before rendering")
    files = []
    for item in measured["slides"]:
        raw = _draw_slide(item, measured["settings"], image_bytes.get(item["assetId"]) if item["assetId"] else None)
        try:
            verified = checks.verify_png(raw)
        except ValueError as error:
            raise RenderError(f"slide {item['position']} failed verification: {error}") from None
        files.append({"position": item["position"], "key": item["key"], "role": item["role"], "png": raw, **verified,
                      "typography": {"weight": item["weight"], "size": item["fit"]["size"], "lines": len(item["fit"]["lines"])},
                      "label": item["label"]})
    return {"checks": public_checks(measured), "files": files, "settings": measured["settings"], "renderer": renderer()}


def renderer() -> dict:
    from PIL import __version__ as pillow, features
    return {"engine": "pillow", "pillow": pillow, "freetype": features.version("freetype2"), "layout": "basic",
            "fonts": {weight: fonts.sha256(weight) for weight in fonts.WEIGHTS}, "png": {"compressLevel": 6, "optimize": False}}
