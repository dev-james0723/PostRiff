"""Operator tool: list and finalize model usage whose provider cost is unknown (FINAL-05).

An unknown hold keeps the customer's approved credits reserved until someone checks the provider's own
records (for example the AI Gateway request log). This tool never guesses a cost: every settlement needs
the actual amount and an evidence reference, and each reservation can be finalized once.

  python3 scripts/reconcile_unknown_usage.py --dsn "host=127.0.0.1 port=55438 dbname=postgres" list
  python3 scripts/reconcile_unknown_usage.py --dsn ... settle --workspace W --reservation R \
      --outcome failed --actual-usd 0.0123 --operator "ops-oncall" --evidence "gateway req 3f2a…"

`failed`: the person got no result, so no credits are charged; the provider cost is still booked.
`completed`: the result was delivered; the actual cost is charged within the amount they approved.
Only a loopback database is accepted unless --confirm-host names the exact database host.
"""
import argparse
import json
import sys
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import psycopg
from psycopg.conninfo import conninfo_to_dict
from postriff_alpha.domain import AlphaError
from postriff_phase2.billing import Ledger


def micro(value):
    try:
        amount = Decimal(value)
    except InvalidOperation as error:
        raise SystemExit("--actual-usd must be a number such as 0.0123") from error
    if amount < 0 or not amount.is_finite():
        raise SystemExit("--actual-usd must be zero or more")
    return int((amount * 1_000_000).to_integral_value(rounding=ROUND_CEILING))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dsn", required=True)
    parser.add_argument("--confirm-host", default="")
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list")
    listing.add_argument("--workspace")
    settle = commands.add_parser("settle")
    settle.add_argument("--workspace", required=True)
    settle.add_argument("--reservation", required=True)
    settle.add_argument("--outcome", choices=("completed", "failed"), required=True)
    settle.add_argument("--actual-usd", required=True)
    settle.add_argument("--operator", required=True)
    settle.add_argument("--evidence", required=True)
    args = parser.parse_args(argv)
    host = conninfo_to_dict(args.dsn).get("host", "")
    if host not in ("127.0.0.1", "localhost", "::1") and args.confirm_host != host:
        raise SystemExit("Refusing a non-loopback database without --confirm-host naming that exact host.")
    ledger = Ledger()
    with psycopg.connect(args.dsn, client_encoding="utf8") as db, db.cursor() as cur:
        if args.command == "list":
            print(json.dumps({"unknown": ledger.unknown_reservations(cur, args.workspace)}, indent=1))
            return 0
        cur.execute("SELECT id FROM public.pr_workspaces WHERE id=%s FOR UPDATE", (args.workspace,))
        try:
            result = ledger.reconcile_unknown(cur, args.workspace, args.reservation, args.outcome, micro(args.actual_usd), operator=args.operator, evidence=args.evidence)
        except AlphaError as error:
            print(json.dumps({"status": "refused", "httpStatus": error.status, "reason": str(error)}))
            return 2
        print(json.dumps({"status": "settled", **result}))
        return 0


if __name__ == "__main__":
    sys.exit(main())
