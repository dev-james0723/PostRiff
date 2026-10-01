#!/usr/bin/env python3
"""Test producer for Rafii's signed first-party results webhook.

Contract: docs/design/rafii-product-growth/contracts/first-party-results-webhook.md

Signs ONE event marked ``"test": true`` with a connection's secret and POSTs it to a Rafii deployment. The secret comes
from the environment variable RAFII_RESULTS_SECRET, never from the command line (so it stays out of shell history and
process listings), and it is never printed.

    RAFII_RESULTS_SECRET=rfs_… python scripts/results_test_producer.py <connection-id>
        [--base-url http://127.0.0.1:4331] [--type booking] [--event-id test-…] [--occurred-at 2026-10-01T15:00:00Z]
        [--ref <slug>.<YYYYMMDD>] [--amount 4500 --currency usd] [--campaign spring-workshop] [--reversal-of <eventId>]
        [--dry-run]

The default base URL is the local dev harness (scripts/postriff_dev_hosted.py --port 4331). Plain http is accepted only
for this machine. A test event shows in the ledger with a "Test" label and never counts in the results summary.
Sending to a real deployment needs a real connection its owner created; a synthetic delivery proves the transport
only, never a business result. Real producer setup and traffic remain a rollout step.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from postriff_phase2.results import signing  # noqa: E402

DEFAULT_BASE_URL = "http://127.0.0.1:4331"
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")


def build_event(args, now):
    event = {"eventId": args.event_id or f"test-{uuid.uuid4().hex[:16]}", "type": args.type,
             "occurredAt": args.occurred_at or datetime.fromtimestamp(now, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
             "test": True}
    if args.amount is not None:
        event["amount"] = {"minor": args.amount, "currency": (args.currency or "").lower()}
    if args.ref:
        event["rafii_ref"] = args.ref
    if args.campaign:
        event["campaignRef"] = args.campaign
    if args.reversal_of:
        event["reversalOf"] = args.reversal_of
    return event


def build_request(base_url, connection_id, secret, event, now):
    """(url, headers, exact body bytes). Refuses plain http to anything but this machine."""
    if not secret or not secret.startswith(signing.SECRET_PREFIX):
        raise ValueError("Set RAFII_RESULTS_SECRET to the connection secret (it starts with rfs_).")
    parts = urlsplit(base_url)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        raise ValueError("The base URL must be http(s)://host[:port].")
    if parts.scheme == "http" and parts.hostname not in LOCAL_HOSTS:
        raise ValueError("Use https:// for anything but this machine.")
    try:
        connection_id = str(uuid.UUID(connection_id))
    except ValueError:
        raise ValueError("The connection id is the UUID shown with the connection.") from None
    body = json.dumps(event, separators=(",", ":"), ensure_ascii=False).encode()
    if len(body) > signing.MAX_BODY_BYTES:
        raise ValueError(f"The event is larger than {signing.MAX_BODY_BYTES} bytes.")
    headers = {"Content-Type": "application/json", "X-Rafii-Signature": signing.sign(secret, now, body), "User-Agent": "rafii-results-test-producer/1"}
    return f"{base_url.rstrip('/')}{'/api/results/webhook/'}{connection_id}", headers, body


def main(argv=None):
    parser = argparse.ArgumentParser(description="Send one signed TEST event to a Rafii results connection.")
    parser.add_argument("connection_id")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--type", default="booking", choices=("click", "lead", "booking", "newsletter_signup", "sale"))
    parser.add_argument("--event-id")
    parser.add_argument("--occurred-at")
    parser.add_argument("--amount", type=int, help="whole minor units, e.g. 4500 for 45.00 (booking or sale only)")
    parser.add_argument("--currency", help="three-letter currency code, required with --amount")
    parser.add_argument("--ref", help="the rafii_ref value a tracking link added, e.g. AbC…xyz.20261001")
    parser.add_argument("--campaign")
    parser.add_argument("--reversal-of")
    parser.add_argument("--dry-run", action="store_true", help="print the request instead of sending it")
    args = parser.parse_args(argv)
    if (args.amount is None) != (args.currency is None):
        parser.error("--amount and --currency go together")
    now = time.time()
    event = build_event(args, now)
    try:
        url, headers, body = build_request(args.base_url, args.connection_id, os.environ.get("RAFII_RESULTS_SECRET", ""), event, now)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if args.dry_run:
        print(json.dumps({"url": url, "headers": headers, "body": event}, indent=2, ensure_ascii=False))
        return 0
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            status, raw = response.status, response.read(65536)
    except urllib.error.HTTPError as error:
        status, raw = error.code, error.read(65536)
    except urllib.error.URLError as error:
        print(f"error: could not reach {args.base_url} ({error.reason})", file=sys.stderr)
        return 3
    try:
        answer = json.loads(raw or b"{}")
    except ValueError:
        answer = {"error": "non-JSON response"}
    print(json.dumps({"status": status, "eventId": event["eventId"], "response": answer}, ensure_ascii=False))
    return 0 if 200 <= status < 300 else 1


if __name__ == "__main__":
    sys.exit(main())
