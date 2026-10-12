"""Erase person-keyed Telegram metadata in the existing account deletion transaction."""


def erase_identity(cur, principal):
    # Older deployments without migration 113 retain their existing deletion path.
    cur.execute("SELECT to_regclass('public.pr_telegram_identities') IS NOT NULL")
    if not cur.fetchone()[0]:
        return
    # Managed-bot events are global. Preserve a record still linked by another
    # Rafii member, even when they share a workspace or a Telegram bot.
    cur.execute("""DELETE FROM public.pr_telegram_managed_bots b
        WHERE EXISTS (SELECT 1 FROM public.pr_telegram_identities i
            WHERE i.member_id=%s AND i.bot_id=b.manager_bot_id::text
              AND i.telegram_user_id=b.owner_user_id)
        AND NOT EXISTS (SELECT 1 FROM public.pr_telegram_identities i
            WHERE i.member_id<>%s AND i.bot_id=b.manager_bot_id::text
              AND i.telegram_user_id=b.owner_user_id)""", (principal, principal))
    cur.execute('DELETE FROM public.pr_telegram_managed_requests WHERE member_id=%s', (principal,))
    cur.execute('DELETE FROM public.pr_telegram_identity_owners WHERE member_id=%s', (principal,))
    cur.execute('DELETE FROM public.pr_telegram_identities WHERE member_id=%s', (principal,))
