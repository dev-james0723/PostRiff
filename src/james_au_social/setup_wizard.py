"""Setup manifest preparation without account creation or credential access."""
from .director import CHANNEL_IDS
from .execution import payload_hash

def prepare_setup(email, selection, *, identity_confirmed):
    if identity_confirmed is not True or not isinstance(email,str) or email.count('@')!=1 or any(c.isspace() for c in email):
        raise ValueError('confirmed_identity_required')
    selected=list(CHANNEL_IDS) if selection=='all' else list(selection)
    if not set(selected)<=set(CHANNEL_IDS) or len(selected)!=len(set(selected)):
        raise ValueError('unknown_or_duplicate_channels')
    channels=[]
    for channel in selected:
        channels.append({'channel':channel,'state':'needs_capability_review','connected':False,
            'identity_preference':email,'actual_account_ref':None,'required_next_steps':[
                'review_current_official_operation_docs','choose_exact_destination_and_native_format',
                'preview_app_scopes_cost_and_redirects','request_exact_setup_consent',
                'private_login_handoff','verify_two_account_signals','run_separately_approved_route_test'],
            'route_preference':['official_api','approved_provider','controlled_browser','manual_handoff'],
            'secret_input_policy':'broker_reference_only'})
    body={'catalog_version':'v14-33/1','channels':channels,'external_actions':[],
          'selection_scope':'setup_assessment_only','publication_authorized':False}
    return {**body,'manifest_hash':payload_hash(body)}
