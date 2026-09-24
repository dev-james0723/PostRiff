"""Deterministic reading of a chat message into an automation, an edit, or a question about one (orchestration §6).

Rafii's model reading (request_model) is the main way a message is understood; this module is the fallback when no
model may read it or its answer is unusable, and it returns the same Reading shape. It is compositional rather than a
list of known requests: a message is split into clauses; each clause's verb says which stage its time belongs to
(the recurrence, drafting, review, or publication), so "every Wednesday … publish it Saturday at 6 PM" keeps two
instants; research, source limits, quotes, platform notes, conditions and the publish policy are each read on their
own and combined. Anything it cannot tell is left empty so the chat asks, never guessed into an authority (the
publish policy in particular is only ever what the person said).
"""
from __future__ import annotations

import datetime as dt
import re
from zoneinfo import ZoneInfo

from postriff_alpha.domain import clean

from . import campaigns, intent

DAYS = campaigns.WEEKDAY_NAMES
DEFAULT_TIME = "09:00"
PERIODS = {"morning": "09:00", "noon": "12:00", "lunchtime": "12:00", "afternoon": "14:00", "evening": "18:00", "night": "20:00", "tonight": "20:00"}
# Publishers by name → their web addresses (a directory, not a list of supported requests). Unknown names stay words.
PUBLISHERS = (
    (r"\bbbc(?:\s+news)?\b", ("bbc.co.uk", "bbc.com")), (r"\breuters\b", ("reuters.com",)), (r"\bassociated press\b|\bap news\b", ("apnews.com",)),
    (r"\bnew york times\b|\bnyt\b", ("nytimes.com",)), (r"\b(?:the\s+)?guardian\b", ("theguardian.com",)), (r"\bwashington post\b", ("washingtonpost.com",)),
    (r"\bwall street journal\b|\bwsj\b", ("wsj.com",)), (r"\bfinancial times\b|\bthe ft\b", ("ft.com",)), (r"\bbloomberg\b", ("bloomberg.com",)),
    (r"\b(?:the\s+)?economist\b", ("economist.com",)), (r"\bnpr\b", ("npr.org",)), (r"\bcnn\b", ("cnn.com",)), (r"\bal jazeera\b", ("aljazeera.com",)),
    (r"\bscmp\b|\bsouth china morning post\b", ("scmp.com",)), (r"\bnature\b(?!\s+of)", ("nature.com",)), (r"\bscience magazine\b|\bscience\.org\b", ("science.org",)),
    (r"\bscientific american\b", ("scientificamerican.com",)), (r"\bnew scientist\b", ("newscientist.com",)), (r"\bquanta\b", ("quantamagazine.org",)),
    (r"\bmit technology review\b|\btechnology review\b", ("technologyreview.com",)), (r"\bwired\b", ("wired.com",)), (r"\bthe verge\b", ("theverge.com",)),
    (r"\btechcrunch\b", ("techcrunch.com",)), (r"\bars technica\b", ("arstechnica.com",)), (r"\bharvard business review\b|\bhbr\b", ("hbr.org",)),
    (r"\bforbes\b", ("forbes.com",)), (r"\bthe atlantic\b", ("theatlantic.com",)), (r"\bnational geographic\b|\bnat ?geo\b", ("nationalgeographic.com",)),
    (r"\bsmithsonian\b", ("smithsonianmag.com",)), (r"\bthe conversation\b", ("theconversation.com",)), (r"\barxiv\b", ("arxiv.org",)),
    (r"\bgramophone\b", ("gramophone.co.uk",)), (r"\bpitchfork\b", ("pitchfork.com",)), (r"\brolling stone\b", ("rollingstone.com",)),
    (r"\bclassic fm\b", ("classicfm.com",)), (r"\bbillboard\b", ("billboard.com",)), (r"\bhong kong free press\b|\bhkfp\b", ("hongkongfp.com",)),
)
# "Reputable <field> publications" → well-known outlets in that field (the person's words are kept as the description).
FIELDS = (
    (r"scien\w*", ("nature.com", "science.org", "scientificamerican.com", "newscientist.com", "quantamagazine.org", "sciencenews.org", "theconversation.com")),
    (r"tech\w*|ai\b|artificial intelligence", ("technologyreview.com", "wired.com", "theverge.com", "arstechnica.com", "techcrunch.com")),
    (r"business|finance|financial|econom\w*|market\w*", ("reuters.com", "ft.com", "bloomberg.com", "economist.com", "hbr.org", "wsj.com")),
    (r"health|medical|medicine", ("statnews.com", "nih.gov", "who.int", "nejm.org", "thelancet.com", "health.harvard.edu")),
    (r"music|classical", ("gramophone.co.uk", "classicfm.com", "npr.org", "theguardian.com", "pitchfork.com")),
    (r"news|world", ("reuters.com", "apnews.com", "bbc.co.uk", "bbc.com", "npr.org")),
    (r"art\w*|design|culture", ("theartnewspaper.com", "artnews.com", "dezeen.com", "theguardian.com")),
)

