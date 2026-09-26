"""Language groups used for calibration (growth Phase 0).

Calibration is validated per group, never across groups: a fit on English is never applied to Traditional Chinese.
zh-HK / zh-TW / zh-MO / zh-Hant* -> "zh-Hant"; en* -> "en"; any other tag is its own group.
"""
_HANT = ("zh-hk", "zh-tw", "zh-mo")


def lang_group(lang):
    tag = (lang or "").strip().lower()
    if tag in _HANT or tag.startswith("zh-hant"):
        return "zh-Hant"
    if tag == "en" or tag.startswith("en-"):
        return "en"
    return lang or "unknown"
