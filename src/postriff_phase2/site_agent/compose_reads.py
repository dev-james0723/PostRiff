"""Grounded answers for workspace reads: status, attention, reviews, publishing, campaigns, calendar, Brand Brain,
voice, drafts and search. Stored facts are stated as facts; anything computed from them is listed under
"Observations" with the rule that produced it; nothing here recommends (a model may, clearly labelled). Each answer
also returns the items it named (`refs`), in the order shown, for "that draft" and "the second one" later.
"""
from __future__ import annotations

import re

from . import contracts, routes

EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]")


def result_list(title: str, items: list[dict], *, empty: str | None = None) -> dict:
    return {"type": "result_list", "title": title, "items": items[:12], "empty": empty}


def _item(kind, title, *, excerpt=None, meta=None, href=None):
    return {"kind": kind, "title": title, "excerpt": excerpt, "meta": meta, "href": href}


def _a(word):
    return "an" if str(word or "")[:1].lower() in "aeiou" else "a"


def _ref(kind, ident, title):
    return {"type": kind, "id": ident, "title": title} if ident else None


def compose(intent: str, classification: dict, results: dict, text: str) -> dict | None:
    """{"lines", "blocks", "refs", "grounded"} for a read intent, or None when the intent is not a read."""
    get = lambda tool_id: (results.get(tool_id) or {}).get("data") if (results.get(tool_id) or {}).get("ok") else None  # noqa: E731
    handler = HANDLERS.get(intent)
    return handler(get, classification, text) if handler else None


def _status(get, classification, text):
    data = get("entity.status")
    if not data and get("content.search") is not None:
        found = _search(get, classification, text)
        if not (get("content.search") or {}).get("results"):
            found["lines"] = ["I couldn't find that item in this workspace, so I can't give its status. Open it (or select it on its page) and ask again."]
        else:
            found["lines"] = ["Nothing is selected, so here is what matches. Which one do you mean?"]
        return found
    if not data:
        return {"lines": ["I couldn't read the selected item in this workspace."], "blocks": [], "refs": [], "grounded": False}
    summary, kind = data["summary"], data["kind"]
    lines, refs = [], []
    if kind == "draft":
        lines.append(f"This is {_a(summary['platform'])} **{summary['platform']} draft** in {summary['language']}" + (f" for **{summary['account']}**" if summary.get("account") else " with no account chosen yet")
                     + f", revision {summary['revision']}, {summary['characters']} characters" + (f" of {summary['limit']}" if summary.get("limit") else "") + ".")
        lines.append("It is scheduled." if summary["scheduled"] else "It is not scheduled yet.")
        if data.get("campaign"):
            lines.append(f"It came from the automation “{data['campaign']['name']}”.")
        refs.append(_ref("draft", summary["draftId"], f"{summary['platform']} draft"))
    elif kind in ("job", "review"):
        lines.append(f"This is {_a(summary.get('platform'))} **{summary.get('platform')} post** for **{summary.get('account')}** at {summary.get('publishAt') or 'no set time'}.")
        lines.append(f"Status: **{summary.get('title') or summary.get('state')}**. {summary.get('meaning') or ''}".strip())
        last = summary.get("lastEvent") or {}
        if summary.get("state") in ("failed", "held", "uncertain") and last.get("message"):
            lines.append(f"Recorded reason: {last['message']}")
        refs.append(_ref("job", summary.get("jobId") or summary.get("reviewId"), f"{summary.get('platform')} post"))
    elif kind == "automation":
        lines.append(f"This is the automation **{summary.get('name')}**: {summary.get('status')}; {summary.get('scheduleText') or ''}".rstrip("; "))
        refs.append(_ref("automation", summary.get("taskId"), summary.get("name")))
    elif kind == "source":
        lines.append(f"This is the source **{summary.get('title')}** with {summary.get('approvedFacts')} approved paragraph(s).")
    if data["stillNeeded"]:
        lines.append("Still needed:")
        lines.extend(f"- {step}" for step in data["stillNeeded"])
    else:
        lines.append("Nothing else is needed from you for it right now.")
    return {"lines": lines, "blocks": [], "refs": [r for r in refs if r], "grounded": True}


