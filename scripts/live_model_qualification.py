"""Operator tool: qualify AI Gateway models through PostRiff's own code paths, with a hard spending cap.

Every request goes through the same code production uses (ServerModelRuntime for drafting, request_model +
GatewayCall for reading a chat request, the deterministic fallbacks), wrapped in a guard that estimates each
call's worst case first and refuses once the ledger's total would pass --cap. Costs come from the gateway's
usage.cost, else tokens x the gateway list price. Fixtures are synthetic; nothing is stored or published.

The gateway credential is read from AI_GATEWAY_API_KEY (or VERCEL_OIDC_TOKEN) and is never printed or written.

  AI_GATEWAY_API_KEY=... python3 scripts/live_model_qualification.py --confirm-spend --cap 2.5 \
      --models anthropic/claude-opus-5.5,openai/gpt-6-sol,google/gemini-3.1-pro-preview --run strong-1 \
      --failures anthropic/claude-haiku-4.5 --out docs/launch-20260923/evidence/live-models

--providers takes the POSTRIFF_MODEL_PROVIDERS shape ({model: [gateway provider slugs]}); the default is each
model's maker only, as in production. Results: <out>/report-<run>.json and the shared <out>/ledger.jsonl.
"""
import argparse, json, math, os, pathlib, re, statistics, sys, time, traceback, urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from postriff_phase2 import model_runtime, request_model, intent, automation_chat  # noqa: E402
from postriff_phase2.model_runtime import ServerModelRuntime, ProviderFailure, gateway_routing  # noqa: E402
from postriff_phase2.learning_model import GatewayCall  # noqa: E402

LIVE = LEDGER = None
SOFT_CAP = 2.50
TOKEN = os.environ.get('AI_GATEWAY_API_KEY') or os.environ.get('VERCEL_OIDC_TOKEN') or ''
CATALOG = {}


def load_catalog():
    with urllib.request.urlopen('https://ai-gateway.vercel.sh/v1/models', timeout=30) as response:
        return {m['id']: m for m in json.loads(response.read())['data']}


def list_price(model):
    p = (CATALOG.get(model) or {}).get('pricing') or {}
    try:
        return float(p['input']) * 1e6, float(p['output']) * 1e6
    except (KeyError, TypeError, ValueError):
        return 20.0, 100.0  # unknown: assume expensive


def spent_so_far():
    if not LEDGER.exists():
        return 0.0
    return sum(json.loads(line).get('costCounted', 0) for line in LEDGER.read_text().splitlines() if line.strip())


class BudgetStop(Exception):
    pass


