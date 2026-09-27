"""Live model comparison on the golden set (growth Phase 0). Paid: every live call costs money.

    python -m postriff_phase2.growth.compare --labels FILE \\
        --models jev,gemini-2.5-flash-lite,claude-haiku-4.5,claude-sonnet-5 \\
        --max-usd 20 [--price MODEL=IN,OUT ...] [--confirm-live --out REPORT.json]

Without --confirm-live it prints the cost estimate and exits 0 without any network call. With it, it aborts
before the first call when the estimate exceeds --max-usd, and stops mid-run before any call that would take
recorded spend past the cap (unknown-cost calls count at their estimate). An auth, budget or bad-request error also
stops the run; the report is still written with everything already judged (`stopped.reason`). The key comes from
AI_GATEWAY_API_KEY and is never printed. Prices are USD per 1M tokens (input, output); a model without a table
price must be given one with --price, so no estimate is ever invented.

Running it live needs James's real labels and a separate cost authorisation; tests use fakes only.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

from . import golden, outcomes, questions
from .judgments import JudgmentService, MemoryJudgmentCache, subject_hash
from .router import FALLBACK_SYSTEM, TASKS, AIModelRouter, RouterError, chat_from_runtime
from .usage import MemoryUsageSink

ALIASES = {
    "jev": "typesafe-ai/jev",
    "gemini-2.5-flash-lite": "google/gemini-2.5-flash-lite",
    "claude-haiku-4.5": "anthropic/claude-haiku-4.5",
    "claude-sonnet-5": "anthropic/claude-sonnet-5",
}
JEV = "typesafe-ai/jev"
TASK = "golden.compare"
SCOPE = "personal:golden"        # the golden set holds the creator's own posts and drafts; never shared
OUTPUT_TOKENS_PER_ANSWER = 24    # {"type":"boolean","probability":0.xx} plus the name, generous


class CompareError(Exception):
    pass


def resolve(names):
    out = []
    for name in names:
        model = ALIASES.get(name, name)
        if "/" not in model:
            raise CompareError(f"unknown model {name!r}; use an alias ({', '.join(ALIASES)}) or provider/model")
        out.append(model)
    return out


def parse_prices(items):
    prices = {}
    for item in items or ():
        try:
            model, pair = item.split("=", 1)
            inp, outp = (float(x) for x in pair.split(","))
        except ValueError as error:
            raise CompareError(f"--price must look like MODEL=IN,OUT, got {item!r}") from error
        if not (math.isfinite(inp) and math.isfinite(outp)) or inp < 0 or outp < 0:
            raise CompareError("prices must be finite and non-negative")
        prices[ALIASES.get(model, model)] = (inp, outp)
    return prices


def state_for(row):
    return {"draft": row.text, "platform": row.platform, "lang": row.lang, "creator": {}}


def estimate(rows, qs, models, prices):
    payload = qs.payload_questions()
    question_tokens = questions.estimate_tokens(payload)
    system_tokens = questions.estimate_tokens(FALLBACK_SYSTEM)
    from postriff_phase2.model_runtime import TYPICAL_REASONING_TOKENS, thinking
    answers = OUTPUT_TOKENS_PER_ANSWER * len(qs.names)
    report, total = {}, 0.0
    for model in models:
        if model not in prices:
            raise CompareError(f"no price for {model}; pass --price {model}=IN,OUT (USD per 1M tokens)")
        inp_price, out_price = prices[model]
        extra = 0 if model == JEV else system_tokens
        # Thinking models bill their reasoning as output tokens on top of the answers.
        output = answers + (TYPICAL_REASONING_TOKENS if model != JEV and thinking(model) else 0)
        inp = sum(questions.estimate_tokens(state_for(r)) + question_tokens + extra for r in rows)
        usd = (inp * inp_price + output * len(rows) * out_price) / 1_000_000
        report[model] = {"calls": len(rows), "input_tokens": inp, "output_tokens": output * len(rows),
                         "usd": round(usd, 6), "per_call_usd": usd / len(rows) if rows else 0.0}
        total += usd
    return {"models": report, "total_usd": round(total, 6)}


def _spent(sinks, per_call):
    """Known cost, plus the estimate for every attempt whose cost was not reported. Sinks are per *requested* model,
    so an attempt counts at its model's estimate whatever model id the provider echoed."""
    return sum(e.cost_usd if e.cost_usd is not None else per_call[model] for model, sink in sinks.items() for e in sink.events)