def _attention(get, classification, text):
    data = get("attention.summary")
    if not data:
        return None
    blocks = [result_list("Needs attention (stored state)", [_item(f["kind"], f["text"], href=f.get("href")) for f in data["facts"]], empty="Nothing is waiting on you in the stored state.")]
    if data["observations"]:
        blocks.append(result_list("Observations (derived from your data)", [_item(o["kind"], o["text"], meta=f"Rule: {o['rule']}", href=o.get("href")) for o in data["observations"]]))
    lines = [f"{len(data['facts'])} item(s) need you, and I noticed {len(data['observations'])} pattern(s) worth a look." if data["facts"] or data["observations"]
             else "Nothing needs your attention right now: no reviews waiting, no held, failed or uncertain posts, and no gaps I can see in the next 7 days."]
    # A narrower question gets its own answer first; the full list follows.
    for pattern, kind, none in ((r"neglect|ignor|quiet|冷落|忽略", "neglected", "No connected platform has gone quiet: each has something scheduled, waiting or published in the last 14 days or the days ahead."),
                                (r"repetit|repeat|same\s+thing|重複", "repetitive", "No two posts in the next 7 days share enough words to look repetitive."),
                                (r"too\s+close|close\s+together|太近", "close", "No two posts on the same account are scheduled close together.")):
        if re.search(pattern, text, re.I):
            found = [o for o in data["observations"] if o["kind"] == kind]
            lines = ([f"{o['text']} (derived — rule: {o['rule']})" for o in found] or [none]) + lines
            break
    return {"lines": lines, "blocks": blocks, "refs": [], "grounded": True}


def _reviews(get, classification, text):
    data = get("reviews.list")
    if not data:
        return None
    blocks, refs = [], []
    blocks.append(result_list("Waiting for approval", [_item("review", f"{r['platform']} · {r['account']}", meta=(r["when"] or "") + (" · review window closed" if r["expired"] else ""), href=r["href"]) for r in data["waitingApproval"]],
                              empty="No post is waiting for approval."))
    refs += [_ref("review", r["reviewId"], f"{r['platform']} post") for r in data["waitingApproval"]]
    if data["automationItems"]:
        blocks.append(result_list("Automation posts waiting for a decision", [_item("automation_item", f"{i['platform']} · {i.get('account') or ''}".rstrip(" ·"), meta=f"{i['state'].replace('_', ' ')}" + (f" · {i['when']}" if i.get("when") else ""), href=i["href"]) for i in data["automationItems"]]))
    if data["returned"]:
        blocks.append(result_list("Returned or rejected", [_item("returned", f"{r['platform']} · {r['decision']}", excerpt=r.get("note") or "No note was left.", meta=r.get("when"), href=r["href"]) for r in data["returned"]]))
    if data["feedback"]:
        blocks.append(result_list("Reviewer notes on drafts", [_item("feedback", f"{f['platform']} draft", excerpt=f["note"], href=f["href"]) for f in data["feedback"]]))
    if data["draftsNeedingReview"]:
        blocks.append(result_list("Drafts that need a look before scheduling", [_item("draft", f"{d['platform']} draft" + (f" · {d['account']}" if d.get("account") else ""), meta=", ".join(d["reasons"]), href=d["href"]) for d in data["draftsNeedingReview"]]))
        refs += [_ref("draft", d["draftId"], f"{d['platform']} draft") for d in data["draftsNeedingReview"]]
    total = len(data["waitingApproval"]) + len(data["automationItems"])
    lines = [f"{total} post(s) are waiting for a decision." if total else "Nothing is waiting for approval right now."]
    if not data["returned"] and re.search(r"reject|return|sent back|退回|被拒|feedback|意見", text, re.I):
        lines.append("No post was rejected or sent back, and no reviewer notes are stored.")
    return {"lines": lines, "blocks": blocks, "refs": [r for r in refs if r], "grounded": True}


