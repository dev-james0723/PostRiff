"""Bounded, explicitly labelled OCR for PDF pages without a reliable text layer (engineering spec §7 Documents; A013).

Only pages that structural extraction listed in `media.ocrNeededPages` are read, never pages with digital text. Each
page's largest embedded image is decoded in the extraction sandbox, re-encoded as a JPEG (metadata dropped) and sent
through `providers.describe_image(task='ocr')`. Results are separate `origin='ocr'` segments with an uncertainty label
and their own extractor, so they never overwrite or supersede digital text.

This is a cloud capability (`cloud`/`ocr`): worker A's job layer checks the processing grant and reserves budget before
`run`. Without a grant the extract capability stays `partial` with the honest reason. Pages that have no embedded image
(vector-only scans) need a page renderer that this runtime does not have; they remain listed, never guessed.
"""
from __future__ import annotations

from postriff_alpha.domain import AlphaError

from . import policy, structure, versions
from .providers import ProviderUnavailable
from .segments import detect_language, job_attr, job_raw, outcome, register_processors

VERSION = "ocr-vision-1"
EXTRACTOR = "ocr-vision"
MAX_PAGES = structure.MAX_OCR_PAGES
MAX_TEXT = 20000
UNCERTAINTY = "OCR from a page image; may contain recognition errors"


def needed_pages(version: dict) -> list[int]:
    pages = (version.get("media") or {}).get("ocrNeededPages") or []
    return sorted({p for p in pages if type(p) is int and p >= 1})


def _applies(version: dict) -> bool:
    return version.get("kind") == "document" and str(version.get("extension") or "").lower() == "pdf" and bool(needed_pages(version))


def _estimate(job):
    pages = needed_pages(job_attr(job, "version"))[:MAX_PAGES]
    return job_attr(job, "providers").estimate("vision", units=len(pages)) if pages else None


def _combine(receipts: list[dict]) -> dict | None:
    if not receipts:
        return None
    costs = [r.get("cost") or {"kind": "unknown"} for r in receipts]
    if all(x.get("kind") == "actual" for x in costs):
        cost = {"kind": "actual", "usdMicro": sum(int(x["usdMicro"]) for x in costs)}
    elif any(x.get("kind") == "unknown" for x in costs):
        cost = {"kind": "unknown", "usdMicro": None}
    else:
        cost = {"kind": "estimated", "usdMicro": sum(int(x.get("usdMicro") or 0) for x in costs), "version": costs[0].get("version")}
    return {"provider": receipts[0]["provider"], "model": receipts[0]["model"], "calls": len(receipts),
            "latencyMs": sum(int(r.get("latencyMs") or 0) for r in receipts), "usage": {"images": len(receipts)}, "cost": cost}


def _pages_phrase(pages) -> str:
    return ("Page " if len(pages) == 1 else "Pages ") + ", ".join(map(str, pages))


def ocr_pages(providers, raw: bytes, pages: list[int], *, images: dict | None = None) -> dict:
    """OCR the given page numbers of one PDF. `images` ({page: jpeg}) may be supplied by the caller; otherwise they are
    decoded in the extraction sandbox."""
    pages = sorted({p for p in pages if type(p) is int and p >= 1})
    todo, skipped = pages[:MAX_PAGES], pages[MAX_PAGES:]
    try:
        providers.require("vision")
    except ProviderUnavailable as error:
        return outcome("unsupported", error="provider_unavailable", detail=f"OCR is not set up: {error.reason}.", extractor=EXTRACTOR,
                       extractor_version=VERSION)
    if images is None:
        try:
            images = structure.page_images(raw, todo)
        except AlphaError as error:
            return outcome("failed", error="unreadable", detail=str(error), extractor=EXTRACTOR, extractor_version=VERSION)
    items, unresolved, receipts, failure = [], [], [], None
    for number in todo:
        image = images.get(number)
        if not image:
            unresolved.append(number)
            continue
        try:
            result = providers.describe_image(image, "image/jpeg", task="ocr")
        except AlphaError as error:
            failure = error
            unresolved += [p for p in todo if p >= number]
            break
        receipts.append(result.receipt())
        value = result.value if isinstance(result.value, dict) else {}
        text = str(value.get("text") or "").replace("\x00", "").strip()[:MAX_TEXT]
        if not text:
            continue  # the page image holds no legible text; nothing is invented for it
        uncertain = value.get("uncertain") is True or "[illegible]" in text
        items.append({"kind": "ocr", "origin": "ocr", "text": text, "locator": {"kind": "page", "page": number},
                      "language": detect_language(text)["language"],
                      "uncertainty": UNCERTAINTY + ("; the model marked some text as uncertain" if uncertain else "")})
    notes = []
    if unresolved:
        notes.append(f"{_pages_phrase(sorted(set(unresolved)))} could not be read: "
                     + ("the OCR provider failed." if failure else "no embedded page image (a page rendering is needed)."))
    if skipped:
        notes.append(f"{_pages_phrase(skipped)} exceed the {MAX_PAGES}-page OCR limit for one run.")
    provider = _combine(receipts)
    model = provider["model"] if provider else providers.model("vision")
    if failure is not None and not items:
        return outcome("failed", error="provider_failed", detail=" ".join(notes), provider=provider,
                       retryable=failure.status >= 500 or failure.code == "library_provider_rate_limited", extractor=EXTRACTOR,
                       extractor_version=f"{VERSION}:{model}"[:80])
    state = "partial" if unresolved or skipped else "ready"
    return outcome(state, segments=items, detail=" ".join(notes) or None, provider=provider, error="provider_failed" if failure else None,
                   retryable=bool(failure), extractor=EXTRACTOR, extractor_version=f"{VERSION}:{model}"[:80])


def _run(job) -> dict:
    version = job_attr(job, "version")
    pages = needed_pages(version)
    if not pages:
        return outcome("ready", detail="No pages need OCR.", extractor=EXTRACTOR, extractor_version=VERSION)
    return ocr_pages(job_attr(job, "providers"), job_raw(job), pages)


PROCESSOR = {"name": "library.ocr", "capability": "extract", "version": VERSION, "location": "cloud", "category": "ocr",
             "applies": _applies, "estimate": _estimate, "run": _run}
PROCESSORS = [PROCESSOR]


def ocr_asset(ctx, ref: dict, *, raw: bytes | None = None, providers=None) -> dict:
    """In-request OCR for one version. Without a cloud OCR grant the result is `partial` with the honest reason and no
    provider call. Budget reservation and the grant recheck before writing belong to the job layer."""
    version = versions.resolve(ctx, ref)
    pages = needed_pages(version)
    if not pages:
        return outcome("ready", detail="No pages need OCR.", extractor=EXTRACTOR, extractor_version=VERSION)
    decision = policy.authorize_processing(ctx, version, "cloud", "ocr")
    if not decision.allowed:
        return outcome("partial", error=decision.reason, detail=f"{policy.message(decision.reason)} {_pages_phrase(pages)} still need OCR.",
                       extractor=EXTRACTOR, extractor_version=VERSION)
    from .media import default_providers, read_original
    return ocr_pages(providers or default_providers(ctx), raw if raw is not None else read_original(ctx, version), pages)


register_processors(PROCESSORS)