_TIMES_A_WEEK = re.compile(r"\b(twice|two\s+times|2\s*x|2\s+times|three\s+times|3\s*x|3\s+times)\s+a\s+week\b", re.I)
_OTHER_WEEK = re.compile(r"\bevery\s+(?:other|second|two)\s+weeks?\b|\bevery\s+other\s+(?:mon|tue|wed|thu|fri|sat|sun)\w*|\bbi-?weekly\b|\bfortnightly\b|隔星期|隔週|隔周", re.I)
_RECUR = re.compile(r"\b(?:every|each)\b|\b(?:twice|two\s+times|three\s+times|[23]\s*x)\s+a\s+week\b|\b(?:weekly|daily|monthly|fortnightly|weekdays|weekends)\b|\bon\s+(?:mon|tues|wednes|thurs|fri|satur|sun)days\b|逢|每(?:個|个)?(?:星期|禮拜|礼拜|週|周|日|天|月)", re.I)
_PUBLISH = re.compile(r"\b(?:publish\w*|post(?:ed|ing)?|go(?:es)?\s+live|put\s+(?:it|them)\s+(?:out|up)|release|share\s+(?:it|them))\b|發佈|发布|出post|發post|发post|出帖|發帖|發到|发到|發去|发去|post去|出去", re.I)
_REVIEW = re.compile(r"\bready\s+(?:for\s+(?:me|my\s+review|review|approval|my\s+approval)|by)\b|\bhave\s+(?:it|them|the\s+drafts?)\s+ready\b|\bsend\s+(?:it|them|the\s+drafts?)\s+(?:to\s+me|for\s+(?:review|approval))\b|\bfor\s+(?:my\s+)?(?:review|approval)\b|\bto\s+(?:review|approve)\b|\blet\s+me\s+(?:review|approve|see|check)\b", re.I)
_GENERATE = re.compile(r"\b(?:find|search|look\s+for|pick|choose|discover|grab|pull|curate|create|make|write|draft|prepare|compose|turn\s+(?:it|them)\s+into|generate|come\s+up\s+with|summari[sz]e)\b|寫|写|準備|准备|搵", re.I)
_DRAFT_ONLY = re.compile(r"\b(?:just|only)\s+(?:prepare\s+)?drafts?\b|\bdrafts?\s+only\b|\b(?:don'?t|do\s+not|never)\s+(?:publish|post)\b|\bi'?ll\s+(?:post|publish)\s+(?:it|them)?\s*(?:myself|manually)\b|\bdraft\s+(?:me|them|it)\b|\bdrafting\s+me\b|淨係|只要草稿", re.I)
_AUTO = re.compile(r"\bauto[- ]?(?:publish|post)\w*\b|\b(?:publish|post)\w*\s+(?:it\s+|them\s+|these\s+)?automatically\b|\bautomatically\s+(?:publish|post)\w*\b|\bwithout\s+(?:asking|checking\s+with)\s+me\b|\bno\s+need\s+(?:to|for)\s+(?:ask|approv|review)\w*\b|自動(?:發佈|发布|出)", re.I)
_APPROVE = re.compile(r"\bif\s+i\s+approve\b|\bonce\s+i\s+approve\b|\bafter\s+i\s+approve\b|\bwhen\s+i\s+approve\b|\b(?:my|for)\s+approval\b|\blet\s+me\s+(?:review|approve|check|see)\b|\bsend\s+(?:it|them|the\s+drafts?)\s+to\s+me\b|\breview\s+(?:it|them)\s+first\b|\bapprove\s+(?:it|them)?\s*first\b|\bask\s+me\s+(?:first|before)\b|\bhave\s+(?:it|them)\s+ready\s+for\s+me\b|畀我(?:睇|批)|俾我(?:睇|批)|要我批|我批准|批准先|審批|审批", re.I)
_RESEARCH = re.compile(r"\b(?:find|search\s+for|look\s+for|pick|choose|discover|grab|pull|curate|get)\b[^.;]{0,80}?\b(?:article|news|story|stories|piece|study|studies|paper|report|headline|something|anything|item|quote|finding|research|post)s?\b|\b(?:latest|recent|top|trending)\s+(?:news|article|stories|headlines|research|papers)\b|\bnews\s+from\b|\b(?:using|with|from)\s+(?:a|an)\s+(?:quote|article|story)\b", re.I)
_QUOTE = re.compile(r"\b(?:using\s+|with\s+|use\s+)?(?:a|an)\s+quote\s+(?:from|by)\s+(?:a|an|the)?\s*([\w\s'-]{3,60}?)(?=[,.;]|\s+(?:and|then|to|for|on|every|each|at)\b|$)", re.I)
_REPUTABLE = re.compile(r"\b(reputable|trusted|credible|reliable|respected|major|well[- ]known|top|leading)\s+((?:[\w-]+\s+){0,3}?)(publications?|sources?|outlets?|journals?|magazines?|news(?:papers?|\s+sites?)?|sites?|media)\b", re.I)
_SKIP = re.compile(r"\bskip\b|\bdon'?t\s+(?:post|publish|write)\b[^.]{0,40}\bif\b|\bonly\s+if\b|\bunless\b|\bif\s+(?:there\s+(?:is|isn'?t|'?s)\s+)?(?:nothing|no)\b", re.I)
_ANYWAY = re.compile(r"\b(?:otherwise|if\s+not)\b[^.]{0,40}\b(?:write|post|draft)\b|\banyway\b", re.I)
_VERSION = re.compile(r"\b(?:a|an)\s+((?:[\w-]+\s+){0,2}?)(?:version|take|edit|cut)\s+(?:on|for|to)\s+([\w\s/()]+?)(?=\s+and\s+(?:a|an)\s|[,.;]|$|\s+(?:on|at|every|each|by)\s)", re.I)
_RELATES = re.compile(r"\b(?:that\s+)?(?:relates?|related|relating|connected|linked)\s+to\s+([^,.;]{3,80})|\b(?:about|on\s+the\s+topic\s+of|regarding|covering)\s+([^,.;]{3,80})", re.I)
_DAY_OFFSET = re.compile(r"\b(?:the\s+)?(day|two\s+days|2\s+days|three\s+days|3\s+days)\s+(before|after|later|earlier)\b|\bthe\s+same\s+day\b|\bthe\s+next\s+day\b|\bthe\s+night\s+before\b|\bthe\s+evening\s+before\b|\bthe\s+morning\s+of\b", re.I)
_MIN_OFFSET = re.compile(r"\b(an?|one|two|three|four|five|six|\d{1,2})\s+(hours?|minutes?|mins?)\s+(before|after|later|earlier|ahead)\b|\bhalf\s+an\s+hour\s+(before|after|later|earlier)\b", re.I)
_WEEKDAY = re.compile(r"\b(?:next\s+)?(mon|tues?|wed(?:nes)?|thu(?:rs?)?|fri|sat(?:ur)?|sun)(?:day)?s?\b", re.I)
_PERIOD = re.compile(r"\b(morning|noon|lunchtime|afternoon|evening|night|tonight)\b", re.I)
_CONTENT = (
    (re.compile(r"\breflect\w*|\bresponse\b|\brespond\b|\breact\w*|\bthoughts?\s+on\b|\bmy\s+take\b|\bcommentary\b", re.I), "reflection"),
    (re.compile(r"\bquotes?\b", re.I), "quote"),
    (re.compile(r"\bsummar\w*|\bdigest\b|\bround-?up\b", re.I), "summary"),
    (re.compile(r"\brecap\w*", re.I), "recap"),
    (re.compile(r"\bstatus\s+update\b|\bupdates?\b|\bnews\s+from\s+(?:my|our)\b", re.I), "update"),
    (re.compile(r"\bannounce\w*", re.I), "announcement"),
    (re.compile(r"\bpromot\w*|\bsale\b|\boffer\b|\bdiscount\b", re.I), "promotion"),
    (re.compile(r"\btips?\b|\bhow[- ]to\b|\btutorial\b|貼士|贴士", re.I), "tip"),
    (re.compile(r"\beducat\w*|\bexplain\w*|\bteach\w*|\blesson\b", re.I), "education"),
    (re.compile(r"\bthread\b", re.I), "thread"),
    (re.compile(r"\bstor(?:y|ies)\b", re.I), "story"),
    (re.compile(r"\bquestions?\b|\bpolls?\b", re.I), "question"),
)
_URL = re.compile(r"https?://[^\s<>\"'）)\]]+")
_CLAUSE_SPLIT = re.compile(r"(?<=[.;!?。！？；])\s+|[.;!?。！？；]$|,\s*(?=(?:and\s+)?(?:then\s+)?(?:find|search|look|pick|choose|create|make|write|draft|prepare|turn|publish|post|share|have|send|skip|if|once|after|when|use|using|summari[sz]e|generate)\b)|\s+(?:and\s+)?then\s+|,?\s+and\s+(?=(?:then\s+)?(?:publish|post|share|have|send|skip|turn|write|make|create)\b)", re.I)