def _publishing(get, classification, text):
    data = get("publishing.summary")
    if not data:
        return None
    label = data["range"]["label"] or "the period"
    blocks = [result_list(f"Published and verified ({label})", [_item("post", f"{p['platform']} · {p['account']}", meta=p.get("publishAt"), href=p["href"]) for p in data["verified"]],
                          empty=f"Nothing was verified as published {label}.")]
    if data["publishedUnconfirmed"]:
        blocks.append(result_list("Handed to the provider, not confirmed yet", [_item("post", f"{p['platform']} · {p['account']}", meta=p.get("publishAt"), href=p["href"]) for p in data["publishedUnconfirmed"]]))
    if data["scheduled"]:
        blocks.append(result_list(f"Scheduled, not published yet ({label})", [_item("post", f"{p['platform']} · {p['account']}", meta=p.get("publishAt"), href=p["href"]) for p in data["scheduled"]]))
    failed = None
    if data["failed"]:
        failed = result_list("Failed, any date (can be prepared again as a new review)", [_item("post", f"{p['platform']} · {p['account']}", excerpt=(p.get("lastEvent") or {}).get("message") or p["meaning"], meta=p.get("publishAt"), href=p["href"]) for p in data["failed"]])
        blocks.append(failed)
    if data["uncertain"]:
        blocks.append(result_list("Uncertain, any date (do not retry until reconciled)", [_item("post", f"{p['platform']} · {p['account']}", excerpt=p["meaning"], meta=p.get("publishAt"), href=p["href"]) for p in data["uncertain"]]))
    if data["held"]:
        blocks.append(result_list("Held, any date (needs a new review)", [_item("post", f"{p['platform']} · {p['account']}", excerpt=(p.get("lastEvent") or {}).get("message") or p["meaning"], href=p["href"]) for p in data["held"]]))
    lines = [f"{len(data['verified'])} post(s) were confirmed published {label}." + (" Scheduled and in-flight posts are not counted as published." if data["scheduled"] or data["inFlight"] else "")]
    person = (classification.get("entities") or {}).get("person")
    if person:
        lines.insert(0, f"I can't tell which posts {person} made: Rafii has no reader for members' activity yet, so nothing below is attributed to anyone. "
                        f"This is what the workspace published {label}.")
    if re.search(r"fail|失敗", text, re.I):
        lines.insert(0, f"{len(data['failed'])} post(s) failed and did not publish." if data["failed"] else "No post has failed.")
        if failed:
            blocks.remove(failed)
            blocks.insert(0, failed)
    refs = [_ref("job", p["jobId"], f"{p['platform']} post") for group in ("verified", "failed", "uncertain", "held") for p in data[group]]
    return {"lines": lines, "blocks": blocks, "refs": [r for r in refs if r], "grounded": True}


def _campaign(get, classification, text):
    one = get("campaign.get")
    listing = get("campaign.list")
    # A name that matched no campaign never shows another campaign's record as the answer.
    detail = one or ((listing or {}).get("detail") if (listing or {}).get("matched") is not False else None)
    if detail:
        lines = [f"**Objective:** {detail['goal']}", f"**Audience:** {detail.get('audience') or 'not stored'}", f"**Status:** {detail['status']}"]
        if detail["missingFacts"]:
            lines.append("**Missing facts:** " + ", ".join(detail["missingFacts"]))
        lines.append("**Platforms covered:** " + (", ".join(detail["platforms"]) if detail["platforms"] else "none yet"))
        blocks = [result_list("Automations", [_item("automation", a["name"] or "Automation", meta=f"{a['status']} · {a.get('schedule') or ''} · posts: {a['policy']}" + (f" · next run {a['nextRun']}" if a.get("nextRun") else ""),
                                                     href=routes.href("automations", query={"edit": a["automationId"]})) for a in detail["automations"]], empty="No automation belongs to this campaign.")]
        blocks.append(result_list(f"Drafts in this campaign ({detail['draftCount']})", [_item("draft", f"{d['platform']} draft" + (f" · {d['account']}" if d.get("account") else ""), excerpt=d["excerpt"],
                                                                                              meta="linked by a person" if d.get("linked") else "made by its automation", href=d["href"]) for d in detail["drafts"]],
                                  empty="No drafts are in this campaign yet: none were linked, and its automations haven't made any."))
        if detail["lastWeek"]:
            blocks.append(result_list("Last week", [_item("run", f"Run {r['when']}", meta=r["status"], excerpt="; ".join(f"{i['platform']}: {i['state']}" for i in r["items"]) or None) for r in detail["lastWeek"]]))
        derived = detail["derived"]
        observations = []
        if derived["platformsNotCovered"]["items"]:
            observations.append(_item("gap", "Connected but not covered: " + ", ".join(derived["platformsNotCovered"]["items"]), meta=f"Rule: {derived['platformsNotCovered']['rule']}"))
        if derived["noUpcomingRun"]["value"]:
            observations.append(_item("gap", "Nothing is set to run next.", meta=f"Rule: {derived['noUpcomingRun']['rule']}"))
        for r in derived["failedOrSkippedLastWeek"]["items"]:
            observations.append(_item("gap", f"A run on {r['when']} ended {r['status']}.", meta=f"Rule: {derived['failedOrSkippedLastWeek']['rule']}"))
        if observations:
            blocks.append(result_list("Observations (derived from the campaign's records)", observations))
        refs = [_ref("campaign", detail["campaignId"], detail["goal"][:60])] + [_ref("draft", d["draftId"], f"{d['platform']} draft") for d in detail["drafts"]]
        return {"lines": lines, "blocks": blocks, "refs": [r for r in refs if r], "grounded": True, "nav": detail.get("href")}
    if not listing:
        return None
    if not listing["campaigns"]:
        return {"lines": ["You don't have any campaigns yet. Campaign briefs are created with automations on the Automations page."], "blocks": [], "refs": [], "grounded": True}
    lines = [f"No campaign matches “{listing['query']}”. These are the campaigns you have:" if listing.get("matched") is False else f"You have {listing['total']} campaign(s). Which one do you mean?"]
    blocks = [result_list("Campaigns", [_item("campaign", c["goal"][:90], meta=f"{c['status']} · {', '.join(c['platforms']) or 'no platforms'}", href=c["href"]) for c in listing["campaigns"]])]
    refs = [_ref("campaign", c["campaignId"], c["goal"][:60]) for c in listing["campaigns"]]
    return {"lines": lines, "blocks": blocks, "refs": [r for r in refs if r], "grounded": True}