def run(rows, qs, models, *, jev_factory, chat, max_usd, costs, evaluator=None):
    """Judge every row with every model until the cap; returns the report dict."""
    sinks = {}
    per_call = {m: costs["models"][m]["per_call_usd"] for m in models}
    results, stopped = {}, None
    for model in models:
        sink = sinks[model] = MemoryUsageSink()
        if model == JEV:
            router = AIModelRouter(jev=jev_factory(), usage=sink, tasks={TASK: TASKS[TASK]})
        else:
            _, _, _, budget, max_tokens = TASKS[TASK]
            router = AIModelRouter(chat=chat, usage=sink, tasks={TASK: ("evaluate", model, (model,), budget, max_tokens)})
        service = JudgmentService(router.evaluator(TASK), MemoryJudgmentCache())
        judgments = {}
        for row in rows:
            if _spent(sinks, per_call) + per_call[model] > max_usd:
                stopped = {"model": model, "row": row.id, "reason": "cap", "spent_usd": round(_spent(sinks, per_call), 6)}
                break
            try:
                judgments[row.id] = service.judge(qs, state_for(row), subject=subject_hash("golden", row.id, row.text),
                                                  scope=SCOPE, model=model)
            except RouterError as error:   # auth / budget / bad request: stop, but keep what was already paid for
                stopped = {"model": model, "row": row.id, "reason": error.code, "spent_usd": round(_spent(sinks, per_call), 6)}
                break
        results[model] = (evaluator or golden.evaluate)(rows, judgments, qs)
        if stopped:
            break
    events = [e for sink in sinks.values() for e in sink.events]
    known = [e.cost_usd for e in events if e.cost_usd is not None]
    return {"estimate": costs, "results": results, "stopped": stopped,
            "spend": {"known_usd": round(sum(known), 6), "unknown_calls": len(events) - len(known),
                      "attempts": len(events), "counted_usd": round(_spent(sinks, per_call), 6)}}


def _live_factories(api_key):
    from postriff_phase2.model_runtime import ServerModelRuntime
    from .jev import JevService
    # The model is pinned: POSTRIFF_JEV_MODEL must not change what a paid comparison measures.
    return (lambda: JevService(api_key, model=JEV)), chat_from_runtime(ServerModelRuntime(api_key))


def main(argv=None, *, env=None, out=sys.stdout, factories=None):
    env = os.environ if env is None else env
    parser = argparse.ArgumentParser(prog="python -m postriff_phase2.growth.compare")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--labels", help="hand-labelled golden CSV (growth.golden)")
    source.add_argument("--outcomes", nargs="+", help="public-post datasets with engagement (growth.outcomes); pre-registered evaluation")
    parser.add_argument("--max-creators", type=int, help="outcomes: at most this many creators per platform and language")
    parser.add_argument("--max-posts", type=int, help="outcomes: at most this many recent posts per creator")
    parser.add_argument("--models", required=True)
    parser.add_argument("--max-usd", type=float, required=True)
    parser.add_argument("--price", action="append", default=[])
    parser.add_argument("--question-set", default="postdoctor.v1")
    parser.add_argument("--confirm-live", action="store_true")
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    try:
        if not math.isfinite(args.max_usd) or args.max_usd <= 0:
            raise CompareError("--max-usd must be a finite amount above 0")
        if args.outcomes:
            if args.max_posts is not None and args.max_posts < outcomes.MIN_POSTS_PER_AUTHOR:
                raise CompareError(f"--max-posts must be at least {outcomes.MIN_POSTS_PER_AUTHOR} (fewer disqualifies every creator)")
            posts, problems = outcomes.parse_many(args.outcomes)
            if problems:
                raise CompareError(f"{len(problems)} problem rows; run growth.outcomes summarize")
            rows = outcomes.eligible(outcomes.sample(outcomes.eligible(posts), max_creators=args.max_creators,
                                                     max_posts=args.max_posts))
            if not rows:
                raise CompareError("no creator has enough eligible posts; run growth.outcomes summarize")
        else:
            rows = golden.load(args.labels)
        evaluator = outcomes.evaluate if args.outcomes else None
        qs = questions.get(args.question_set)
        models = resolve([m.strip() for m in args.models.split(",") if m.strip()])
        from postriff_phase2.model_runtime import DEFAULT_PRICES
        prices = {**DEFAULT_PRICES, **parse_prices(args.price)}
        costs = estimate(rows, qs, models, prices)
    except (CompareError, ValueError, KeyError, OSError) as error:
        print(f"error: {error}", file=out)
        return 2
    print(json.dumps({"estimate": costs, "max_usd": args.max_usd}, indent=2), file=out)
    if not args.confirm_live:
        print("dry run: no network calls made (add --confirm-live to run)", file=out)
        return 0
    if costs["total_usd"] > args.max_usd:
        print(f"aborted: estimate {costs['total_usd']} USD exceeds --max-usd {args.max_usd}", file=out)
        return 3
    if not args.out:
        print("error: --out is required with --confirm-live", file=out)
        return 2
    api_key = env.get("AI_GATEWAY_API_KEY")
    if not api_key and factories is None:
        print("error: AI_GATEWAY_API_KEY is not set", file=out)
        return 2
    jev_factory, chat = factories if factories is not None else _live_factories(api_key)
    report = run(rows, qs, models, jev_factory=jev_factory, chat=chat, max_usd=args.max_usd, costs=costs, evaluator=evaluator)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print(f"wrote {args.out}; spent {report['spend']['known_usd']} USD known, "
          f"{report['spend']['unknown_calls']} calls with unknown cost", file=out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