# Edits and questions about existing automations.
_EDIT_MOVE = re.compile(r"\b(?:move|change|switch|shift|reschedule|push|make)\s+(?:it|this|that|them|these|the\s+[\w\s-]{1,40}?(?:automation|post|posts))?\s*(?:to|until|till|on|for)?\s*(?=(?:next\s+)?(?:mon|tue|wed|thu|fri|sat|sun|today|tomorrow|\d)|\d)|\binstead\b|\bactually\b[^.]{0,40}\b(?:mon|tue|wed|thu|fri|sat|sun|\d{1,2}\s*(?:am|pm)|at\s+\d)", re.I)
_EDIT_REMOVE = re.compile(r"\b(?:stop|quit)\s+(?:posting|publishing|sharing)\s+(?:this\s+|it\s+|these\s+|them\s+)?(?:to|on)\s+([\w\s/]+?)(?=[,.;]|$)|\b(?:don'?t|do\s+not|no\s+longer)\s+(?:post|publish|share)\s+(?:this\s+|it\s+|these\s+|them\s+)?(?:to|on)\s+([\w\s/]+?)(?=[,.;]|$)|\b(?:remove|drop)\s+([\w/]+)\s*(?:from\s+(?:it|this|the\s+automation))?(?=[,.;]|$)", re.I)
_EDIT_ADD = re.compile(r"\b(?:also|add)\s+(?:post\s+|publish\s+|share\s+)?(?:it\s+|this\s+|them\s+|the\s+[\w\s'-]{1,40}?\s+(?:one|automation|posts?)\s+)?(?:to|on)\s+([\w\s/]+?)(?=[,.;]|$)", re.I)
_EDIT_SOURCE = re.compile(r"\buse\s+([\w\s.&'-]{2,60}?)\s+instead\s+of\s+([\w\s.&'-]{2,60}?)(?=[,.;]|$)|\b(?:switch|change)\s+(?:the\s+)?source\s+to\s+([\w\s.&'-]{2,60}?)(?=[,.;]|$)|\bonly\s+(?:use|from)\s+([\w\s.&'-]{2,60}?)(?=[,.;]|$)", re.I)
_EDIT_AUTO = re.compile(r"\bmake\s+(?:it|this|these|them)\s+auto[- ]?publish\w*|\b(?:publish|post)\w*\s+(?:these\s+|them\s+|it\s+)?automatically\b|\bauto[- ]?publish\w*\s+(?:from\s+now\s+on|going\s+forward)", re.I)
_EDIT_REVIEW = re.compile(r"\b(?:ask\s+me|check\s+with\s+me)\s+(?:before|first)\b|\bi\s+want\s+to\s+(?:approve|review)\b|\bstop\s+auto[- ]?publish\w*|\brequire\s+(?:my\s+)?approval\b", re.I)
_EDIT_PAUSE = re.compile(r"\bpause\b(?:[^.]{0,40}?\bfor\s+(a|an|one|two|three|four|five|six|\d{1,2})\s+(days?|weeks?|months?))?(?:[^.]{0,40}?\buntil\s+([^,.;]{3,30}))?", re.I)
_EDIT_RESUME = re.compile(r"\b(?:resume|unpause|restart)\b|\bturn\s+(?:it|this|them)\s+(?:back\s+)?on\b|\bstart\s+(?:it|this)\s+again\b", re.I)
_EDIT_DELETE = re.compile(r"\b(?:delete|remove|cancel|get\s+rid\s+of|kill|stop)\s+(?:the\s+|this\s+|that\s+|my\s+)?([\w\s'-]{0,60}?)\s*automation\b|\bdelete\s+(?:it|this|that)\b", re.I)
_EXPLAIN = re.compile(r"\bwhy\s+(?:did|didn'?t|was|wasn'?t|is|isn'?t|has|hasn'?t)\b|\bwhere\s+did\s+(?:this|that|the)\b|\bwhat\s+happened\s+(?:to|with)\b|\bwhen\s+(?:will|does)\s+(?:it|this|the\s+next)\b|\bwhat(?:'s| is)\s+(?:the\s+)?status\b", re.I)
_NUMBERS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}