def _calendar(get, classification, text):
    data = get("calendar.range")
    if not data:
        return None
    label = data["range"]["label"]
    entries = data["entries"]
    # Never blur scheduled and published: each entry sits under what actually happened to it.
    groups = {"waiting": [], "verified": [], "moving": [], "attention": []}
    for e in entries:
        if e["kind"] != "job" or e["state"] in ("approved", "scheduled", "claimed"):
            groups["waiting"].append(e)
        elif e["state"] == "verified":
            groups["verified"].append(e)
        elif e["state"] in ("failed", "held", "uncertain"):
            groups["attention"].append(e)
        else:
            groups["moving"].append(e)
    row = lambda e: _item(e["kind"], f"{e['platform']} · {e.get('account') or ''}".rstrip(" ·"), meta=f"{e['when']} · {e['title']}", href=e["href"])  # noqa: E731
    if entries:
        counts = [f"{len(groups['waiting'])} scheduled or waiting", f"{len(groups['verified'])} published and verified"]
        counts += [f"{len(groups['moving'])} being published, not confirmed yet"] if groups["moving"] else []
        counts += [f"{len(groups['attention'])} failed, held or uncertain"] if groups["attention"] else []
        lines = [f"{label[:1].upper() + label[1:]}: " + ", ".join(counts) + "."]
        if data["total"] > len(entries):
            lines.append(f"Showing the first {len(entries)} of {data['total']}.")
    else:
        lines = [f"Nothing is scheduled, waiting or planned {label}."]
    # With nothing at all, the lead line says so; an empty list under it would only repeat it.
    blocks = [result_list(f"Scheduled or waiting ({label})", [row(e) for e in groups["waiting"]], empty=f"Nothing is scheduled or waiting {label}.")] if entries else []
    if groups["verified"]:
        blocks.append(result_list(f"Published and verified ({label})", [row(e) for e in groups["verified"]]))
    if groups["moving"]:
        blocks.append(result_list("Being published (not confirmed yet)", [row(e) for e in groups["moving"]]))
    if groups["attention"]:
        blocks.append(result_list("Failed, held or uncertain", [row(e) for e in groups["attention"]]))
    derived = data["derived"]
    observations = []
    if derived["emptyDays"]["days"]:
        observations.append(_item("gap", "Empty days: " + ", ".join(derived["emptyDays"]["days"][:10]), meta=f"Rule: {derived['emptyDays']['rule']}"))
    for pair in derived["closeTogether"]["pairs"]:
        observations.append(_item("close", f"{pair['platform']} · {pair['account']}: {pair['minutes']} minutes apart ({pair['first']} and {pair['second']})", meta=f"Rule: {derived['closeTogether']['rule']}"))
    for pair in derived["similarText"]["pairs"]:
        observations.append(_item("repetitive", f"{pair['first']} and {pair['second']} share {int(pair['similarity'] * 100)}% of their words", meta=f"Rule: {derived['similarText']['rule']}"))
    if observations:
        blocks.append(result_list("Observations (derived from the calendar)", observations))
    elif re.search(r"close|gap|空檔|太近|open|free|empty", text, re.I):
        lines.append("No two posts on the same account are closer than two hours, and there are no empty days left in this range." if not derived["emptyDays"]["days"] else "")
    refs = [_ref("job" if e["kind"] in ("job", "review") else e["kind"], e["id"], f"{e['platform']} post {e['when']}") for e in entries if e["kind"] in ("job", "review")]
    return {"lines": [line for line in lines if line], "blocks": blocks, "refs": [r for r in refs if r], "grounded": True, "nav": data.get("href")}


