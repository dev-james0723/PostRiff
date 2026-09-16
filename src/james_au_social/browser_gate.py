"""Secret-blind browser state gate. Does not inspect or control a browser."""
from urllib.parse import urlsplit

PRIVATE={'login','password','mfa','qr','captcha','consent','legal','billing','secret'}

class BrowserGate:
    def __init__(self, account_ref, origin):
        parts=urlsplit(origin)
        if parts.scheme!='https' or not parts.hostname or parts.username or parts.password:
            raise ValueError('invalid_origin')
        self.account_ref=account_ref
        self.origin=origin.rstrip('/')
        self.state='identity_required'
        self.observation_allowed=True

    def result(self):
        return {'state':self.state,'observation_allowed':self.observation_allowed,
                'retention_allowed':False,'submit_allowed':False}

    def checkpoint(self, surface, assertion):
        if surface in PRIVATE:
            self.state='private_handoff'
            self.observation_allowed=False
            return self.result()
        if not self.observation_allowed:
            return self.result()
        if set(assertion)!={'origin','landmarks_match','unexpected_dialog','semantic_submit_control'}:
            raise ValueError('assertion_only_fields_required')
        if assertion['origin'].rstrip('/')!=self.origin or assertion['landmarks_match'] is not True or assertion['unexpected_dialog'] is not False or assertion['semantic_submit_control'] is not True:
            self.state='ui_changed'
        return self.result()

    def resume(self, *, surface_closed, signals):
        if surface_closed is not True:
            return self.result()
        if len(signals)<2 or any(set(s)!={'kind','account_ref'} for s in signals):
            self.state='identity_mismatch'
        elif len({s['kind'] for s in signals})<2 or any(s['account_ref']!=self.account_ref for s in signals):
            self.state='identity_mismatch'
        else:
            self.state='identity_verified'
        self.observation_allowed=self.state=='identity_verified'
        return self.result()
