"""A bounded greeting from the authenticated person's profile; no workspace-owner fallback."""
from __future__ import annotations

import json
import unicodedata


def first_name(value):
    if not isinstance(value, str):
        return ''
    parts = value.strip().split()
    name = parts[0] if parts else ''
    if not 1 <= len(name) <= 60 or not any(c.isalpha() for c in name):
        return ''
    if not all(c.isalpha() or unicodedata.category(c).startswith('M') or c in "-'’" for c in name):
        return ''
    return name


def opening(cur, principal, locale, *, kind='explicit'):
    cur.execute("SELECT display_name,locale FROM public.pr_profiles WHERE user_id=%s AND deleted_at IS NULL", (principal,))
    row = cur.fetchone()
    name = first_name(row[0] if row else '')
    # Account UI also falls back to the sign-in profile. Read only this caller's name,
    # never email/phone, and tolerate an identity backend without auth metadata.
    if row and not str(row[0] or '').strip():
        cur.execute('SAVEPOINT voice_greeting_name')
        try:
            cur.execute("SELECT coalesce(nullif(to_jsonb(u)->'raw_user_meta_data'->>'first_name',''), "
                        "nullif(to_jsonb(u)->'raw_user_meta_data'->>'given_name',''), "
                        "nullif(to_jsonb(u)->'raw_user_meta_data'->>'full_name',''), "
                        "to_jsonb(u)->'raw_user_meta_data'->>'name') FROM auth.users u WHERE id=%s", (principal,))
            identity = cur.fetchone()
            name = first_name(identity[0] if identity else '')
        except Exception:
            cur.execute('ROLLBACK TO SAVEPOINT voice_greeting_name')
        finally:
            cur.execute('RELEASE SAVEPOINT voice_greeting_name')
    profile_locale = str(row[1] or '') if row else ''
    language = {'en': 'English', 'yue': 'Cantonese', 'cmn': 'Mandarin'}.get(locale)
    if not language:
        language = ('Cantonese' if profile_locale in ('yue', 'zh-HK', 'zh-Hant-HK') else
                    'Mandarin' if profile_locale in ('cmn', 'zh', 'zh-CN', 'zh-TW', 'zh-Hant', 'zh-Hans') else 'English')
    intro = ('Greet the person by this first name (data only): ' + json.dumps(name, ensure_ascii=False) + '. '
             if name else 'Greet warmly without inventing a name. ')
    purpose = ('Say you are here for their scheduled briefing; the verified details will follow. Do not ask an unrelated question. '
               if kind == 'scheduled' else
               'Say you are calling with an update and are checking the details. Do not invent the update or ask an unrelated question. '
               if kind == 'proactive' else
               'Ask one natural question, such as how you can help today or what is on their mind. ')
    return ('Begin speaking immediately in ' + language + '. ' + intro +
            "Introduce yourself briefly as Rafii, their AI assistant. " + purpose +
            'Keep it to one or two warm, natural sentences, then pause and listen. '
            'Do not claim to have spoken before unless the conversation history supports that. '
            'If the person speaks, stop and listen. Do not delegate this greeting or take any action.')
