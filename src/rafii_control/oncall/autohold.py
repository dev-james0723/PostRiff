"""Option D: the compensating automatic operator hold (docs/ops/H07-OPTIONS.md, section D).

When an incident of a listed rule is live at the listed severity (page), the engine runs the PHONE-RUNBOOK HOLD_ON
statement through an injected executor, reads the hold back, audits the decision and opens its own P0
(ONCALL_AUTO_HOLD_ENGAGED, or ONCALL_AUTO_HOLD_FAILED when the read-back does not show the hold). It engages at most once
per triggering incident, so a person who lifts the hold is not overruled by the same incident. It never lifts a hold.

Off unless RAFII_ONCALL_AUTO_HOLD_ENABLED is exactly 'true' AND the integration passes an executor (engine.stage). The
statements are the runbook's own blocks (a test asserts they are identical). A hold longer than about an hour lets
approvals lapse, so the rules exclude backlog, silent-halt and configuration alerts.
"""
import re
from pathlib import Path

RUNBOOK = Path(__file__).resolve().parents[3] / 'docs' / 'ops' / 'PHONE-RUNBOOK.md'
HOLD_ON = "UPDATE public.pr_discord_rate_state SET manual_hold = true WHERE kind = 'policy';"
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
            if not before['held']:
                self.executor(HOLD_ON)
            after = self.readback()
        except Exception:
            for incident in fresh:
                engine._event('auto_hold_failed', now, incident, reason='executor_error')
            return [meta_alert('ONCALL_AUTO_HOLD_FAILED', 'page', 'The automatic hold could not be set (database error) for %s. '
                               'Set it by hand: PHONE-RUNBOOK HOLD_ON.' % ', '.join(rules), rules=rules, reason='executor_error')]
        if after['policyRows'] == 0 or not after['held']:
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
