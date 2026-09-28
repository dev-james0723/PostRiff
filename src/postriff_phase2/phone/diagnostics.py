"""Bounded phone-media diagnostics; never log exception text or provider payloads."""
import json
import logging
import uuid


LOG = logging.getLogger('rafii.phone.media')
PHASES = frozenset(('runtime_init', 'stream_start', 'stream_claim', 'controller_init', 'live_client',
    'live_connect', 'live_start', 'live_receive', 'live_started', 'live_greeting', 'phone_audio_out',
    'phone_transcript', 'phone_input_wait', 'phone_audio_in', 'live_audio_in', 'live_event',
    'session_guard', 'live_bridge', 'live_close'))
ERROR_CLASSES = frozenset(('TypeError', 'ValueError', 'KeyError', 'RuntimeError', 'TimeoutError',
    'AlphaError', 'OpenAIError', 'APIConnectionError', 'APIStatusError', 'AuthenticationError',
    'PermissionDeniedError', 'BadRequestError', 'RateLimitError', 'InvalidStatus',
    'ConnectionClosedError', 'ConnectionClosedOK', 'WebSocketDisconnect', 'OperationalError',
    'ProgrammingError', 'InsufficientPrivilege', 'UndefinedTable', 'UndefinedColumn'))
ERROR_CODES = frozenset(('invalid_api_key', 'authentication_error', 'permission_denied',
    'insufficient_quota', 'rate_limit_exceeded', 'model_not_found', 'invalid_request_error',
    'server_error', 'context_length_exceeded', 'session_expired', 'phone_ended', 'phone_expired',
    'stream_closed', 'missing_required_parameter', 'invalid_value', 'invalid_argument', 'unknown_parameter', 'unsupported_value'))
ERROR_PARAMS = frozenset(('delegation_id', 'content', 'model', 'session.model', 'audio.format', 'session.audio.format',
    'session.audio.format.type', 'session.audio.format.rate', 'audio.output.voice',
    'session.audio.output.voice', 'instructions', 'session.instructions', 'input', 'session.input',
    'delegation', 'session.delegation', 'store', 'session.store'))


def metadata(phase, error=None, *, event=None):
    details = {'phase': phase if phase in PHASES else 'unknown'}
    if error is not None:
        name = type(error).__name__
        details['errorClass'] = name if name in ERROR_CLASSES else 'OtherError'
    body = (event or {}).get('error') if isinstance(event, dict) else None
    body = body if isinstance(body, dict) else {}
    code = body.get('code') if event is not None else getattr(error, 'code', None)
    if code is not None:
        details['errorCode'] = code if isinstance(code, str) and code in ERROR_CODES else 'other'
    for field, allowed in (('type', ERROR_CODES), ('param', ERROR_PARAMS)):
        value = body.get(field)
        if value is not None:
            details['error' + field.capitalize()] = value if isinstance(value, str) and value in allowed else 'other'
    status = getattr(error, 'status_code', None)
    if status is None:
        status = getattr(getattr(error, 'response', None), 'status_code', None)
    if type(status) is int and 400 <= status <= 599:
        details['httpStatus'] = status
    return details


class MediaFailure(Exception):
    def __init__(self, phase, error=None, *, event=None):
        super().__init__('Phone media failed.')
        self.diagnostic = error.diagnostic if isinstance(error, MediaFailure) else metadata(phase, error, event=event)


def report_failure(call_id, phase, error=None, *, event=None):
    details = dict(error.diagnostic) if isinstance(error, MediaFailure) else metadata(phase, error, event=event)
    try:
        details['callId'] = str(uuid.UUID(str(call_id)))
    except (ValueError, TypeError, AttributeError):
        pass
    LOG.warning('rafii.phone.media.failure %s', json.dumps(details, sort_keys=True))
