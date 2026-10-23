#!/usr/bin/env python3
"""Reconcile Rafii's Discord posts after a database point-in-time restore. Read-only against Discord; fail-safe.

Why: a restore rewinds the database. A post Discord already shows, sent after the restore point, looks unsent again,
and while its approval is still valid the worker would create it a second time: the duplicate protection (intents,
leases, the request coordinator's admissions) lives in the database and was rewound with it (docs/ops/
RESTORE-HAZARD-DRILL.md). Run this with the operator hold set in the RESTORED database, before any worker sends.

What it does (`reconcile`):
  1. Reads every Discord job of the restored database that the worker could still send or has not resolved: not
     verified/failed/canceled, no provider reference, no receipt carrying a message id.
  2. Reads, through the same Discord API shapes the product uses for read-back (`GET /users/@me` for the bot,
     `GET /channels/{id}/messages?limit=50` for channel history, paged with `before=`, and
     `GET /channels/{id}/messages/{id}` for one message), each destination channel back to the restore point.
     Only GET requests exist in this tool; it never creates, edits or deletes anything in Discord.
  3. Matches with what the product itself knows: the channel, the author (the bot of the frozen target, with
     author.bot true), the content's SHA-256 equal to the approved text's (whose wire digest must equal the frozen
     manifest's wireDigest), no mentions or attachments, never edited, created at or after the restore point.
  4. Decides per job (the rules below), then with --apply writes, under each workspace row lock and revision fence:
     - matched -> the receipt in the shape of the product's own record_receipt, providerReference, state
       'uncertain', the product's adoption event, nextAt now. The product's worker then verifies it by read-back
       (HostedSocial.reconcile_discord, PostgresWorker.complete: state 'verified', verification 'provider_lookup')
       once the hold is lifted. No create is ever made for it.
     - ambiguous -> state 'held' with a reason, for human review. Never sent automatically.
     - everything else is left exactly as it is (posts that could not have been sent in the rewound interval are
       then sent once by the product; expired approvals are held by the product itself).

Rules (fail-safe: when unsure it holds, never sends):
  - exactly one exact candidate, and that message is a candidate for no other job and owned by no job -> matched
  - several exact candidates, a candidate shared by several jobs, a near match (same channel and bot author, content
    equal after whitespace/case folding, or with mentions/attachments, or any edited bot message in the window), a
    channel that cannot be read, history that does not reach back to the restore point within --max-pages, a bot
    identity that differs from the frozen target, or a manifest whose text does not match its frozen wire digest
    -> ambiguous (held)
  - no candidate, and the post could have been sent inside the rewound interval [restore point, interval end] while
    its approval was valid -> ambiguous (held): a moderator may have deleted it; Discord cannot show a deleted message
  - no candidate, and the post could not have been sent inside the interval -> not_sent (left; the product sends it
    once if its approval is still valid, and holds it if the approval expired)
  - a job that already has a sealed intent (claimed/submitting/uncertain without a message id): the product never
    resends it; a unique exact match only attaches the message id so the product can verify it, anything else
    leaves it as it is

Idempotent: a second run finds matched jobs out of scope (they carry a provider reference) and ambiguous jobs already
held with the same marker, and writes nothing. --dry-run prints counts only (no ids, no text).

Subcommands: `status` and `hold` (set the operator hold and verify it took effect: an UPDATE that matches no policy
row means NO hold; --create-missing inserts the policy row already held). Lifting the hold needs --lift --confirm.

Live use (`reconcile --live`) needs the bot token in an environment variable (never printed) and the restored
database's connection string in another; agents must not run it against Production without the owner's approval.
"""
import argparse
import copy
import hashlib
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone

