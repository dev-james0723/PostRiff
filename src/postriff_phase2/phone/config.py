from dataclasses import dataclass, field

from .contracts import FLAGS


@dataclass
class PhoneConfig:
    values: dict = field(default_factory=dict, repr=False)

    def enabled(self, name):
        return name in FLAGS and str(self.values.get(name, '')).lower() in ('1', 'true', 'yes', 'on')

    @property
    def cap_seconds(self):
        # Product maximum. The former 60-second test environment value is obsolete.
        return 3600

    @property
    def telephony_rate(self):
        return max(0, int(self.values.get('RAFII_PHONE_USD_MICRO_PER_MINUTE', 0)))

    @property
    def daily_budget(self):
        return min(5_000_000, max(0, int(self.values.get('RAFII_PHONE_DAILY_USD_MICRO', 2_000_000))))

    @property
    def inbound_auth_budget(self):
        return min(5_000_000, max(0, int(self.values.get('RAFII_PHONE_INBOUND_AUTH_DAILY_USD_MICRO', 1_000_000))))

    @property
    def base_url(self):
        return str(self.values.get('RAFII_PHONE_PUBLIC_BASE_URL') or '').rstrip('/')

    def public(self):
        return {name: self.enabled(name) for name in FLAGS}