def _days_in(text: str) -> list[str]:
    found = []
    for match in _WEEKDAY.finditer(text):
        name = next(day for day in DAYS if day.lower().startswith(match.group(1).lower()[:3]))
        if name not in found:
            found.append(name)
    return found


_BARE_AT = re.compile(r"\bat\s+(\d{1,2})(?![:\d])(?!\s*(?:am|pm|a\.m\.|p\.m\.|%|th|st|nd|rd))\b", re.I)


def _bare_hour(text: str) -> str | None:
    """"at 5" / "at 6": an hour without am/pm reads as the afternoon for 1–7 (people post at 5 PM, not 5 AM)."""
    match = _BARE_AT.search(text)
    if not match:
        return None
    hour = int(match.group(1))
    if hour > 23:
        return None
    if re.search(r"\bmorning\b|\bam\b|早上|朝早|上午", text, re.I):
        return f"{hour % 12:02d}:00"
    return f"{hour + 12 if 1 <= hour <= 7 else hour:02d}:00"


def _time_in(text: str) -> str | None:
    clock = next(iter(intent._clock_tokens(text)), None)
    if clock:
        return f"{clock[0]:02d}:{clock[1]:02d}"
    bare = _bare_hour(text)
    if bare:
        return bare
    period = _PERIOD.search(text)
    return PERIODS[period.group(1).lower()] if period else None


def _day_slots(text: str) -> list[tuple[str, str | None]]:
    """Each named weekday with the time that follows it before the next day ("Monday at 9am and Thursday at 5pm")."""
    marks = [(m.start(), m) for m in _WEEKDAY.finditer(text)]
    slots = []
    for index, (start, match) in enumerate(marks):
        end = marks[index + 1][0] if index + 1 < len(marks) else len(text)
        name = next(day for day in DAYS if day.lower().startswith(match.group(1).lower()[:3]))
        own = _time_in(text[start:end])
        if all(name != existing for existing, _ in slots):
            slots.append((name, own))
    # A shared time written once at the end ("Wednesday and Friday at 4:30 PM") applies to every day before it.
    shared = next((t for _, t in reversed(slots) if t), None)
    return [(name, own or shared) for name, own in slots]


def _has_when(text: str) -> bool:
    return bool(_WEEKDAY.search(text) or _time_in(text) or _DAY_OFFSET.search(text) or _MIN_OFFSET.search(text)
                or re.search(r"\b(?:today|tomorrow|tonight|next\s+week)\b|\d{4}-\d{2}-\d{2}|今日|聽日|明天|今天", text, re.I))


def _offset_when(text: str, fallback_time: str | None) -> dict | None:
    """Relative instants: "the day before at 5 PM", "two hours before", "the same day at 9"."""
    minutes = _MIN_OFFSET.search(text)
    if minutes:
        if minutes.group(0).lower().startswith("half"):
            value, direction = 30, minutes.group(1)
        else:
            count = _NUMBERS.get(minutes.group(1).lower()) or int(minutes.group(1))
            value = count * (60 if minutes.group(2).lower().startswith("hour") else 1)
            direction = minutes.group(3)
        return {"minutesOffset": -value if direction.lower() in ("before", "earlier", "ahead") else value}
    days = _DAY_OFFSET.search(text)
    if days:
        phrase = days.group(0).lower()
        local = _time_in(text) or fallback_time or DEFAULT_TIME
        if "same day" in phrase or "morning of" in phrase:
            return {"dayOffset": 0, "localTime": _time_in(text) or ("09:00" if "morning" in phrase else local)}
        if "next day" in phrase:
            return {"dayOffset": 1, "localTime": local}
        if "night before" in phrase or "evening before" in phrase:
            return {"dayOffset": -1, "localTime": _time_in(text) or ("20:00" if "night" in phrase else "18:00")}
        count = {"day": 1, "two days": 2, "2 days": 2, "three days": 3, "3 days": 3}.get(days.group(1).lower(), 1)
        return {"dayOffset": -count if days.group(2).lower() in ("before", "earlier") else count, "localTime": local}
    return None


def _clauses(text: str) -> list[str]:
    return [part.strip(" ,") for part in _CLAUSE_SPLIT.split(text) if part and part.strip(" ,")]