VERSION = 1
MARKER = 'restoreReconciliation'
EXECUTION = 'restore-reconciliation'
API = 'https://discord.com/api/v10'
PAGE = 50
DISCORD_EPOCH_MS = 1420070400000
TERMINAL = ('verified', 'failed', 'canceled')
IN_FLIGHT = ('processing', 'provider_accepted', 'published', 'uncertain')  # store.IN_FLIGHT minus 'submitting'
ADOPTED = 'Restore reconciliation: Discord receipt from the rewound interval retained; reconcile the original channel without resubmission'
HELD = 'Restore reconciliation could not prove whether this post is already in Discord (%s); held for human review, never resent automatically'
HELD_ACTION = 'Review the destination channel after the database restore; do not approve this text again until a person confirms it is not already posted'
DECISIONS = ('matched', 'resolved', 'ambiguous', 'not_sent', 'left')


class ReconcileError(RuntimeError):
    pass


def digest(value):
    """The product's canonical JSON digest (discord/authorization.digest)."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def text_digest(text):
    return hashlib.sha256((text if isinstance(text, str) else '').encode()).hexdigest()


def snowflake(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9]{5,25}', value) is not None


def created_at(message):
    """Creation time from the message id (a snowflake): it cannot be edited, unlike any other field."""
    return ((int(message['id']) >> 22) + DISCORD_EPOCH_MS) / 1000.0


def epoch(value):
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if re.fullmatch(r'[0-9]+(\.[0-9]+)?', text):
        return float(text)
    parsed = datetime.fromisoformat(text.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ReconcileError('give times with a time zone (for example 2026-10-23T05:00:00+00:00)')
    return parsed.timestamp()


def _normalized(text):
    return ' '.join((text or '').split()).casefold()


def _number(value, default=0.0):
    return float(value) if type(value) in (int, float) else default


# --- the jobs the restored database holds -------------------------------------------------------------------------

def job_view(workspace, job):
    """What the tool needs from one Discord job, or None when it is not a Discord job."""
    manifest = job.get('manifest') or {}
    if manifest.get('platform') != 'Discord':
        return None
    frozen = manifest.get('discord') or {}
    target = frozen.get('target') or {}
    text = (manifest.get('payload') or {}).get('text')
    webhook = manifest.get('senderKind') == 'webhook' or target.get('senderKind') == 'webhook'
    reply = manifest.get('operation') == 'discord.reply'
    media = bool(manifest.get('media'))
    # The approved wire for a text-only bot post (discord/authorization.wire_content); anything else is not matched.
    wire_ok = (not webhook and not reply and not media and isinstance(text, str)
               and digest({'content': text, 'allowed_mentions': {'parse': []}, 'files': []}) == frozen.get('wireDigest'))
    receipts = [r for r in job.get('discordReceipts') or [] if isinstance(r, dict)]
    intents = [i for i in job.get('discordDispatchIntents') or [] if isinstance(i, dict)]
    return {
        'workspaceId': workspace, 'jobId': job.get('id'), 'state': job.get('state'),
        'channelId': target.get('channelId'), 'guildId': target.get('guildId'), 'botUserId': target.get('botUserId'),
        'applicationId': target.get('applicationId'), 'textDigest': text_digest(text), 'normalized': _normalized(text),
        'supported': wire_ok, 'kind': 'webhook' if webhook else 'reply' if reply else 'media' if media else 'text',
        'nextAt': _number(job.get('nextAt')), 'leaseUntil': _number(job.get('leaseUntil')),
        'expiresAt': _number(manifest.get('expiresAt'), float('inf')),
        'intentTimes': sorted(_number(i.get('at')) for i in intents), 'reference': job.get('providerReference'),
        'receiptReferences': [r['reference'] for r in receipts if isinstance(r.get('reference'), str)],
        'marker': job.get(MARKER) if isinstance(job.get(MARKER), dict) else None,
        'fingerprint': fingerprint(job),
    }


def fingerprint(job):
    """The fields a decision depends on; the writer refuses to act when any changed after the read."""
    return digest({'state': job.get('state'), 'nextAt': job.get('nextAt'), 'leaseOwner': job.get('leaseOwner'),
                   'leaseUntil': job.get('leaseUntil'), 'reference': job.get('providerReference'),
                   'intents': len(job.get('discordDispatchIntents') or []),
                   'receipts': len(job.get('discordReceipts') or []), 'approvalDigest': job.get('approvalDigest'),
                   'marker': (job.get(MARKER) or {}).get('decision') if isinstance(job.get(MARKER), dict) else None})


def in_scope(view):
    return (view['state'] not in TERMINAL and not view['reference'] and not view['receiptReferences']
            and view['channelId'] is not None)


def load(connection):
    """(views of every Discord job, message ids the database already owns, hold status) from the restored database."""
    with connection.cursor() as cur:
        cur.execute("SELECT id::text, state FROM public.pr_workspaces WHERE state ? 'phase2'")
        rows = cur.fetchall()
    views, owned = [], set()
    for workspace, raw in rows:
        state = json.loads(raw) if isinstance(raw, str) else raw
        for job in (state.get('phase2') or {}).get('jobs') or []:
            view = job_view(workspace, job)
            if view is None:
                continue
            views.append(view)
            for reference in [view['reference'], *view['receiptReferences']]:
                if isinstance(reference, str) and '/' in reference:
                    owned.add(reference.split('/', 1)[1])
    return views, owned, hold_status(connection)


def hold_status(connection):
    with connection.cursor() as cur:
        cur.execute("SELECT count(*), count(*) FILTER (WHERE manual_hold) FROM public.pr_discord_rate_state WHERE kind='policy'")
        rows, held = cur.fetchone()
    return {'policyRows': rows, 'held': rows > 0 and held == rows}


# --- Discord, read-only ---------------------------------------------------------------------------------------------

class DiscordReader:
    """GET-only Discord client in the product's request shapes. Self-paced: it runs while the shared coordinator is
    held (the hold refuses every request), so it waits `pace` seconds between requests, obeys 429 retry hints and
    stops after `max_invalid` 401/403/404 answers, so it cannot spend Discord's invalid-request budget."""

    def __init__(self, transport, token, *, website='https://rafii.example.invalid', max_pages=20, pace=0.25,
                 max_invalid=25, max_retries=5, sleep=time.sleep, monotonic=time.monotonic):
        self.transport, self._token, self.website = transport, token, website
        self.max_pages, self.pace, self.max_invalid, self.max_retries = max_pages, pace, max_invalid, max_retries
        self.sleep, self.monotonic = sleep, monotonic
        self.requests, self.invalid, self.limited = 0, 0, 0
        self._last = None

    def get(self, path):
        if self.invalid >= self.max_invalid:
            raise ReconcileError('stopped: too many invalid Discord answers (%d); nothing more is read' % self.invalid)
        for _ in range(self.max_retries + 1):
            if self._last is not None:
                wait = self._last + self.pace - self.monotonic()
                if wait > 0:
                    self.sleep(wait)
            self._last = self.monotonic()
            self.requests += 1
            response = self.transport('GET', API + path, headers={'Authorization': 'Bot ' + self._token,
                                                                 'User-Agent': 'DiscordBot (%s, 1)' % self.website})
            status = response.get('status')
            if status == 429:
                self.limited += 1
                body = response.get('body') if isinstance(response.get('body'), dict) else {}
                hint = body.get('retry_after', (response.get('headers') or {}).get('retry-after'))
                try:
                    pause = min(60.0, max(0.05, float(hint)))
                except (TypeError, ValueError):
                    pause = 5.0
                self.sleep(pause)
                continue
            if status in (401, 403, 404):
                self.invalid += 1
            return status, response.get('body')
        return 429, None

    def bot_identity(self):
        status, body = self.get('/users/@me')
        if status != 200 or not isinstance(body, dict) or body.get('bot') is not True or not snowflake(str(body.get('id', ''))):
            return None
        return str(body['id'])

    def history(self, channel, since):
        """Messages of `channel` newest first, back to `since` (epoch) or until --max-pages; with readability and
        whether the pages reached back past `since` (complete)."""
        messages, before = [], None
        for _ in range(self.max_pages):
            status, page = self.get('/channels/%s/messages?limit=%d%s' % (channel, PAGE, '&before=' + before if before else ''))
            if status != 200 or not isinstance(page, list) or len(page) > PAGE:
                return {'readable': False, 'complete': False, 'messages': messages, 'status': status}
            page = [m for m in page if isinstance(m, dict) and snowflake(str(m.get('id', '')))]
            messages.extend(page)
            if len(page) < PAGE or (page and created_at(page[-1]) < since):
                return {'readable': True, 'complete': True, 'messages': messages, 'status': status}
            before = page[-1]['id']
        return {'readable': True, 'complete': False, 'messages': messages, 'status': 200}

    def message(self, channel, message_id):
        return self.get('/channels/%s/messages/%s' % (channel, message_id))