class Guard:
    """Transport wrapper: refuse before the cap, pace to the team's per-model rate limit, record every call
    (no content, no credential)."""
    PER_MINUTE = 4  # the free tier allows 5 requests per minute per model and region; keep one spare

    def __init__(self, run):
        self.run, self.scenario, self.mutate, self.recent = run, None, None, {}

    def _pace(self, model):
        window = [t for t in self.recent.get(model, []) if time.monotonic() - t < 60]
        if len(window) >= self.PER_MINUTE:
            time.sleep(60 - (time.monotonic() - window[0]) + 1)
        self.recent[model] = [t for t in window if time.monotonic() - t < 60] + [time.monotonic()]

    def __call__(self, method, url, headers=None, body=None, timeout=model_runtime.TIMEOUT_SECONDS):
        model = body.get('model')
        self._pace(model)
        inp, out = list_price(model)
        tokens_in = len(json.dumps(body.get('messages'), ensure_ascii=False).encode()) / 2.5
        max_out = body.get('max_tokens') or 4096
        worst = (tokens_in * inp + max_out * out * 2) / 1e6  # x2 output: reasoning tokens may be billed on top
        before = spent_so_far()
        if before + worst > SOFT_CAP:
            raise BudgetStop(f'budget: spent {before:.4f} + worst case {worst:.4f} would pass {SOFT_CAP}')
        started = time.monotonic()
        response = model_runtime.model_transport(method, url, headers=headers, body=body, timeout=timeout)
        latency = time.monotonic() - started
        data = response.get('body') if isinstance(response.get('body'), dict) else {}
        usage = data.get('usage') if isinstance(data.get('usage'), dict) else {}
        provider, gateway_cost = gateway_routing(data)
        reported = usage.get('cost') if isinstance(usage.get('cost'), (int, float)) else gateway_cost
        pt, ct = usage.get('prompt_tokens'), usage.get('completion_tokens')
        if reported is not None:
            cost, source = float(reported), 'gateway usage.cost'
        elif isinstance(pt, int) and isinstance(ct, int):
            cost, source = (pt * inp + ct * out) / 1e6, 'tokens x list price'
        elif response.get('status') == 200:
            cost, source = worst, 'unknown: counted at worst case'
        else:
            cost, source = 0.0, f"refused ({response.get('status')}): not billed"
        error = data.get('error') if isinstance(data.get('error'), dict) else None
        choice = (data.get('choices') or [{}])[0] if isinstance(data.get('choices'), list) and data.get('choices') else {}
        row = {'at': time.time(), 'run': self.run, 'scenario': self.scenario, 'model': model, 'status': response.get('status'),
               'latencyS': round(latency, 3), 'promptTokens': pt, 'completionTokens': ct,
               'reasoningTokens': (usage.get('completion_tokens_details') or {}).get('reasoning_tokens'),
               'finish': choice.get('finish_reason') if isinstance(choice, dict) else None, 'executionProvider': provider,
               'costUsd': round(cost, 8), 'costSource': source, 'costCounted': cost, 'worstCaseUsd': round(worst, 6),
               'error': {'type': error.get('type'), 'message': str(error.get('message'))[:160]} if error else None}
        with LEDGER.open('a') as f:
            f.write(json.dumps(row) + '\n')
        if self.mutate and response.get('status') == 200:
            response = self.mutate(response)
        return response


# --- fixtures ------------------------------------------------------------------------------------------
def source(sid, facts, policy='own'):
    items = [{'id': f'{sid}-f{i}', 'text': t, 'sourceId': sid, 'locator': ''} for i, t in enumerate(facts, 1)]
    return {'id': sid, 'policy': policy, 'candidateOnly': False, 'facts': items, 'hash': sid}


def context(*sources):
    return {'schema': 'postriff.context.v1', 'operation': 'draft', 'providerClass': 'cloud', 'sources': list(sources),
            'excluded': [], 'policyEpoch': 'live', 'candidateOnly': False}


RECITAL = source('src-recital', ['The autumn recital is on 18 October 2026 at 7:30 pm.',
                                 'Venue: City Hall Recital Hall, Hong Kong.',
                                 'Programme: Chopin Ballade No. 1 and Debussy Images, Book 1.',
                                 'Tickets are free but need registration.'])
SIMPLIFIED_ONLY = set('这说们来时发会对过还没为着学么里样钢琴门')  # 钢 (TC 鋼) is a common tell in this topic


def lang_ok(text, tag):
    cjk = sum(1 for ch in text if '一' <= ch <= '鿿')
    letters = sum(1 for ch in text if ch.isalpha())
    if tag.startswith('zh'):
        return cjk >= 0.3 * max(1, letters) and not (set(text) & SIMPLIFIED_ONLY)
    return cjk == 0


def numbers(text):
    return set(re.findall(r'\d+', text))


MONTHS = ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october', 'november', 'december']


def invented_numbers(text, *allowed_texts):
    """Digits in the text that no fact or the idea supports. A month named in the facts may be written as its
    number (10月18日), a pm time in 24-hour form (19:30), and a leading zero may be added (09:00)."""
    allowed = set().union(*(numbers(t) for t in allowed_texts))
    joined = ' '.join(allowed_texts).lower()
    allowed |= {str(i + 1) for i, name in enumerate(MONTHS) if name in joined}
    allowed |= {str(int(h) + 12) for h in re.findall(r'(\d{1,2})(?::\d{2})?\s*pm', joined) if int(h) < 12}
    return sorted(n for n in numbers(text) if n not in allowed and n.lstrip('0') not in allowed)


EMOJI = re.compile('[\U0001F300-\U0001FAFF☀-➿]')