def _publisher_domains(text: str) -> tuple[list[str], str]:
    domains, names = [], []
    for pattern, hosts in PUBLISHERS:
        match = re.search(pattern, text, re.I)
        if match:
            names.append(match.group(0).strip())
            domains += [host for host in hosts if host not in domains]
    reputable = _REPUTABLE.search(text)
    publications = ""
    if reputable:
        publications = reputable.group(0)
        field = (reputable.group(2) or "").strip()
        if not domains and field:
            for pattern, hosts in FIELDS:
                if re.search(pattern, field, re.I):
                    domains += [host for host in hosts if host not in domains]
                    break
    elif names:
        publications = ", ".join(dict.fromkeys(names))
    return domains[:12], clean(publications, 200) if publications else ""


def _topic(text: str) -> str:
    match = _RELATES.search(text)
    if match:
        topic = (match.group(1) or match.group(2) or "").strip()
        topic = re.split(r"\s+(?:and|then|every|each|today|tomorrow|tonight|this\s+(?:week|month|morning|evening|afternoon)|next\s+\w+|on\s+(?:mon|tue|wed|thu|fri|sat|sun)|at\s+\d|by\s+\d|(?:for|on|to)\s+(?:linkedin|x|instagram|threads|xiaohongshu|facebook)|on\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*|on\s+\d)\b", topic, flags=re.I)[0]
        return clean(topic.strip(" \"'“”"), 160) if topic.strip() else ""
    from .automation_chat import topic_of
    return topic_of(text) or ""


def _content_task(text: str) -> str:
    for pattern, task in _CONTENT:
        if pattern.search(text):
            return task
    return "post"


_ADJ_PLATFORM = re.compile(r"\b(?:a|an)\s+(short|shorter|brief|punchy|punchier|sharp|sharper|concise|long|longer|full|fuller|detailed|in-depth|casual|professional)\s+(?:[\w-]+\s+){0,2}?(?:on|for|to)\s+([\w/()]+)", re.I)


def _platform_notes(text: str) -> dict:
    notes = {}
    for match in _ADJ_PLATFORM.finditer(text):
        for platform in intent._platform_mentions(intent.mark_platform_x("on " + match.group(2)) if hasattr(intent, "mark_platform_x") else match.group(2)):
            notes.setdefault(platform, clean(f"a {match.group(1).lower()} version", 200))
    for match in _VERSION.finditer(text):
        adjectives = (match.group(1) or "").strip()
        platforms = intent._platform_mentions(intent.mark_platform_x("on " + match.group(2)) if hasattr(intent, "mark_platform_x") else match.group(2))
        for platform in platforms:
            if adjectives:
                notes[platform] = clean(f"a {adjectives} version", 200)
    return notes


# "a news article post", "my weekly posts": post as a thing, not as a verb.
_POST_NOUN = re.compile(r"\b(?:a|an|the|my|our|one|this|that|these|those|some|two|three)\s+(?:(?!(?:at|on|in|to|for|every|each|and|then|today|tomorrow)\b)[a-z'-]+\s+){0,3}?posts?\b", re.I)
_DRAFTING = re.compile(r"\bdraft(?:ing|s)?\s+(?:me\s+|us\s+)?(?:a|an|some|my|the|one|two|three)\b|\bprepare\s+(?:me\s+)?(?:a\s+)?drafts?\b", re.I)


def _publish_verb(text: str) -> bool:
    return bool(_PUBLISH.search(_POST_NOUN.sub(" ", text)))


def _publish_verb_beyond_drafting(text: str) -> bool:
    """A publish verb besides the drafting words ("draft me a post and publish it Friday"); "a post" stays a noun."""
    return bool(_PUBLISH.search(_DRAFTING.sub(" ", _DRAFT_ONLY.sub(" ", _POST_NOUN.sub(" ", text)))))


_AUTO_SPAN = re.compile(r"\b(?:publish|post|share|send)\w*\b[^.!?\n]{0,80}?\bautomatically\b", re.I)


def explicit_auto(text: str) -> bool:
    """Automatic publishing only when the message itself asks for it and does not negate it ("don't publish
    automatically"); never inferred from a word like "automation"."""
    from .request_model import explicit_auto as asked
    negation = re.compile(r"\b(?:don'?t|do\s+not|never|not|no|without)\b|唔好|不要|別|别", re.I)
    for match in list(_AUTO.finditer(text)) + list(_AUTO_SPAN.finditer(text)):
        # Neither just before the phrase nor inside it, right before "automatically" ("post it, but don't publish automatically").
        before = text[max(0, match.start() - 24):match.start()]
        # Phrases like "no need to ask me" carry their own "no"; only a span ending in "automatically" is checked inside.
        auto_at = match.group(0).lower().rfind("automatic")
        inside = text[max(match.start(), match.start() + auto_at - 40):match.start() + auto_at] if auto_at > 0 else ""
        if not negation.search(before) and not negation.search(inside):
            return True
    return asked(text) and not negation.search(text)


def _policy(text: str) -> str | None:
    if _APPROVE.search(text):
        return "review"
    if explicit_auto(text):
        return "auto"
    if (_DRAFT_ONLY.search(text) or _DRAFTING.search(text)) and not _publish_verb_beyond_drafting(text):
        return "drafts"
    return None


def wants_publishing(text: str) -> bool:
    """Whether the message asks for posts to go out (then the publish policy matters), not only for drafts: a publish
    verb, or a post made for a named platform ("make a post for LinkedIn") unless the person asked only for drafts."""
    if explicit_auto(text):
        return True
    if _DRAFT_ONLY.search(text) or _DRAFTING.search(text):
        return _publish_verb_beyond_drafting(text)
    platforms = intent._platform_mentions(intent.mark_platform_x(text) if hasattr(intent, "mark_platform_x") else text)
    return _publish_verb(text) or bool(platforms and _GENERATE.search(text))