def read_channels(reader, views, restore_point, skew):
    """History for every channel an in-scope job targets, reaching back to the earliest bound any of them needs."""
    since = {}
    for view in views:
        if in_scope(view):
            bound = min([restore_point, *view['intentTimes']]) - skew
            since[view['channelId']] = min(bound, since.get(view['channelId'], bound))
    return {channel: reader.history(channel, bound) for channel, bound in sorted(since.items())}


# --- the decision, pure -----------------------------------------------------------------------------------------------

def _exact(view, message, lower):
    author = message.get('author') or {}
    return (message.get('channel_id') == view['channelId'] and author.get('id') == view['botUserId']
            and author.get('bot') is True and text_digest(message.get('content')) == view['textDigest']
            and message.get('mention_everyone') is False and message.get('mentions') == []
            and message.get('mention_roles') == [] and message.get('attachments') == []
            and message.get('edited_timestamp') is None and message.get('type', 0) == 0
            and created_at(message) >= lower)


def _near(view, message, lower):
    author = message.get('author') or {}
    if (message.get('channel_id') != view['channelId'] or author.get('id') != view['botUserId']
            or created_at(message) < lower or _exact(view, message, lower)):
        return False
    return (message.get('edited_timestamp') is not None
            or _normalized(message.get('content')) == view['normalized'])


