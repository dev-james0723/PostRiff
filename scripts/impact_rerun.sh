#!/usr/bin/env bash
# Re-run the customer impact evidence (docs/CUSTOMER-IMPACT-INVENTORY.md) for one candidate SHA. Read-only on the
# repository (trees come from git objects), local PostgreSQL only, no network, no deployment.
#
#   scripts/impact_rerun.sh <candidate sha> [live sha]
#
# Environment: POSTRIFF_PG_BIN (default /usr/lib/postgresql/16/bin), PYTHON (default /opt/prvenv/bin/python),
# IMPACT_PYPDF_PYTHONS (interpreters with different pypdf versions, os.pathsep separated), IMPACT_OLD_PILLOW_PYTHON
# (an interpreter with the live Pillow pin, default /usr/bin/python3), SUPERSET_ALLOW (default: the ledger's
# superset-allowlist.json if present).
set -u -o pipefail
RC=${1:?usage: scripts/impact_rerun.sh <candidate sha> [live sha]}
LIVE=${2:-c5fc1fd10350f3142ec6f34b2c373139e85abb39}
BASE=7dc95e2e005cd10069b835867c5b8f8c47a9e391
HERE=$(cd "$(dirname "$0")/.." && pwd)
PYTHON=${PYTHON:-/opt/prvenv/bin/python}
export POSTRIFF_PG_BIN=${POSTRIFF_PG_BIN:-/usr/lib/postgresql/16/bin} PYTHONDONTWRITEBYTECODE=1
export IMPACT_LIVE_REV=$LIVE IMPACT_RC_REV=$(git -C "$HERE" rev-parse --verify "$RC^{commit}") || exit 2
ALLOW=${SUPERSET_ALLOW:-$(git -C "$HERE" rev-parse --show-toplevel)/../PostRiff/docs/launch-20261023-discord/superset-allowlist.json}
status=0
echo "== candidate $IMPACT_RC_REV, live $LIVE (load: $(cut -d' ' -f1-3 /proc/loadavg))"
echo "== 1/4 superset proof (everything the live line added is still in the candidate)"
if [ -f "$ALLOW" ]; then
  "$PYTHON" "$HERE/scripts/rc_superset_proof.py" --live "$LIVE" --rc "$IMPACT_RC_REV" --base "$BASE" --allow "$ALLOW" | tail -1 || status=1
else
  echo "   allowlist not found ($ALLOW): set SUPERSET_ALLOW"; status=1
fi
echo "== 2/4 differential run on real PostgreSQL (sign-in, ordinary post, reads, minute worker, W-02 shards, Discord surface)"
(cd "$HERE" && "$PYTHON" -m unittest tests.test_customer_impact_shared_paths 2>&1 | tail -3) || status=1
echo "== 3/4 public and unauthenticated HTTP answers of both builds' API, served offline"
(cd "$HERE" && "$PYTHON" -m unittest tests.test_impact_compare 2>&1 | tail -3) || status=1
echo "== 4/4 dependency moves on the customer image and PDF paths"
(cd "$HERE" && "$PYTHON" -m unittest tests.test_customer_impact_dependencies 2>&1 | tail -3) || status=1
echo "== expected: every step OK; 'expected failures=2' are findings FB-1 and CH-1 (an unexpected success means one was fixed:"
echo "   remove its expectedFailure decorator and update the inventory). Any other failure is a new difference to classify."
exit $status