def draft(runtime, model, ctx, destinations, idea, reasoning='standard', **extra):
    events = []
    request = {'context': ctx, 'destinations': destinations, 'reasoning': reasoning, 'model': model, 'idea': idea, 'tone': 'warm', **extra}
    started = time.monotonic()
    result = runtime.start_turn(request, lambda e: events.append(e) or True)
    return result, events, time.monotonic() - started


def facts_text(ctx):
    return ' '.join(f['text'] for s in ctx['sources'] for f in s['facts'])


# --- scenarios -----------------------------------------------------------------------------------------
def s_drafting(rt, m):
    dests = [{'platform': 'LinkedIn', 'language': 'en-GB', 'channelId': 'acct-a'}, {'platform': 'Threads', 'language': 'zh-Hant-HK'}]
    idea = 'Invite people to my autumn recital.'
    result, events, dt = draft(rt, m, context(RECITAL), dests, idea)
    v = result['artifact']['variants']
    checks = {
        'one variant per destination, account kept': [x['platform'] for x in v] == ['LinkedIn', 'Threads'] and v[0].get('channelId') == 'acct-a',
        'languages native (en-GB; Traditional Chinese for zh-Hant-HK)': lang_ok(v[0]['text'], 'en') and lang_ok(v[1]['text'], 'zh'),
        'no invented numbers': not any(invented_numbers(x['text'], facts_text(context(RECITAL)), idea) for x in v),
        'no hashtags or emoji (rule 4)': not any('#' in x['text'] or EMOJI.search(x['text']) for x in v),
        'within platform limits': not any('limit by' in w for x in v for w in x['warnings']),
        'cites the recital source': all(x['sourceIds'] == ['src-recital'] for x in v),
    }
    return checks, result, dt, {'texts': [x['text'][:400] for x in v]}


def s_chat_followup(rt, m):
    first, _, _ = draft(rt, m, context(RECITAL), [{'platform': 'LinkedIn', 'language': 'en-GB'}], 'Invite people to my autumn recital.')
    before = first['artifact']['variants'][0]['text']
    idea = 'Follow-up from the author: make this LinkedIn post shorter and warmer, keep every fact.\n\nCurrent draft:\n' + before
    result, _, dt = draft(rt, m, context(RECITAL), [{'platform': 'LinkedIn', 'language': 'en-GB'}], idea)
    after = result['artifact']['variants'][0]['text']
    checks = {'shorter than the first draft': len(after) < len(before),
              'keeps the date': '18' in after and 'October' in after,
              'no invented numbers': not invented_numbers(after, facts_text(context(RECITAL)), idea)}
    return checks, result, dt, {'before': before[:400], 'after': after[:400]}


CASES = [
    ('Every Tuesday at 9am, post a practice tip on LinkedIn in my voice', {'action': 'automation', 'weekdays': ['Tuesday'], 'localTime': '09:00', 'voice': True}),
    ("Write my weekly recap about this week's rehearsal", {'action': 'draft'}),
    ('逢星期五晚上八點幫我出一個練琴小貼士', {'action': 'automation', 'weekdays': ['Friday'], 'localTime': '20:00'}),
    ('Twice a week, share one AI news summary for musicians', {'action': 'automation', 'weekdayCount': 2, 'assumptions': True}),
    ('I practise every day. Write a post about it.', {'action': 'draft'}),
]


def understand(call, text, state, zone='Asia/Hong_Kong'):
    user = request_model.user_prompt(text, zone, time.time(), state)
    answer = call(request_model.SYSTEM_PROMPT, user, request_model.schema(state))  # ModelResponse is the answer dict
    return request_model.reading(answer, state), answer


