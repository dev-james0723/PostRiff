"""Outcome validation (growth Phase 0): does Post Doctor's score track how posts actually perform?

Decided by James on 2026-09-26: instead of ~200 hand labels, Phase 0 validates Post Doctor against public posts'
engagement, compared *within each creator* so that follower count, niche and posting habits cancel out. Each
eligible post's outcome is log1p(likes + reposts + quotes + replies) minus its creator's median of the same; a post
is "top" or "bottom" when it falls in its creator's top or bottom third.

The pass criteria were fixed before any data was collected (PREREGISTERED) and are evaluated per language group
(Traditional Chinese and English separately):
- Spearman correlation between Post Doctor's overall score and the within-creator outcome is at least 0.10, and the
  lower bound of its 95% interval (bootstrap over creators) is above 0;
- the overall score separates each creator's top third from their bottom third with AUC at least 0.56.

What this does and does not show: it tests whether higher Post Doctor scores go with better relative performance.
It does not validate each dimension's level (a post does not reveal *why* it performed), so dimension levels stay
uncalibrated until hand labels or more data exist. It shows association, never that a score *causes* performance.

    python -m postriff_phase2.growth.outcomes summarize FILE   # eligibility per language and creator, no network

The dataset lives outside the repository (it holds other people's public posts) and is never published.
"""
from __future__ import annotations

import csv
import hashlib
import math
import os
import random
import re
import statistics
import sys
from dataclasses import dataclass

from .lang import lang_group
from .post_doctor import levels_from_judgment

COLUMNS = ("id", "platform", "lang", "author", "created_at", "text", "likes", "reposts", "replies", "quotes",
           "has_media", "collected_at", "source_uri")
MIN_POSTS_PER_AUTHOR = 20
LINK_FEED_SHARE = 0.8          # creators whose posts are this often "mostly a link" are feeds, not writers
LINK_POST_OWN_CHARS = 60
_URL = re.compile(r"(https?://\S+|\b[\w-]+(\.[\w-]+)+/\S*)")
_TAG = re.compile(r"[#@]\S+")
MIN_AUTHORS = 15
PREREGISTERED = {"spearman_min": 0.10, "ci_lower_above": 0.0, "auc_min": 0.56, "confidence": 0.95, "bootstrap": 2000,
                 "min_authors": MIN_AUTHORS, "min_posts_per_author": MIN_POSTS_PER_AUTHOR,
                 "exclude_link_feeds": {"share": 0.8, "own_chars_below": 60}}
_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")


@dataclass(frozen=True)
class Post:
    line: int
    id: str
    platform: str
    lang: str
    author: str
    created_at: float
    text: str
    engagement: int
    has_media: bool


def _int(value):
    value = (value or "").strip()
    return int(value) if value.isdigit() else None


