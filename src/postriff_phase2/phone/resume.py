"""Bounded, authenticated Dial handoff before the media function expires."""
from postriff_alpha.domain import AlphaError
from . import billing, store


def prepare(phone, call_id, generation, seconds):
    if not isinstance(seconds,(int,float)) or not 0 <= seconds <= 86400:
        raise AlphaError('Voice usage must be confirmed before handoff.',409)
    with phone.hosted.connection_factory() as db, db.cursor() as cur:
        billing.lock_workspace(cur,call_id)
        value=store.call(cur,call_id,lock=True)
        if not value or value['state'] != 'live' or value['media_generation'] != generation or value['media_resume_until'] or phone.clock()+20 >= float(value['answered_at'])+min(value['max_seconds'],value['funded_seconds'] or value['max_seconds']):
            raise AlphaError('Phone handoff unavailable.',409)
        cur.execute('UPDATE public.pr_phone_calls SET media_resume_until=to_timestamp(%s),'
                    'media_usage_seconds=media_usage_seconds+%s WHERE id=%s', (phone.clock()+20,seconds,call_id))
        db.commit()


def claim(phone, call_ref, meta):
    with phone.hosted.connection_factory() as db, db.cursor() as cur:
        cur.execute("SELECT id::text FROM public.pr_phone_calls WHERE provider='dial' AND provider_call_ref=%s",(call_ref,))
        row=cur.fetchone()
        if not row: raise AlphaError('Phone resume unavailable.',403)
        value=store.call(cur,row[0],lock=True)
        if not (value['state']=='live' and value['media_resume_until'] and
                phone.clock()<float(value['media_resume_until']) and value['direction']==meta.get('direction') and
                phone.clock()<float(value['answered_at'])+min(value['max_seconds'],value['funded_seconds'] or value['max_seconds'])):
            raise AlphaError('Phone resume unavailable.',403)
        if value['direction']=='outbound':
            identity=store.number(cur,value['user_id'])
            if not (identity and identity['verified'] and identity['hash']==value['number_hash'] and
                    phone.vault.decrypt(identity['ciphertext'],identity['key_id'])==meta.get('to') and
                    phone.provider.local_call_id(meta.get('instruction'))==value['id']):
                raise AlphaError('Phone resume unavailable.',403)
        # Inbound reuses the consumed authenticated ticket's call binding, never caller ID.
        cur.execute('UPDATE public.pr_phone_calls SET media_resume_until=NULL,media_generation=media_generation+1 WHERE id=%s',(value['id'],))
        db.commit()
        return value['id']
