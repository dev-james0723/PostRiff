"""Deterministic Brand interview inside a durable conversation. Never activates a voice."""
import copy
import json
from pathlib import Path
from postriff_alpha.domain import AlphaError
from .permissions import require
from .contracts import digest

INTERVIEW = json.loads((Path(__file__).resolve().parents[1] / 'postriff_alpha' / 'voice_interview.json').read_text())

def question_for(answers):
    for question in INTERVIEW['questions']:
        if question['key'] in answers or (question.get('modes') and answers.get('mode') not in question['modes']):
            continue
        question = dict(question)
        if isinstance(question.get('options'), str):
            question['options'] = INTERVIEW[question['options']]
        return question
    return None

def context_hash(state):
    return digest({'brand':state.get('brandHub'), 'active':state.get('speaker',{}).get('activeRevision'), 'proposal':state.get('speaker',{}).get('provisional')})

def respond(ideas, workspace_id, token, conversation_id, payload):
    from .api_tokens import is_api_token
    from .hosted import audit
    if is_api_token(token):
        raise AlphaError('Voice onboarding requires an interactive member session.', 403)
    with ideas.repository.transaction(token, workspace_id) as (cur, row, principal):
        require(ideas._member(row), 'edit')
        conversation = ideas._conversation(cur, workspace_id, conversation_id)
        if conversation['archived']:
            raise AlphaError('This conversation is archived.', 409)
        before = ideas._state(row)
        if before.get('workspace',{}).get('sample'):
            raise AlphaError('Sample workspaces are read-only.', 403)
        cur.execute('SELECT seq,body FROM public.pr_messages WHERE conversation_id::text=%s ORDER BY seq DESC LIMIT 1', (conversation_id,))
        previous = cur.fetchone()
        if previous is None:
            if type(payload.get('expectedSeq')) is not int or payload['expectedSeq'] != 0:
                raise AlphaError('Reload this conversation before continuing.', 409)
            answers, original_hash = {}, context_hash(before)
        else:
            if type(payload.get('expectedSeq')) is not int or payload['expectedSeq'] != previous[0]:
                raise AlphaError('This interview changed; reload before answering.', 409)
            progress = previous[1].get('onboarding')
            if not progress or progress.get('complete'):
                raise AlphaError('Start a new voice interview from Home.', 409)
            answers = dict(progress['answers'])
            original_hash = progress['contextHash']
            question = question_for(answers)
            answer = payload.get('answer')
            if not isinstance(answer, str) or '\0' in answer or len(answer) > question.get('limit', 1500):
                raise AlphaError('Use plain text within this question’s limit.', 400)
            answer = answer.strip()
            if not answer and not question.get('optional'):
                raise AlphaError('Answer this question, or leave the interview and draft from Home.', 400)
            options = question.get('options')
            if options and answer not in [item['id'] for item in options]:
                raise AlphaError('Choose one of the displayed answers.', 400)
            answers[question['key']] = answer
            label = next((item['label'] for item in options or [] if item['id'] == answer), answer or 'Skip writing sample')
            ideas._append_message(cur, workspace_id, conversation_id, 'user', {'text':label, 'intent':'onboarding'})
        question = question_for(answers)
        complete = question is None
        if complete:
            if context_hash(before) != original_hash or before['speaker'].get('provisional'):
                raise AlphaError('Brand changed or a voice is already waiting. Review it on Brand before starting another interview.', 409)
            candidate = copy.deepcopy(before)
            ideas.commands(candidate, principal, 'mode', {'mode':answers['mode']})
            context = {key:answers.get(key,'') for key in ('purpose','audience','subject','speaker')}
            if answers['mode'] == 'hybrid': context['layers'] = ['voice','niche']
            ideas.commands(candidate, principal, 'context', context)
            ideas.commands(candidate, principal, 'profile_propose', {'tone':answers['tone'], 'writing':answers['writing']})
            state = copy.deepcopy(before)
            profile = candidate['speaker']['provisional']
            profile['brandContext'] = {'mode':answers['mode'], **context}
            profile['observations'] += [f"{key.title()}: {value}" for key,value in context.items() if value and key != 'layers']
            state['speaker']['provisional'] = profile
            cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s', (json.dumps(state), workspace_id))
            for effect in ideas.repository.effects:
                effect(cur, workspace_id, before, state, principal)
            audit(cur, workspace_id, principal, 'voice.proposed', conversation_id, {'origin':'guided-chat'})
        progress = {'answers':answers, 'contextHash':original_hash, 'question':question, 'complete':complete}
        text = 'Your voice proposal is ready on Brand. Only an owner can activate it; your current voice is unchanged.' if complete else question['question']
        return ideas._append_message(cur, workspace_id, conversation_id, 'assistant', {'text':text, 'intent':'onboarding', 'onboarding':progress})
