"""Native poll custody only; this module never grants publication authority."""
from postriff_alpha.domain import AlphaError
from .mastodon_protocol import status_options


def binding(variant, options, media=()):
    """Bind public question/ordered choices to the exact reviewed provider options.

    Duration and boolean settings are chosen in Queue and frozen by its existing
    full-manifest digest. Missing/contradictory draft fields fail closed.
    """
    native = variant.get('native')
    native = native if isinstance(native, dict) else {}
    formats = (variant.get('format'), native.get('formatId'))
    if variant.get('platform') != 'Mastodon' or 'mastodon.poll' not in formats:
        return None
    if any(value and value != 'mastodon.poll' for value in formats) or native.get('platform') != 'Mastodon':
        raise AlphaError('The native poll format changed. Prepare a new draft.', 409)
    fields = native.get('fields')
    fields = fields if isinstance(fields, dict) else {}
    question, choices = fields.get('question'), fields.get('options')
    if not isinstance(question, str) or not question.strip() or question != variant.get('text'):
        raise AlphaError('The poll question must exactly match the public draft text. Create a new native draft.', 409)
    if not isinstance(choices, list):
        raise AlphaError('The native poll needs an ordered list of answers. Create a new native draft.', 409)
    answers = []
    for index, choice in enumerate(choices, 1):
        if isinstance(choice, dict) and set(choice) == {'index', 'text'} and type(choice['index']) is int and choice['index'] == index:
            choice = choice['text']
        if not isinstance(choice, str):
            raise AlphaError('The native poll answers must retain their exact draft order.', 409)
        answers.append(choice)
    choices = answers
    if not isinstance(options, dict) or not isinstance(options.get('poll'), dict):
        raise AlphaError('Review the poll answers, duration and settings before approval.', 409)
    normalized = status_options(options, media)['poll']
    # Do not silently repair public answers or discard an unreviewed answer.
    if normalized['options'] != choices or options['poll'].get('options') != choices:
        raise AlphaError('The reviewed poll answers differ from the native draft. Prepare a new review.', 409)
    return {'formatId': 'mastodon.poll', 'question': question, 'options': list(choices)}
