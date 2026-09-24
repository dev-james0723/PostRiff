"""Operator tool: payment events that were verified but could not be applied (FINAL-06).

The webhook acknowledges these so the provider stops retrying, and keeps a minimal record (identifiers,
amounts, status; never customer or card details) with the reason. Resolving an item records what the
operator checked; it never grants, reverses or refunds anything by itself.

  python3 scripts/credit_payment_inbox.py --dsn "host=127.0.0.1 port=55438 dbname=postgres" list
  python3 scripts/credit_payment_inbox.py --dsn ... resolve --event evt_... --operator ops --note "..."

Only a loopback database is accepted unless --confirm-host names the exact database host.
"""
import argparse
import json
import sys

import psycopg
from psycopg.conninfo import conninfo_to_dict


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dsn", required=True)
    parser.add_argument("--confirm-host", default="")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    resolve = commands.add_parser("resolve")
    resolve.add_argument("--event", required=True)
    resolve.add_argument("--operator", required=True)
    resolve.add_argument("--note", required=True)
    args = parser.parse_args(argv)
    host = conninfo_to_dict(args.dsn).get("host", "")
    if host not in ("127.0.0.1", "localhost", "::1") and args.confirm_host != host:
        raise SystemExit("Refusing a non-loopback database without --confirm-host naming that exact host.")
    with psycopg.connect(args.dsn, client_encoding="utf8") as db, db.cursor() as cur:
        if args.command == "list":
            cur.execute("SELECT event_id,kind,event_created,livemode,event,reason,extract(epoch from received_at) FROM public.pr_credit_payment_inbox WHERE status='needs_review' ORDER BY received_at,event_id")
            rows = [{"eventId": r[0], "kind": r[1], "eventCreated": r[2], "livemode": r[3], "event": r[4], "reason": r[5], "receivedAt": float(r[6])} for r in cur.fetchall()]
            print(json.dumps({"needsReview": rows}, indent=1))
            return 0
        if not args.operator.strip() or not args.note.strip():
            raise SystemExit("Name the operator and what was checked.")
        cur.execute("UPDATE public.pr_credit_payment_inbox SET status='resolved',resolved_at=now(),resolution=%s::jsonb WHERE event_id=%s AND status='needs_review' RETURNING event_id",
                    (json.dumps({"operator": args.operator.strip()[:80], "note": args.note.strip()[:500]}), args.event))
        if not cur.fetchone():
            print(json.dumps({"status": "refused", "reason": "No open review item has this event id."}))
            return 2
        print(json.dumps({"status": "resolved", "eventId": args.event}))
        return 0


if __name__ == "__main__":
    sys.exit(main())
