"""Send-level and same-server sender-name scenarios for the Q-05 local harness (sender-name builds only).

Run by tests/q05_backend.py AFTER the probe, against the same real application, PostgreSQL database and mock
Discord (no real Discord, synthetic data only). Every post is reviewed and approved through the app
(p2_review / p2_approve), every name or nickname is changed through the sender-name service, and every send goes
through the real worker (PostgresWorker over HostedSocial, the production wiring) with two worker instances
released together, as two cron invocations would run.

  name_pollution     A and B approve one post each under their own saved webhook names, then both rename their
                     webhooks; dispatched concurrently, each webhook gets exactly one execute carrying exactly the
                     name frozen at approval (never the other workspace's name, never the later rename).
  switch_off         with the master switch off, a post approved under a custom name is HELD with nothing sent
                     (never stripped and sent under the webhook's own name); a post approved without a name still
                     sends; switched back on, the held post is not resent on its own.
  nickname_authority one bot nickname per Discord server: with two live installations of the same server neither
                     workspace may write it; a sole installation may; a second installation makes the first one
                     read-only again, and the other workspace sees only the boolean reason
                     `nickname_authority_other_workspace`. Both directions, plus three concurrent orders: the
                     competing installation commits after the other's read, during its Discord reads, and between
                     its preflight and the final write guard. A refusal sends no PATCH, changes no state of the
                     other workspace and writes no sender-name audit row.
  nickname_hold      a bot post approved under the observed nickname is HELD (`discord_bot_nickname_changed`)
                     with nothing sent when a server admin renamed the bot in Discord after the approval; an
                     unchanged one sends.

Each scenario returns {"ok": bool, "checks": {name: bool}, "detail": {...}}: counts and booleans only, no ids,
tokens or names of either workspace.
"""
import copy
import json
import os
import threading
import time
from datetime import datetime, timezone
from unittest.mock import patch

SETTLED = ('verified', 'held', 'uncertain', 'failed', 'canceled')
ENV_NAMES = 'POSTRIFF_DISCORD_SENDER_NAMES_ENABLED'
AUTHORITY = 'nickname_authority_other_workspace'
RENAMED = {'A': 'Q05 Alpha Renamed', 'B': 'Q05 Beta Renamed'}
NICKS = {'A': 'Q05 Alpha Bot', 'B': 'Q05 Beta Bot'}
ADMIN_RENAME = 'Renamed by a server admin'


def _refusal(call):
    """(status, code, reason codes) of an AlphaError the call raised, or (200, None, []) when it succeeded."""
    from postriff_alpha.domain import AlphaError
    try:
        call()
    except AlphaError as error:
        fields = getattr(error, 'public_fields', None) or {}
        reasons = [r.get('code') for r in fields.get('reasons') or [] if isinstance(r, dict)]
        return error.status, error.code, reasons
    return 200, None, []