def is_edit(text: str) -> bool:
    return bool(_EDIT_MOVE.search(text) or _EDIT_REMOVE.search(text) or _EDIT_ADD.search(text) or _EDIT_SOURCE.search(text) or _EDIT_AUTO.search(text)
                or _EDIT_REVIEW.search(text) or re.search(r"^\s*(?:please\s+)?pause\b|\bpause\s+(?:it|this|that|the)\b", text, re.I) or _EDIT_RESUME.search(text) or _EDIT_DELETE.search(text))


_DRAFTING_LEAD = re.compile(r"^\s*(?:please\s+|can\s+you\s+|could\s+you\s+)?(?:write|draft|create|make|compose|give\s+me|turn\s+this)\b|\b(?:write|draft)\s+(?:me\s+)?(?:a|an|one|some)\s+(?:[\w-]+\s+){0,3}?(?:post|thread|caption|article|piece|update)\b", re.I)
_REFERENCE = re.compile(r"\bautomations?\b|\b(?:this|that|the|my|yesterday'?s|today'?s|last|latest|next)\s+(?:post|posts|run|draft|article|one)\b|\b(?:it|this|that|these|them)\b", re.I)


def is_drafting_request(text: str) -> bool:
    """A request to write something now ("write a post about why I pause before the chorus")."""
    return bool(_DRAFTING_LEAD.search(text))


def refers_to_automation(text: str, names: list[str], in_context: bool) -> bool:
    """Whether a message is about an existing automation: it names one or says "automation", or, in a
    conversation about one, points at it ("move it", "this post")."""
    if re.search(r"\bautomations?\b|自動化|自动化", text, re.I) or names_automation(text, names):
        return True
    return in_context and bool(_REFERENCE.search(text))


def names_automation(text: str, names: list[str]) -> bool:
    """Whether a message mentions one of these automations by a distinctive word of its name ("the Gramophone one")."""
    words = {w for w in re.findall(r"[a-z0-9]{4,}", text.lower())}
    stop = {"post", "posts", "automation", "every", "week", "weekly", "daily", "about", "with", "from", "that", "this", "update", "tips", "news"}
    return any(words & ({w for w in re.findall(r"[a-z0-9]{4,}", name.lower())} - stop) for name in names)


def is_explain(text: str) -> bool:
    return bool(_EXPLAIN.search(text))


def is_recurring_request(text: str) -> bool:
    """A request to do something on a recurring schedule ("every Monday, find … and summarize it"), whatever the verb;
    a recurrence that describes the person's own habit ("I practise every day, write about it") is not one."""
    if not (_GENERATE.search(text) or _PUBLISH.search(text)):
        return False
    return any(_RECUR.search(clause) and not intent._HABIT.search(clause) for clause in intent._CLAUSE.split(text) if clause)


_EXISTING = re.compile(r"\b(?:post|publish|share|schedule|send)\s+(?:this|it|that|these|them|the\s+(?:draft|post|last\s+one)|my\s+draft)\b(?!\s+(?:about|on\s+the\s+topic))", re.I)


def is_scheduled_post(text: str) -> bool:
    """A one-time post of new content at a stated time ("post an update about my studio today at 2 PM"). Posting what
    is already drafted in the conversation ("post this at 4 PM") stays with the draft's own scheduling plan."""
    return _publish_verb(text) and _has_when(text) and not _RECUR.search(text) and not _DRAFT_ONLY.search(text) and not _EXISTING.search(text)


