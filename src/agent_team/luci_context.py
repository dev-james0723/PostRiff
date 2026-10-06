"""Local, bounded context hints. Screen content cannot authorize task actions.

Only finite enums leave this classifier. No title, URL, text, screenshot path,
customer detail or arbitrary app name becomes cloud context. A hint requires
independent native evidence before it can be associated with a blocked mission.
"""
import re

APP_KINDS = frozenset({'codex', 'claude', 'terminal', 'editor', 'browser', 'luci', 'other'})
SIGNALS = frozenset({'activity_observed', 'quota_indicator_observed',
                     'approval_indicator_observed', 'error_indicator_observed'})
_APPS = {
    'codex': 'codex', 'com.openai.codex': 'codex',
    'claude': 'claude', 'com.anthropic.claudefordesktop': 'claude',
    'terminal': 'terminal', 'com.apple.terminal': 'terminal',
    'iterm2': 'terminal', 'com.googlecode.iterm2': 'terminal',
    'visual studio code': 'editor', 'com.microsoft.vscode': 'editor',
    'cursor': 'editor', 'com.todesktop.230313mzl4w4u92': 'editor',
    'google chrome': 'browser', 'com.google.chrome': 'browser',
    'safari': 'browser', 'com.apple.safari': 'browser',
    'luci': 'luci', 'ai.luci.desktop': 'luci',
}
_QUOTA = re.compile(r"you(?:'|’)?ve (?:hit|reached) your (?:usage )?limit|usage limit reached|weekly limit reached|rate.limit.exceeded", re.I)
_APPROVAL = re.compile(r'waiting for (?:your )?approval|approval required|permission required|needs your approval', re.I)
_ERROR = re.compile(r'(?m)^\s*(?:error:|failed:|traceback \(most recent call last\):)|build failed|tests? failed', re.I)


def classify(app, text):
    kind = _APPS.get(app.strip().casefold(), 'other') if isinstance(app, str) and len(app) <= 256 else 'other'
    signal = 'activity_observed'
    # Generic browsers, LUCI itself and unknown apps can show quoted prompts,
    # articles or private information. They never yield a blocking hint.
    if kind in {'codex', 'claude', 'terminal', 'editor'} and isinstance(text, str):
        bounded = text[:16_000]
        if _QUOTA.search(bounded): signal = 'quota_indicator_observed'
        elif _APPROVAL.search(bounded): signal = 'approval_indicator_observed'
        elif _ERROR.search(bounded): signal = 'error_indicator_observed'
    return {'app_kind': kind, 'context_signal': signal}


def event_context(payload):
    """Reject arbitrary observer strings even when rendering a stored event."""
    if (payload.get('origin') != 'read_only_luci_capture_context'
            or payload.get('verified') is not False
            or not isinstance(payload.get('app'), str) or not isinstance(payload.get('reportedState'), str)
            or payload.get('app') not in APP_KINDS or payload.get('reportedState') not in SIGNALS):
        return None
    return {'appKind': payload['app'], 'signal': payload['reportedState'],
            'verified': False, 'executionAuthority': 'none'}