def _brand(get, classification, text):
    data = get("brand.summary")
    if not data:
        return None
    if data["empty"]:
        return {"lines": ["Your Brand Brain has no stored brand identity, voice, boundaries or learned preferences yet, so I won't describe one. Set them up on Brand; they then appear on Memory."],
                "blocks": [], "refs": [], "grounded": True, "nav": data.get("brandHref")}
    identity, voice = data["identity"], data["voice"]
    lines = []
    wants = lambda pattern: bool(re.search(pattern, text, re.I))  # noqa: E731
    draft = get("draft.get")
    if draft and wants(r"conflict|on[- ]brand|off[- ]brand|guidance|符合|衝突"):
        # "Does this draft conflict with our brand guidance?": the check is the answer.
        return {"lines": [f"I checked this {draft['platform']} draft against the rules stored in your Brand Brain (a writer model can judge tone; this check can't)."],
                "blocks": [_brand_check(draft, data)], "refs": [], "grounded": True, "nav": data.get("href")}
    if wants(r"avoid|banned|don'?t|off[- ]limits|要避免|唔好"):
        avoid = [l for l in data["learned"] if l.get("polarity") in ("avoid", "negative", "never")]
        if not data["boundaries"] and not avoid:
            return {"lines": ["No phrases or styles to avoid are stored. I won't invent any."], "blocks": [], "refs": [], "grounded": True, "nav": data.get("href")}
        lines.append("**What to avoid (stored):**")
        lines.extend(f"- {b['label']}: " + ("kept private" if b["private"] else (b["value"] or "")) for b in data["boundaries"])
        lines.extend(f"- {l['statement']} ({l['scope']})" for l in avoid)
        others = [l for l in data["learned"] if l not in avoid]
        if others:
            lines.append("**Other learned preferences:**")
            lines.extend(f"- {l['statement']} ({l['scope']})" for l in others[:6])
        return {"lines": lines, "blocks": [], "refs": [], "grounded": True, "nav": data.get("href")}
    audience_first = wants(r"audience|受眾|觀眾|讀者")
    if audience_first:
        lines.append(f"**Target audience (stored):** {identity['audience'] or 'not recorded yet'}")
    fields = [("Purpose", "purpose"), ("Audience", "audience"), ("Subject", "subject"), ("Mode", "mode"), ("Speaker", "speaker"), ("Identity sentence", "identitySentence")]
    stored = [f"- **{label}:** {identity[key]}" for label, key in fields if identity.get(key) and not (audience_first and key == "audience")]
    if stored:
        lines.append("**Brand identity (stored):**")
        lines.extend(stored)
    if voice:
        lines.append(f"**Voice (approved revision {voice['revision']}):** tone {voice['tone'] or 'not set'}.")
        lines.extend(f"- {o}" for o in voice["observations"][:6])
    else:
        lines.append("No voice profile is approved yet.")
    if data["boundaries"]:
        lines.append("**Boundaries — what stays out of content:**")
        lines.extend(f"- {b['label']}: " + ("kept private" if b["private"] else (b["value"] or "")) for b in data["boundaries"])
    if data["learned"]:
        lines.append("**Learned preferences (accepted by an owner):**")
        lines.extend(f"- {l['statement']} ({l['scope']})" for l in data["learned"][:8])
    return {"lines": lines, "blocks": [], "refs": [], "grounded": True, "nav": data.get("href")}


