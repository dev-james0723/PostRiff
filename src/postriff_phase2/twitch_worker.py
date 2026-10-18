"""Dedicated bounded worker entry point; deployment remains an operator action.

The existing authenticated Rafii cron invokes one bounded maintenance batch.
An isolated long-lived worker can drain further batches without blocking requests.
Production credentials and explicit release/purpose gates are required at runtime;
this module creates no external worker and incurs no cost merely by existing.
"""
from __future__ import annotations
import argparse
import json
import os
import time
from urllib.parse import parse_qs, urlsplit

PRODUCTION_PROJECT = 'buoyhkbodnhzngaotoel'


def production_target_allowed(values):
    """Match both identity/storage and SQL routing without revealing a credential."""
    if values.get('POSTRIFF_SUPABASE_URL', '').rstrip('/') != f'https://{PRODUCTION_PROJECT}.supabase.co':
        return False
    try:
        database = urlsplit(values.get('POSTRIFF_DATABASE_URL', ''))
        if database.scheme not in ('postgres', 'postgresql') or database.path != '/postgres' or database.port not in (None, 5432, 6543):
            return False
        # URI query routing can override the host/user in a libpq connection URI.
        if not set(parse_qs(database.query, keep_blank_values=True)) <= {'sslmode', 'connect_timeout', 'application_name'}:
            return False
        if database.fragment:
            return False
        direct = database.hostname == f'db.{PRODUCTION_PROJECT}.supabase.co' and database.username == 'postgres'
        pooler = (database.hostname or '').endswith('.pooler.supabase.com') and database.username == f'postgres.{PRODUCTION_PROJECT}'
        return direct or pooler
    except (TypeError, ValueError):
        return False


def tick(twitch, *, limit=10, startup=False):
    if not twitch.enabled:
        return twitch.maintenance(limit=limit)
    validation = twitch.validation_tick(limit=min(limit,100), startup=True) if startup else None
    result = twitch.maintenance(limit=limit)
    if validation is not None:
        result['startupValidation'] = validation
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description='Run approved Twitch native jobs with durable consent and revocation fences.')
    parser.add_argument('--watch',action='store_true',help='Continue polling the existing durable queue.')
    parser.add_argument('--limit',type=int,default=10)
    parser.add_argument('--poll-seconds',type=int,default=15)
    args=parser.parse_args(argv)
    if not 1<=args.limit<=100 or not 1<=args.poll_seconds<=60:
        parser.error('Use limit 1..100 and poll-seconds 1..60.')
    # A production invocation must never silently target the known staging project.
    if os.environ.get('VERCEL_ENV')=='production' and not production_target_allowed(os.environ):
        parser.error('Production must target the canonical Rafii Supabase project.')
    from .hosted_app import runtime_from_environment
    service,_,_=runtime_from_environment()
    first=True
    while True:
        result=tick(service.twitch,limit=args.limit,startup=first)
        # Counters/states only. No provider results, viewer content or secret text.
        summary={key:value for key,value in result.items() if key in ('enabled','migrationReady','purgedEvents','processedEvents','recoveredUnknown')}
        summary['actionStates']=[item.get('state','unknown') for item in result.get('actions',[])]
        print(json.dumps(summary,separators=(',',':')),flush=True)
        first=False
        if not args.watch: return 0
        time.sleep(args.poll_seconds)


if __name__=='__main__': raise SystemExit(main())