def s_tool_decision(rt, m):
    call = GatewayCall(TOKEN, model=m, transport=rt.transport, allowed_providers=rt.allowed_for(m))
    state, checks, readings, started = {}, {}, [], time.monotonic()
    for text, want in CASES:
        try:
            got, _ = understand(call, text, state)
        except Exception as error:  # noqa: BLE001 - recorded as a failed case
            got = {'error': str(error)[:160]}
        readings.append({'text': text, 'reading': got})
        a = (got or {}).get('automation') or {}
        ok = (got or {}).get('action') == want['action']
        if ok and 'weekdays' in want:
            ok = a.get('weekdays') == want['weekdays']
        if ok and 'localTime' in want:
            ok = a.get('localTime') == want['localTime']
        if ok and 'voice' in want:
            ok = a.get('voice') is want['voice']
        if ok and 'weekdayCount' in want:
            ok = len(a.get('weekdays') or []) == want['weekdayCount'] and (not want.get('assumptions') or bool(a.get('assumptions')))
        checks[f'reads: {text[:48]}'] = ok
    return checks, None, time.monotonic() - started, {'readings': readings}


def s_research(rt, m):
    a = source('web-a', ['Organisers said the 2026 Harbour Piano Festival sold 12,000 tickets across four days.',
                         'The festival ran from 5 to 8 September 2026 at West Kowloon.'], policy='web')
    b = source('web-b', ['A newspaper report put attendance at about 11,500 people.',
                         'The report said most concerts were free for students.'], policy='web')
    c = source('web-c', ['A performer interview described the outdoor stage as "windy but joyful".'], policy='web')
    idea = "Summarise what is known about the Harbour Piano Festival's attendance for my followers, and say where each figure comes from."
    result, _, dt = draft(rt, m, context(a, b, c), [{'platform': 'LinkedIn', 'language': 'en-GB'}], idea)
    v = result['artifact']['variants'][0]
    blob = (v['text'] + ' ' + ' '.join(v['unknowns'] + v['warnings'])).lower()
    checks = {'cites at least the two figure sources': {'web-a', 'web-b'} <= set(v['sourceIds']),
              'no invented numbers': not invented_numbers(v['text'], facts_text(context(a, b, c)), idea),
              'conflicting figures surfaced, not merged': ('12,000' in v['text'] and '11,500' in v['text']) or any(w in blob for w in ('differ', 'conflict', 'discrepan', 'vary', 'varies'))}
    return checks, result, dt, {'text': v['text'][:500], 'unknowns': v['unknowns'], 'warnings': v['warnings']}


# What an automation reading may carry: the fields the request schema lets the model send, plus the ones the app
# derives from its schedule (request_model._automation). Anything else would be an invented field.
DERIVED_AUTOMATION_FIELDS = {'weekdays', 'monthDays', 'countdown', 'localTime'}


def automation_fields(state=None):
    node = request_model.schema(state or {})['properties']['automation']
    node = next((n for n in node.get('anyOf', []) if n.get('type') == 'object'), node)
    return set(node.get('properties') or {})


def invented_automation_fields(answer, reading, state=None):
    """Fields in the model's raw automation answer or in the app's reading that the schema does not define."""
    allowed = automation_fields(state)
    raw = (answer or {}).get('automation') if isinstance(answer, dict) else None
    read = (reading or {}).get('automation') or {}
    return sorted((set(raw or {}) - allowed) | (set(read) - allowed - DERIVED_AUTOMATION_FIELDS))


def s_campaign(rt, m):
    call = GatewayCall(TOKEN, model=m, transport=rt.transport, allowed_providers=rt.allowed_for(m))
    reading, answer = understand(call, 'Count down to my recital on 18 October on LinkedIn: a post two weeks before, one week before and on the day.', {})
    a = (reading or {}).get('automation') or {}
    idea = 'Autumn recital countdown: one week to go.'
    result, _, dt = draft(rt, m, context(RECITAL), [{'platform': 'LinkedIn', 'language': 'en-GB'}], idea)
    text = result['artifact']['variants'][0]['text']
    counted = a.get('countdown') or {}
    checks = {'countdown read as a countdown (or left as a draft), never as repeating days': (reading or {}).get('action') == 'draft'
              or (counted.get('eventDate', '').endswith('-10-18') and set(counted.get('daysBefore', [])) == {14, 7, 0} and not a.get('weekdays') and not a.get('monthDays')),
              'no invented schedule fields beyond the schema': not invented_automation_fields(answer, reading),
              'countdown draft keeps date and venue': '18' in text and 'City Hall' in text,
              'no invented numbers': not invented_numbers(text, facts_text(context(RECITAL)), idea)}
    return checks, result, dt, {'reading': reading, 'text': text[:400], 'invented': invented_automation_fields(answer, reading)}