def _brand_check(draft, brand):
    """Deterministic checks of a draft against stored rules only (a writer model can judge tone; this cannot)."""
    text = draft.get("text") or ""
    findings = []
    for item in brand["learned"]:
        statement = (item.get("statement") or "").lower()
        if "emoji" in statement and re.search(r"\b(?:no|never|avoid|don'?t)\b", statement) and EMOJI.search(text):
            findings.append(f"Uses emoji, but a learned preference says: “{item['statement']}”.")
        if "hashtag" in statement and re.search(r"\b(?:no|never|avoid|don'?t)\b", statement) and re.search(r"(^|\s)#\w", text):
            findings.append(f"Uses hashtags, but a learned preference says: “{item['statement']}”.")
        if "exclamation" in statement and re.search(r"\b(?:no|never|avoid|don'?t)\b", statement) and "!" in text:
            findings.append(f"Uses exclamation marks, but a learned preference says: “{item['statement']}”.")
    for boundary in brand["boundaries"]:
        value = (boundary.get("value") or "").strip()
        if value and len(value) >= 4 and value.lower() in text.lower():
            findings.append(f"Mentions “{value}”, which is listed as a boundary ({boundary['label']}).")
    steps = findings or ["No stored rule is broken. Tone and wording beyond the stored rules need a writer model or your own read."]
    return contracts.diagnostic("Check against stored brand rules", "Conflicts found" if findings else "No stored rule broken", evidence=[f"{draft['platform']} draft, {draft['characters']} characters"],
                                cause="Derived check: the draft compared with the learned preferences and boundaries stored in your Brand Brain.", steps=steps)


def _voice(get, classification, text):
    data = get("voice.profile")
    if not data:
        return None
    voice = data["voice"]
    lines = []
    if not voice and not data["learnedByScope"]:
        return {"lines": ["No voice profile is approved and no preferences have been learned yet, so there are no patterns I can quote. Approve writing samples on Brand to build one."],
                "blocks": [], "refs": [], "grounded": True, "nav": data.get("href")}
    opening = re.search(r"\bopen|start|begin|hook|first\s+line|開頭", text, re.I)
    if opening:
        related = [o for o in (voice or {}).get("observations", []) if re.search(r"open|start|begin|hook|first|lead", o, re.I)]
        related += [s for statements in data["learnedByScope"].values() for s in statements if re.search(r"open|start|begin|hook|first|lead", s or "", re.I)]
        if related:
            lines.append("What your profile records about openings:")
            lines.extend(f"- {r}" for r in related[:6])
        else:
            lines.append("Your voice profile doesn't record how you open posts.")
            if voice and voice.get("writingExample"):
                lines.append(f"Your approved writing example opens with: “{voice['writingExample'].split('.')[0][:160]}.” (one sample, not a rule)")
    if voice:
        lines.append(f"**Approved voice (revision {voice['revision']}):** tone {voice['tone'] or 'not set'}.")
        lines.extend(f"- {o}" for o in voice["observations"][:8])
    platforms = classification["entities"].get("platforms") or []
    if len(platforms) >= 2 or re.search(r"differ|compare|vs|versus|分別", text, re.I):
        for platform in (platforms or data["platformSpecific"])[:3]:
            specific = [s for scope, statements in data["learnedByScope"].items() if scope.startswith(platform) for s in statements]
            lines.append(f"**{platform}:** " + ("; ".join(specific) if specific else "no platform-specific preferences learned, so the shared voice applies."))
    elif data["learnedByScope"]:
        lines.append("**Learned from how you edit:**")
        for scope, statements in list(data["learnedByScope"].items())[:5]:
            lines.extend(f"- {s} ({scope})" for s in statements[:3])
    if re.search(r"why|點解", text, re.I) and re.search(r"sound|like\s+me|似", text, re.I):
        lines.insert(0, "Judging one sentence against your voice needs a writer model; I can show what your profile records, and nothing beyond it.")
    lines.append(f"Based on {data['samples']} approved writing sample(s)." if data["samples"] else "No writing samples are active.")
    return {"lines": lines, "blocks": [], "refs": [], "grounded": True, "nav": data.get("href")}


