"""Bounded phone-media diagnostics; never log exception text or provider payloads."""
import json
import logging
import re
import uuid


LOG = logging.getLogger('rafii.phone.media')
PHASES = frozenset(('inbound_admission', 'runtime_init', 'stream_start', 'stream_claim', 'controller_init', 'live_client',
    'live_connect', 'live_start', 'live_receive', 'live_started', 'live_greeting', 'phone_audio_out',
    'phone_transcript', 'phone_input_wait', 'phone_audio_in', 'live_audio_in', 'live_event',
    'session_guard', 'live_bridge', 'live_close'))
ERROR_CLASSES = frozenset(('TypeError', 'ValueError', 'KeyError', 'RuntimeError', 'TimeoutError',
    'AlphaError', 'OpenAIError', 'APIConnectionError', 'APIStatusError', 'AuthenticationError',
    'PermissionDeniedError', 'BadRequestError', 'RateLimitError', 'InvalidStatus',
    'ConnectionClosedError', 'ConnectionClosedOK', 'WebSocketDisconnect', 'OperationalError',
    'ProgrammingError', 'InsufficientPrivilege', 'UndefinedTable', 'UndefinedColumn'))
ERROR_CODES = frozenset(('inbound_hourly_limit', 'inbound_caller_limit', 'inbound_auth_budget', 'invalid_api_key', 'authentication_error', 'permission_denied',
    'insufficient_quota', 'credit_balance_exhausted', 'organization_spend_limit_exceeded',
    'project_spend_limit_exceeded', 'organization_usage_limit_exceeded', 'rate_limit_exceeded',
    'slow_down', 'server_is_overloaded', 'model_not_found', 'invalid_request_error',
    'server_error', 'context_length_exceeded', 'session_expired', 'phone_ended', 'phone_expired',
    'stream_closed', 'missing_required_parameter', 'invalid_value', 'invalid_argument', 'unknown_parameter', 'unsupported_value',
    'unsupported_audio_format', 'invalid_audio_format', 'unsupported_sample_rate', 'invalid_sample_rate',
    'too_many_concurrent_sessions', 'too_many_concurrent_live_sessions', 'concurrent_session_limit_exceeded',
    'live_session_concurrency_limit'))
ERROR_TYPES = ERROR_CODES | frozenset(('permission_error', 'rate_limit_error'))
ERROR_PARAMS = frozenset(('delegation_id', 'content', 'model', 'session.model', 'audio.format', 'session.audio.format',
    'audio.format.type', 'audio.format.rate', 'session.audio.format.type', 'session.audio.format.rate', 'audio.output.voice',
    'session.audio.output.voice', 'instructions', 'session.instructions', 'input', 'session.input',
    'delegation', 'session.delegation', 'store', 'session.store'))
COMMANDS = {'start': 'session_start', 'opening': 'greeting', 'commentary': 'delegation_result',
            'input': 'input_audio', 'close': 'session_close'}
ERROR_CATEGORIES = {'insufficient_quota': 'quota', 'credit_balance_exhausted': 'credits_exhausted',
    'organization_spend_limit_exceeded': 'spend_limit', 'project_spend_limit_exceeded': 'spend_limit',
    'organization_usage_limit_exceeded': 'usage_limit', 'rate_limit_exceeded': 'rate_limit',
    'slow_down': 'rate_limit', 'server_is_overloaded': 'provider_capacity', 'model_not_found': 'model_not_found',
    'unsupported_audio_format': 'audio_format', 'invalid_audio_format': 'audio_format',
    'unsupported_sample_rate': 'audio_format', 'invalid_sample_rate': 'audio_format',
    'too_many_concurrent_sessions': 'live_capacity', 'too_many_concurrent_live_sessions': 'live_capacity',
    'concurrent_session_limit_exceeded': 'live_capacity', 'live_session_concurrency_limit': 'live_capacity'}
AUDIO_CONFIG_CODES = frozenset(('missing_required_parameter', 'invalid_value', 'invalid_argument', 'unknown_parameter', 'unsupported_value'))
AUDIO_FORMAT_PARAMS = frozenset(('audio.format', 'audio.format.type', 'audio.format.rate',
    'session.audio.format', 'session.audio.format.type', 'session.audio.format.rate'))


def command_echo(event, body):
    value = body.get('client_event_id')
    return value if value is not None else event.get('client_event_id')


def rejected_command(event, body):
    """Classify only our bounded command IDs; the provider's echoed value is never logged."""
    value = command_echo(event, body)
    if not isinstance(value, str) or len(value) > 48:
        return 'unknown'
    if value == 'phone-opening':  # previous release's greeting identifier
        return 'greeting'
    match = re.fullmatch(r'phone-(start|opening|commentary|input|close)-[1-9][0-9]{0,8}', value)
    return COMMANDS[match[1]] if match else 'unknown'