def could_have_been_sent(view, restore_point, interval_end, skew):
    """Was there a moment inside the rewound interval when the worker could send this post with a valid approval?"""
    due = max(view['nextAt'], view['leaseUntil'])
    return max(due, restore_point) <= min(interval_end, view['expiresAt']) + skew


def plan(views, channels, owned, *, restore_point, interval_end, bot_id, skew=5.0):
    """Decisions for every in-scope job and a count summary. No IO."""
    scoped = [v for v in views if in_scope(v)]
    candidates, near = {}, {}
    for view in scoped:
        lower = min([restore_point, *view['intentTimes']]) - skew
        history = channels.get(view['channelId']) or {'readable': False, 'complete': False, 'messages': []}
        candidates[view['jobId'], view['workspaceId']] = [m for m in history['messages'] if _exact(view, m, lower)]
        near[view['jobId'], view['workspaceId']] = [m for m in history['messages'] if _near(view, m, lower)]
    claimants = {}
    for key, found in candidates.items():
        for message in found:
            claimants.setdefault(message['id'], set()).add(key)
    decisions = []
    for view in scoped:
        key = (view['jobId'], view['workspaceId'])
        history = channels.get(view['channelId']) or {'readable': False, 'complete': False, 'messages': []}
        found, close = candidates[key], near[key]
        # The product never sends these again (a sealed intent, or an in-flight state): reconcile by read-back only.
        sealed = bool(view['intentTimes']) or view['state'] in IN_FLIGHT
        decision = reason = message = None
        # Evidence problems first: each one alone makes "no candidate" meaningless.
        if not view['supported']:
            reason = 'unsupported_kind' if view['kind'] != 'text' else 'manifest_mismatch'
        elif bot_id is None or bot_id != view['botUserId']:
            reason = 'bot_identity_changed'
        elif not history['readable']:
            reason = 'channel_unreadable'
        elif not history['complete']:
            reason = 'history_incomplete'
        elif close:
            reason = 'partial_match'
        elif len(found) > 1:
            reason = 'several_candidates'
        elif len(found) == 1 and len(claimants[found[0]['id']]) > 1:
            reason = 'shared_candidate'
        elif len(found) == 1 and found[0]['id'] in owned:
            reason = 'message_owned_by_another_job'
        elif len(found) == 1:
            decision, message = ('resolved' if sealed else 'matched'), found[0]
        if decision is None and reason is not None:
            # Unsure: a post the product could still send is held. A sealed one is already never resent.
            decision, reason = ('left', 'sealed_' + reason) if sealed else ('ambiguous', reason)
        elif decision is None:
            # Complete, readable history of the channel and no message with this text since the restore point.
            if sealed:
                decision, reason = 'left', 'sealed_no_message'
            elif view['state'] == 'held':
                decision, reason = 'left', ('already_held_' + view['marker']['reason']
                                            if (view['marker'] or {}).get('reason') else 'held_no_message')
            elif could_have_been_sent(view, restore_point, interval_end, skew):
                # It may have been sent and then deleted by a moderator: Discord cannot show that.
                decision, reason = 'ambiguous', 'due_in_interval_not_found'
            elif view['expiresAt'] <= max(view['nextAt'], restore_point):
                decision, reason = 'left', 'approval_expired'  # the product holds it at claim, never sends it late
            else:
                decision, reason = 'not_sent', 'due_after_interval'
        if decision == 'ambiguous' and view['state'] == 'held' and (view['marker'] or {}).get('reason') == reason:
            decision, reason = 'left', 'already_held_' + reason
        decisions.append({'workspaceId': view['workspaceId'], 'jobId': view['jobId'], 'channelId': view['channelId'],
                          'decision': decision, 'reason': reason, 'messageId': message['id'] if message else None,
                          'fingerprint': view['fingerprint'], 'state': view['state']})
    # Bot messages in the window that no job claims: posts approved after the restore point (lost with it), or
    # duplicates already visible next to a post the database owns. Counted for the human review.
    by_text = {}
    for view in views:
        if view['reference'] or view['receiptReferences']:
            by_text.setdefault((view['channelId'], view['textDigest']), set()).update(
                r.split('/', 1)[1] for r in [view['reference'], *view['receiptReferences']] if isinstance(r, str) and '/' in r)
    claimed = set(claimants) | {m['id'] for found in near.values() for m in found}
    orphans = duplicates = 0
    for channel, history in channels.items():
        for message in history['messages']:
            author = message.get('author') or {}
            if (author.get('id') != bot_id or created_at(message) < restore_point - skew or message['id'] in claimed
                    or message['id'] in owned):
                continue
            if by_text.get((channel, text_digest(message.get('content')))):
                duplicates += 1
            else:
                orphans += 1
    summary = {'jobs': len(views), 'inScope': len(scoped), 'channels': len(channels),
               'decisions': {name: sum(d['decision'] == name for d in decisions) for name in DECISIONS},
               'reasons': {}, 'unclaimedBotMessages': orphans, 'duplicatesAlreadyVisible': duplicates}
    for item in decisions:
        summary['reasons'][item['reason']] = summary['reasons'].get(item['reason'], 0) + 1
    return decisions, summary