def _search(get, classification, text):
    data = get("content.search")
    if not data:
        return None
    labels = {"draft": "Draft", "source": "Source", "campaign": "Campaign", "automation": "Automation", "post": "Post"}
    items = [_item(r["kind"], f"{labels.get(r['kind'], r['kind'])}: {r['title']}", excerpt=r.get("excerpt"),
                   meta=" · ".join(x for x in (r.get("when"), r.get("state"), ", ".join(r.get("needs") or []) or None, r.get("via")) if x) or None, href=r.get("href"))
             for r in data["results"]]
    terms = " ".join(data.get("terms") or []) or text
    span = f" {data['range']['label']}" if data.get("range") else ""
    if data.get("listing"):
        lines = [f"{data['total']} draft(s), newest first." if data["total"] else "You have no drafts yet."]
    elif data["results"]:
        lines = [f"{data.get('direct', data['total'])} match(es) for “{terms}”{span} across {', '.join(data['searched'])}."
                 + (f" {data['linked']} more item(s) are linked to a match (made from it, or part of it)." if data.get("linked") else "")]
    else:
        lines = [f"Nothing in your {', '.join(data['searched']) or 'workspace'} matches “{terms}”{span}. I searched this workspace only."]
    if data.get("undated"):
        lines.append("Left out because they have no date I can check: " + ", ".join(f"{n} {kind}(s)" for kind, n in data["undated"].items()) + ".")
    # Titles that tell options apart when Rafii later asks "which one?".
    refs = [_ref({"post": "job"}.get(r["kind"], r["kind"]), r["id"], r["title"] + (f": “{r['excerpt'][:40]}…”" if r.get("excerpt") and r["kind"] in ("draft", "post") else ""))
            for r in data["results"]]
    return {"lines": lines, "blocks": [result_list("Results", items)] if items else [], "refs": [r for r in refs if r], "grounded": True}


BASIS = {"measured": "Measured", "heuristic": "Rule of thumb", "needs_writer": "Needs a writer's judgement"}


def _voice_check(get, classification, text):
    data = get("voice.check")
    if not data:
        return {"lines": ["Select a draft, or put the sentence in quotes, and I'll compare it with your stored voice."], "blocks": [], "refs": [], "grounded": True}
    if data["empty"]:
        return {"lines": ["There's no approved voice profile or learned preference to compare with, so I won't judge this. Approve writing samples on Brand to build one."],
                "blocks": [], "refs": [], "grounded": True, "nav": data.get("profileHref")}
    s = data["summary"]
    lines = [f"I compared {data['subject']} with your stored voice: {s['matches']} match, {s['differs']} differ, and {s['unclear']} need a writer's judgement."]
    checked = [f for f in data["findings"] if f["basis"] != "needs_writer"]
    judged = [f for f in data["findings"] if f["basis"] == "needs_writer"]
    differs = [f for f in checked if f["verdict"] == "differs"]
    if differs:
        lines.append("Where it differs: " + "; ".join(f"{f['trait'].rstrip('.')} ({f['evidence'].rstrip('.')})" for f in differs[:3]) + ".")
    lines.append("Tone and word choice weren't judged here: that needs a writer model, and none phrased this answer.")
    rows = [_item(f["verdict"], f"{'✓' if f['verdict'] == 'matches' else '✗'} {f['trait']}", excerpt=f["evidence"], meta=f"{BASIS[f['basis']]} · {f['source']}") for f in checked]
    blocks = [result_list("Checked against your stored voice", rows, empty="Nothing in your profile can be measured in this text.")]
    if judged:
        blocks.append(result_list("Needs a writer's judgement", [_item("unclear", f["trait"], meta=f["source"]) for f in judged]))
    refs = [_ref("draft", data["draftId"], data["subject"])] if data.get("draftId") else []
    return {"lines": lines, "blocks": blocks, "refs": [r for r in refs if r], "grounded": True, "nav": data.get("href") or data.get("profileHref")}


def _member_activity(get, classification, text):
    data = get("member.activity")
    if not data:
        return None
    person = classification["entities"].get("person") or ""
    found = data.get("match") or {}
    if found.get("none"):
        known = found.get("known") or []
        return {"lines": [f"No member of this workspace is called “{person}”, so there's nothing to attribute to them. I won't guess who you mean."
                          + (f" Members with a display name: {', '.join(known)}." if known else " No member has a display name yet.")], "blocks": [], "refs": [], "grounded": True,
                "nav": routes.href("members")}
    if found.get("ambiguous"):
        return {"lines": [f"More than one member matches “{person}”. Which one do you mean?"], "blocks": [contracts.question("Which member?", found["ambiguous"])],
                "refs": [], "grounded": True}
    who = (data.get("member") or {}).get("name") or "your team"
    window = (data.get("range") or {}).get("label") or "recently"
    posts_only = classification["entities"].get("only") == "posts"
    events = data["events"]
    if not events:
        lead = (f"No post was approved or prepared by {who} {window}." if posts_only else f"Nothing in the stored records names {who} {window}.")
    else:
        lead = (f"Posts {who} approved or prepared {window}: {data['total']}." if posts_only else f"{data['total']} record(s) name {who} {window}, newest first.")
    lines = [lead]
    if posts_only and events:
        lines.append("Rafii's publisher sends a post after it is approved, so the records say who approved or prepared it, not who \"posted\" it.")
    blocks = [result_list(f"Activity ({window})", [_item(e["kind"], f"{e['who'][:1].upper() + e['who'][1:]} {e['summary']}", meta=f"{e['when']} · {e['source']}", href=e.get("href"))
                                                   for e in events])] if events else []
    blocks.append(result_list("Not attributed", [_item("note", note) for note in data["notAttributed"]]))
    return {"lines": lines, "blocks": blocks, "refs": [], "grounded": True}


