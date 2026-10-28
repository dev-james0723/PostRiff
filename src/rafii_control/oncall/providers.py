"""Delivery providers for the on-call engine: the interface, a recording fake for tests and drills, a null provider,
fixed-vocabulary messages and signed acknowledgement tokens.

A real adapter (founder outbox for push and e-mail, PhoneService for calls, or a paging vendor) implements send() and
returns a DeliveryResult. 'accepted' means only that the provider took the message: it proves nothing about a person
reading it. Only an acknowledgement proves that.
"""
import base64
import hashlib
import hmac
import re
from collections import namedtuple
from datetime import datetime
from zoneinfo import ZoneInfo

ACCEPTED, FAILED, UNCONFIGURED, REFUSED = 'accepted', 'failed', 'unconfigured', 'refused'
STATUSES = (ACCEPTED, FAILED, UNCONFIGURED, REFUSED)
NOT_DELIVERED = (FAILED, UNCONFIGURED, REFUSED, 'lost')
ACK_CHANNELS = ('push', 'email', 'phone', 'dashboard')
_REASON = re.compile(r'^[a-z0-9_:.-]{1,80}$')
_TOKEN_CONTEXT = b'rafii.oncall.ack.v1:'

DeliveryResult = namedtuple('DeliveryResult', 'status reference reason')
# kind: page (an escalation step), record (acknowledged / resolved / raised), summary (storm summary).
Message = namedtuple('Message', 'channel person destination kind incident_id priority rule subject body ack_url')


def result(status, reference=None, reason=None):
    """A checked DeliveryResult: a known status, a short reference, a reason code (never provider text)."""
    if status not in STATUSES:
        status, reason = FAILED, 'bad_status'
    reference = reference if isinstance(reference, str) and 0 < len(reference) <= 200 else None
    reason = reason if isinstance(reason, str) and _REASON.match(reason) else None
    return DeliveryResult(status, reference, reason)


class Provider:
    """One channel. send(message) -> DeliveryResult; it must not raise for an ordinary refusal."""
    channel = None

    def send(self, message):
        raise NotImplementedError


class NullProvider(Provider):
    """The default for a channel without an adapter: nothing is sent and the step counts as not delivered."""
    def __init__(self, channel):
        self.channel = channel

    def send(self, message):
        return result(UNCONFIGURED, reason='no_provider')


class FakeProvider(Provider):
    """Records every message. Scriptable: fail_next(n, status), fail_for(person, status), raise_next(n). Proves the
    engine's logic; it delivers nothing to anyone."""
    def __init__(self, channel):
        self.channel = channel
        self.sent = []
        self._next = []
        self._people = {}

    def fail_next(self, count=1, status=FAILED, reason='scripted'):
        self._next.extend([(status, reason)] * count)

    def raise_next(self, count=1):
        self._next.extend([('raise', None)] * count)

    def fail_for(self, person, status=FAILED, reason='scripted'):
        self._people[person] = (status, reason)

    def heal(self, person=None):
        if person is None:
            self._next, self._people = [], {}
        else:
            self._people.pop(person, None)

    def send(self, message):
        self.sent.append(message)
        if self._next:
            status, reason = self._next.pop(0)
            if status == 'raise':
                raise RuntimeError('scripted provider exception')
            return result(status, reason=reason)
        if message.person in self._people:
            status, reason = self._people[message.person]
            return result(status, reason=reason)
        return result(ACCEPTED, reference='fake-%s-%d' % (self.channel, len(self.sent)))

    def to(self, person, kind=None):
        return [m for m in self.sent if m.person == person and (kind is None or m.kind == kind)]


# --- messages: fixed vocabulary, no customer data -------------------------------------------------------------------------

def _clean_text(text, limit=500):
    text = re.sub(r'[^\x20-\x7e]', ' ', str(text or ''))
    return re.sub(r'\s+', ' ', text).strip()[:limit]


def _local(epoch, zone):
    return datetime.fromtimestamp(float(epoch), ZoneInfo(zone)).strftime('%Y-%m-%d %H:%M %Z')


def compose(channel, kind, incident, person, destination, *, zone='America/New_York', what=None, ack_url=None,
            step=None, held=0):
    """The message for one delivery. Push and phone carry only codes; e-mail adds the evaluator's message, which holds
    rule codes and counts only (scripts/discord_ops_check.py builds it from aggregates, never customer content)."""
    rule, priority = incident['rule'], incident['priority']
    opened = _local(incident['openedAt'], zone)
    if kind == 'summary':
        subject = '[storm] %d more alert notifications held back' % held
        body = ('More than the storm limit of notifications went to you on this channel in the last window. %d were '
                'held back and go out when the window allows, if still unacknowledged. Open Founder Control for the '
                'full list.' % held)
    elif kind == 'record':
        subject = '[%s] %s %s' % (priority, rule, what)
        body = 'Incident %s (%s, %s) was %s at %s.' % (incident['id'], rule, priority, what, _local(incident.get('updatedAt') or incident['lastSeenAt'], zone))
        if what == 'acknowledged':
            body += ' Acknowledged by %s via %s.' % (incident.get('acknowledgedBy'), incident.get('ackChannel'))
        if what == 'resolved':
            body += ' Resolution: %s.' % incident.get('resolution')
    else:
        subject = '[%s] %s' % (priority, rule)
        if channel == 'phone':
            body = ('Rafii on-call. Priority %s alert: %s. Opened %s. Press 1 to acknowledge.'
                    % (priority[1:], rule.replace('_', ' ').lower(), opened))
        elif channel == 'push':
            body = '%s alert open since %s. Acknowledge to stop the escalation.' % (priority, opened)
        else:
            body = ('%s alert %s, opened %s, step %s. %s Runbook: docs/ops/PHONE-RUNBOOK.md. Incident %s.'
                    % (priority, rule, opened, step, _clean_text(incident.get('message')), incident['id']))
    if ack_url and kind != 'summary' and channel != 'phone':
        body += ' Acknowledge: %s' % ack_url
    return Message(channel, person, destination, kind, incident['id'], priority, rule, subject[:160], body[:2000], ack_url)


# --- acknowledgement tokens ----------------------------------------------------------------------------------------------

def _b64(data):
    return base64.urlsafe_b64encode(data).decode('ascii').rstrip('=')


def ack_token(secret, incident_id, person, expires_at):
    """An HMAC-SHA256 signed token naming the incident and the person, valid until expires_at (epoch seconds). The
    secret is injected at run time (never in the repository); without one, no link is offered."""
    if not isinstance(secret, (bytes, bytearray)) or len(secret) < 16:
        raise ValueError('an acknowledgement secret of at least 16 bytes is required')
    payload = '%s|%s|%d' % (incident_id, person, int(expires_at))
    signature = hmac.new(bytes(secret), _TOKEN_CONTEXT + payload.encode(), hashlib.sha256).hexdigest()[:32]
    return _b64(payload.encode()) + '.' + signature


def verify_ack_token(secret, token, now):
    """(incident_id, person) when the token is genuine and unexpired, else None. Constant-time comparison."""
    try:
        encoded, signature = str(token).split('.', 1)
        payload = base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)).decode('ascii')
        expected = hmac.new(bytes(secret), _TOKEN_CONTEXT + payload.encode(), hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(expected, signature):
            return None
        incident_id, person, expires = payload.split('|')
        return (incident_id, person) if float(now) < int(expires) else None
    except (ValueError, TypeError, UnicodeError):
        return None