def parse(path):
    """(posts, problems). A row with any problem is left out; problems carry the file's line number."""
    posts, problems, seen = [], [], set()
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = [c for c in COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            return [], [(1, f"missing columns: {', '.join(missing)}")]
        for record in reader:
            line = reader.line_num
            get = lambda k: (record.get(k) or "").strip()
            counts = [_int(get(k)) for k in ("likes", "reposts", "replies", "quotes")]
            try:
                created = float(get("created_at"))
            except ValueError:
                created = None
            issue = None
            if not _ID.match(get("id")) or get("id") in seen:
                issue = "id must be unique and 1-64 letters, digits or _ . : -"
            elif not get("author"):
                issue = "author is empty"
            elif not get("text"):
                issue = "text is empty"
            elif created is None:
                issue = "created_at must be epoch seconds"
            elif any(c is None for c in counts):
                issue = "likes, reposts, replies and quotes must be whole numbers"
            if issue:
                problems.append((line, issue))
                continue
            seen.add(get("id"))
            posts.append(Post(line, get("id"), get("platform") or "other", get("lang"), get("author"), created, get("text"),
                              sum(counts), get("has_media").lower() in ("1", "true", "yes")))
    return posts, problems


def parse_many(paths):
    """Parse several dataset files (for example one per platform and language); problems are prefixed by file."""
    posts, problems, seen = [], [], set()
    for path in paths:
        got, issues = parse(path)
        problems += [(f"{os.path.basename(path)}:{line}", msg) for line, msg in issues]
        for p in got:
            if p.id in seen:
                problems.append((f"{os.path.basename(path)}:{p.line}", "id repeats a row from another file"))
                continue
            seen.add(p.id)
            posts.append(p)
    return posts, problems


def sample(posts, *, max_creators=None, max_posts=None, seed=20260926):
    """Deterministic subset for a budget: per (platform, language group) at most `max_creators` creators (chosen by a
    seeded hash of their id), and per creator their `max_posts` most recent posts."""
    if not max_creators and not max_posts:
        return list(posts)
    by_creator = {}
    for p in posts:
        by_creator.setdefault((p.platform, lang_group(p.lang), p.author), []).append(p)
    cells = {}
    for key in by_creator:
        cells.setdefault(key[:2], []).append(key)
    rank = lambda key: hashlib.sha256(f"{seed}:{key[2]}".encode()).hexdigest()
    chosen = []
    for keys in cells.values():
        for key in sorted(keys, key=rank)[:max_creators or None]:
            group = sorted(by_creator[key], key=lambda p: -p.created_at)
            chosen += group[:max_posts or None]
    return chosen


def mostly_link(text):
    """A post that shares a link with little of the creator's own writing around it."""
    if not _URL.search(text or ""):
        return False
    own = _TAG.sub("", _URL.sub("", text)).strip()
    return len(own) < LINK_POST_OWN_CHARS


def link_feed(group):
    return bool(group) and sum(mostly_link(p.text) for p in group) >= LINK_FEED_SHARE * len(group)


def eligible(posts, min_posts=MIN_POSTS_PER_AUTHOR):
    """Posts whose creator has at least `min_posts` posts in the same language group on the same platform and is not
    a link feed (automated news or aggregator accounts are not the writers Post Doctor serves)."""
    by_key = {}
    for p in posts:
        by_key.setdefault((p.platform, lang_group(p.lang), p.author), []).append(p)
    return [p for group in by_key.values() if len(group) >= min_posts and not link_feed(group) for p in group]


def relative_outcomes(posts):
    """{post id: (outcome, tercile)} where outcome = log1p(engagement) - creator median and tercile is
    'top' / 'middle' / 'bottom' within that creator (ties broken by id, deterministically)."""
    by_author = {}
    for p in posts:
        by_author.setdefault((p.platform, lang_group(p.lang), p.author), []).append(p)
    out = {}
    for group in by_author.values():
        logs = {p.id: math.log1p(p.engagement) for p in group}
        median = statistics.median(logs.values())
        ranked = sorted(group, key=lambda p: (logs[p.id], p.id))
        n = len(ranked)
        for rank, p in enumerate(ranked):
            tercile = "bottom" if rank < n / 3 else ("top" if rank >= n - n / 3 else "middle")
            out[p.id] = (logs[p.id] - median, tercile)
    return out


def _ranks(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def spearman(xs, ys):
    if len(xs) < 3:
        return None
    rx, ry = _ranks(xs), _ranks(ys)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    sx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    sy = math.sqrt(sum((b - my) ** 2 for b in ry))
    if sx == 0 or sy == 0:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(rx, ry)) / (sx * sy)


def auc(positive_scores, negative_scores):
    """Probability a random top-third post outscores a random bottom-third post (ties count half)."""
    if not positive_scores or not negative_scores:
        return None
    ranks = _ranks(list(positive_scores) + list(negative_scores))
    n_pos, n_neg = len(positive_scores), len(negative_scores)
    return (sum(ranks[:n_pos]) - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


def _metrics(items):
    """items: [(author, score, outcome, tercile)] -> (spearman, auc)."""
    rho = spearman([s for _, s, _, _ in items], [o for _, _, o, _ in items])
    area = auc([s for _, s, _, t in items if t == "top"], [s for _, s, _, t in items if t == "bottom"])
    return rho, area


def _bootstrap(items, rounds, seed, confidence):
    """Percentile intervals from resampling creators (posts of one creator are not independent)."""
    authors = sorted({a for a, _, _, _ in items})
    by_author = {a: [it for it in items if it[0] == a] for a in authors}
    rng = random.Random(seed)
    rhos, aucs = [], []
    for _ in range(rounds):
        sample = [it for a in (rng.choice(authors) for _ in authors) for it in by_author[a]]
        rho, area = _metrics(sample)
        if rho is not None:
            rhos.append(rho)
        if area is not None:
            aucs.append(area)
    def interval(values):
        if len(values) < rounds // 2:
            return None
        values.sort()
        lo = values[int((1 - confidence) / 2 * len(values))]
        hi = values[min(len(values) - 1, int((1 + confidence) / 2 * len(values)))]
        return [round(lo, 4), round(hi, 4)]
    return interval(rhos), interval(aucs)


def overall_score(dimensions):
    """Mean of the dimension scores Post Doctor could compute; None when it could compute none."""
    scores = [d.score for d in dimensions if d.score is not None]
    return statistics.fmean(scores) if scores else None


def _score_group(members, outcomes, judgments_by_id, qs, rounds, seed):
    items, per_dim, unscored, text_only = [], {}, 0, []
    for p in members:
        judgment = judgments_by_id.get(p.id)
        dims = levels_from_judgment(qs, judgment) if judgment is not None else ()
        score = overall_score(dims) if judgment is not None else None
        if score is None:
            unscored += 1
            continue
        outcome, tercile = outcomes[p.id]
        items.append((p.author, score, outcome, tercile))
        if not p.has_media:
            text_only.append((score, outcome))
        for d in dims:
            if d.score is not None:
                per_dim.setdefault(d.id, []).append((d.score, outcome))
    authors = len({a for a, _, _, _ in items})
    rho, area = _metrics(items) if items else (None, None)
    rho_ci, auc_ci = _bootstrap(items, rounds, seed, PREREGISTERED["confidence"]) if authors >= 2 else (None, None)
    reasons = []
    if authors < PREREGISTERED["min_authors"]:
        reasons.append("too_few_creators")
    if rho is None or rho < PREREGISTERED["spearman_min"]:
        reasons.append("correlation_below_target")
    if rho_ci is None or rho_ci[0] <= PREREGISTERED["ci_lower_above"]:
        reasons.append("interval_includes_zero")
    if area is None or area < PREREGISTERED["auc_min"]:
        reasons.append("auc_below_target")
    return {
        "posts": len(members), "scored": len(items), "unscored": unscored, "creators": authors,
        "spearman": _round(rho), "spearman_ci": rho_ci, "auc_top_vs_bottom": _round(area), "auc_ci": auc_ci,
        "per_dimension_spearman": {d: _round(spearman([s for s, _ in v], [o for _, o in v])) for d, v in sorted(per_dim.items())},
        "text_only_spearman": _round(spearman([s for s, _ in text_only], [o for _, o in text_only])),
        "passes": not reasons, "reasons": reasons,
    }


def evaluate(posts, judgments_by_id, qs, *, seed=20260926, rounds=None):
    """Pre-registered evaluation. `groups` (one per language group) carry the pass/fail verdicts; `platforms` and
    `platform_languages` apply the same criteria as diagnostics. Outcomes are always within a creator on one
    platform, so platforms never mix inside a creator's baseline."""
    rounds = rounds or PREREGISTERED["bootstrap"]
    posts = eligible(posts)
    outcomes = relative_outcomes(posts)
    report = {"preregistered": dict(PREREGISTERED), "groups": {}, "platforms": {}, "platform_languages": {}}
    cuts = {"groups": lambda p: lang_group(p.lang), "platforms": lambda p: p.platform,
            "platform_languages": lambda p: f"{p.platform}/{lang_group(p.lang)}"}
    for section, key in cuts.items():
        buckets = {}
        for p in posts:
            buckets.setdefault(key(p), []).append(p)
        for name, members in sorted(buckets.items()):
            report[section][name] = _score_group(members, outcomes, judgments_by_id, qs, rounds, seed)
    return report


def _round(value):
    return None if value is None else round(value, 4)


def summarize(posts):
    cells, by_creator = {}, {}
    for p in posts:
        cell = f"{p.platform}/{lang_group(p.lang)}"
        g = cells.setdefault(cell, {})
        g[p.author] = g.get(p.author, 0) + 1
        by_creator.setdefault((cell, p.author), []).append(p)
    out = {}
    for cell, authors in sorted(cells.items()):
        feeds = {a for a in authors if link_feed(by_creator[(cell, a)])}
        ok = {a: n for a, n in authors.items() if n >= MIN_POSTS_PER_AUTHOR and a not in feeds}
        out[cell] = {"posts": sum(authors.values()), "creators": len(authors), "eligible_creators": len(ok),
                     "eligible_posts": sum(ok.values()), "link_feeds_excluded": len(feeds), "meets_minimum": len(ok) >= MIN_AUTHORS}
    return out


def main(argv=None, out=sys.stdout):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 2 or argv[0] != "summarize":
        print("usage: python -m postriff_phase2.growth.outcomes summarize FILE [FILE ...]", file=out)
        return 2
    posts, problems = parse_many(argv[1:])
    for line, message in problems[:50]:
        print(f"line {line}: {message}", file=out)
    for cell, info in summarize(posts).items():
        print(f"{cell}: {info['eligible_creators']}/{info['creators']} creators and {info['eligible_posts']}/{info['posts']} posts "
              f"eligible ({info['link_feeds_excluded']} link feeds excluded); "
              f"{'enough' if info['meets_minimum'] else 'needs at least ' + str(MIN_AUTHORS) + ' eligible creators'}", file=out)
    print(f"{len(posts)} valid rows, {len(problems)} problems", file=out)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