# --- confirmation by id and the fenced write ---------------------------------------------------------------------------

def confirm(reader, decisions, views):
    """Re-read each matched message by id (the product's own read-back shape) just before writing; a message that
    vanished or changed since the listing turns the decision into ambiguous."""
    lookup = {(v['jobId'], v['workspaceId']): v for v in views}
    for item in decisions:
        if item['decision'] not in ('matched', 'resolved'):
            continue
        view = lookup[item['jobId'], item['workspaceId']]
        status, body = reader.message(item['channelId'], item['messageId'])
        if (status != 200 or not isinstance(body, dict) or body.get('id') != item['messageId']
                or not _exact(view, body, float('-inf'))):
            item.update(decision='ambiguous' if item['decision'] == 'matched' else 'left',
                        reason='changed_before_write' if item['decision'] == 'matched' else 'sealed_intent_changed_before_write')
    return decisions


def _event(job, state, message, at):
    """The product's event shape (PostgresWorker._event), with this tool as the execution."""
    job['state'] = state
    job.setdefault('events', []).append({'at': at, 'state': state, 'message': message, 'execution': EXECUTION})


def _mark(job, item, run, at):
    reference = '%s/%s' % (item['channelId'], item['messageId']) if item.get('messageId') else None
    job[MARKER] = {'version': VERSION, 'runId': run['runId'], 'decision': item['decision'], 'reason': item['reason'],
                   'restorePoint': run['restorePoint'], 'intervalEnd': run['intervalEnd'], 'at': at,
                   **({'reference': reference} if reference else {})}


