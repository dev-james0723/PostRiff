"""Server-owned real release evidence; connection rights are checked separately."""
import math

RELEASE_VERSION = 'rafii.telegram.public.v1'
DESTINATION_VERSION = 'rafii.telegram.bot.v2'


def positive_number(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def proven(record):
    return (isinstance(record, dict) and record.get('passed') is True
            and positive_number(record.get('timestamp'))
            and isinstance(record.get('evidenceRef'), str) and bool(record['evidenceRef']))


def release_capabilities(evidence, mode):
    """A reviewed adapter release applies to new users without operator enrollment.

    Synthetic tests cannot qualify a release. The server file must be installed
    only after reviewed real A–D receipts. This never grants destination rights.
    """
    if (not isinstance(evidence, dict) or evidence.get('source') != 'telegram_real_e2e'
            or evidence.get('releaseVersion') != RELEASE_VERSION
            or evidence.get('qualificationVersion') != DESTINATION_VERSION
            or evidence.get('reviewed') is not True
            or not isinstance(evidence.get('flows'), dict)
            or not all(proven(evidence['flows'].get(flow)) for flow in ('A', 'B', 'C', 'D'))):
        return set()
    cases = evidence.get('cases')
    if not isinstance(cases, list):
        return set()
    result = set()
    for case in cases:
        if (not proven(case) or case.get('connectionType') != mode
                or type(case.get('botId')) is not int or not 0 < case['botId'] < 2**52
                or type(case.get('chatId')) is not int or not 0 < abs(case['chatId']) < 2**52
                or type(case.get('messageId')) is not int or case['messageId'] <= 0
                or not isinstance(case.get('capability'), str)
                or (mode == 'business' and not isinstance(case.get('businessConnectionId'), str))
                or (mode == 'business' and not case.get('businessConnectionId'))):
            continue
        result.add(case['capability'])
    return result
