#!/usr/bin/env python3
"""The sequence of events of typical released posts, from a capacity run directory (W-02 capacity harness).

A post is "released" when the lane let go of it before the create (a refused request, `rateDelayed` in the lane's counters)
and a later claim started its preflight pass again from the grant check. This script reads only what a downloaded artifact
holds (mock/mock-requests.jsonl, admissions.jsonl, config.json) and prints, as Markdown:

  - the summary the receipt prints (passes per post, where released passes stopped, re-claim delays, the application window);
  - for a few typical posts, every request of the workspace in order: seconds after T, route, lane shard, the wait between
    the previous answer being observed and this request's admission, how many sends the application window held at that
    moment, and each release with the wait until the next pass.

A refused reservation leaves no row anywhere, so the wait that was quoted for it is not in the artifact; the attempt log of
the invocation wrapper (attempts.jsonl, harness commits after this script) holds it.

  python3 scripts/discord_lane_cap_release_trace.py RUN_DIR [--posts 4]
"""
import argparse
import bisect
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import discord_lane_cap_analysis as analysis  # noqa: E402

SHORT = {'GET /oauth2/@me': 'grant check (user)', 'GET /guilds/{id}': 'server read', 'GET /guilds/{id}/members/{id}': 'member read',
         'GET /guilds/{id}/channels': 'channel list', analysis.CREATE: 'CREATE', analysis.READBACK: 'read-back'}


def load(run_dir):
    config = analysis.load_json(os.path.join(run_dir, 'config.json'))
    window = [r for r in analysis.load_jsonl(os.path.join(run_dir, 'mock', 'mock-requests.jsonl'))
              if r['processed'] >= config['runStartedAt']]
    admissions = analysis.load_jsonl(os.path.join(run_dir, 'admissions.jsonl'))
    return config, window, admissions


def pick(by_tenant):
    """One typical post per kind, the first in workspace order: a single quick release, several in a row, a long wait for the
    re-claim, and a release at the create itself."""
    chosen = {}
    for tenant in sorted(by_tenant):
        items = by_tenant[tenant]
        for number, item in enumerate(items):
            if item['end'] != 'released' or number + 1 >= len(items):
                continue
            wait = items[number + 1]['start'] - analysis.last_answer(item['requests'][-1])
            run = 0
            while number + run < len(items) and items[number + run]['end'] == 'released':
                run += 1
            stages = [r['route'] for r in item['requests']]
            if 'one quick release' not in chosen and run == 1 and wait < 2 and items[number + 1]['end'] == 'created':
                chosen['one quick release'] = (tenant, number)
            elif 'several releases in a row' not in chosen and run >= 4 and number + run < len(items):
                chosen['several releases in a row'] = (tenant, number)
            elif 'a long wait for the re-claim' not in chosen and wait > 100 and wait < 400:
                chosen['a long wait for the re-claim'] = (tenant, number)
            elif 'released at the create' not in chosen and 'GET /guilds/{id}/channels' in stages:
                chosen['released at the create'] = (tenant, number)
        if len(chosen) == 4:
            break
    return chosen


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('run_dir')
    parser.add_argument('--span', type=float, default=1.1, help='seconds a send occupies a slot of the application window')
    args = parser.parse_args(argv)
    config, window, admissions = load(args.run_dir)
    T = config['dueAt']
    summary = analysis.preflight_passes(window, admissions, span=args.span)
    by_tenant = analysis.workspace_passes(window)
    pairs, _unpaired, _every = analysis.pair_admissions(window, admissions, with_rows=True)
    row_of = {id(record): row for _at, record, _publish, row in pairs}
    sends = sorted(row[2] for row in admissions if row[2] is not None)
    occupied = lambda t: bisect.bisect_right(sends, t) - bisect.bisect_right(sends, t - args.span)
    print('# Released posts in %s (%s)\n' % (config.get('label'), config.get('scenario')))
    print('```json\n%s\n```\n' % json.dumps({k: v for k, v in (summary or {}).items() if k != 'stepWait'}, indent=1, sort_keys=True))
    for kind, (tenant, number) in pick(by_tenant).items():
        items = by_tenant[tenant]
        first = number
        while first > 0 and items[first - 1]['end'] == 'released':
            first -= 1
        last = number
        while last < len(items) and items[last]['end'] == 'released':
            last += 1
        print('## %s: workspace %d\n' % (kind, tenant))
        print('| t after T (s) | request | shard | wait after the previous answer (ms) | sends in the last %.1f s at admission | note |' % args.span)
        print('|---|---|---|---|---|---|')
        previous = None
        for pass_number in range(first, min(last + 1, len(items))):
            item = items[pass_number]
            for record in item['requests']:
                row = row_of.get(id(record))
                wait = (1000 * (row[0] - row_of[id(previous)][3])) if (previous is not None and row is not None
                                                                       and row_of.get(id(previous)) and row_of[id(previous)][3]) else None
                print('| %.3f | %s | %s | %s | %s | %s |' % (
                    record['arrived'] - T, SHORT.get(record['route'], record['route']), record.get('src', ''),
                    '%.0f' % wait if wait is not None else '', occupied(row[0]) if row is not None else '',
                    'status %s' % record.get('status')))
                previous = record
            if item['end'] == 'released':
                t = analysis.last_answer(item['requests'][-1])
                following = items[pass_number + 1]['start'] - t if pass_number + 1 < len(items) else None
                print('| %.3f | **released** after %s | | | %s at +0 / +0.25 / +0.5 / +0.75 / +1 s | next pass %s s later |' % (
                    t - T, '+'.join(analysis._WITNESS[r['route']] for r in item['requests'] if r['route'] in analysis._WITNESS),
                    ' / '.join(str(occupied(t + dt)) for dt in (0, .25, .5, .75, 1.0)),
                    '%.2f' % following if following is not None else 'n/a'))
                previous = None
        print()
    return 0


if __name__ == '__main__':
    sys.exit(main())