def read_automation(text: str, now: float, zone: str) -> dict:
    """The automation a message describes, in the Reading shape (request_model / orchestration §6)."""
    text = clean(text, 2000)
    clauses = _clauses(text)
    recurring = bool(_RECUR.search(text))
    anchor_days, anchor_time, time_role = [], None, "generate"
    stages = {"generate": None, "review": None, "publish": None}
    once_date = None
    assumptions = []
    local_now = dt.datetime.fromtimestamp(now, ZoneInfo(zone))
    for clause in clauses:
        has_recur = bool(_RECUR.search(clause))
        publish, review = bool(_PUBLISH.search(clause)), bool(_REVIEW.search(clause))
        if not _has_when(clause):
            if has_recur and publish:
                time_role = "publish"
            continue
        when_time = _time_in(clause)
        if has_recur or (not recurring and not anchor_days and once_date is None and not review and (publish or not stages["publish"])):
            if has_recur:
                for day, own in _day_slots(clause):
                    if day not in [d for d, _ in anchor_days]:
                        anchor_days.append((day, own or when_time))
                anchor_time = anchor_time or when_time
                time_role = "publish" if publish else time_role
            else:
                day, _label = intent._explicit_day(clause, local_now.replace(tzinfo=None, hour=0, minute=0, second=0, microsecond=0))
                once_date = (day.date() if day else local_now.date())
                anchor_time = when_time
                time_role = "publish" if publish else "generate"
            continue
        relative = _offset_when(clause, anchor_time)
        days = _days_in(clause)
        spec = relative or ({"weekday": days[0], "localTime": when_time or anchor_time or DEFAULT_TIME} if days else ({"dayOffset": 0, "localTime": when_time} if when_time else None))
        if spec is None:
            continue
        if review:
            stages["review"] = spec
        elif publish:
            stages["publish"] = spec
        elif _GENERATE.search(clause):
            stages["generate"] = spec
    if time_role == "generate" and (recurring or once_date is not None):
        # "Every Tuesday at 3 PM, post a tip …": the time names when it goes out when the first thing asked is to post.
        first_action = next((c for c in clauses if _GENERATE.search(c) or _PUBLISH.search(c)), "")
        verbs = [m.start() for m in (_PUBLISH.search(first_action), _GENERATE.search(first_action)) if m]
        if _PUBLISH.search(first_action) and (not _GENERATE.search(first_action) or _PUBLISH.search(first_action).start() == min(verbs)):
            time_role = "publish"
    times_a_week = _TIMES_A_WEEK.search(text)
    if recurring and not anchor_days and times_a_week:
        many = 3 if "three" in times_a_week.group(1).lower() or "3" in times_a_week.group(1) else 2
        anchor_days = [(day, anchor_time) for day in (("Monday", "Wednesday", "Friday") if many == 3 else ("Tuesday", "Friday"))]
        assumptions.append(f"{times_a_week.group(0).capitalize()}: {' and '.join(day for day, _ in anchor_days)}; say other days if you prefer.")
    if _OTHER_WEEK.search(text):
        assumptions.append("Every other week isn't available yet, so it runs every week; pause it for the weeks you don't need.")
    if recurring and not anchor_days:
        from .automation_chat import schedule_of
        rest = " ".join(c for c in clauses if _RECUR.search(c)) or text
        schedule, notes = schedule_of(rest, zone)
        if schedule.get("kind") == "monthly":
            schedule_out = {"kind": "monthly", "monthDays": schedule["monthDays"], "localTime": anchor_time or schedule["localTime"]}
        else:
            schedule_out = {"kind": "weekly", "slots": [{"weekday": day, "localTime": anchor_time or schedule["localTime"]} for day in schedule["weekdays"]]}
        assumptions += [note for note in notes if "time was named" not in note or not anchor_time]
    elif recurring:
        if not anchor_time and not any(own for _, own in anchor_days):
            assumptions.append(f"No time was named, so each run starts at {DEFAULT_TIME}.")
        schedule_out = {"kind": "weekly", "slots": [{"weekday": day, "localTime": own or anchor_time or DEFAULT_TIME} for day, own in anchor_days]}
    elif once_date is not None:
        if not anchor_time:
            assumptions.append(f"No time was named, so it is planned for {DEFAULT_TIME}.")
        schedule_out = {"kind": "once", "date": once_date.isoformat(), "localTime": anchor_time or DEFAULT_TIME}
    else:
        schedule_out = None
    policy = _policy(text)
    if policy is None and not wants_publishing(text) and (_DRAFT_ONLY.search(text) or _DRAFTING.search(text)):
        policy = "drafts"
    research = None
    domains, publications = _publisher_domains(text)
    urls = _URL.findall(text)
    quote_match = _QUOTE.search(text)
    topic = _topic(text)
    if _RESEARCH.search(text) or domains or urls or quote_match or publications:
        research = {"query": _query(text, clauses, topic, quote_match),
                    "about": topic, "domains": domains, "publications": publications, "urls": urls[:5],
                    "recencyDays": 3 if re.search(r"\b(?:latest|newest|today'?s)\b", text, re.I) else 7,
                    "onNothing": "draft_without" if _ANYWAY.search(text) else "skip",
                    "quote": {"about": clean(quote_match.group(1).strip(), 120)} if quote_match else None}
        if research["onNothing"] == "skip" and not _SKIP.search(text):
            assumptions.append("If nothing is genuinely worth posting, that run is skipped rather than filled.")
    platforms = intent._platform_mentions(intent.mark_platform_x(text)) if hasattr(intent, "mark_platform_x") else intent._platform_mentions(text)
    content_task = _content_task(" ".join(c for c in clauses if _GENERATE.search(c)) or text)
    instructions = clean(" ".join(c for c in clauses if _GENERATE.search(c) and not _RESEARCH.search(c))[:600], 600)
    from .automation_chat import _VOICE, _phrase, _upper_first
    phrase = re.sub(r"^(?:ll|ve|re|d|s|m)\s+", "", _phrase(text)) or "post"
    label = {"reflection": "reflection", "quote": "quote post", "summary": "summary", "recap": "recap", "update": "update", "tip": "tip",
             "announcement": "announcement", "promotion": "promotion", "education": "explainer", "thread": "thread", "story": "story", "question": "question"}.get(content_task)
    publisher = publications.split(",")[0].strip() if domains and publications and not _REPUTABLE.search(publications) else ""
    if publisher and label:
        name = f"{publisher} {label}"
    elif topic and label:
        name = f"{_upper_first(topic)} {label}"
    elif topic:
        name = f"{_upper_first(topic)} · {phrase}"
    else:
        name = _upper_first(phrase)
    return {
        "name": clean(name, 80), "topic": topic, "goal": "", "schedule": schedule_out, "timeRole": time_role, "stages": stages,
        "policy": policy, "platforms": platforms, "research": research,
        "content": {"task": content_task, "instructions": instructions}, "platformNotes": _platform_notes(text),
        "voice": bool(_VOICE.search(text)), "contentTypeId": None, "formatId": None, "assumptions": assumptions[:4],
        "publishIntent": wants_publishing(text),
    }


_LEAD_VERB = re.compile(r"^\s*(?:and\s+|then\s+)?(?:every\s+\w+\s*,?\s*)?(?:find|search\s+for|look\s+for|pick|choose|discover|grab|pull|curate|get)\s+(?:me\s+)?(?:(?:a|an|the|one|some)\s+)?", re.I)