def exception_body(error):
    """Use SDK-decoded data or a bounded WebSocket upgrade failure body; never its message."""
    body = getattr(error, 'body', None)
    if body is None:
        body = getattr(getattr(error, 'response', None), 'body', None)
    if isinstance(body, (bytes, bytearray, str)):
        if len(body) > 8192:
            return {}
        try:
            body = json.loads(body)
        except (ValueError, TypeError, UnicodeError, RecursionError):
            return {}
    if not isinstance(body, dict):
        return {}
    nested = body.get('error')
    return nested if isinstance(nested, dict) else body


def valid_request_id(value):
    return value if isinstance(value, str) and re.fullmatch(r'req_[0-9a-f]{32}', value) else None


def response_request_id(response):
    headers = getattr(response, 'headers', None)
    try:
        value = headers.get('x-request-id') if headers is not None else None
    except (AttributeError, TypeError, ValueError, LookupError):
        return None
    return valid_request_id(value)


def provider_request_id(error):
    return valid_request_id(getattr(error, 'request_id', None)) or response_request_id(getattr(error, 'response', None))


def handshake_request_id(connection):
    """Only the SDK socket's upgrade x-request-id; never event/session IDs or other headers."""
    return response_request_id(getattr(getattr(connection, '_connection', None), 'response', None))


def metadata(phase, error=None, *, event=None, live_started=None, greeting_sent=None, request_id=None):
    details = {'phase': phase if phase in PHASES else 'unknown'}
    if error is not None:
        name = type(error).__name__
        details['errorClass'] = name if name in ERROR_CLASSES else 'OtherError'
    body = event.get('error') if isinstance(event, dict) else exception_body(error)
    body = body if isinstance(body, dict) else {}
    if isinstance(event, dict) or 'client_event_id' in body or type(live_started) is bool:
        source = event if isinstance(event, dict) else {}
        rejected = rejected_command(source, body)
        echo = command_echo(source, body)
        details['rejectedCommand'] = rejected
        details['commandEchoState'] = ('known' if rejected != 'unknown' else 'missing' if echo is None
                                      else 'unrecognized' if isinstance(echo, str) else 'invalid_type')
    for key, value in (('liveStarted', live_started), ('greetingSent', greeting_sent)):
        if type(value) is bool:
            details[key] = value
    code = body.get('code')
    if code is None and event is None:
        code = getattr(error, 'code', None)
    if code is not None:
        details['errorCode'] = code if isinstance(code, str) and code in ERROR_CODES else 'other'
    for field, allowed in (('type', ERROR_TYPES), ('param', ERROR_PARAMS)):
        value = body.get(field)
        if value is None and event is None:
            value = getattr(error, field, None)
        if value is not None:
            details['error' + field.capitalize()] = value if isinstance(value, str) and value in allowed else 'other'
    if code is not None:
        category = ERROR_CATEGORIES.get(code, 'other') if isinstance(code, str) else 'other'
        details.update(errorCategory=category, reasonBasis='exact_code' if category != 'other' else 'unclassified')
        if isinstance(code, str) and code in AUDIO_CONFIG_CODES and details.get('errorParam') in AUDIO_FORMAT_PARAMS:
            details.update(errorCategory='audio_format', reasonBasis='code_param')
    status = getattr(error, 'status_code', None)
    if status is None:
        status = getattr(getattr(error, 'response', None), 'status_code', None)
    if type(status) is int and 400 <= status <= 599:
        details['httpStatus'] = status
    request_id = provider_request_id(error) or valid_request_id(request_id)
    if request_id is not None:
        details['providerRequestId'] = request_id
    return details


class MediaFailure(Exception):
    def __init__(self, phase, error=None, *, event=None, provider_request_id=None):
        super().__init__('Phone media failed.')
        self.diagnostic = dict(error.diagnostic) if isinstance(error, MediaFailure) else metadata(
            phase, error, event=event, request_id=provider_request_id)
        request_id = valid_request_id(provider_request_id)
        if request_id is not None:
            self.diagnostic.setdefault('providerRequestId', request_id)


def report_failure(call_id, phase, error=None, *, event=None, live_started=None, greeting_sent=None, provider_request_id=None):
    details = dict(error.diagnostic) if isinstance(error, MediaFailure) else metadata(
        phase, error, event=event, live_started=live_started, greeting_sent=greeting_sent, request_id=provider_request_id)
    request_id = valid_request_id(provider_request_id)
    if request_id is not None:
        details.setdefault('providerRequestId', request_id)
    try:
        details['callId'] = str(uuid.UUID(str(call_id)))
    except (ValueError, TypeError, AttributeError):
        pass
    LOG.warning('rafii.phone.media.failure %s', json.dumps(details, sort_keys=True))
