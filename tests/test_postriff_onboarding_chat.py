"""Shared interview contract stays aligned across independently packaged API and web services."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from postriff_phase2.onboarding_chat import question_for

def test_brand_and_chat_interview_copies_match():
    assert (ROOT/'src/postriff_alpha/voice_interview.json').read_bytes() == (ROOT/'web/src/features/workspace/voice-interview.generated.json').read_bytes()

def test_conditional_questions_and_confirmation():
    assert question_for({})['key'] == 'mode'
    common={'mode':'personal','purpose':'Explain','audience':'Readers'}
    assert question_for(common)['key'] == 'tone'
    assert question_for({**common,'mode':'business'})['key'] == 'subject'
    assert question_for({**common,'mode':'hybrid','subject':'Studio'})['key'] == 'speaker'
    assert question_for({**common,'tone':'warm','writing':''})['key'] == 'confirm'
    assert question_for({**common,'tone':'warm','writing':'','confirm':'propose'}) is None


def test_onboarding_is_not_a_token_scope():
    from postriff_phase2.api_tokens import route_scope
    assert route_scope('POST', 'api/workspaces/w/ideas/conversations/c/onboarding'.split('/')) is None