VOICE = ("# VOICE.md\nI write short, plain sentences. I open with one concrete observation from the practice room. "
         "I never use exclamation marks or hashtags. British spelling (practise, colour). I sign off with '— J'.")


def s_rewrite_voice(rt, m):
    idea = "Rewrite this in my voice: 'Super excited!!! Come to my recital, it's going to be AMAZING #piano #music'"
    result, _, dt = draft(rt, m, context(RECITAL), [{'platform': 'Instagram', 'language': 'en-GB'}], idea,
                          memory=[{'name': 'VOICE.md', 'body': VOICE}], styleDirectives={'shortOpenings': True, 'shortParagraphs': True})
    text = result['artifact']['variants'][0]['text']
    sentences = [s for s in re.split(r'[.!?]\s', text) if s.strip()]
    checks = {'no exclamation marks': '!' not in text, 'no hashtags': '#' not in text, 'signs off — J': '— J' in text or '- J' in text,
              'short sentences (mean ≤ 16 words)': statistics.mean(len(s.split()) for s in sentences) <= 16 if sentences else False,
              'keeps the date': '18' in text and 'October' in text}
    return checks, result, dt, {'text': text[:500]}


def s_long_context(rt, m):
    filler = []
    for i in range(1, 181):
        filler.append(f'Practice log {i}: worked on voicing in bar {i % 90 + 1}, slow tempo {40 + i % 30} bpm, '
                      f'noted tension in the left wrist and a plan to relax the thumb before the next session. '
                      f'Session length {20 + i % 40} minutes; focus on legato pedalling and quieter inner voices.')
    logs1, logs2 = source('src-logs-1', filler[:90]), source('src-logs-2', filler[90:])
    needle = source('src-update', ['Update on 22 September: the recital moves to the Hong Kong Cultural Centre Studio Theatre. The date stays 18 October 2026, 7:30 pm.'])
    ctx = context(RECITAL, logs1, needle, logs2)
    size = len(json.dumps(ServerModelRuntime._user_payload({'context': ctx, 'destinations': [{'platform': 'LinkedIn', 'language': 'en-GB'}]}), ensure_ascii=False).encode())
    idea = 'Tell people where and when the recital is.'
    result, _, dt = draft(rt, m, ctx, [{'platform': 'LinkedIn', 'language': 'en-GB'}], idea)
    v = result['artifact']['variants'][0]
    text = v['text']
    checks = {'uses the buried update (Cultural Centre)': 'Cultural Centre' in text,
              'does not present City Hall as the venue': 'City Hall' not in text or any(w in text.lower() for w in ('moved', 'moves', 'instead', 'changed', 'new venue')),
              'cites the update source': 'src-update' in v['sourceIds'],
              'no invented numbers': not invented_numbers(text, facts_text(ctx), idea)}
    return checks, result, dt, {'contextBytes': size, 'text': text[:400]}


def s_deep(rt, m):
    result, events, dt = draft(rt, m, context(RECITAL), [{'platform': 'Threads', 'language': 'en-GB'}], 'Invite people to my autumn recital.', reasoning='deep')
    checks = {'two passes (draft + revise)': result['usage']['modelRequests'] == 2,
              'revise pass kept (no failure warning)': not any('revise pass did not complete' in (e.get('message') or '') for e in events if isinstance(e, dict))}
    return checks, result, dt, {'text': result['artifact']['variants'][0]['text'][:300]}


SCENARIOS = [('drafting', s_drafting), ('chat_followup', s_chat_followup), ('tool_decision_automation_intent', s_tool_decision),
             ('research_synthesis', s_research), ('campaign_planning', s_campaign), ('rewrite_voice', s_rewrite_voice),
             ('long_context', s_long_context), ('deep_reasoning', s_deep)]


