"""Conservative Unicode validation from official twitter-text v3 weights.
https://github.com/twitter/twitter-text/blob/master/config/v3.json
https://docs.x.com/fundamentals/counting-characters

An upper bound can accept short input; uncertain URL/emoji overcounts never
become an invented X restriction. Full parser conformance remains a release gate.
"""
import re
import unicodedata

_WEIGHT_ONE = ((0,0x10ff),(0x2000,0x200d),(0x2010,0x201f),(0x2032,0x2037))
_URL_MARKERS = re.compile(r"[.:\u3002\uff0e\uff61]")
_EMOJI_COMPLEX = re.compile(r"[\u200d\ufe0f\u20e3\U0001f000-\U0001faff]")


def weighted_upper_bound(text):
    value = unicodedata.normalize("NFC", text)
    weight = sum(1 if any(lo <= ord(c) <= hi for lo,hi in _WEIGHT_ONE) else 2 for c in value)
    # Each possible URL contains a dot or colon. Adding 23 per marker overcounts
    # raw text but cannot undercount a recognized short URL's transformed length.
    return weight + 23 * len(_URL_MARKERS.findall(value))


def text_eligibility(text):
    if not isinstance(text, str):
        return "unverified"
    if weighted_upper_bound(text) <= 280:
        return "ordinary"
    if _URL_MARKERS.search(text) or _EMOJI_COMPLEX.search(text):
        return "unverified"
    return "long"
