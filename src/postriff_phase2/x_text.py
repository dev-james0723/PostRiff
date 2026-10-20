"""X v3 weighted text using reviewed local parser and pinned Unicode data.

Official rules: https://docs.x.com/fundamentals/counting-characters
Source/license/patch hashes: _vendor/twitter_text/VENDOR.json.
This validates local input; it never establishes provider acceptance.
"""
import unicodedata
from ._vendor.twitter_text import parse_tweet
from ._vendor.twitter_text.has_invalid_characters import has_invalid_characters

def normalize_text(value):
    if not isinstance(value,str):
        raise ValueError("Text must be a string.")
    # Scan the complete input even where the parser skips URL/emoji entities.
    if "\x00" in value or has_invalid_characters(value):
        raise ValueError("Text contains characters that X does not permit.")
    value.encode("utf-8",errors="strict")
    return unicodedata.normalize("NFC",value).replace("\r\n","\n").replace("\r","\n")

def text_eligibility(text):
    try:
        result=parse_tweet(normalize_text(text))
    except (TypeError,ValueError,UnicodeError):
        return "invalid"
    if result.valid:
        return "ordinary"
    return "long" if result.weightedLength>280 else "invalid"