def mutate(job, item, run, at):
    """Apply one decision to the job dict in place. Returns True when it changed anything."""
    if item['decision'] in ('matched', 'resolved'):
        manifest = job['manifest']
        target = manifest['discord']['target']
        reference = '%s/%s' % (item['channelId'], item['messageId'])
        receipt = {'intentId': None, 'publicationId': job['id'],
                   'authorizationDigest': (job.get('discordAuthorization') or {}).get('digest'),
                   'manifestDigest': digest(manifest), 'at': at, 'late': True, 'state': 'provider_accepted',
                   'deliveryEvidence': 'accepted', 'reference': reference,
                   'url': 'https://discord.com/channels/%s/%s/%s' % (target['guildId'], item['channelId'], item['messageId']),
                   'source': EXECUTION}
        receipt['id'] = digest({k: v for k, v in receipt.items() if k not in ('at', 'late')})
        if any(r.get('id') == receipt['id'] for r in job.get('discordReceipts') or []):
            return False
        job.setdefault('discordReceipts', []).append(receipt)
        job['providerReference'] = reference
        job['leaseOwner'], job['leaseUntil'] = None, 0
        job['nextAt'] = at
        job['nextAction'] = 'Await provider reconciliation; do not resubmit'
        _event(job, 'uncertain', ADOPTED, at)
        _mark(job, item, run, at)
        return True
    if item['decision'] == 'ambiguous':
        _event(job, 'held', HELD % item['reason'], at)
        job['leaseOwner'], job['leaseUntil'] = None, 0
        job['nextAction'] = HELD_ACTION
        _mark(job, item, run, at)
        return True
    return False


def apply(connection_factory, decisions, run):
    """Write the decisions, one workspace transaction at a time: row lock, unchanged-job check, revision fence.
    Returns counts of written, skipped (changed since the read) and unchanged decisions."""
    written = skipped = 0
    by_workspace = {}
    for item in decisions:
        if item['decision'] in ('matched', 'resolved', 'ambiguous'):
            by_workspace.setdefault(item['workspaceId'], []).append(item)
    for workspace, items in sorted(by_workspace.items()):
        with connection_factory() as db, db.cursor() as cur:
            cur.execute('SELECT revision, state FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (workspace,))
            row = cur.fetchone()
            if not row:
                skipped += len(items)
                continue
            revision, raw = row
            state = json.loads(raw) if isinstance(raw, str) else raw
            cur.execute('SELECT extract(epoch from clock_timestamp())::double precision')
            at = cur.fetchone()[0]
            jobs = {job.get('id'): job for job in (state.get('phase2') or {}).get('jobs') or []}
            changed = False
            for item in items:
                job = jobs.get(item['jobId'])
                if job is None or fingerprint(job) != item['fingerprint']:
                    skipped += 1  # someone or something changed it since the read: decide again, never guess
                    continue
                if mutate(job, item, run, at):
                    written += 1
                    changed = True
            if changed:
                cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb, revision=revision+1 WHERE id=%s AND revision=%s',
                            (json.dumps(state), workspace, revision))
                if cur.rowcount != 1:
                    raise ReconcileError('workspace revision changed during the write; nothing was written for it')
    return {'written': written, 'skipped': skipped}