# --- failure paths (one model) -------------------------------------------------------------------------
def failures(guard, model, restricted):
    out = {}
    one = [{'platform': 'LinkedIn', 'language': 'en-GB'}]
    rt = ServerModelRuntime(TOKEN, model=model, models=[model, restricted, 'anthropic/not-a-model'], transport=guard,
                            prices={model: list_price(model), restricted: list_price(restricted), 'anthropic/not-a-model': (1.0, 1.0)})
    rt.sleep = lambda s: None

    def corrupt_first(times):
        state = {'left': times}

        def mutate(response):
            if state['left'] > 0:
                state['left'] -= 1
                body = dict(response['body'])
                choice = dict(body['choices'][0]); msg = dict(choice['message'])
                msg['content'] = msg['content'][: max(1, len(msg['content']) // 3)]  # truncated JSON
                choice['message'] = msg; body['choices'] = [choice]
                return {**response, 'body': body}
            return response
        return mutate

    guard.scenario, guard.mutate = 'malformed_once_then_ok', corrupt_first(1)
    try:
        r, ev, _ = draft(rt, model, context(RECITAL), one, 'Invite people to my autumn recital.')
        out['malformed JSON once → one retry → valid draft, cost of both calls known'] = (r['usage']['modelRequests'] == 2 and r['usage']['costUsd'] is not None
                                                                                          and any('valid JSON' in (e.get('message') or '') for e in ev if isinstance(e, dict)))
    except Exception as error:  # noqa: BLE001
        out['malformed JSON once → one retry → valid draft, cost of both calls known'] = f'error: {error}'
    guard.scenario, guard.mutate = 'malformed_twice', corrupt_first(2)
    try:
        draft(rt, model, context(RECITAL), one, 'Invite people to my autumn recital.')
        out['malformed twice → run fails, no third paid call'] = 'unexpected success'
    except ProviderFailure as error:
        out['malformed twice → run fails, no third paid call'] = error.dispatched and error.cost_usd is not None and error.cost_usd > 0
    guard.mutate = None

    guard.scenario = 'truncated_output'
    # Both caps: output_cap() reads them at call time, so thinking models are forced to the limit too.
    saved = (model_runtime.MAX_OUTPUT_TOKENS, model_runtime.THINKING_OUTPUT_TOKENS)
    model_runtime.MAX_OUTPUT_TOKENS = model_runtime.THINKING_OUTPUT_TOKENS = 24
    try:
        draft(rt, model, context(RECITAL), one, 'Invite people to my autumn recital.')
        out['output limit reached twice → clean failure with known cost'] = 'unexpected success'
    except ProviderFailure as error:
        out['output limit reached twice → clean failure with known cost'] = error.dispatched and error.cost_usd is not None and 'output limit' in str(error)
    finally:
        model_runtime.MAX_OUTPUT_TOKENS, model_runtime.THINKING_OUTPUT_TOKENS = saved

    for label, bad in (('gateway refuses a restricted model (free tier)', restricted), ('gateway refuses an unknown model id', 'anthropic/not-a-model')):
        guard.scenario = label
        try:
            draft(rt, bad, context(RECITAL), one, 'Invite people to my autumn recital.')
            out[f'{label} → failure, charged 0'] = 'unexpected success'
        except ProviderFailure as error:
            out[f'{label} → failure, charged 0'] = error.dispatched is True and error.cost_usd == 0.0

    guard.scenario = 'understanding_fallback'
    text = 'Every Tuesday at 9am, post a practice tip on LinkedIn'
    try:
        understand(GatewayCall(TOKEN, model=request_model.UNDERSTANDING_MODEL, transport=guard), text, {})
        out["app's understanding model call fails → deterministic reading takes over"] = 'model call unexpectedly succeeded'
    except Exception:  # noqa: BLE001 - the app falls back on any failure
        schedule, notes = automation_chat.schedule_of(text, 'Asia/Hong_Kong')
        out["app's understanding model call fails → deterministic reading takes over"] = bool(intent.is_automation_request(text)) and bool(schedule)
        out['_deterministic_schedule'] = {'schedule': schedule, 'notes': notes}
    guard.scenario = None
    return out


def main():
    global LIVE, LEDGER, SOFT_CAP, CATALOG
    ap = argparse.ArgumentParser()
    ap.add_argument('--models', required=True)
    ap.add_argument('--run', required=True)
    ap.add_argument('--failures', default=None)
    ap.add_argument('--restricted', default='anthropic/claude-opus-5.5')
    ap.add_argument('--only', default=None)
    # Same shape as POSTRIFF_MODEL_PROVIDERS: {model: [gateway provider slugs]}; default is the model's maker.
    ap.add_argument('--providers', default='{}')
    ap.add_argument('--out', default=str(ROOT / 'docs/launch-20260923/evidence/live-models'))
    ap.add_argument('--cap', type=float, default=2.50, help='stop before the ledger total would pass this (USD)')
    ap.add_argument('--confirm-spend', action='store_true', help='required: this sends paid requests')
    args = ap.parse_args()
    if not args.confirm_spend:
        sys.exit('Refusing: pass --confirm-spend to send paid requests (capped by --cap).')
    if not TOKEN:
        sys.exit('Set AI_GATEWAY_API_KEY (or VERCEL_OIDC_TOKEN) in the environment.')
    LIVE = pathlib.Path(args.out); LIVE.mkdir(parents=True, exist_ok=True); LEDGER = LIVE / 'ledger.jsonl'
    SOFT_CAP, CATALOG = args.cap, load_catalog()
    providers = model_runtime.provider_map({'POSTRIFF_MODEL_PROVIDERS': args.providers})
    guard = Guard(args.run)
    report = {'run': args.run, 'startedSpentUsd': round(spent_so_far(), 6), 'models': {}, 'failures': None, 'providers': providers}
    if args.models == 'none':
        args.models = ''
    for model in filter(None, args.models.split(',')):
        rt = ServerModelRuntime(TOKEN, model=model, models=[model], transport=guard, prices={model: list_price(model)}, allowed_providers=providers)
        rt.sleep = lambda s: None
        per = report['models'][model] = {'scenarios': {}, 'latencyS': []}
        for name, fn in SCENARIOS:
            if args.only and name not in args.only.split(','):
                continue
            guard.scenario = name
            try:
                checks, result, dt, detail = fn(rt, model)
                usage = (result or {}).get('usage') or {}
                per['scenarios'][name] = {'pass': all(v is True for v in checks.values()), 'checks': checks, 'latencyS': round(dt, 2),
                                          'costUsd': usage.get('costUsd'), 'provenance': usage.get('provenance'), 'detail': detail}
                per['latencyS'].append(dt)
            except BudgetStop as stop:
                per['scenarios'][name] = {'pass': False, 'budgetStop': str(stop)}
                report['budgetStopped'] = str(stop)
                break
            except Exception as error:  # noqa: BLE001 - a scenario failure is a result
                per['scenarios'][name] = {'pass': False, 'error': f'{type(error).__name__}: {str(error)[:300]}', 'trace': traceback.format_exc()[-800:]}
            print(f"{model:32s} {name:34s} {'PASS' if per['scenarios'][name]['pass'] else 'FAIL'}", flush=True)
        if per['latencyS']:
            per['latencySummary'] = {'p50': round(statistics.median(per['latencyS']), 2), 'max': round(max(per['latencyS']), 2)}
        if report.get('budgetStopped'):
            break
    if args.failures and not report.get('budgetStopped'):
        report['failures'] = failures(guard, args.failures, args.restricted)
        for k, v in report['failures'].items():
            if not k.startswith('_'):
                print(f"failure-path {k:80s} {'PASS' if v is True else 'FAIL: ' + str(v)}", flush=True)
    rows = [json.loads(line) for line in LEDGER.read_text().splitlines() if line.strip() and json.loads(line).get('run') == args.run]
    report['calls'] = len(rows)
    report['runCostUsd'] = round(sum(r['costCounted'] for r in rows), 6)
    report['totalSpentUsd'] = round(spent_so_far(), 6)
    report['costSources'] = sorted({r['costSource'] for r in rows})
    (LIVE / f'report-{args.run}.json').write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str))
    print(json.dumps({k: report[k] for k in ('calls', 'runCostUsd', 'totalSpentUsd', 'costSources')}))


if __name__ == '__main__':
    main()