class Scenarios:
    def __init__(self, backend):
        self.b = backend
        self.service = backend.service
        self.oauth = backend.service.oauth
        self.dc = self.oauth.discord_connections
        self.wire = backend.wire
        self.c = backend.constants
        self.t = backend.tenants
        self.seq = 0
        # every scenario post is scheduled one minute after the (frozen) service clock; dispatch waits for it
        self.at = backend.now + 60

    # ------------------------------------------------------------------------------------------------ helpers
    def db_now(self):
        with self.b.connect() as db:
            return float(db.execute("SELECT extract(epoch from clock_timestamp())").fetchone()[0])

    def reset_throttles(self):
        """The probe has just spent the sender-name throttles of both workspaces; the scenarios model a later
        session (the fixed 10-minute windows have passed)."""
        with self.b.connect() as db:
            db.execute("DELETE FROM public.pr_auth_throttle")

    def state(self, key):
        with self.b.connect() as db:
            return db.execute("SELECT state FROM public.pr_workspaces WHERE id=%s", (self.t[key]['ws'],)).fetchone()[0]

    def job(self, key, job_id):
        return next(j for j in self.state(key)['phase2']['jobs'] if j['id'] == job_id)

    def channel(self, key, conn):
        return next(c for c in self.state(key)['phase2']['channels'] if c['id'] == conn)

    def sender_audit(self, key):
        with self.b.connect() as db:
            rows = db.execute("SELECT kind FROM public.pr_audit_events WHERE workspace_id=%s AND kind LIKE 'discord.sender_name%%'",
                              (self.t[key]['ws'],)).fetchall()
        return len(rows)

    def profile(self, key, conn):
        t = self.t[key]
        return self.dc.sender_profile(t['ws'], t['token'], conn)

    def save(self, key, conn, body):
        t = self.t[key]
        return _refusal(lambda: self.dc.set_sender_name(t['ws'], t['token'], conn, body))

    def install(self, key):
        """The bot installed again in the shared server, through the app's OAuth flow. A server's installation card
        is stable per workspace, so this is the reconnect of the existing (disconnected) card: a live installation
        row again, same connection id, new authorization generation."""
        from urllib.parse import parse_qs, urlsplit
        t, guild = self.t[key], self.c['GUILD']
        started = self.oauth.start(t['ws'], t['token'], 'discord', 'publish',
                                   {'discordPurpose': 'installation', 'identityConnectionId': t['identity'],
                                    'guildId': guild, 'connectionId': t['conn']})
        state = parse_qs(urlsplit(started['authorizeUrl']).query)['state'][0]
        return self.oauth.complete(t['ws'], t['token'], 'discord', state, 'install-' + guild)['connectionId']

    def disconnect(self, key, conn):
        t = self.t[key]
        self.oauth.disconnect(t['ws'], t['token'], conn)

    def post(self, key, conn, channel_id, text):
        """Review and approve one post through the app; returns (job id, manifest)."""
        t = self.t[key]
        ws, token = t['ws'], t['token']
        self.seq += 1
        variant = copy.deepcopy(self.b.variant_template)
        variant['id'], variant['text'] = f'q05-scenario-{self.seq}', text
        with self.b.connect() as db:
            state = db.execute("SELECT state FROM public.pr_workspaces WHERE id=%s FOR UPDATE", (ws,)).fetchone()[0]
            state['variants'].append(variant)
            db.execute("UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s",
                       (json.dumps(state), ws))
        snap = self.service.repository.get(ws, token)
        snap = self.service.repository.mutate(ws, token, snap['revision'], 'p2_review', {
            'variantId': variant['id'], 'channelId': conn,
            'destinationId': self.b.dauth.destination_id(ws, conn, self.c['GUILD'], channel_id),
            'localTime': datetime.fromtimestamp(self.at, timezone.utc).strftime('%Y-%m-%dT%H:%M'),
            'timeZone': 'UTC', 'acknowledgedWarnings': []})
        review = snap['state']['phase2']['reviews'][-1]
        self.service.repository.mutate(ws, token, snap['revision'], 'p2_approve',
                                       {'reviewId': review['id'], 'digest': review['digest'], 'confirmed': True})
        state = self.state(key)            # the approval links the review to its job
        job_id = next(r for r in state['phase2']['reviews'] if r['id'] == review['id'])['jobId']
        job = next(j for j in state['phase2']['jobs'] if j['id'] == job_id)
        return job['id'], job.get('manifest') or {}

    def dispatch(self, jobs, *, lanes=2, timeout=120):
        """`lanes` real workers (separate HostedSocial instances, as separate processes would have) released
        together, each stepping the Discord lane until every listed (key, job id) is settled."""
        from postriff_phase2.hosted_social import HostedSocial
        from postriff_phase2.hosted_worker import PostgresWorker
        while self.db_now() < self.at + 1:
            time.sleep(1)
        workers = [PostgresWorker(self.b.connect, social=HostedSocial(self.oauth, {'discord': self.b.provider}),
                                  worker_id=f'q05-lane-{n}', discord_workers=True) for n in range(lanes)]
        start, errors, deadline = threading.Barrier(lanes, timeout=60), [], time.monotonic() + timeout

        def settled():
            return all(self.job(key, job_id)['state'] in SETTLED for key, job_id in jobs)

        def lane(worker):
            try:
                start.wait()
                while time.monotonic() < deadline:
                    if not worker.step(discord_only=True):
                        if settled():
                            return
                        time.sleep(.2)
            except BaseException as error:       # reported, never raised past the scenario
                errors.append(type(error).__name__ + ': ' + str(error)[:160])

        # Billing is not under test here (the target's own lane tests patch it the same way).
        with patch('postriff_phase2.billing.require_publishing', return_value=None):
            threads = [threading.Thread(target=lane, args=(w,), name=f'q05-lane-{n}') for n, w in enumerate(workers)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout + 60)
        return errors

    @staticmethod
    def _held(job, words):
        events = job.get('events') or []
        last = events[-1] if events else {}
        return (job.get('state') == 'held' and words in str(last.get('message', ''))
                and not job.get('discordDispatchIntents') and 'providerReference' not in job)

    def _foreign(self, value, key):
        """Does a response of workspace `key` carry anything of the OTHER workspace (ids or Rafii-side names)?"""
        other = self.t['B' if key == 'A' else 'A']
        text = json.dumps(value)
        markers = [other['ws'], other['conn'], other.get('webhook'), other.get('identity'),
                   *other.get('extra_conns', [])]
        return any(m and m in text for m in markers) or any(
            n in text for n in (self.b.sender_names['B' if key == 'A' else 'A'], RENAMED['B' if key == 'A' else 'A']))

    # ------------------------------------------------------------------------------------------- scenarios
    def name_pollution(self):
        checks, detail = {}, {}
        texts, jobs = {}, {}
        # each workspace's CURRENT saved webhook name (the probe saved and restored it; the setup gave them distinct
        # names): what a review must freeze now
        names = {k: self.channel(k, self.t[k]['webhook']).get('discordSenderName') for k in ('A', 'B')}
        checks['distinct_saved_names'] = all(isinstance(n, str) and n for n in names.values()) and names['A'] != names['B']
        for key in ('A', 'B'):
            t = self.t[key]
            texts[key] = f'Q05 name-pollution post {key}'
            jobs[key], manifest = self.post(key, t['webhook'], t['hook_channel'], texts[key])
            checks[f'frozen_{key}'] = manifest.get('discordSenderName') == names[key]
        for key in ('A', 'B'):      # renamed after approval: queued posts keep the approved name
            prof = self.profile(key, self.t[key]['webhook'])
            status, _, _ = self.save(key, self.t[key]['webhook'],
                                     {'name': RENAMED[key], 'fingerprint': prof['fingerprint'], 'confirmed': True})
            checks[f'renamed_after_approval_{key}'] = status == 200
        errors = self.dispatch([(k, jobs[k]) for k in ('A', 'B')])
        detail['workerErrors'] = errors
        every = set(names.values()) | set(RENAMED.values())
        executes = {k: [e for e in self.wire.sent if texts[k] in (e['content'] or '')] for k in ('A', 'B')}
        for key in ('A', 'B'):
            mine = executes[key]
            hook = self.wire.hooks[self.t[key]['hook_id']]
            checks[f'one_execute_{key}'] = len(mine) == 1 and mine[0]['hook'] == self.t[key]['hook_id']
            checks[f'own_username_{key}'] = bool(mine) and mine[0]['username'] == names[key]
            checks[f'no_other_name_{key}'] = bool(mine) and not any(
                n in json.dumps(mine[0]) for n in every - {names[key]})
            checks[f'author_{key}'] = bool(mine) and hook['messages'][mine[0]['message']]['author']['username'] == names[key]
            checks[f'verified_{key}'] = self.job(key, jobs[key])['state'] == 'verified'
        checks['workers_clean'] = not errors
        detail['lanesUsed'] = sorted({e['thread'] for k in executes for e in executes[k]})
        return checks, detail

    def switch_off(self):
        checks, detail = {}, {}
        b = self.t['B']
        prof = self.profile('B', b['webhook'])          # B clears its name (contract "clear"): an unnamed post
        status, _, _ = self.save('B', b['webhook'], {'reset': True, 'fingerprint': prof['fingerprint'], 'confirmed': True})
        checks['cleared_B'] = status == 200
        texts = {k: f'Q05 switch-off post {k}' for k in ('A', 'B')}
        ja, ma = self.post('A', self.t['A']['webhook'], self.t['A']['hook_channel'], texts['A'])
        jb, mb = self.post('B', b['webhook'], b['hook_channel'], texts['B'])
        checks['named_A'] = ma.get('discordSenderName') == RENAMED['A']
        checks['unnamed_B'] = 'discordSenderName' not in mb
        os.environ[ENV_NAMES] = 'false'
        try:
            errors = self.dispatch([('A', ja), ('B', jb)])
        finally:
            os.environ[ENV_NAMES] = 'true'
        sent_a = [e for e in self.wire.sent if texts['A'] in (e['content'] or '')]
        sent_b = [e for e in self.wire.sent if texts['B'] in (e['content'] or '')]
        checks['held_named_A'] = self._held(self.job('A', ja), 'switched off')
        checks['nothing_sent_A'] = sent_a == []
        checks['unnamed_sent_B'] = (len(sent_b) == 1 and 'username' not in sent_b[0]['keys']
                                    and self.job('B', jb)['state'] == 'verified')
        before = len(self.wire.sent)
        errors += self.dispatch([('A', ja)], timeout=20)       # switched back on: never resent on its own
        checks['still_held_A'] = self.job('A', ja)['state'] == 'held'
        checks['no_resend'] = len(self.wire.sent) == before and not [e for e in self.wire.sent if texts['A'] in (e['content'] or '')]
        checks['workers_clean'] = not errors
        detail['workerErrors'] = errors
        return checks, detail

    def nickname_authority(self, hold):
        """Both directions and three concurrent orders; `hold` runs while A is the server's sole installation."""
        checks, detail = {}, {}
        guild = self.c['GUILD']
        a, b = self.t['A'], self.t['B']
        conns = {'A': a['conn'], 'B': b['conn']}

        def blocked_view(key):
            prof = self.profile(key, conns[key])
            codes = [r.get('code') for r in prof.get('unavailable') or []]
            return prof.get('editable') is False and AUTHORITY in codes and not self._foreign(prof, key)

        def refused(key, holder, label):
            """`key` (a second live installation) cannot change the nickname `holder` set: 409 with only the boolean
            reason, no PATCH, the holder's channel and the shared nickname unchanged, no audit row for `key`."""
            fields = ('discordSenderName', 'discordSenderRevision', 'discordBotNickname', 'discordSenderEdit')
            before_holder = {f: self.channel(holder, conns[holder]).get(f) for f in fields}
            before_nick, before_patches, before_audit = self.wire.nick.get(guild), len(self.wire.patches), self.sender_audit(key)
            prof = self.profile(key, conns[key])
            status, code, reasons = self.save(key, conns[key], {'name': NICKS[key], 'fingerprint': prof['fingerprint'],
                                                                'confirmed': True, 'sharedServerConfirmed': True})
            checks[f'{label}_refused'] = (status, code, reasons) == (409, 'discord_sender_name_unavailable', [AUTHORITY])
            checks[f'{label}_no_patch'] = len(self.wire.patches) == before_patches and self.wire.nick.get(guild) == before_nick
            checks[f'{label}_holder_unchanged'] = {f: self.channel(holder, conns[holder]).get(f) for f in fields} == before_holder
            checks[f'{label}_no_audit'] = self.sender_audit(key) == before_audit
            checks[f'{label}_boolean_only'] = blocked_view(key)

        def sole_save(key, label):
            prof = self.profile(key, conns[key])
            checks[f'{label}_editable'] = prof.get('editable') is True
            before = len(self.wire.patches)
            status, _, _ = self.save(key, conns[key], {'name': NICKS[key], 'fingerprint': prof['fingerprint'],
                                                       'confirmed': True, 'sharedServerConfirmed': True})
            reason = self.wire.patches[-1][2] if len(self.wire.patches) == before + 1 else None
            checks[f'{label}_saved'] = status == 200 and self.wire.nick.get(guild) == NICKS[key]
            checks[f'{label}_one_patch_with_opaque_reason'] = bool(reason) and not any(
                m in reason for m in (a['ws'], b['ws'], NICKS['A'], NICKS['B']))

        # both installed the server at setup: neither may write
        checks['initially_both_blocked'] = blocked_view('A') and blocked_view('B')
        # A holds: B's installation removed, A writes, B installs again and is refused
        self.disconnect('B', conns['B'])
        sole_save('A', 'A_sole')
        self.hold_result = hold()                    # while A is the only installation and has observed its nickname
        conns['B'] = self.install('B')
        b.setdefault('extra_conns', []).append(conns['B'])
        refused('B', 'A', 'B_after_A')
        checks['A_now_blocked_too'] = blocked_view('A')
        # B holds: A's installation removed, B writes, A installs again and is refused
        self.disconnect('A', conns['A'])
        sole_save('B', 'B_sole')
        conns['A'] = self.install('A')
        a.setdefault('extra_conns', []).append(conns['A'])
        refused('A', 'B', 'A_after_B')

        def concurrent(label, arm):
            """B is the sole installation again; a competing installation of A commits at the point `arm` picks."""
            self.disconnect('A', conns['A'])
            prof = self.profile('B', conns['B'])
            before_nick, before_patches = self.wire.nick.get(guild), len(self.wire.patches)
            fired = arm()
            status, code, reasons = self.save('B', conns['B'], {'name': 'Q05 Beta Race', 'fingerprint': prof['fingerprint'],
                                                                'confirmed': True, 'sharedServerConfirmed': True})
            checks[f'{label}_installed_in_between'] = bool(fired)
            checks[f'{label}_refused'] = status == 409 and code in ('discord_sender_name_unavailable', 'discord_sender_name_required')
            checks[f'{label}_no_patch'] = len(self.wire.patches) == before_patches and self.wire.nick.get(guild) == before_nick
            detail[label] = {'status': status, 'code': code, 'reasons': reasons}

        def after_read():                          # B read the form, then A's installation committed
            conns['A'] = self.install('A')
            a['extra_conns'].append(conns['A'])
            return True

        concurrent('race_after_read', after_read)

        def during_reads():                        # A's installation commits while B's save reads Discord
            fired = []
            bot_member = f"/guilds/{guild}/members/{self.c['BOT']}"

            def hook(method, path):
                if method != 'GET' or path != bot_member:
                    return False
                conns['A'] = self.install('A')
                a['extra_conns'].append(conns['A'])
                fired.append(True)
                return True
            self.wire.on_request = hook
            return fired

        concurrent('race_during_reads', during_reads)
        self.wire.on_request = None

        def before_guard():                        # A's installation commits between B's preflight and the write guard
            from postriff_phase2.discord import sender_names
            original, fired = sender_names.SenderNames.write_guard, []

            def guard(this, stamp, claim_id):
                if not fired:
                    conns['A'] = self.install('A')
                    a['extra_conns'].append(conns['A'])
                    fired.append(True)
                return original(this, stamp, claim_id)
            self._restore_guard = (sender_names.SenderNames, original)
            sender_names.SenderNames.write_guard = guard
            return fired

        try:
            concurrent('race_before_write_guard', before_guard)
        finally:
            cls, original = getattr(self, '_restore_guard', (None, None))
            if cls is not None:
                cls.write_guard = original
        return checks, detail

    def nickname_hold(self):
        """A is the server's sole installation and has observed (written) its nickname."""
        checks = {}
        a, guild = self.t['A'], self.c['GUILD']
        texts = {n: f'Q05 nickname-hold post {n}' for n in (1, 2)}
        j1, m1 = self.post('A', a['conn'], self.c['FIRST'], texts[1])
        checks['frozen_1'] = m1.get('discordBotNickname') == NICKS['A']
        errors = self.dispatch([('A', j1)])
        checks['unchanged_nickname_sends'] = (self.job('A', j1)['state'] == 'verified'
                                              and len([m for m in self.wire.bot_sent if texts[1] in (m['content'] or '')]) == 1)
        j2, m2 = self.post('A', a['conn'], self.c['FIRST'], texts[2])
        checks['frozen_2'] = m2.get('discordBotNickname') == NICKS['A']
        with self.wire.q05_lock:
            self.wire.nick[guild] = ADMIN_RENAME          # a server admin renames the bot in Discord
        errors += self.dispatch([('A', j2)])
        checks['renamed_nickname_holds'] = self._held(self.job('A', j2), 'no longer the one this post was approved under')
        checks['nothing_sent'] = not [m for m in self.wire.bot_sent if texts[2] in (m['content'] or '')]
        checks['workers_clean'] = not errors
        with self.wire.q05_lock:
            self.wire.nick[guild] = NICKS['A']            # the admin puts it back (the authority checks follow)
        return {'ok': all(checks.values()), 'checks': checks, 'detail': {'workerErrors': errors}}


def run_scenarios(backend):
    """All scenarios, in order (each one starts from what the previous left). Never raises."""
    s = Scenarios(backend)
    out = {}
    for name, call in (('name_pollution', s.name_pollution), ('switch_off', s.switch_off),
                       ('nickname_authority', lambda: s.nickname_authority(s.nickname_hold))):
        s.reset_throttles()
        try:
            checks, detail = call()
            out[name] = {'ok': bool(checks) and all(checks.values()), 'checks': checks, 'detail': detail}
        except Exception as error:      # a scenario that cannot complete is a failure, reported by type only
            out[name] = {'ok': False, 'checks': {}, 'detail': {'error': type(error).__name__ + ': ' + str(error)[:200]}}
    out['nickname_hold'] = getattr(s, 'hold_result', None) or {'ok': False, 'checks': {}, 'detail': {'error': 'did not run'}}
    return out
