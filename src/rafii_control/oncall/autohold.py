"""Option D: an automatic operator hold (docs/ops/H07-OPTIONS.md, section D). AN OWNER DECISION, OFF BY DEFAULT, AND
ADVISED AGAINST: the independent review of 8e76afdd and the Release Captain recommend not automating HOLD_ON, because the
hold itself strands posts (each created post's read-back is parked for 24 hours when a Discord-claiming worker runs
under it, and a post needs a new approval from about 55 minutes after its own scheduled time; PHONE-RUNBOOK.md).

CROSS_TENANT_PROBE_FAILED has no producer in this build (second review N-5): nothing writes security.probe, so the
default rule cannot engage until the Q-05 hosted run feeds its result to the payload or the scheduled runner.

If the owner enables it anyway: when an incident of a listed rule (by default only CROSS_TENANT_PROBE_FAILED, a
confirmed isolation failure; never probing, which is the gate working) is live at the listed severity, the engine runs
the PHONE-RUNBOOK HOLD_ON statement through an injected executor. The statement returns the rows it held, so an empty
result is a proven failure (no policy row: HOLD_INSERT is a person's step), and the read-back must show the hold. It
audits the decision and opens its own P0 (ONCALL_AUTO_HOLD_ENGAGED, or ONCALL_AUTO_HOLD_FAILED). It engages at most once
per triggering incident, so a person who lifts the hold is not overruled by the same incident. It never lifts a hold.

Off unless RAFII_ONCALL_AUTO_HOLD_ENABLED is exactly 'true' AND the integration passes an executor (engine.stage). The
statements are the runbook's own blocks (a test asserts they are identical). A database hold is rewound by a restore;
the Discord-paused build is the stop that does not live in the database (PHONE-RUNBOOK.md, lever 2).
"""
import re
from pathlib import Path

RUNBOOK = Path(__file__).resolve().parents[3] / 'docs' / 'ops' / 'PHONE-RUNBOOK.md'
HOLD_ON = "UPDATE public.pr_discord_rate_state SET manual_hold = true WHERE kind = 'policy' RETURNING kind, manual_hold;"
HOLD_READBACK = """SELECT count(*) AS policy_rows,
       count(*) FILTER (WHERE manual_hold) AS held,
       (SELECT round(extract(epoch FROM now() - reserved_at)) FROM public.pr_discord_request_admissions
         ORDER BY request_seq DESC LIMIT 1) AS seconds_since_last_request
FROM public.pr_discord_rate_state WHERE kind = 'policy';"""


def runbook_block(label, path=RUNBOOK):
    """The SQL under '-- H07:<label>' in the runbook, without the label line."""
    text = Path(path).read_text()
    match = re.search(r'```sql\n-- H07:%s[^\n]*\n(.*?)\n```' % re.escape(label), text, re.S)
    return match.group(1).strip() if match else None


class AutoHold:
    def __init__(self, policy, executor):
        """executor(sql) runs one statement on the Discord coordinator's database and returns a list of row dicts."""
        self.policy, self.executor = policy, executor
        self.armed = executor is not None and bool(policy['autoHold']['rules'])

    def triggers(self, incidents):
        rules, severity = set(self.policy['autoHold']['rules']), self.policy['autoHold']['severity']
        return [i for i in incidents if i['rule'] in rules and i['severity'] == severity and i['state'] != 'resolved']

    def readback(self):
        rows = self.executor(HOLD_READBACK) or [{}]
        row = rows[0] if isinstance(rows[0], dict) else {}
        return {'policyRows': int(row.get('policy_rows') or 0), 'held': int(row.get('held') or 0)}

    def consider(self, engine, now):
        """Engage the hold for new triggering incidents; return the engine's own alerts about it."""
        from .engine import meta_alert
        if not self.armed:
            return []
        fresh = [i for i in self.triggers(engine.store.live()) if not engine.store.once_exists('autohold:%s' % i['id'])]
        if not fresh:
            return []
        rules = sorted({i['rule'] for i in fresh})
        try:
            before = self.readback()
            held_rows = self.executor(HOLD_ON) if not before['held'] else [{'manual_hold': True}]
            after = self.readback()
        except Exception:
            for incident in fresh:
                engine._event('auto_hold_failed', now, incident, reason='executor_error')
            return [meta_alert('ONCALL_AUTO_HOLD_FAILED', 'page', 'The automatic hold could not be set (database error) for %s. '
                               'Set it by hand: PHONE-RUNBOOK HOLD_ON.' % ', '.join(rules), rules=rules, reason='executor_error')]
        if not held_rows or after['policyRows'] == 0 or not after['held']:
            for incident in fresh:
                engine._event('auto_hold_failed', now, incident, policyRows=after['policyRows'], held=after['held'])
            return [meta_alert('ONCALL_AUTO_HOLD_FAILED', 'page', 'The automatic hold did not take (policy_rows %d, held %d) for %s. '
                               'Use PHONE-RUNBOOK HOLD_INSERT.' % (after['policyRows'], after['held'], ', '.join(rules)),
                               rules=rules, policyRows=after['policyRows'], held=after['held'])]
        for incident in fresh:
            engine._event('auto_hold_engaged', now, incident, once='autohold:%s' % incident['id'], alreadyHeld=bool(before['held']),
                          policyRows=after['policyRows'])
        return [meta_alert('ONCALL_AUTO_HOLD_ENGAGED', 'page', 'The automatic hold is ON because of %s: every Discord request is '
                           'refused until a person lifts it (Release Captain, PHONE-RUNBOOK HOLD_OFF). Approvals lapse after '
                           'about an hour.' % ', '.join(rules), rules=rules, alreadyHeld=bool(before['held']))]