def reconcile(connection_factory, reader, *, restore_point, interval_end, skew=5.0, dry_run=True, run_id=None,
              require_hold=True):
    """The whole run. Returns (summary, decisions). With dry_run nothing is written."""
    started = time.monotonic()
    restore_point, interval_end = epoch(restore_point), epoch(interval_end)
    if interval_end < restore_point:
        raise ReconcileError('the interval end is before the restore point')
    with connection_factory() as db:
        views, owned, hold = load(db)
    if require_hold and not dry_run and not hold['held']:
        raise ReconcileError('the operator hold is not in effect in this database (policy rows %d); set it first '
                             '(`hold --set`) so no worker sends while this runs' % hold['policyRows'])
    bot_id = reader.bot_identity()
    channels = read_channels(reader, views, restore_point, skew)
    decisions, summary = plan(views, channels, owned, restore_point=restore_point, interval_end=interval_end,
                              bot_id=bot_id, skew=skew)
    run = {'runId': run_id or uuid.uuid4().hex, 'restorePoint': restore_point, 'intervalEnd': interval_end}
    if not dry_run:
        decisions = confirm(reader, decisions, views)
        summary['decisions'] = {name: sum(d['decision'] == name for d in decisions) for name in DECISIONS}
        summary['write'] = apply(connection_factory, decisions, run)
    summary.update(mode='dry-run' if dry_run else 'apply', holdInEffect=hold['held'], discordRequests=reader.requests,
                   discordInvalid=reader.invalid, discordRateLimited=reader.limited,
                   seconds=round(time.monotonic() - started, 3))
    return summary, decisions


# --- the operator hold ------------------------------------------------------------------------------------------------

def set_hold(connection, *, application_id=None, create_missing=False):
    """Set manual_hold on every policy row and prove it took effect. An UPDATE that matches no row sets nothing: in
    a database restored to before the coordinator's first request there is no policy row yet, and the first
    request would create it unheld. --create-missing inserts it held (the coordinator then refuses every request)."""
    with connection.cursor() as cur:
        cur.execute("UPDATE public.pr_discord_rate_state SET manual_hold=true, revision=revision+1, "
                    "updated_at=clock_timestamp() WHERE kind='policy' RETURNING scope_key")
        updated = len(cur.fetchall())
        inserted = 0
        if updated == 0 and create_missing:
            if not snowflake(str(application_id or '')):
                raise ReconcileError('--create-missing needs --application-id (the Discord application id)')
            cur.execute("""INSERT INTO public.pr_discord_rate_state(scope_key,kind,limit_count,remaining,window_seconds,
                    reset_at,manual_hold,policy_revision,policy_expires_at)
                VALUES('00:'||encode(sha256(convert_to(%s,'UTF8')),'hex'),'policy',1,0,1,clock_timestamp(),true,
                    'restore-hold',clock_timestamp()) ON CONFLICT(scope_key) DO UPDATE SET manual_hold=true""",
                        (str(application_id),))
            inserted = cur.rowcount
    connection.commit()
    status = hold_status(connection)
    return {'updated': updated, 'inserted': inserted, **status}


