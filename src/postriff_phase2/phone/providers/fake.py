"""Deterministic local transport. Never dials, sends SMS, or captures audio."""
import hashlib
import hmac
import json

from ..contracts import CallReceipt, ProviderEvent


class FakeTelephonyProvider:
    name, real, configured = 'fake', False, True

    def __init__(self, outcome='ringing', secret='local-fake-signing-key'):
        self.outcome, self.secret, self.calls = outcome, secret, {}
        self.create_count, self.end_count = 0, 0

    def create_outbound_call(self, *, number, call_id, max_seconds, detect_machine=True):
        self.create_count += 1
        # Deliberately do not retain the target number.
        ref = 'fake_' + call_id
        self.calls[ref] = {'state': 'ringing' if self.outcome == 'ambiguous' else self.outcome, 'cap': max_seconds}
        return CallReceipt(self.outcome, None if self.outcome == 'ambiguous' else ref)

    def reconcile(self, *, number, call_id, call_ref, requested_at):
        ref = call_ref or 'fake_' + call_id
        return CallReceipt(self.calls[ref]['state'], ref) if ref in self.calls else CallReceipt('ambiguous')

    def end_call(self, call_ref):
        self.end_count += 1
        self.calls[call_ref]['state'] = 'completed'
        return True

    def sign(self, url, parameters):
        return hmac.new(self.secret.encode(), (url + json.dumps(parameters, sort_keys=True)).encode(), hashlib.sha256).hexdigest()

    def verify_webhook(self, url, parameters, signature):
        return hmac.compare_digest(self.sign(url, parameters), signature or '')

    def normalize_event(self, parameters):
        scalar=lambda name: parameters.get(name)[0] if isinstance(parameters.get(name),list) else parameters.get(name)
        duration=scalar('durationSeconds')
        return ProviderEvent(scalar('eventId'),scalar('callRef'),scalar('state'),int(duration) if duration is not None else None)

    def start_verification(self, number):
        return 'fake_verification'

    def check_verification(self, number, code):
        return code == '123456'