def _attribution(get, classification, text):
    data = get("record.attribution")
    if not data:
        focus = classification["entities"].get("focus")
        if not focus:
            return {"lines": ["Select the post, draft or automation first, and I'll tell you who acted on it from its records."], "blocks": [], "refs": [], "grounded": True}
        return None
    events = data["events"]
    wanted = re.search(r"\bwho\s+(\w+)", text, re.I)
    verb = (wanted.group(1).lower() if wanted else "")
    changes = tuple(e["kind"] for e in events if e["kind"].startswith("automation.") or e["kind"] in ("campaign.updated", "draft.edited", "draft.update_accepted"))
    kinds = {"approved": ("post.approved", "automation_post.approve"), "prepared": ("post.prepared",), "scheduled": ("post.prepared", "post.approved"),
             "linked": ("campaign.link",), "added": ("campaign.link",), "created": ("automation.created", "campaign.created", "draft.run"),
             "paused": ("automation.paused",), "resumed": ("automation.resumed",), "activated": ("automation.turned",),
             "changed": changes, "edited": changes, "updated": changes, "modified": changes}.get(verb)
    pick = next((e for e in events if e["kind"] in kinds), None) if kinds is not None else (events[0] if events else None)
    noun = {"job": "post", "draft": "draft", "automation": "automation"}.get(data.get("kind"), "item")
    if pick:
        lead = f"{pick['who'][:1].upper() + pick['who'][1:]} {pick['summary']} ({pick['when']}; from the {pick['source']})."
    elif kinds:
        lead = f"No record names who {verb} this {noun}" + (": it hasn't been approved yet." if verb == "approved" else ".")
    else:
        lead = f"No stored record names anyone for this {noun}."
    blocks = [result_list("Who acted on it (newest first)", [_item(e["kind"], f"{e['who'][:1].upper() + e['who'][1:]} {e['summary']}", meta=f"{e['when']} · {e['source']}",
                                                                   href=e.get("href")) for e in events])] if events else []
    if data.get("notAttributed"):
        blocks.append(result_list("Not attributed", [_item("note", note) for note in data["notAttributed"]]))
    return {"lines": [lead], "blocks": blocks, "refs": [], "grounded": True}


def _campaign_membership(get, classification, text):
    data = get("campaign.membership")
    if not data:
        return {"lines": ["Select the draft or post first, and I'll tell you which campaigns it belongs to."], "blocks": [], "refs": [], "grounded": True}
    noun = "draft" if data["kind"] == "draft" else "post"
    if not data["campaigns"]:
        return {"lines": [f"This {noun} isn't in any campaign: nobody linked it, and no campaign's automation made it. "
                          f"You can say “Add this {noun} to the … campaign”."], "blocks": [], "refs": [], "grounded": True}
    rows = [_item("campaign", c["goal"][:90] if c.get("goal") else "Campaign",
                  meta=(f"linked {c['at']}" if c["how"] == "linked" else f"made by its automation “{c.get('automation') or 'automation'}”"), href=c["href"]) for c in data["campaigns"]]
    names = "; ".join(f"“{(c.get('goal') or 'Campaign')[:60]}”" for c in data["campaigns"])
    refs = [_ref("campaign", c["campaignId"], (c.get("goal") or "")[:60]) for c in data["campaigns"]]
    return {"lines": [f"This {noun} is in {len(data['campaigns'])} campaign(s): {names}."], "blocks": [result_list("Campaigns", rows)], "refs": [r for r in refs if r], "grounded": True}


HANDLERS = {"status": _status, "attention": _attention, "reviews": _reviews, "publishing": _publishing, "campaign": _campaign, "calendar": _calendar,
            "brand": _brand, "voice": _voice, "drafts": _search, "search": _search, "voice_check": _voice_check, "member_activity": _member_activity,
            "attribution": _attribution, "campaign_membership": _campaign_membership}