def _query(text: str, clauses: list[str], topic: str, quote_match) -> str:
    """What to search for, in the person's words: the research clause without its verb, plus the topic."""
    if quote_match:
        from .automation_chat import _phrase
        kind = re.sub(r"\s*\bposts?\b", "", _phrase(text)).strip() or "quote"
        return clean(f"{kind} {quote_match.group(1).strip()} {topic}".strip(), 300)
    clause = next((c for c in clauses if _RESEARCH.search(c)), "")
    words = _LEAD_VERB.sub("", clause).strip(" ,.")
    words = re.split(r"\s*,\s*|\s+(?:and|then)\s+(?:turn|write|make|create|publish|post|share|have|send)\b", words, flags=re.I)[0]
    query = " ".join(dict.fromkeys(filter(None, [words, topic if topic and topic.lower() not in words.lower() else ""])))
    return clean(query, 300) or clean(topic or text, 300)


_TARGET = re.compile(r"\b(?:the|my|our|that)\s+([\w\s'-]{2,60}?)\s+(?:automation|one)\b", re.I)


def read_edit(text: str, now: float, zone: str) -> dict:
    """The changes a message asks for on an existing automation (Change union, orchestration §6)."""
    changes = []
    delete = _EDIT_DELETE.search(text)
    target = None
    if delete and re.search(r"\b(?:delete|remove|get\s+rid\s+of|kill)\b", delete.group(0), re.I):
        changes.append({"op": "delete"})
        target = (delete.group(1) or "").strip() or None
    elif delete and re.search(r"\b(?:cancel|stop)\b", delete.group(0), re.I):
        changes.append({"op": "delete"})
        target = (delete.group(1) or "").strip() or None
    pause = _EDIT_PAUSE.search(text) if re.search(r"\bpause\b", text, re.I) else None
    if pause and not changes:
        change = {"op": "pause"}
        if pause.group(1):
            count = _NUMBERS.get(pause.group(1).lower()) or int(pause.group(1))
            unit = pause.group(2).lower()
            change["days"] = count * (7 if unit.startswith("week") else 30 if unit.startswith("month") else 1)
        elif pause.group(3):
            day, _ = intent._explicit_day(pause.group(3), dt.datetime.fromtimestamp(now, ZoneInfo(zone)).replace(tzinfo=None, hour=0, minute=0, second=0, microsecond=0))
            if day:
                change["until"] = day.date().isoformat()
        changes.append(change)
    if _EDIT_RESUME.search(text) and not changes:
        changes.append({"op": "resume"})
    for match in _EDIT_REMOVE.finditer(text):
        for platform in intent._platform_mentions(intent.mark_platform_x(" to " + next(g for g in match.groups() if g))):
            changes.append({"op": "remove_platform", "platform": platform})
    for match in _EDIT_ADD.finditer(text):
        for platform in intent._platform_mentions(intent.mark_platform_x(" to " + match.group(1))):
            changes.append({"op": "add_platform", "platform": platform})
    source = _EDIT_SOURCE.search(text)
    if source:
        wanted = source.group(1) or source.group(3) or source.group(4)
        domains, publications = _publisher_domains(wanted)
        changes.append({"op": "sources", "domains": domains, "publications": clean(publications or wanted, 200)})
    if _EDIT_REVIEW.search(text) or re.search(r"\b(?:don'?t|do\s+not|never|stop)\b[^.]{0,20}\bauto", text, re.I):
        changes.append({"op": "policy", "policy": "review"})
    elif _EDIT_AUTO.search(text) and explicit_auto(text):
        changes.append({"op": "policy", "policy": "auto"})
    elif False:
        changes.append({"op": "policy", "policy": "review"})
    elif re.search(r"\b(?:just|only)\s+drafts?\b|\bdon'?t\s+publish\b", text, re.I):
        changes.append({"op": "policy", "policy": "drafts"})
    if not any(c["op"] in ("delete", "pause", "resume") for c in changes) and (_EDIT_MOVE.search(text) or (not changes and _has_when(text))):
        days = _days_in(text)
        local = _time_in(text)
        if local is None:
            bare = re.search(r"\bat\s+(\d{1,2})(?::(\d{2}))?\b(?!\s*(?:am|pm))", text, re.I)
            if bare:
                hour = int(bare.group(1))
                hour = hour + 12 if 1 <= hour <= 7 else hour
                local = f"{hour:02d}:{int(bare.group(2) or 0):02d}"
        move = {"op": "move", "stage": "auto"}
        if days:
            move["weekdays"] = days
        if local:
            move["localTime"] = local
        day, _ = intent._explicit_day(text, dt.datetime.fromtimestamp(now, ZoneInfo(zone)).replace(tzinfo=None, hour=0, minute=0, second=0, microsecond=0))
        if day is not None and not days:
            move["date"] = day.date().isoformat()
        if len(move) > 2:
            changes.append(move)
    if not target:
        named = _TARGET.search(text)
        target = named.group(1).strip() if named else None
    return {"target": {"name": target}, "changes": changes}


def read_explain(text: str) -> dict:
    lower = text.lower()
    named = _TARGET.search(text)
    about = ("source" if re.search(r"\bwhere\s+did\b|\bsource\b|\barticle\b|\bcome\s+from\b", lower) else
             "not_published" if re.search(r"\bwhy\s+(?:wasn'?t|didn'?t|isn'?t|hasn'?t)\b|\bnot\s+(?:published|posted)\b", lower) else
             "why_posted" if re.search(r"\bwhy\s+did\b.*\b(?:post|publish)", lower) else
             "next" if re.search(r"\bwhen\s+(?:will|does)\b|\bnext\b", lower) else "status")
    return {"question": clean(text, 400), "target": {"name": named.group(1).strip() if named else None}, "about": about}