def lift_hold(connection):
    with connection.cursor() as cur:
        cur.execute("UPDATE public.pr_discord_rate_state SET manual_hold=false, revision=revision+1, "
                    "updated_at=clock_timestamp() WHERE kind='policy' AND manual_hold RETURNING scope_key")
        lifted = len(cur.fetchall())
    connection.commit()
    return {'lifted': lifted, **hold_status(connection)}


# --- command line -----------------------------------------------------------------------------------------------------

def _connect(args):
    import psycopg
    dsn = args.dsn or os.environ.get(args.dsn_env or '')
    if not dsn:
        raise ReconcileError('give --dsn (local drill) or the name of an environment variable with --dsn-env')
    return lambda: psycopg.connect(dsn, prepare_threshold=None)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('command', choices=('status', 'hold', 'reconcile'))
    parser.add_argument('--dsn', help='connection string of the RESTORED database (local drill only)')
    parser.add_argument('--dsn-env', default='POSTRIFF_RESTORE_DSN', help='environment variable holding it')
    parser.add_argument('--set', action='store_true')
    parser.add_argument('--lift', action='store_true')
    parser.add_argument('--confirm', action='store_true', help='needed with --lift: the Release Captain said so')
    parser.add_argument('--create-missing', action='store_true')
    parser.add_argument('--application-id')
    parser.add_argument('--restore-point')
    parser.add_argument('--interval-end', help='the latest time the old database could have sent anything')
    parser.add_argument('--skew', type=float, default=5.0)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true', default=True)
    mode.add_argument('--apply', action='store_true')
    parser.add_argument('--live', action='store_true', help='read the real Discord API (needs the bot token)')
    parser.add_argument('--bot-token-env', default='POSTRIFF_DISCORD_BOT_TOKEN')
    parser.add_argument('--max-pages', type=int, default=20)
    parser.add_argument('--pace', type=float, default=0.25)
    parser.add_argument('--detail', help='with --apply: write per-job decisions (ids only, no text) to this file')
    args = parser.parse_args(argv)
    factory = _connect(args)
    if args.command == 'status':
        with factory() as db:
            print(json.dumps(hold_status(db)))
        return 0
    if args.command == 'hold':
        if args.set == args.lift:
            raise ReconcileError('give exactly one of --set or --lift')
        with factory() as db:
            if args.set:
                result = set_hold(db, application_id=args.application_id, create_missing=args.create_missing)
            elif not args.confirm:
                raise ReconcileError('lifting the hold needs --confirm (only on the Release Captain\'s word)')
            else:
                result = lift_hold(db)
        print(json.dumps(result))
        return 0 if (result['held'] if args.set else not result['held']) else 3
    if not (args.restore_point and args.interval_end):
        raise ReconcileError('reconcile needs --restore-point and --interval-end')
    if not args.live:
        raise ReconcileError('reconcile reads Discord: pass --live (real API, bot token from --bot-token-env) or use '
                             'the library API with a test transport (scripts/discord_restore_drill.py)')
    token = os.environ.get(args.bot_token_env)
    if not token:
        raise ReconcileError('the bot token environment variable %s is empty' % args.bot_token_env)
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
    from postriff_phase2.providers import http_transport
    reader = DiscordReader(http_transport, token, website=os.environ.get('POSTRIFF_PUBLIC_BASE_URL', 'https://rafii.example.invalid'),
                           max_pages=args.max_pages, pace=args.pace)
    summary, decisions = reconcile(factory, reader, restore_point=args.restore_point, interval_end=args.interval_end,
                                   skew=args.skew, dry_run=not args.apply)
    if args.apply and args.detail:
        descriptor = os.open(args.detail, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, 'w') as out:
            json.dump([{k: d[k] for k in ('workspaceId', 'jobId', 'channelId', 'decision', 'reason', 'messageId')}
                       for d in decisions], out, indent=1)
    print(json.dumps(summary, indent=1, sort_keys=True))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except ReconcileError as error:
        print('discord_restore_reconcile: ' + str(error), file=sys.stderr)
        sys.exit(2)
